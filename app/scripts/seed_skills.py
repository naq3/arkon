"""
Seed built-in skills from the skills/ directory into DB + MinIO.

Runs after Alembic migrations in entrypoint.sh and as a lifespan guard in main.py.
Idempotent: skips skills whose content hash has not changed.
"""

import asyncio
import io
import mimetypes
import zipfile
from pathlib import Path

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import async_session_factory
from app.database.models import Skill, SkillVersion
from app.services.skill_service import SkillService
from app.services.storage_service import storage_service


def _build_zip(skill_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file():
                arcname = f"{skill_dir.name}/{f.relative_to(skill_dir).as_posix()}"
                zf.writestr(arcname, f.read_bytes())
    return buf.getvalue()


def _upload_to_minio(zip_bytes: bytes, skill_id: str, version_num: int) -> None:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            with zf.open(member) as f:
                content = f.read()
            object_name = f"skills/{skill_id}/versions/{version_num}/content/{member.filename}"
            content_type = mimetypes.guess_type(member.filename)[0] or "application/octet-stream"
            storage_service.upload_file(
                object_name=object_name,
                data=content,
                content_type=content_type,
            )


async def _seed_one(skill_dir: Path) -> None:
    import uuid as _uuid

    slug = skill_dir.name
    zip_bytes = _build_zip(skill_dir)
    content_hash = SkillService._calculate_zip_content_hash(zip_bytes)

    async with async_session_factory() as session:
        result = await session.execute(select(Skill).where(Skill.slug == slug))
        skill = result.scalar_one_or_none()

        if skill is not None:
            if skill.version_hash == content_hash:
                logger.info(f"Built-in skill '{slug}' already up to date (v{skill.current_version})")
                return

            # Content changed → new version
            new_v = skill.current_version + 1
            version = SkillVersion(skill_id=skill.id, version_number=new_v, created_by=None)
            session.add(version)
            await session.flush()

            _upload_to_minio(zip_bytes, str(skill.id), new_v)

            storage_path = f"skills/{skill.id}/versions/{new_v}/content/"
            skill.current_version = new_v
            skill.version_hash = content_hash
            skill.storage_path = storage_path
            skill.status = "active"
            version.storage_path = storage_path
            version.version_hash = content_hash
            await session.commit()
            logger.success(f"Updated built-in skill '{slug}' to v{new_v}")
        else:
            skill_id = _uuid.uuid4()
            skill = Skill(
                id=skill_id,
                name=slug,
                slug=slug,
                scope_type="global",
                current_version=1,
                version_hash=content_hash,
                is_system=True,
                status="active",
            )
            session.add(skill)
            await session.flush()

            version = SkillVersion(
                skill_id=skill_id, version_number=1, created_by=None,
            )
            session.add(version)
            await session.flush()

            _upload_to_minio(zip_bytes, str(skill_id), 1)

            storage_path = f"skills/{skill_id}/versions/1/content/"
            skill.storage_path = storage_path
            version.storage_path = storage_path
            version.version_hash = content_hash
            await session.commit()
            logger.success(f"Seeded built-in skill '{slug}' (v1)")


async def seed_builtin_skills(skills_root: str | None = None) -> None:
    if skills_root is None:
        skills_root = Path(__file__).parent.parent.parent / "skills"
    else:
        skills_root = Path(skills_root)

    if not skills_root.exists():
        logger.warning(f"Skills directory not found at {skills_root}, skipping built-in seed")
        return

    # Ensure MinIO bucket exists before any upload attempts
    try:
        await storage_service.ensure_bucket()
    except Exception as e:
        logger.warning(f"MinIO not available, skipping built-in skill seed: {e}")
        return

    skill_dirs = sorted(d for d in skills_root.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    if not skill_dirs:
        logger.info("No built-in skill directories found, skipping seed")
        return

    for skill_dir in skill_dirs:
        try:
            await _seed_one(skill_dir)
        except IntegrityError:
            logger.info(f"Built-in skill '{skill_dir.name}' already seeded by concurrent process")
        except Exception as e:
            logger.error(f"Failed to seed built-in skill '{skill_dir.name}': {e}")


if __name__ == "__main__":
    asyncio.run(seed_builtin_skills())
