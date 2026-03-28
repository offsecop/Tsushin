"""
Phase 22: Custom Skills Foundation - CRUD API Routes

Provides endpoints for creating, reading, updating, and deleting
tenant-created custom skills. Includes Sentinel scan integration
for instruction-based skills and version tracking for audit/rollback.
"""

import re
import logging
from datetime import datetime
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models import CustomSkill, CustomSkillVersion, AgentCustomSkill, CustomSkillExecution
from models_rbac import User
from auth_dependencies import (
    TenantContext,
    get_tenant_context,
    require_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Global engine reference
_engine = None


def set_engine(engine):
    """Set the global engine reference"""
    global _engine
    _engine = engine


def get_db():
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=_engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== Pydantic Schemas ====================

class CustomSkillCreate(BaseModel):
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    skill_type_variant: str = Field(default="instruction")
    execution_mode: str = Field(default="tool")
    instructions_md: Optional[str] = None
    trigger_mode: str = Field(default="llm_decided")
    trigger_keywords: List[str] = Field(default_factory=list)
    input_schema: Optional[dict] = Field(default_factory=dict)
    config_schema: Optional[list] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30)
    priority: int = Field(default=50)
    sentinel_profile_id: Optional[int] = None


class CustomSkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    skill_type_variant: Optional[str] = None
    execution_mode: Optional[str] = None
    instructions_md: Optional[str] = None
    trigger_mode: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    input_schema: Optional[dict] = None
    config_schema: Optional[list] = None
    timeout_seconds: Optional[int] = None
    priority: Optional[int] = None
    is_enabled: Optional[bool] = None
    sentinel_profile_id: Optional[int] = None


class CustomSkillResponse(BaseModel):
    id: int
    tenant_id: str
    source: str
    slug: str
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    skill_type_variant: str
    execution_mode: str
    instructions_md: Optional[str] = None
    input_schema: Optional[dict] = None
    output_schema: Optional[dict] = None
    config_schema: Optional[list] = None
    trigger_mode: str
    trigger_keywords: Optional[List[str]] = None
    priority: int
    sentinel_profile_id: Optional[int] = None
    timeout_seconds: int
    is_enabled: bool
    scan_status: str
    last_scan_result: Optional[dict] = None
    version: str
    created_by: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class CustomSkillVersionResponse(BaseModel):
    id: int
    custom_skill_id: int
    version: str
    snapshot_json: dict
    changed_by: Optional[int] = None
    changed_at: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== Helpers ====================

