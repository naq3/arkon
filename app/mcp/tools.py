"""
Arkon MCP Tools — Knowledge Base operations exposed to Claude.

All tools verify the employee's MCP token and enforce their knowledge scope:
  - Token from Authorization header → MCPAuthService.verify_token()
  - ResolvedIdentity drives what sources the employee can see
  - apply_scope_filter() is applied before any source data is returned

Tools:
  - search_knowledge: Semantic search with scope filtering
  - get_document: Retrieve document (scope-checked)
  - list_sources: List accessible documents
  - list_categories: Browse category tree
  - find_contacts: Find relevant contacts
  - get_category_knowledge: Get docs in a category
"""

from typing import Optional

from fastmcp import FastMCP, Context
from loguru import logger


# ---------------------------------------------------------------------------
# Auth helpers (module-level, used by every tool)
# ---------------------------------------------------------------------------

async def _get_identity():
    """
    Extract Bearer token from the current HTTP request and resolve identity.
    Returns (ResolvedIdentity, None) on success or (None, error_message) on failure.
    """
    from fastmcp.server.dependencies import get_http_request
    from app.database import async_session_factory
    from app.services.mcp_auth_service import MCPAuthService

    try:
        request = get_http_request()
        auth_header = request.headers.get("authorization", "")
        token = auth_header.removeprefix("Bearer ").strip()
    except RuntimeError:
        return None, "No HTTP request context available."

    if not token:
        return None, (
            "Authentication required. Configure your MCP token in Claude Desktop:\n"
            '{"mcpServers": {"arkon": {"url": "...", '
            '"headers": {"Authorization": "Bearer <your-token>"}}}}'
        )

    async with async_session_factory() as session:
        auth_svc = MCPAuthService(session)
        identity = await auth_svc.verify_token(token)
        if identity is None:
            return None, "Invalid or inactive MCP token. Contact your administrator."
        await session.commit()

    return identity, None


