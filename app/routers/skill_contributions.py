import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.database.models import (
    Employee,
    Skill,
    SkillContribution,
    SkillContributionStatus,
    SkillVersion,
)
from app.routers.skills import is_text_file
from app.services.auth_service import (
    get_current_user,
    require_permission,
)
from app.services.permission_engine import _get_user_permissions
from app.services.skill_service import SkillService

router = APIRouter()

class SkillContributionCreate(BaseModel):
    skill_id: Optional[uuid.UUID] = None
    base_version: Optional[int] = None
    title: str
    scope_type: str = "global"
    scope_ids: Optional[List[uuid.UUID]] = None

class SkillContributionResponse(BaseModel):
    id: uuid.UUID
    skill_id: Optional[uuid.UUID]
    contributor_id: uuid.UUID
    base_version: Optional[int]
    status: str
    title: str
    storage_path: Optional[str]
    scope_type: str
    scope_ids: Optional[List[uuid.UUID]]
    contributor_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}

class PutFileRequest(BaseModel):
    path: str
    content: str

class SkillContributionApprove(BaseModel):
    final_scope_type: Optional[str] = None
    final_scope_ids: Optional[List[uuid.UUID]] = None

# --- Routes ---

@router.get("/skill-contributions/check")
async def check_existing_draft(
    title: str = Query(...),
    skill_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Check if the user already has a draft for this skill/title."""
    stmt = select(SkillContribution).where(
        SkillContribution.contributor_id == user.id,
        SkillContribution.status == SkillContributionStatus.DRAFT.value
    )
    if skill_id:
        stmt = stmt.where(SkillContribution.skill_id == skill_id)
    else:
        stmt = stmt.where(SkillContribution.title == title)
        
    res = await db.execute(stmt)
    draft = res.scalars().first()
    return draft

@router.post("/skill-contributions", response_model=SkillContributionResponse)
async def create_skill_contribution(
    req: SkillContributionCreate,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Start a new skill contribution (fork from a version or create new)."""
    perms = _get_user_permissions(user)
    if user.role != "admin" and "skill:create:all" not in perms:
        if "skill:create:own_dept" not in perms:
            raise HTTPException(403, "Permission required: skill:create")

    if req.skill_id:
        base_skill = await db.get(Skill, req.skill_id)
        if base_skill and base_skill.is_system:
            raise HTTPException(403, "System skills cannot be modified via contributions")

    contribution = await SkillService.create_contribution(
        db, req.skill_id, req.base_version, user.id, req.title, req.scope_type, req.scope_ids
    )
    return contribution

@router.get("/admin/skill-contributions", response_model=List[SkillContributionResponse])
async def list_pending_skill_contributions(
    skill_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: Employee = require_permission("skill:contribution:review"),
):
    """List skill contribution requests for admin review."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    
    stmt = select(SkillContribution).options(joinedload(SkillContribution.contributor))
    stmt = stmt.where(SkillContribution.status == SkillContributionStatus.PENDING.value)
    if skill_id:
        stmt = stmt.where(SkillContribution.skill_id == skill_id)
    stmt = stmt.order_by(SkillContribution.created_at.desc())
    res = await db.execute(stmt)
    contributions = res.scalars().unique().all()
    
    results = []
    for c in contributions:
        resp = SkillContributionResponse.model_validate(c)
        resp.contributor_name = c.contributor.name if c.contributor else "Unknown"
        results.append(resp)
        
    return results

@router.get("/skill-contributions", response_model=List[SkillContributionResponse])
async def list_skill_contributions(
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """List only the current user's skill contributions."""
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    
    stmt = select(SkillContribution).options(joinedload(SkillContribution.contributor))
    
    if status:
        stmt = stmt.where(SkillContribution.status == status)
    
    # Always filter by current user's ID (even for admins in this personal view)
    stmt = stmt.where(SkillContribution.contributor_id == user.id)
    
    stmt = stmt.order_by(SkillContribution.created_at.desc())
    res = await db.execute(stmt)
    contributions = res.scalars().unique().all()
    
    results = []
    for c in contributions:
        resp = SkillContributionResponse.model_validate(c)
        resp.contributor_name = c.contributor.name if c.contributor else "Unknown"
        results.append(resp)
        
    return results

@router.get("/skill-contributions/{contribution_id}", response_model=SkillContributionResponse)
async def get_skill_contribution(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Get details of a specific skill contribution."""
    from sqlalchemy.orm import joinedload
    contribution = await db.get(
        SkillContribution, 
        contribution_id,
        options=[joinedload(SkillContribution.contributor)]
    )
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id) and "skill:contribution:review" not in _get_user_permissions(user):
        logger.warning(f"[Auth] Access Denied for contribution {contribution_id}. Contributor: {contribution.contributor_id}, User: {user.id}")
        raise HTTPException(403, "Access denied")
    
    resp = SkillContributionResponse.model_validate(contribution)
    resp.contributor_name = contribution.contributor.name if contribution.contributor else "Unknown"
    return resp

@router.delete("/skill-contributions/{contribution_id}")
async def delete_skill_contribution(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Delete a skill contribution request and its storage."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id):
        raise HTTPException(403, "Access denied")
    
    if user.role != "admin" and contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, "Cannot delete an approved contribution")

    if contribution.storage_path:
        storage_service.delete_prefix(contribution.storage_path)
    
    await db.delete(contribution)
    await db.commit()
    return {"status": "ok"}

@router.get("/skill-contributions/{contribution_id}/files")
async def list_skill_contribution_files(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """List files in the temporary storage of a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id) and "skill:contribution:review" not in _get_user_permissions(user):
        raise HTTPException(403, "Access denied")

    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, f"Cannot access contribution files in status: {contribution.status}")
    
    prefix = contribution.storage_path
    if not prefix:
        return []

    from app.config import settings
    objects = storage_service.client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
    
    files = []
    for obj in objects:
        rel_path = obj.object_name.replace(prefix, "", 1)
        if not rel_path: 
            continue
        files.append({
            "path": rel_path,
            "size": obj.size,
            "is_text": is_text_file(rel_path)
        })
    return sorted(files, key=lambda x: x["path"])