def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a skill name."""
    slug = name.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def _to_response(skill: CustomSkill) -> CustomSkillResponse:
    """Convert a CustomSkill model to a response schema."""
    return CustomSkillResponse(
        id=skill.id,
        tenant_id=skill.tenant_id,
        source=skill.source,
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        icon=skill.icon,
        skill_type_variant=skill.skill_type_variant,
        execution_mode=skill.execution_mode,
        instructions_md=skill.instructions_md,
        input_schema=skill.input_schema,
        output_schema=skill.output_schema,
        config_schema=skill.config_schema,
        trigger_mode=skill.trigger_mode,
        trigger_keywords=skill.trigger_keywords,
        priority=skill.priority,
        sentinel_profile_id=skill.sentinel_profile_id,
        timeout_seconds=skill.timeout_seconds,
        is_enabled=skill.is_enabled,
        scan_status=skill.scan_status,
        last_scan_result=skill.last_scan_result,
        version=skill.version,
        created_by=skill.created_by,
        created_at=skill.created_at.isoformat() if skill.created_at else None,
        updated_at=skill.updated_at.isoformat() if skill.updated_at else None,
    )


def _to_version_response(v: CustomSkillVersion) -> CustomSkillVersionResponse:
    """Convert a CustomSkillVersion model to a response schema."""
    return CustomSkillVersionResponse(
        id=v.id,
        custom_skill_id=v.custom_skill_id,
        version=v.version,
        snapshot_json=v.snapshot_json,
        changed_by=v.changed_by,
        changed_at=v.changed_at.isoformat() if v.changed_at else None,
    )


async def _scan_instructions(instructions: str, db) -> dict:
    """Run Sentinel scan on instruction content. Fail-open if unavailable."""
    try:
        from services.sentinel_service import SentinelService
        sentinel = SentinelService(db)
        result = await sentinel.analyze_prompt(prompt=instructions, source=None)
        if hasattr(result, 'is_threat_detected') and result.is_threat_detected:
            return {
                "scan_status": "rejected",
                "last_scan_result": {"reason": getattr(result, 'threat_reason', 'Unknown')},
            }
        return {"scan_status": "clean", "last_scan_result": None}
    except Exception as e:
        logger.warning(f"Sentinel scan failed, defaulting to clean: {e}")
        return {"scan_status": "clean", "last_scan_result": None}


def _snapshot_skill(skill: CustomSkill) -> dict:
    """Create a JSON snapshot of the current skill state for versioning."""
    return {
        "name": skill.name,
        "description": skill.description,
        "icon": skill.icon,
        "skill_type_variant": skill.skill_type_variant,
        "execution_mode": skill.execution_mode,
        "instructions_md": skill.instructions_md,
        "input_schema": skill.input_schema,
        "output_schema": skill.output_schema,
        "config_schema": skill.config_schema,
        "trigger_mode": skill.trigger_mode,
        "trigger_keywords": skill.trigger_keywords,
        "priority": skill.priority,
        "timeout_seconds": skill.timeout_seconds,
        "version": skill.version,
    }


# ==================== Endpoints ====================

@router.get("/custom-skills", response_model=List[CustomSkillResponse])
async def list_custom_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.read")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List all custom skills for the current tenant."""
    query = db.query(CustomSkill)
    query = ctx.filter_by_tenant(query, CustomSkill.tenant_id)
    skills = query.order_by(CustomSkill.name).all()
    return [_to_response(s) for s in skills]


