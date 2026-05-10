import hashlib
import io
import os
import uuid
import zipfile
from typing import Any, Dict, List, Optional, Tuple

import sqlalchemy as sa
from fastapi import HTTPException
from loguru import logger
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    Employee,
    Skill,
    SkillContribution,
    SkillContributionStatus,
    SkillDepartment,
    SkillVersion,
)
from app.services.storage_service import storage_service
from app.utils.text import slugify
from app.worker import get_arq_pool


class SkillService:
    @staticmethod
    def _calculate_zip_content_hash(file_data: bytes) -> Optional[str]:
        """
        Calculates a stable SHA256 hash based on the content of the ZIP file.
        The hash is derived from filenames and MD5 hashes of individual files to detect actual content changes.
        """
        hasher = hashlib.sha256()
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                # Sort by filename for stability across different ZIP generators
                for info in sorted(zf.infolist(), key=lambda x: x.filename):
                    if info.is_dir():
                        continue
                    
                    # Track path changes
                    hasher.update(info.filename.encode("utf-8"))
                    
                    # Track content changes using MD5 (efficient for individual files)
                    with zf.open(info) as f:
                        md5 = hashlib.md5()
                        while True:
                            chunk = f.read(8192)
                            if not chunk:
                                break
                            md5.update(chunk)
                        hasher.update(md5.hexdigest().encode("utf-8"))
            return hasher.hexdigest()
        except zipfile.BadZipFile:
            return None

    @staticmethod
    async def validate_zip_content(file_data: bytes, zip_name: str) -> Optional[str]:
        """
        Validates the structural integrity of a skill ZIP file.
        Checks for the presence of the mandatory SKILL.md file.
        """
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                filenames = [f.filename.lower() for f in zf.infolist()]
                
                # We expect SKILL.md either at the root or inside a directory named after the zip
                target_readme = f"{zip_name}/skill.md".lower()
                
                has_readme = any(
                    name == "skill.md" or 
                    name == target_readme or 
                    name.endswith("/skill.md") 
                    for name in filenames
                )
                
                if not has_readme:
                    return "Missing mandatory SKILL.md file in ZIP package."
                    
            return None
        except zipfile.BadZipFile:
            return "Invalid or corrupted ZIP file."
        except Exception as e:
            logger.error(f"Unexpected error validating zip: {e}")
            return f"Validation error: {str(e)}"


    @staticmethod
    async def _upsert_skill_db_records(
        db: AsyncSession,
        name: str,
        file_hash: str,
        department_ids: Optional[List[uuid.UUID]],
        scope_type: str,
        scope_id: Optional[uuid.UUID],
        force: bool
    ) -> Tuple[Optional[Skill], Optional[int], Optional[str]]:
        """
        Finds an existing skill or creates a new one, updating metadata and department links.
        
        Args:
            db (AsyncSession): Database session.
            name (str): Skill name.
            file_hash (str): Content-based hash.
            department_ids (List[uuid.UUID]): List of department IDs.
            scope_type (str): 'global' or 'department'.
            scope_id (uuid.UUID): Primary scope ID.
            force (bool): Whether to overwrite if exists.
            
        Returns:
            Tuple[Optional[Skill], Optional[int], Optional[str]]: 
                (Skill object, new version number, error/status message)
        """
        # Collect all unique department IDs from both legacy and new sources
        all_depts = list(set(filter(None, (department_ids or []) + ([scope_id] if scope_id else []))))
        
        # Check for existing skill by name
        stmt = select(Skill).where(Skill.name == name)
        res = await db.execute(stmt)
        existing_skill = res.scalars().first()

        if existing_skill:
            if not force:
                return None, None, "duplicate"
            
            # Update Visibility/Department Metadata
            if scope_type == "department" or all_depts:
                existing_skill.scope_type = "department"
                existing_skill.scope_id = scope_id or (all_depts[0] if all_depts else None)
                
                # Wipe and recreate Many-to-Many links
                await db.execute(sa.delete(SkillDepartment).where(SkillDepartment.skill_id == existing_skill.id))
                for d_id in all_depts:
                    db.add(SkillDepartment(skill_id=existing_skill.id, department_id=d_id))
            else:
                existing_skill.scope_type = "global"
                existing_skill.scope_id = None
                await db.execute(sa.delete(SkillDepartment).where(SkillDepartment.skill_id == existing_skill.id))

            # Skip versioning if content hasn't changed
            if existing_skill.version_hash == file_hash:
                return existing_skill, None, "metadata_only"
            
            new_version_num = existing_skill.current_version + 1
            existing_skill.status = "processing"
            existing_skill.version_hash = file_hash
            return existing_skill, new_version_num, "updated"
        
        else:
            # Create a brand new Skill record
            new_skill = Skill(
                name=name, slug=slugify(name), status="processing", current_version=1,
                version_hash=file_hash, 
                scope_type="department" if all_depts else "global",
                scope_id=all_depts[0] if all_depts else None
            )
            db.add(new_skill)
            await db.flush() # Get ID for M2M links
            
            if all_depts:
                for d_id in all_depts:
                    db.add(SkillDepartment(skill_id=new_skill.id, department_id=d_id))
            
            return new_skill, 1, "created"

    @staticmethod
    def _save_temp_zip(file_data: bytes) -> str:
        """
        Saves binary ZIP data to a temporary file for background ingestion.
        
        Args:
            file_data (bytes): Binary data of the ZIP.
            
        Returns:
            str: Absolute path to the saved temporary file.
        """
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, f"{uuid.uuid4()}.zip")
        with open(temp_path, "wb") as f:
            f.write(file_data)
        return temp_path

    @staticmethod
    async def upload_skills(
        db: AsyncSession, 
        files: List[Any], 
        department_ids: Optional[List[uuid.UUID]], 
        scope_type: str,
        scope_id: Optional[uuid.UUID],
        force: bool, 
        current_user_id: uuid.UUID
    ) -> List[Any]:
        """
        Main entry point for uploading multiple skill ZIP files.
        Orchestrates hashing, validation, DB updates, and background task enqueuing.
        """
        pool = await get_arq_pool()
        results = []
        duplicates = []
        jobs_to_enqueue = []

        try:
            for file in files:
                file_data = await file.read()
                name = file.filename.rsplit(".", 1)[0]
                
                # 1. Calculate Content Hash
                file_hash = SkillService._calculate_zip_content_hash(file_data)
                if not file_hash:
                    results.append({"name": name, "status": "error", "message": "Invalid ZIP file."})
                    continue

                # 2. Structural Validation (e.g. SKILL.md existence)
                err = await SkillService.validate_zip_content(file_data, name)
                if err:
                    results.append({"name": name, "status": "rejected", "message": err})
                    continue

                # 3. DB Upsert
                skill, new_v_num, status = await SkillService._upsert_skill_db_records(
                    db, name, file_hash, department_ids, scope_type, scope_id, force
                )

                if status == "duplicate":
                    duplicates.append(name)
                    continue
                
                if status == "metadata_only":
                    results.append({"name": name, "status": "updated_metadata", "message": "Metadata updated, content unchanged."})
                    continue

                # 4. Versioning & Background Job Prep
                new_version = SkillVersion(
                    skill_id=skill.id, version_number=new_v_num, version_hash=file_hash, created_by=current_user_id
                )
                db.add(new_version)
                await db.flush()

                # Save file to disk for the worker to pick up
                temp_path = SkillService._save_temp_zip(file_data)
                jobs_to_enqueue.append((str(skill.id), str(new_version.id), temp_path, file.filename))
                
                results.append(skill)

            # Error handling for duplicates in non-force mode
            if duplicates and not force:
                await db.rollback()
                raise HTTPException(status_code=409, detail={"message": "Duplicate skill names detected", "conflicts": duplicates})
                
            await db.commit()
            
            # Dispatch jobs to the background worker (arq)
            for job_args in jobs_to_enqueue:
                await pool.enqueue_job("ingest_skill_task", *job_args, _queue_name="skills_queue")
                
        except Exception as e:
            # Cleanup any temp files if the whole transaction fails
            for job_args in jobs_to_enqueue:
                temp_path = job_args[2]
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
            raise e

        return results

    @staticmethod
    async def reupload_skill(db: AsyncSession, slug: str, file: Any, current_user_id: uuid.UUID) -> Dict:
        """
        Updates an existing skill with a new version from a ZIP file.
        Enforces filename consistency and skips update if content hash is identical.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): Skill slug or ID.
            file (Any): Uploaded file object.
            current_user_id (uuid.UUID): ID of the user performing the update.
            
        Returns:
            Dict: Status and information about the processing version.
        """
        pool = await get_arq_pool()
        
        # 1. Locate existing skill
        try:
            skill_uuid = uuid.UUID(slug)
            stmt = select(Skill).where(Skill.id == skill_uuid)
        except ValueError:
            stmt = select(Skill).where(Skill.slug == slug)

        res = await db.execute(stmt)
        skill = res.scalars().first()
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        # 2. Read and Validate Content
        file_data = await file.read()
        file_hash = SkillService._calculate_zip_content_hash(file_data)
        if not file_hash:
             raise HTTPException(status_code=400, detail="Invalid ZIP file.")

        zip_name = file.filename.rsplit(".", 1)[0]
        
        # Strict check: Filename must match skill name to prevent accidental overwrites
        if zip_name != skill.name:
            raise HTTPException(status_code=400, detail=f"Filename mismatch. Expected '{skill.name}.zip', got '{file.filename}'.")

        # Optimization: Skip if content hash is exactly the same
        if skill.version_hash == file_hash:
            return {
                "status": "skipped", 
                "message": "Content unchanged. No new version created.", 
                "skill_id": str(skill.id), 
                "version": skill.current_version
            }

        # Validate structural integrity (e.g. SKILL.md)
        err = await SkillService.validate_zip_content(file_data, zip_name)
        if err:
            raise HTTPException(status_code=400, detail=err)

        # 3. Prepare New Version
        new_version_num = skill.current_version + 1
        skill.status = "processing"
        skill.version_hash = file_hash
        
        new_version = SkillVersion(
            skill_id=skill.id, 
            version_number=new_version_num, 
            version_hash=file_hash, 
            created_by=current_user_id
        )
        db.add(new_version)
        
        # 4. Storage & Background Task
        temp_path = SkillService._save_temp_zip(file_data)
        
        try:
            await db.commit()
            await pool.enqueue_job(
                "ingest_skill_task", 
                str(skill.id), 
                str(new_version.id), 
                temp_path, 
                file.filename, 
                _queue_name="skills_queue"
            )
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise e
            
        return {"status": "processing", "skill_id": str(skill.id), "version": new_version_num}

    @staticmethod
    async def inspect_zip(file: Any) -> Dict:
        file_data = await file.read()
        name = file.filename.rsplit(".", 1)[0]
        readme_content = ""
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                target_readme = f"{name}/SKILL.md".lower()
                for member in zf.infolist():
                    curr = member.filename.lower()
                    if curr == "skill.md" or curr == target_readme or curr.endswith("/skill.md"):
                        with zf.open(member) as f:
                            readme_content = f.read().decode("utf-8", errors="ignore")
                        break
            return {"name": name, "description": readme_content}
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file.")
        except Exception as e:
            logger.error(f"Error inspecting zip: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @staticmethod
    def _apply_skill_filters(
        stmt,
        q: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[uuid.UUID] = None,
        ids: Optional[List[uuid.UUID]] = None,
        allowed_department_ids: Optional[List[uuid.UUID]] = None
    ):
        """
        Applies shared filtering logic to a Skill SQLAlchemy statement.
        Used by both the main list query and the count query for consistency.

        Args:
            stmt: The SQLAlchemy select statement.
            q (str): Search query for name.
            department_id (UUID): Filter by specific department link.
            scope_type (str): Filter by scope type (global/department).
            scope_id (UUID): Filter by specific scope ID.
            ids (List[UUID]): Filter by a specific set of Skill IDs.
            allowed_department_ids (List[UUID]): RBAC filter for accessible departments.
            
        Returns:
            The modified statement.
        """
        # 1. RBAC Filtering: Visible if Global (no depts) OR user's dept matches
        if allowed_department_ids is not None:
            rbac_filter = or_(
                ~Skill.departments.any(),
                Skill.departments.any(SkillDepartment.department_id.in_(allowed_department_ids))
            )
            stmt = stmt.where(rbac_filter)

        # 2. Status Filtering: Hide soft-deleted items
        stmt = stmt.where(Skill.status != "deleting")

        # 3. ID-based Filtering
        if ids:
            stmt = stmt.where(Skill.id.in_(ids))

        # 4. Search Query (Case-insensitive)
        if q:
            stmt = stmt.where(Skill.name.ilike(f"%{q}%"))

        # 5. Department/Scope Filtering
        if department_id:
            stmt = stmt.where(Skill.departments.any(SkillDepartment.department_id == department_id))
            
        if scope_type:
            stmt = stmt.where(Skill.scope_type == scope_type)
            if scope_id:
                stmt = stmt.where(Skill.scope_id == scope_id)
        
        return stmt

    @staticmethod
    async def list_skills(
        db: AsyncSession, 
        q: Optional[str], 
        department_id: Optional[uuid.UUID], 
        scope_type: Optional[str],
        scope_id: Optional[uuid.UUID],
        ids: Optional[List[uuid.UUID]], 
        cursor: Optional[str], 
        limit: int,
        allowed_department_ids: Optional[List[uuid.UUID]] = None
    ) -> Tuple[List[Skill], int]:
        """
        Retrieves a paginated and filtered list of skills.
        
        Args:
            db (AsyncSession): Database session.
            q (str): Search keyword for name.
            department_id (UUID): Filter by a specific department.
            scope_type (str): Filter by scope type.
            scope_id (UUID): Filter by scope target ID.
            ids (List[UUID]): Specific skill IDs to fetch.
            cursor (str): Slug of the last seen item for stable pagination.
            limit (int): Max items to return.
            allowed_department_ids (List[UUID]): RBAC filter based on user access.
            
        Returns:
            Tuple[List[Skill], int]: A list of Skill objects and the total count.
        """
        # Base query with eager loading of departments
        stmt = select(Skill).options(
            selectinload(Skill.departments).selectinload(SkillDepartment.department)
        ).order_by(Skill.updated_at.desc(), Skill.id.desc())

        # Handle cursor-based pagination
        if cursor:
            ref_skill_res = await db.execute(select(Skill).where(Skill.slug == cursor))
            ref_skill = ref_skill_res.scalars().first()
            if ref_skill:
                stmt = stmt.where(or_(
                    Skill.updated_at < ref_skill.updated_at, 
                    and_(Skill.updated_at == ref_skill.updated_at, Skill.id < ref_skill.id)
                ))

        # Apply common filters to the data query
        stmt = SkillService._apply_skill_filters(
            stmt, q, department_id, scope_type, scope_id, ids, allowed_department_ids
        )

        # Build and apply filters to the count query
        count_stmt = select(func.count(func.distinct(Skill.id))).select_from(Skill)
        count_stmt = SkillService._apply_skill_filters(
            count_stmt, q, department_id, scope_type, scope_id, ids, allowed_department_ids
        )

        # Execute count query
        total_res = await db.execute(count_stmt)
        total = total_res.scalar() or 0

        # Execute data query with limit
        stmt = stmt.limit(limit)
        res = await db.execute(stmt)
        return list(res.scalars().unique().all()), total



    @staticmethod
    async def get_skill(db: AsyncSession, slug: str, version_number: Optional[int] = None) -> Skill:
        """
        Retrieves a single skill by either its UUID or unique slug.
        Automatically eager-loads associated departments.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): The skill's identifier (UUID string or slug).
            version_number (int, optional): If provided, validates that the specific version exists.
            
        Returns:
            Skill: The Skill ORM object.
            
        Raises:
            HTTPException: 404 if the skill is not found or is marked as 'deleting'.
        """
        try:
            # Determine if we are querying by UUID or Slug
            try:
                skill_uuid = uuid.UUID(slug)
                stmt = select(Skill).where(Skill.id == skill_uuid)
            except ValueError:
                stmt = select(Skill).where(Skill.slug == slug)
            
            # Eager load departments to avoid N+1 issues
            stmt = stmt.options(selectinload(Skill.departments).selectinload(SkillDepartment.department))
            res = await db.execute(stmt)
            skill = res.scalars().first()
            
            if not skill or skill.status == "deleting":
                raise HTTPException(status_code=404, detail="Skill not found")


            # Validate specific version if requested
            if version_number and version_number != skill.current_version:
                v_stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version_number == version_number)
                v_res = await db.execute(v_stmt)
                version = v_res.scalars().first()
                if not version:
                    raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
            
            return skill
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving skill '{slug}': {e}")
            raise HTTPException(status_code=500, detail="Internal server error while fetching skill")

    @staticmethod
    async def list_versions(db: AsyncSession, slug: str) -> List[SkillVersion]:
        """
        Retrieves the full version history for a given skill.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): Skill identifier (UUID or slug).
            
        Returns:
            List[SkillVersion]: List of versions ordered by version number descending.
        """
        skill = await SkillService.get_skill(db, slug)
        stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id).order_by(SkillVersion.version_number.desc())
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def set_latest_version(db: AsyncSession, slug: str, version_number: int) -> Skill:
        """
        Changes the current active version of a skill to a specific historical version.
        Updates the main Skill record's version, hash, and storage path.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): Skill identifier (UUID or slug).
            version_number (int): The version number to promote as current.
            
        Returns:
            Skill: The updated Skill object.
            
        Raises:
            HTTPException: 404 if the requested version number does not exist.
        """
        skill = await SkillService.get_skill(db, slug)
        if version_number == skill.current_version:
            return skill
            
        stmt = select(SkillVersion).where(SkillVersion.skill_id == skill.id, SkillVersion.version_number == version_number)
        res = await db.execute(stmt)
        version = res.scalars().first()
        if not version:
            raise HTTPException(status_code=404, detail=f"Version {version_number} not found")
            
        # Update main skill record with version metadata
        skill.current_version = version_number
        skill.version_hash = version.version_hash
        skill.storage_path = version.storage_path
        

        await db.commit()
        await db.refresh(skill)
        return skill

    @staticmethod
    async def delete_skill(db: AsyncSession, slug: str):
        """
        Performs a soft-delete by marking the skill as 'deleting' and enqueuing a cleanup task.
        This ensures the skill is immediately hidden from the UI while storage is cleaned up in the background.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): Skill identifier (UUID or slug).
        """
        logger.info(f"Deleting skill: {slug}")
        skill = await SkillService.get_skill(db, slug)
        
        # Atomically mark as deleting to prevent further access
        logger.info(f"Marking skill {skill.id} as deleting")
        skill.status = "deleting"
        await db.commit()
        
        try:
            # Dispatch background task for storage (MinIO) cleanup
            pool = await get_arq_pool()
            await pool.enqueue_job("delete_skill_task", str(skill.id), _queue_name="skills_queue")
            logger.info(f"Queued deletion task for skill {skill.id}")
        except Exception as e:
            logger.error(f"Failed to enqueue deletion task for skill {skill.id}: {e}")
            # Note: Skill is already hidden in DB, so it's safe even if task fails initially.

    @staticmethod
    async def update_skill(db: AsyncSession, slug: str, req_data: dict) -> Skill:
        """
        Updates a skill's metadata, including name, slug, and department visibility.
        Ensures all provided departments (from both scope_id and department_ids) are saved.
        
        Args:
            db (AsyncSession): Database session.
            slug (str): Skill identifier (UUID or slug).
            req_data (dict): Dictionary containing the fields to update.
            
        Returns:
            Skill: The updated Skill object.
        """
        skill = await SkillService.get_skill(db, slug)
        
        name = req_data.get("name")
        department_ids = req_data.get("department_ids")
        is_department_explicit = "department_ids" in req_data.get("_explicit_fields", [])
        scope_type = req_data.get("scope_type")
        scope_id = req_data.get("scope_id")
        is_scope_explicit = "scope_type" in req_data.get("_explicit_fields", [])

        # 1. Update Name and Slug
        if name is not None and name != skill.name:
            stmt = select(Skill).where(Skill.name == name, Skill.id != skill.id)
            res = await db.execute(stmt)
            if res.scalars().first():
                raise HTTPException(status_code=409, detail=f"Skill with name '{name}' already exists.")
            skill.name = name
            skill.slug = slugify(name)

        # 2. Update Visibility / Departments (Merged Logic)
        if (scope_type is not None or is_scope_explicit or 
            department_ids is not None or is_department_explicit):
            
            # Combine all unique department IDs from both sources
            all_depts = list(set(filter(None, (department_ids or []) + ([scope_id] if scope_id else []))))
            
            if all_depts:
                skill.scope_type = "department"
                # Primary department ID for legacy/fast-filtering
                skill.scope_id = scope_id or all_depts[0]
                
                # Sync Many-to-Many links
                await db.execute(sa.delete(SkillDepartment).where(SkillDepartment.skill_id == skill.id))
                for d_id in all_depts:
                    db.add(SkillDepartment(skill_id=skill.id, department_id=d_id))
            else:
                # If explicitly set to global or no departments provided
                skill.scope_type = "global"
                skill.scope_id = None
                await db.execute(sa.delete(SkillDepartment).where(SkillDepartment.skill_id == skill.id))

        await db.commit()
        await db.refresh(skill)
        return skill

    @staticmethod
    async def create_contribution(
        db: AsyncSession,
        skill_id: Optional[uuid.UUID],
        base_version: Optional[int],
        user_id: uuid.UUID,
        title: str,
        scope_type: str = "global",
        scope_ids: Optional[List[uuid.UUID]] = None
    ) -> SkillContribution:
        contribution = SkillContribution(
            skill_id=skill_id,
            contributor_id=user_id,
            base_version=base_version,
            title=title,
            scope_type=scope_type,
            scope_ids=[str(i) for i in scope_ids] if scope_ids else None,
            status=SkillContributionStatus.DRAFT.value
        )
        db.add(contribution)
        await db.flush() # Get the ID
        contribution.storage_path = f"skill-contributions/{contribution.id}/"
        
        # Determine skill slug for the root folder
        skill_slug = ""
        if skill_id:
            skill_stmt = select(Skill).where(Skill.id == skill_id)
            skill_res = await db.execute(skill_stmt)
            skill_obj = skill_res.scalars().first()
            if skill_obj:
                skill_slug = skill_obj.slug
        
        if not skill_slug:
            # For new skills, derive slug from title
            import re
            skill_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        # Fork from base version if provided
        if skill_id and base_version:
            # Find the storage path of the base version
            stmt = select(SkillVersion).where(
                SkillVersion.skill_id == skill_id,
                SkillVersion.version_number == base_version
            )
            v_res = await db.execute(stmt)
            v_obj = v_res.scalars().first()
            if v_obj and v_obj.storage_path:
                # Copy files in background thread
                import asyncio
                # The files are already inside a folder in the source, so we copy them as is
                await asyncio.to_thread(storage_service.copy_prefix, v_obj.storage_path, contribution.storage_path)
            else:
                logger.warning(f"Base version {base_version} for skill {skill_id} not found.")
        else:
            # New skill contribution - create folder structure with SKILL.md
            readme_content = f"# {title}\n\nGenerated by contribution request."
            storage_service.upload_file(
                f"{contribution.storage_path}{skill_slug}/SKILL.md",
                readme_content.encode("utf-8"),
                content_type="text/markdown"
            )
            
        await db.commit()
        await db.refresh(contribution)
        return contribution

    @staticmethod

    async def bulk_change_scope(
        db: AsyncSession, 
        skill_ids: List[uuid.UUID], 
        scope_type: str,
        scope_id: Optional[uuid.UUID]
    ) -> int:
        if not skill_ids:
            return 0
        
        # Sync department_ids for compatibility
        dept_ids = [scope_id] if (scope_type == "department" and scope_id) else []
        
        stmt = sa.update(Skill).where(Skill.id.in_(skill_ids)).values(
            scope_type=scope_type,
            scope_id=scope_id
        )
        await db.execute(stmt)

        # Update M2M for all skills
        await db.execute(sa.delete(SkillDepartment).where(SkillDepartment.skill_id.in_(skill_ids)))
        if dept_ids:
            for skill_id in skill_ids:
                for d_id in dept_ids:
                    db.add(SkillDepartment(skill_id=skill_id, department_id=d_id))
        await db.commit()
        return len(skill_ids)

    @staticmethod
    async def submit_contribution(db: AsyncSession, contribution_id: uuid.UUID):
        contribution = await db.get(SkillContribution, contribution_id)
        if not contribution:
            raise HTTPException(404, "Contribution not found")
        contribution.status = SkillContributionStatus.PENDING.value
        await db.commit()
        return contribution

    @staticmethod
    async def approve_contribution(
        db: AsyncSession, 
        contribution_id: uuid.UUID, 
        admin_id: uuid.UUID,
        final_scope_type: Optional[str] = None,
        final_scope_ids: Optional[List[uuid.UUID]] = None
    ):
        from sqlalchemy.orm import selectinload
        stmt = select(SkillContribution).where(SkillContribution.id == contribution_id).options(selectinload(SkillContribution.skill))
        res = await db.execute(stmt)
        contribution = res.scalars().first()
        
        if not contribution:
            raise HTTPException(404, "Contribution not found")
        
        # 1. Calculate contribution hash and check for duplicates
        contribution_hash = storage_service.calculate_prefix_hash(contribution.storage_path)

        if contribution.skill_id:
            # Check against all previous versions
            stmt_v = select(SkillVersion).where(
                SkillVersion.skill_id == contribution.skill_id,
                SkillVersion.version_hash == contribution_hash
            )
            v_dup_res = await db.execute(stmt_v)
            if v_dup_res.scalars().first():
                contribution.status = SkillContributionStatus.REJECTED.value
                await db.commit()
                raise HTTPException(400, "This contribution is identical to an existing version of the skill.")

        # 2. Determine final scope and departments
        # Use provided final values, otherwise fallback to contribution values
        scope_type = final_scope_type or contribution.scope_type
        scope_ids = final_scope_ids if final_scope_ids is not None else contribution.scope_ids

        # 3. Update or Create Skill
        skill = contribution.skill
        
        if not skill:
            # Create new skill
            skill = Skill(
                name=contribution.title,
                slug=slugify(contribution.title),
                current_version=0,
                status="processing",
                scope_type=scope_type,
                version_hash=contribution_hash
            )
            db.add(skill)
            await db.flush()
        else:
            # Update existing skill metadata if overridden
            if final_scope_type:
                skill.scope_type = final_scope_type
        
        # 4. Sync Departments
        # Clear existing and add new if scope is department
        if scope_type == "department" and scope_ids:
            from sqlalchemy import delete

            from app.database.models import SkillDepartment
            # Remove old links (if updating)
            await db.execute(delete(SkillDepartment).where(SkillDepartment.skill_id == skill.id))
            # Add new links
            for d_id in scope_ids:
                db.add(SkillDepartment(skill_id=skill.id, department_id=d_id))
            
            # Legacy support: set primary scope_id
            if len(scope_ids) > 0:
                skill.scope_id = scope_ids[0]
        elif scope_type == "global":
            from sqlalchemy import delete

            from app.database.models import SkillDepartment
            await db.execute(delete(SkillDepartment).where(SkillDepartment.skill_id == skill.id))
            skill.scope_id = None
        
        # 5. Create New Version
        new_v = skill.current_version + 1
        v_path = f"skills/{skill.id}/versions/{new_v}/"
        
        # 6. Copy files from contribution to skill version
        import asyncio
        await asyncio.to_thread(storage_service.copy_prefix, contribution.storage_path, v_path)
        
        # 7. Finalize Skill Version record
        new_version = SkillVersion(
            skill_id=skill.id,
            version_number=new_v,
            version_hash=contribution_hash,
            storage_path=v_path,
            changelog=f"Approved contribution: {contribution.title}",
            created_by=contribution.contributor_id
        )
        db.add(new_version)
        
        # 8. Update Skill master record
        skill.current_version = new_v
        skill.storage_path = v_path 
        skill.version_hash = contribution_hash
        skill.status = "active"
        
        # 9. Mark contribution as approved
        contribution.status = SkillContributionStatus.APPROVED.value
        contribution.skill_id = skill.id # Link if it was new
        
        await db.commit()
        return skill

    @staticmethod
    async def reject_contribution(db: AsyncSession, contribution_id: uuid.UUID):
        contribution = await db.get(SkillContribution, contribution_id)
        if not contribution:
            raise HTTPException(404, "Contribution not found")
        
        contribution.status = SkillContributionStatus.DRAFT.value
        await db.commit()
        return contribution

    @staticmethod
    async def create_contribution_from_zip(
        db: AsyncSession, 
        file: Any, 
        user: Employee,
        skill_id: Optional[uuid.UUID] = None,
        base_version: Optional[int] = None
    ) -> SkillContribution:
        """
        Initializes a skill contribution by extracting an uploaded ZIP file.
        Used for the user-driven contribution workflow where admin approval is required.
        Each file within the ZIP is individually uploaded to a contribution-specific storage path.
        
        Args:
            db (AsyncSession): Database session.
            file (Any): Uploaded ZIP file object.
            user (Employee): The contributor.
            skill_id (UUID, optional): Targeted skill if this is an update contribution.
            base_version (int, optional): The version number this contribution intends to update.
            
        Returns:
            SkillContribution: The initialized contribution record in DRAFT status.
        """
        file_data = await file.read()
        zip_name = file.filename.rsplit(".", 1)[0]
        # 1. Determine target root folder name (skill_slug)
        skill_slug = ""
        if skill_id:
            skill_stmt = select(Skill).where(Skill.id == skill_id)
            skill_res = await db.execute(skill_stmt)
            skill_obj = skill_res.scalars().first()
            if skill_obj:
                skill_slug = skill_obj.slug
        
        if not skill_slug:
            skill_slug = slugify(zip_name)

        # 2. Create contribution record
        contribution = SkillContribution(
            contributor_id=user.id,
            skill_id=skill_id,
            base_version=base_version,
            status=SkillContributionStatus.PENDING.value,
            title=f"Upload: {zip_name}",
        )
        db.add(contribution)
        await db.flush()
        
        contribution.storage_path = f"skill-contributions/{contribution.id}/"
        
        # 3. Extract ZIP to storage
        from app.services.storage_service import storage_service
        try:
            with zipfile.ZipFile(io.BytesIO(file_data)) as zf:
                # Detect if ZIP already has a consistent single root folder
                all_files = [m.filename for m in zf.infolist() if not m.is_dir()]
                if not all_files:
                    raise HTTPException(400, "ZIP file contains no files.")
                
                # A ZIP has a single root if all file paths contain at least one '/' 
                # and share the same first segment.
                first_segments = {p.split('/')[0] for p in all_files}
                has_single_root = len(first_segments) == 1 and all('/' in p for p in all_files)
                
                for member in zf.infolist():
                    if member.is_dir(): 
                        continue
                    
                    # Extract content
                    with zf.open(member) as f:
                        content = f.read()
                    
                    member_path = member.filename
                    
                    # If the ZIP is "flat" (files at root), wrap them in skill_slug/
                    if not has_single_root:
                        member_path = f"{skill_slug}/{member_path.lstrip('/')}"
                    
                    full_path = f"{contribution.storage_path}{member_path.lstrip('/')}"
                    
                    # Determine content type
                    is_text = any(member_path.lower().endswith(ext) for ext in [
                        ".py", ".md", ".txt", ".json", ".yaml", ".yml", ".sh", ".js", ".ts", ".tsx", 
                        ".html", ".css", ".sql", ".env", ".cfg", ".ini", ".xml", ".csv", ".bat", ".ps1"
                    ])
                    content_type = "text/plain" if is_text else "application/octet-stream"
                    
                    storage_service.upload_file(full_path, content, content_type=content_type)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to ingest ZIP to contribution: {e}")
            raise HTTPException(500, f"ZIP extraction failed: {str(e)}")
            
        await db.commit()
        return contribution
