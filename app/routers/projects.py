"""
Projects router — cross-functional knowledge contexts.

A Project groups employees and sources across departments for a specific purpose
(client engagement, event, initiative). Only project members and admins can access
project-scoped sources via MCP.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.database.models import Employee, Project, ProjectMember, ProjectSource, Source
from app.services.auth_service import get_current_user, require_admin, require_permission

router = APIRouter()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # "active" or "archived"


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    status: str
    member_count: int = 0
    source_count: int = 0
    created_at: str

    class Config:
        from_attributes = True


class MemberOut(BaseModel):
    employee_id: str
    employee_name: str
    employee_email: str
    role: str
    added_at: str


class ProjectSourceOut(BaseModel):
    source_id: str
    title: Optional[str]
    source_type: Optional[str]
    status: str
    knowledge_type_name: Optional[str] = None
    added_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, uuid.UUID(project_id))
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _project_out(project: Project, member_count: int = 0, source_count: int = 0) -> ProjectOut:
    return ProjectOut(
        id=str(project.id),
        name=project.name,
        description=project.description,
        status=project.status,
        member_count=member_count,
        source_count=source_count,
        created_at=project.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# Project CRUD
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    """
    Admin: returns all projects.
    Employee: returns only projects they are a member of.
    """
    from sqlalchemy import func

    if current_user.role == "admin":
        result = await db.execute(select(Project).order_by(Project.created_at.desc()))
        projects = result.scalars().all()
    else:
        result = await db.execute(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.employee_id == current_user.id)
            .order_by(Project.created_at.desc())
        )
        projects = result.scalars().all()

    # Fetch counts in bulk
    member_counts_result = await db.execute(
        select(ProjectMember.project_id, func.count(ProjectMember.employee_id))
        .group_by(ProjectMember.project_id)
    )
    member_counts = {str(r[0]): r[1] for r in member_counts_result.all()}

    source_counts_result = await db.execute(
        select(ProjectSource.project_id, func.count(ProjectSource.source_id))
        .group_by(ProjectSource.project_id)
    )
    source_counts = {str(r[0]): r[1] for r in source_counts_result.all()}

    return [
        _project_out(p, member_counts.get(str(p.id), 0), source_counts.get(str(p.id), 0))
        for p in projects
    ]


@router.post("/projects", status_code=201, response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = require_permission("projects.manage"),
):
    project = Project(
        name=body.name,
        description=body.description,
        status="active",
        created_by_id=current_user.id,
    )
    db.add(project)
    await db.flush()
    return _project_out(project)


@router.put("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    project = await _get_project_or_404(db, project_id)

    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    if body.status is not None:
        if body.status not in ("active", "archived"):
            raise HTTPException(400, "Status must be 'active' or 'archived'")
        project.status = body.status

    await db.flush()
    return _project_out(project)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    project = await _get_project_or_404(db, project_id)
    await db.delete(project)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

class AddMemberBody(BaseModel):
    employee_id: str
    role: str = "member"


@router.get("/projects/{project_id}/members", response_model=list[MemberOut])
async def list_members(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    await _get_project_or_404(db, project_id)
    result = await db.execute(
        select(ProjectMember)
        .options(selectinload(ProjectMember.employee))
        .where(ProjectMember.project_id == uuid.UUID(project_id))
    )
    members = result.scalars().all()
    return [
        MemberOut(
            employee_id=str(m.employee_id),
            employee_name=m.employee.name,
            employee_email=m.employee.email,
            role=m.role,
            added_at=m.added_at.isoformat(),
        )
        for m in members
    ]


@router.post("/projects/{project_id}/members", status_code=201)
async def add_member(
    project_id: str,
    body: AddMemberBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    await _get_project_or_404(db, project_id)

    emp = await db.get(Employee, uuid.UUID(body.employee_id))
    if not emp:
        raise HTTPException(404, "Employee not found")

    existing = await db.get(
        ProjectMember,
        (uuid.UUID(project_id), uuid.UUID(body.employee_id)),
    )
    if existing:
        raise HTTPException(409, "Employee is already a member")

    if body.role not in ("owner", "member"):
        raise HTTPException(400, "Role must be 'owner' or 'member'")

    member = ProjectMember(
        project_id=uuid.UUID(project_id),
        employee_id=uuid.UUID(body.employee_id),
        role=body.role,
    )
    db.add(member)
    await db.flush()
    return {"added": True}


@router.delete("/projects/{project_id}/members/{employee_id}")
async def remove_member(
    project_id: str,
    employee_id: str,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    member = await db.get(
        ProjectMember,
        (uuid.UUID(project_id), uuid.UUID(employee_id)),
    )
    if not member:
        raise HTTPException(404, "Member not found")
    await db.delete(member)
    return {"removed": True}


# ---------------------------------------------------------------------------
# Project Sources
# ---------------------------------------------------------------------------

class AddSourceBody(BaseModel):
    source_id: str


@router.get("/projects/{project_id}/sources", response_model=list[ProjectSourceOut])
async def list_project_sources(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Employee = Depends(get_current_user),
):
    await _get_project_or_404(db, project_id)
    result = await db.execute(
        select(ProjectSource)
        .options(
            selectinload(ProjectSource.source).selectinload(Source.knowledge_type)
        )
        .where(ProjectSource.project_id == uuid.UUID(project_id))
    )
    rows = result.scalars().all()
    return [
        ProjectSourceOut(
            source_id=str(r.source_id),
            title=r.source.title,
            source_type=r.source.source_type,
            status=r.source.status,
            knowledge_type_name=r.source.knowledge_type.name if r.source.knowledge_type else None,
            added_at=r.added_at.isoformat(),
        )
        for r in rows
    ]


@router.post("/projects/{project_id}/sources", status_code=201)
async def add_project_source(
    project_id: str,
    body: AddSourceBody,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    await _get_project_or_404(db, project_id)

    source = await db.get(Source, uuid.UUID(body.source_id))
    if not source:
        raise HTTPException(404, "Source not found")

    existing = await db.get(
        ProjectSource,
        (uuid.UUID(project_id), uuid.UUID(body.source_id)),
    )
    if existing:
        raise HTTPException(409, "Source already in project")

    ps = ProjectSource(
        project_id=uuid.UUID(project_id),
        source_id=uuid.UUID(body.source_id),
    )
    db.add(ps)
    await db.flush()
    return {"added": True}


@router.delete("/projects/{project_id}/sources/{source_id}")
async def remove_project_source(
    project_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
    _user: Employee = require_permission("projects.manage"),
):
    ps = await db.get(
        ProjectSource,
        (uuid.UUID(project_id), uuid.UUID(source_id)),
    )
    if not ps:
        raise HTTPException(404, "Source not in project")
    await db.delete(ps)
    return {"removed": True}