async def _get_allowed_source_ids(identity) -> Optional[set[str]]:
    """
    Return a set of allowed source IDs for the identity, or None if open access.
    Uses apply_scope_filter() on the sources table.
    """
    # Admin or open access: no restriction
    if identity.is_admin:
        return None
    if identity.allowed_source_ids is None and identity.allowed_knowledge_types is None:
        return None

    from sqlalchemy import select
    from app.database import async_session_factory
    from app.database.models import Source
    from app.services.mcp_auth_service import apply_scope_filter

    async with async_session_factory() as session:
        stmt = select(Source.id).where(Source.status == "ready")
        stmt = apply_scope_filter(stmt, identity)
        result = await session.execute(stmt)
        return {str(r[0]) for r in result.all()}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP):
    """Register all KB tools on the MCP server."""

    @mcp.tool()
    async def search_knowledge(
        query: str,
        top_k: int = 5,
        min_similarity: float = 0.3,
        knowledge_type: Optional[str] = None,
    ) -> str:
        """
        Search the enterprise knowledge base using semantic search.

        Use this tool when the employee asks a question that might be
        answered by internal documents, SOPs, product info, or FAQs.

        Args:
            query: The search query (natural language)
            top_k: Maximum number of results to return (default: 5)
            min_similarity: Minimum relevance score 0-1 (default: 0.3)
            knowledge_type: Filter by type slug (e.g. "sop", "product")

        Returns:
            Formatted search results with source titles, content excerpts,
            page numbers, and relevance scores. Cite these sources in
            your answer.
        """
        identity, err = await _get_identity()
        if err:
            return err

        allowed_ids = await _get_allowed_source_ids(identity)

        from app.database import async_session_factory
        from app.services.kb_service import search_kb

        # Fetch extra results to compensate for scope filtering
        fetch_k = top_k if allowed_ids is None else top_k * 4

        async with async_session_factory() as session:
            results = await search_kb(
                session=session,
                query=query,
                top_k=fetch_k,
                min_similarity=min_similarity,
            )

        # Apply scope filter
        if allowed_ids is not None:
            results = [r for r in results if str(r.source_id) in allowed_ids]

        # Apply knowledge_type filter if requested
        if knowledge_type:
            from app.database.models import Source, KnowledgeType
            from sqlalchemy import select
            async with async_session_factory() as session:
                kt_stmt = select(KnowledgeType.id).where(KnowledgeType.slug == knowledge_type)
                kt_result = await session.execute(kt_stmt)
                kt_id = kt_result.scalar()
                if kt_id:
                    type_filtered = []
                    for r in results:
                        source = await session.get(Source, r.source_id)
                        if source and source.knowledge_type_id == kt_id:
                            type_filtered.append(r)
                    results = type_filtered

        results = results[:top_k]

        if not results:
            return "No relevant documents found in the knowledge base for this query."

        parts = []
        for i, r in enumerate(results, 1):
            source_label = f"**{r.source_title}**" if r.source_title else "Untitled"
            page_label = f" (page {r.page_number})" if r.page_number else ""
            similarity_pct = f"{r.similarity:.0%}"

            part = f"### Result {i} — {source_label}{page_label} [{similarity_pct} match]\n\n"
            part += r.content

            if r.image_urls:
                part += f"\n\n_[{len(r.image_urls)} image(s) available in this section]_"

            if r.source_download_url:
                part += f"\n\n[Download source]({r.source_download_url})"

            parts.append(part)

        header = f"Found {len(results)} relevant result(s) for: \"{query}\"\n\n---\n\n"
        return header + "\n\n---\n\n".join(parts)

    @mcp.tool()
    async def get_document(
        source_id: str,
        max_length: int = 10000,
    ) -> str:
        """
        Retrieve the full content of a specific document by its ID.

        Use this when you need more detail from a document that appeared
        in search results.

        Args:
            source_id: The document source ID (UUID)
            max_length: Maximum characters to return (default: 10000)

        Returns:
            Document title, metadata, knowledge type, and full text content.
        """
        import uuid as uuid_mod
        from app.database import async_session_factory
        from app.database.models import Source, SourceInsight
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        identity, err = await _get_identity()
        if err:
            return err

        try:
            sid = uuid_mod.UUID(source_id)
        except ValueError:
            return f"Invalid source ID: {source_id}"

        async with async_session_factory() as session:
            stmt = (
                select(Source)
                .where(Source.id == sid)
                .options(selectinload(Source.knowledge_type))
            )
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()
            if not source:
                return f"Document not found: {source_id}"

            # Scope check
            allowed_ids = await _get_allowed_source_ids(identity)
            if allowed_ids is not None and str(sid) not in allowed_ids:
                return "Access denied: this document is outside your knowledge scope."

            stmt2 = select(SourceInsight).where(
                SourceInsight.source_id == sid,
                SourceInsight.insight_type == "summary",
            )
            result2 = await session.execute(stmt2)
            insight = result2.scalar_one_or_none()

            parts = [f"# {source.title or 'Untitled Document'}"]
            parts.append(f"\n**Type:** {source.source_type or 'file'}")
            kt_label = source.knowledge_type.name if source.knowledge_type else "Uncategorized"
            parts.append(f"**Knowledge Type:** {kt_label}")
            if source.file_name:
                parts.append(f"**File:** {source.file_name}")
            if source.url:
                parts.append(f"**URL:** {source.url}")
            parts.append(f"**Status:** {source.status}")
            if source.created_at:
                parts.append(f"**Added:** {source.created_at.strftime('%Y-%m-%d %H:%M')}")

            if insight:
                parts.append(f"\n## Summary\n{insight.content}")

            if source.full_text:
                text = source.full_text[:max_length]
                if len(source.full_text) > max_length:
                    text += f"\n\n... (truncated, {len(source.full_text) - max_length} more characters)"
                parts.append(f"\n## Full Content\n{text}")

        return "\n".join(parts)

    @mcp.tool()
    async def list_sources(
        status: str = "ready",
        knowledge_type: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """
        List all available knowledge sources (documents) in the system.

        Args:
            status: Filter by status — "ready", "processing", "error", or "all"
            knowledge_type: Filter by type slug, or None for all
            limit: Maximum number of sources to return (default: 20)

        Returns:
            List of documents with titles, types, knowledge types, and IDs.
        """
        from app.database import async_session_factory
        from app.database.models import Source, KnowledgeType
        from app.services.mcp_auth_service import apply_scope_filter
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        identity, err = await _get_identity()
        if err:
            return err

        async with async_session_factory() as session:
            stmt = (
                select(Source)
                .options(selectinload(Source.knowledge_type))
                .order_by(Source.created_at.desc())
            )
            if status != "all":
                stmt = stmt.where(Source.status == status)
            if knowledge_type:
                kt_stmt = select(KnowledgeType.id).where(KnowledgeType.slug == knowledge_type)
                kt_result = await session.execute(kt_stmt)
                kt_id = kt_result.scalar()
                if kt_id:
                    stmt = stmt.where(Source.knowledge_type_id == kt_id)

            # Apply scope filter at SQL level
            stmt = apply_scope_filter(stmt, identity)
            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            sources = result.scalars().all()

        if not sources:
            msg = "No documents found"
            if knowledge_type:
                msg += f" of type '{knowledge_type}'"
            return msg + "."

        lines = [f"**Knowledge Base — {len(sources)} document(s)**\n"]

        from collections import defaultdict
        by_type = defaultdict(list)
        for s in sources:
            kt_name = s.knowledge_type.name if s.knowledge_type else "Uncategorized"
            by_type[kt_name].append(s)

        for kt_name, type_sources in by_type.items():
            lines.append(f"\n### {kt_name} ({len(type_sources)})")
            for s in type_sources:
                title = s.title or s.file_name or s.url or "Untitled"
                lines.append(f"- **{title}** (ID: `{s.id}`)")

        return "\n".join(lines)

    @mcp.tool()
    async def list_categories() -> str:
        """
        List all knowledge categories in the system.

        Categories organize documents into logical groups.
        Use this to understand what knowledge areas are available.

        Returns:
            Category tree with names and document counts.
        """
        identity, err = await _get_identity()
        if err:
            return err

        from app.services.neo4j_service import neo4j_service

        if not neo4j_service.available:
            return "Knowledge graph is not available. Categories cannot be retrieved."

        try:
            categories = await neo4j_service.list_categories()
        except Exception as e:
            logger.warning(f"Failed to list categories: {e}")
            return "Failed to retrieve categories from the knowledge graph."

        if not categories:
            return "No categories defined yet."

        lines = ["**Knowledge Categories**\n"]
        for cat in categories:
            name = cat.get("name", "Unnamed")
            desc = cat.get("description", "")
            doc_count = cat.get("document_count", 0)
            indent = "  " * cat.get("depth", 0)
            line = f"{indent}- **{name}** ({doc_count} docs)"
            if desc:
                line += f" — {desc}"
            lines.append(line)

        return "\n".join(lines)

    @mcp.tool()
    async def find_contacts(
        topic: Optional[str] = None,
        department: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """
        Find relevant internal contacts who can help with a topic.

        Use this when the knowledge base doesn't have enough information
        and the employee needs to reach a human expert.

        Args:
            topic: Topic to search for (optional)
            department: Filter by department name (optional)
            limit: Maximum contacts to return (default: 5)

        Returns:
            Contact list with names, roles, departments, phone, email.
        """
        identity, err = await _get_identity()
        if err:
            return err

        from app.database import async_session_factory
        from app.database.models import Contact, Department
        from sqlalchemy import select

        async with async_session_factory() as session:
            stmt = select(Contact).limit(limit * 3)
            if department:
                stmt = (
                    select(Contact)
                    .join(Department, Contact.department_id == Department.id, isouter=True)
                    .where(Department.name.ilike(f"%{department}%"))
                    .limit(limit)
                )
            result = await session.execute(stmt)
            contacts = result.scalars().all()

        if not contacts:
            return "No contacts found in the directory."

        if topic:
            topic_lower = topic.lower()
            scored = []
            for c in contacts:
                score = 0
                if c.topics:
                    score = sum(1 for t in c.topics if t.lower() in topic_lower or topic_lower in t.lower())
                if c.role and topic_lower in c.role.lower():
                    score += 1
                scored.append((score, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            contacts = [c for _, c in scored[:limit]]

        lines = ["**Relevant Contacts**\n"]
        for c in contacts:
            parts = [f"- **{c.name}**"]
            if c.role:
                parts.append(f"  Role: {c.role}")
            if c.phone:
                parts.append(f"  Phone: {c.phone}")
            if c.email:
                parts.append(f"  Email: {c.email}")
            if c.topics:
                parts.append(f"  Topics: {', '.join(c.topics)}")
            lines.append("\n".join(parts))

        return "\n\n".join(lines)

    @mcp.tool()
    async def get_category_knowledge(
        category_name: str,
        top_k: int = 10,
    ) -> str:
        """
        Get all documents linked to a specific knowledge category.

        Args:
            category_name: Name of the category to browse
            top_k: Maximum documents to return (default: 10)

        Returns:
            List of documents in this category with summaries.
        """
        identity, err = await _get_identity()
        if err:
            return err

        from app.services.neo4j_service import neo4j_service

        if not neo4j_service.available:
            return "Knowledge graph is not available."

        try:
            docs = await neo4j_service.get_sources_by_category(category_name, limit=top_k)
        except Exception as e:
            logger.warning(f"Failed to get category documents: {e}")
            return f"Failed to retrieve documents for category: {category_name}"

        if not docs:
            return f"No documents found in category: {category_name}"

        # Apply scope filter: only show docs the employee can access
        allowed_ids = await _get_allowed_source_ids(identity)

        lines = [f"**Documents in '{category_name}'**\n"]
        shown = 0
        for doc in docs:
            title = doc.get("title", "Untitled")
            source_id = doc.get("pg_source_id", "")
            if allowed_ids is not None and source_id not in allowed_ids:
                continue
            lines.append(f"- **{title}** (ID: `{source_id}`)")
            shown += 1

        if shown == 0:
            return f"No accessible documents found in category: {category_name}"

        lines[0] = f"**Documents in '{category_name}'** ({shown} found)\n"
        lines.append(f"\n_Use `get_document(source_id)` to read full content._")
        return "\n".join(lines)