@router.get("/skill-contributions/{contribution_id}/files/content")
async def get_skill_contribution_file_content(
    contribution_id: uuid.UUID,
    path: str,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Read content of a file in a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id) and "skill:contribution:review" not in _get_user_permissions(user):
        raise HTTPException(403, "Access denied")
        
    full_path = f"{contribution.storage_path}{path.lstrip('/')}"
    try:
        content_bytes = storage_service.download_file(full_path)
        return {"content": content_bytes.decode("utf-8", errors="ignore")}
    except Exception as e:
        raise HTTPException(500, f"Failed to read file: {str(e)}")

@router.post("/skill-contributions/{contribution_id}/rename")
async def rename_skill_contribution_file(
    contribution_id: uuid.UUID,
    old_path: str = Query(...),
    new_path: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Rename a file or folder in a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id):
        raise HTTPException(403, "Access denied")
    
    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, f"Cannot edit contribution in status: {contribution.status}")

    parts = old_path.strip("/").split("/")
    if len(parts) == 1:
        raise HTTPException(400, "Cannot rename the root folder.")
    
    if old_path.endswith("SKILL.md"):
        raise HTTPException(400, "Cannot rename SKILL.md.")

    full_old_path = f"{contribution.storage_path}{old_path.lstrip('/')}"
    full_new_path = f"{contribution.storage_path}{new_path.lstrip('/')}"
    
    if contribution.status == SkillContributionStatus.PENDING.value:
        contribution.status = SkillContributionStatus.DRAFT.value

    storage_service.move_prefix(full_old_path, full_new_path)
    await db.commit()
    return {"status": "ok", "old_path": old_path, "new_path": new_path, "contribution_status": contribution.status}

@router.delete("/skill-contributions/{contribution_id}/files")
async def delete_skill_contribution_file(
    contribution_id: uuid.UUID,
    path: str,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Delete a file or folder (prefix) from a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id):
        raise HTTPException(403, "Access denied")
    
    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, f"Cannot edit contribution in status: {contribution.status}")

    full_path = f"{contribution.storage_path}{path.lstrip('/')}"
    
    if contribution.status == SkillContributionStatus.PENDING.value:
        contribution.status = SkillContributionStatus.DRAFT.value

    storage_service.delete_prefix(full_path)
    await db.commit()
    return {"status": "ok", "path": path, "contribution_status": contribution.status}