@router.post("/custom-skills", response_model=CustomSkillResponse, status_code=status.HTTP_201_CREATED)
async def create_custom_skill(
    payload: CustomSkillCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.create")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Create a new custom skill with optional Sentinel scan."""
    tenant_id = ctx.tenant_id

    # Generate slug
    slug = _slugify(payload.name)
    if not slug:
        raise HTTPException(status_code=400, detail="Invalid skill name (cannot generate slug)")

    # Check uniqueness
    existing = db.query(CustomSkill).filter(
        CustomSkill.tenant_id == tenant_id,
        CustomSkill.slug == slug,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A skill with slug '{slug}' already exists")

    # Validate skill_type_variant
    if payload.skill_type_variant not in ('instruction', 'script', 'mcp_server'):
        raise HTTPException(status_code=400, detail="skill_type_variant must be one of: instruction, script, mcp_server")

    # Validate execution_mode
    if payload.execution_mode not in ('tool', 'hybrid', 'passive'):
        raise HTTPException(status_code=400, detail="execution_mode must be one of: tool, hybrid, passive")

    # Validate trigger_mode
    if payload.trigger_mode not in ('keyword', 'always_on', 'llm_decided'):
        raise HTTPException(status_code=400, detail="trigger_mode must be one of: keyword, always_on, llm_decided")

    # Create skill
    skill = CustomSkill(
        tenant_id=tenant_id,
        source='tenant',
        slug=slug,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        skill_type_variant=payload.skill_type_variant,
        execution_mode=payload.execution_mode,
        instructions_md=payload.instructions_md,
        input_schema=payload.input_schema or {},
        config_schema=payload.config_schema or [],
        trigger_mode=payload.trigger_mode,
        trigger_keywords=payload.trigger_keywords or [],
        priority=payload.priority,
        sentinel_profile_id=payload.sentinel_profile_id,
        timeout_seconds=payload.timeout_seconds,
        is_enabled=True,
        scan_status='pending',
        version='1.0.0',
        created_by=current_user.id,
    )

    db.add(skill)
    db.flush()

    # Run Sentinel scan on instructions if provided
    if payload.instructions_md:
        scan_result = await _scan_instructions(payload.instructions_md, db)
        skill.scan_status = scan_result["scan_status"]
        skill.last_scan_result = scan_result.get("last_scan_result")
    else:
        skill.scan_status = 'clean'

    db.commit()
    db.refresh(skill)

    logger.info(f"Custom skill created: {skill.name} (slug={skill.slug}, tenant={tenant_id})")
    return _to_response(skill)


@router.get("/custom-skills/{skill_id}", response_model=CustomSkillResponse)
async def get_custom_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.read")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get a single custom skill by ID."""
    query = db.query(CustomSkill).filter(CustomSkill.id == skill_id)
    query = ctx.filter_by_tenant(query, CustomSkill.tenant_id)
    skill = query.first()

    if not skill:
        raise HTTPException(status_code=404, detail="Custom skill not found")

    return _to_response(skill)


@router.put("/custom-skills/{skill_id}", response_model=CustomSkillResponse)
async def update_custom_skill(
    skill_id: int,
    payload: CustomSkillUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.create")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Update a custom skill. Creates a version snapshot before applying changes."""
    query = db.query(CustomSkill).filter(CustomSkill.id == skill_id)
    query = ctx.filter_by_tenant(query, CustomSkill.tenant_id)
    skill = query.first()

    if not skill:
        raise HTTPException(status_code=404, detail="Custom skill not found")

    # Create version snapshot before updating
    version_entry = CustomSkillVersion(
        custom_skill_id=skill.id,
        version=skill.version,
        snapshot_json=_snapshot_skill(skill),
        changed_by=current_user.id,
    )
    db.add(version_entry)

    # Track if instructions changed for re-scan
    instructions_changed = False

    # Apply updates
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == 'instructions_md' and value != skill.instructions_md:
            instructions_changed = True
        setattr(skill, field, value)

    # Bump version
    parts = skill.version.split('.')
    try:
        parts[-1] = str(int(parts[-1]) + 1)
        skill.version = '.'.join(parts)
    except (ValueError, IndexError):
        skill.version = '1.0.1'

    skill.updated_at = datetime.utcnow()

    # Re-scan if instructions changed
    if instructions_changed and skill.instructions_md:
        scan_result = await _scan_instructions(skill.instructions_md, db)
        skill.scan_status = scan_result["scan_status"]
        skill.last_scan_result = scan_result.get("last_scan_result")

    db.commit()
    db.refresh(skill)

    logger.info(f"Custom skill updated: {skill.name} (id={skill.id}, version={skill.version})")
    return _to_response(skill)


@router.delete("/custom-skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_skill(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.delete")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Delete a custom skill and all associated data."""
    query = db.query(CustomSkill).filter(CustomSkill.id == skill_id)
    query = ctx.filter_by_tenant(query, CustomSkill.tenant_id)
    skill = query.first()

    if not skill:
        raise HTTPException(status_code=404, detail="Custom skill not found")

    skill_name = skill.name
    db.delete(skill)
    db.commit()

    logger.info(f"Custom skill deleted: {skill_name} (id={skill_id})")
    return None


@router.get("/custom-skills/{skill_id}/versions", response_model=List[CustomSkillVersionResponse])
async def list_custom_skill_versions(
    skill_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("skills.custom.read")),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List version history for a custom skill."""
    # Verify skill belongs to tenant
    skill_query = db.query(CustomSkill).filter(CustomSkill.id == skill_id)
    skill_query = ctx.filter_by_tenant(skill_query, CustomSkill.tenant_id)
    skill = skill_query.first()

    if not skill:
        raise HTTPException(status_code=404, detail="Custom skill not found")

    versions = db.query(CustomSkillVersion).filter(
        CustomSkillVersion.custom_skill_id == skill_id
    ).order_by(CustomSkillVersion.changed_at.desc()).all()

    return [_to_version_response(v) for v in versions]