@router.post("/skill-contributions/{contribution_id}/upload")
async def upload_skill_contribution_file(
    contribution_id: uuid.UUID,
    file: UploadFile = File(...),
    path: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """Upload a binary file to a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if current_user.role != "admin" and str(contribution.contributor_id) != str(current_user.id):
        raise HTTPException(403, "Access denied")
    
    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, f"Cannot edit contribution in status: {contribution.status}")

    file_path = path if path else file.filename
    
    # 1. Determine the actual root folder by checking existing files in storage
    from app.config import settings
    objects = storage_service.client.list_objects(settings.minio_bucket, prefix=contribution.storage_path, recursive=True)
    existing_files = [obj.object_name.replace(contribution.storage_path, "", 1) for obj in objects]
    
    root_folder = ""
    if existing_files:
        # Take the first segment of the first file as the root
        root_folder = existing_files[0].split('/')[0]
    
    if not root_folder:
        # Fallback to skill slug if no files exist yet
        from sqlalchemy import select

        from app.database.models import Skill
        if contribution.skill_id:
            skill_stmt = select(Skill).where(Skill.id == contribution.skill_id)
            skill_res = await db.execute(skill_stmt)
            skill_obj = skill_res.scalars().first()
            if skill_obj:
                root_folder = skill_obj.slug
        
        if not root_folder:
            from app.utils.text import slugify
            root_folder = slugify(contribution.title.replace("Upload: ", ""))

    # 2. Ensure file_path starts with the detected root_folder
    if root_folder and not file_path.startswith(f"{root_folder}/"):
        file_path = f"{root_folder}/{file_path.lstrip('/')}"

    full_path = f"{contribution.storage_path}{file_path.lstrip('/')}"
    
    try:
        if contribution.status == SkillContributionStatus.PENDING.value:
            contribution.status = SkillContributionStatus.DRAFT.value
            
        content = await file.read()
        storage_service.upload_file(full_path, content, content_type=file.content_type)
        await db.commit()
        return {"status": "ok", "path": file_path, "contribution_status": contribution.status}
    except Exception as e:
        logger.error(f"Failed to upload to MinIO: {str(e)}")
        raise HTTPException(500, f"MinIO upload failed: {str(e)}")

@router.put("/skill-contributions/{contribution_id}/files")
async def put_skill_contribution_file(
    contribution_id: uuid.UUID,
    request: PutFileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """Create or update a text file in a skill contribution."""
    from app.services.storage_service import storage_service
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if current_user.role != "admin" and str(contribution.contributor_id) != str(current_user.id):
        raise HTTPException(403, "Access denied")

    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, f"Cannot edit contribution in status: {contribution.status}")
    
    file_path = request.path
    content = request.content
    
    # 1. Determine the actual root folder by checking existing files in storage
    from app.config import settings
    objects = storage_service.client.list_objects(settings.minio_bucket, prefix=contribution.storage_path, recursive=True)
    existing_files = [obj.object_name.replace(contribution.storage_path, "", 1) for obj in objects]
    
    root_folder = ""
    if existing_files:
        # Take the first segment of the first file as the root
        root_folder = existing_files[0].split('/')[0]
    
    if not root_folder:
        # Fallback to skill slug if no files exist yet
        from sqlalchemy import select

        from app.database.models import Skill
        if contribution.skill_id:
            skill_stmt = select(Skill).where(Skill.id == contribution.skill_id)
            skill_res = await db.execute(skill_stmt)
            skill_obj = skill_res.scalars().first()
            if skill_obj:
                root_folder = skill_obj.slug
        
        if not root_folder:
            from app.utils.text import slugify
            root_folder = slugify(contribution.title.replace("Upload: ", ""))

    # 2. Ensure file_path starts with the detected root_folder
    if root_folder and not file_path.startswith(f"{root_folder}/"):
        file_path = f"{root_folder}/{file_path.lstrip('/')}"

    full_path = f"{contribution.storage_path}{file_path.lstrip('/')}"

    if contribution.status == SkillContributionStatus.PENDING.value:
        contribution.status = SkillContributionStatus.DRAFT.value

    storage_service.upload_file(full_path, content.encode("utf-8"), content_type="text/plain")
    await db.commit()
    return {"status": "ok", "path": file_path, "contribution_status": contribution.status}

@router.post("/skill-contributions/{contribution_id}/submit")
async def submit_skill_contribution(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """Submit skill contribution for review."""
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if contribution.status == SkillContributionStatus.APPROVED.value:
        raise HTTPException(400, "Contribution already approved")

    contribution = await SkillService.submit_contribution(db, contribution_id)
    return {"status": contribution.status}

@router.post("/skill-contributions/{contribution_id}/approve")
async def approve_skill_contribution(
    contribution_id: uuid.UUID,
    req: Optional[SkillContributionApprove] = None,
    db: AsyncSession = Depends(get_db),
    admin: Employee = require_permission("skill:contribution:review"),
):
    """
    Approve and merge skill contribution into the main skill.
    Enforces department-level review for non-admin users if scope is 'department'.
    """
    contribution = await db.get(SkillContribution, contribution_id)
    if contribution.status in [SkillContributionStatus.APPROVED.value,SkillContributionStatus.REJECTED.value,]:
        raise HTTPException(400, "Contribution already approved")
    
    if not contribution:
        raise HTTPException(404, "Contribution not found")

    # Permission check: 
    # 1. Global admins can approve anything.
    # 2. If scope is 'global', any reviewer can approve.
    # 3. If scope is 'department', reviewer must belong to one of the target departments.
    if admin.role != "admin" and contribution.scope_type == "department":
        target_dept_ids = [str(id) for id in (contribution.scope_ids or [])]
        if str(admin.department_id) not in target_dept_ids:
            raise HTTPException(
                403, 
                "You do not have permission to approve contributions for these departments. "
                "Reviewer must belong to one of the target departments."
            )

    # Use values from request if provided, otherwise default to None
    final_scope_type = req.final_scope_type if req else None
    final_scope_ids = req.final_scope_ids if req else None

    skill = await SkillService.approve_contribution(
        db, 
        contribution_id, 
        admin.id,
        final_scope_type=final_scope_type,
        final_scope_ids=final_scope_ids
    )
    return {
        "status": "approved", 
        "skill_id": skill.id, 
        "skill_slug": skill.slug,
        "version": skill.current_version
    }

@router.post("/skill-contributions/{contribution_id}/reject")
async def reject_skill_contribution(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: Employee = require_permission("skill:contribution:review"),
):
    """Reject a skill contribution request (moves back to draft)."""
    contribution = await SkillService.reject_contribution(db, contribution_id)
    if contribution.status in [SkillContributionStatus.APPROVED.value,SkillContributionStatus.REJECTED.value]:
        raise HTTPException(400, "Contribution already approved")
    
    return {"status": contribution.status}

@router.get("/skill-contributions/{contribution_id}/diff-status")
async def get_skill_contribution_diff_status(
    contribution_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: Employee = Depends(get_current_user),
):
    """
    Returns a map of {path: status} where status is 'A' (Added), 'D' (Deleted), or 'M' (Modified).
    """
    from app.services.storage_service import storage_service
    
    contribution = await db.get(SkillContribution, contribution_id)
    if not contribution:
        raise HTTPException(404, "Contribution not found")
    
    if user.role != "admin" and str(contribution.contributor_id) != str(user.id) and "skill:contribution:review" not in _get_user_permissions(user):
        raise HTTPException(403, "Access denied")
        
    contrib_files = storage_service.list_objects(contribution.storage_path, recursive=True)
    contrib_map = {f.object_name.replace(contribution.storage_path, "", 1).lstrip("/"): f for f in contrib_files}
    
    base_files_map = {}
    if contribution.skill_id:
        # User requested to ALWAYS compare with latest version
        stmt = select(SkillVersion).where(SkillVersion.skill_id == contribution.skill_id).order_by(SkillVersion.version_number.desc())
        v_res = await db.execute(stmt)
        v_obj = v_res.scalars().first()
        
        if v_obj:
            base_prefix = v_obj.storage_path
            base_files = storage_service.list_objects(base_prefix, recursive=True)
            
            for f in base_files:
                rel = f.object_name.replace(base_prefix, "", 1).lstrip("/")
                # Handle 'content/' prefix if present in original storage
                if rel.startswith("content/"):
                    rel = rel.replace("content/", "", 1).lstrip("/")
                
                if rel:
                    base_files_map[rel] = f

    # Determine if there's a root folder shift (e.g. contrib has 'slug/' but base doesn't, or vice-versa)
    contrib_paths = list(contrib_map.keys())
    base_paths = list(base_files_map.keys())
    
    # Simple check for common root folder in contrib
    contrib_root = ""
    if contrib_paths:
        first = contrib_paths[0]
        if "/" in first:
            root = first.split("/")[0]
            if all(p.startswith(root + "/") or p == root for p in contrib_paths):
                contrib_root = root

    # Simple check for common root folder in base
    base_root = ""
    if base_paths:
        first = base_paths[0]
        if "/" in first:
            root = first.split("/")[0]
            if all(p.startswith(root + "/") or p == root for p in base_paths):
                base_root = root

    status_map = {}
    
    # If roots match (both have it or both don't), simple comparison
    # If roots differ, we should try to match paths by stripping/adding roots
    
    def get_norm(p, root):
        if root and (p.startswith(root + "/") or p == root):
            return p[len(root):].lstrip("/")
        return p

    # Map normalized paths back to actual paths for each side
    norm_to_contrib = {get_norm(p, contrib_root): p for p in contrib_paths}
    norm_to_base = {get_norm(p, base_root): p for p in base_paths}
    
    all_norms = set(norm_to_contrib.keys()) | set(norm_to_base.keys())
    
    for norm in all_norms:
        if not norm: 
            continue
        
        p_contrib = norm_to_contrib.get(norm)
        p_base = norm_to_base.get(norm)
        
        if p_contrib and not p_base:
            status_map[p_contrib] = "A"
        elif p_base and not p_contrib:
            # For deleted files, we prefer the path WITH the contrib root if it exists
            # so it shows up in the same folder in the UI
            target_path = f"{contrib_root}/{norm}" if contrib_root else norm
            status_map[target_path] = "D"
        else:
            # Both exist
            c_file = contrib_map[p_contrib]
            b_file = base_files_map[p_base]
            if c_file.size != b_file.size or c_file.etag != b_file.etag:
                status_map[p_contrib] = "M"
                
    return status_map
