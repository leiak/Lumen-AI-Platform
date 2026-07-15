"""M35: /api/v1/playbooks/* endpoints.

CRUD for tenant playbooks. Built-in playbooks (is_builtin=True) are
read-only: the API refuses PUT/DELETE on them. The /import-yaml
endpoint accepts a YAML string + a name and creates a new playbook
(used by the frontend's "Import YAML" button).

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.playbook import Playbook
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.playbook import (
    PlaybookCreate, PlaybookRead, PlaybookListItem, PlaybookUpdate,
)
from lumen_services.playbook_service import (
    list_for_tenant, get_for_tenant, load_yaml,
)

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


@router.get("/", response_model=PaginatedResponse[PlaybookListItem])
def list_playbooks(
    scope: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List playbooks visible to the current tenant.

    Built-ins (tenant_id=1, is_builtin=True) are always included unless
    ``scope`` is given (then in-memory filtered to playbooks that
    include the target).
    """
    rows, total = list_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        scope=scope,
        page=page,
        page_size=page_size,
    )
    items = [PlaybookListItem.model_validate(r) for r in rows]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/{playbook_id}", response_model=SingleResponse[PlaybookRead])
def get_playbook(
    playbook_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pb = get_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        playbook_id=playbook_id,
    )
    if not pb:
        raise HTTPException(404, "Playbook not found")
    return SingleResponse(data=PlaybookRead.model_validate(pb))


@router.post("/", response_model=SingleResponse[PlaybookRead])
def create_playbook(
    data: PlaybookCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new playbook for the current tenant. Built-in playbooks
    must be created via the seed script, not the API."""
    style_tokens = _safe_parse(data.yaml_content)
    # Unique constraint on (tenant_id, name). Detect early to give a
    # clear 409 instead of a 500.
    existing = (
        db.query(Playbook)
        .filter(
            Playbook.tenant_id == current_user.tenant_id,
            Playbook.name == data.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, f"Playbook with name {data.name!r} already exists")
    pb = Playbook(
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        yaml_content=data.yaml_content,
        style_tokens=style_tokens,
        scope=data.scope,
        is_builtin=False,
        created_by=current_user.id,
    )
    db.add(pb)
    db.commit()
    db.refresh(pb)
    return SingleResponse(data=PlaybookRead.model_validate(pb))


@router.put("/{playbook_id}", response_model=SingleResponse[PlaybookRead])
def update_playbook(
    playbook_id: int,
    data: PlaybookUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pb = get_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        playbook_id=playbook_id,
    )
    if not pb:
        raise HTTPException(404, "Playbook not found")
    if pb.is_builtin:
        raise HTTPException(403, "Built-in playbooks are read-only")
    update_data = data.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(pb, k, v)
    if "yaml_content" in update_data:
        pb.style_tokens = _safe_parse(pb.yaml_content)  # type: ignore[assignment]
    db.commit()
    db.refresh(pb)
    return SingleResponse(data=PlaybookRead.model_validate(pb))


@router.delete("/{playbook_id}", status_code=204)
def delete_playbook(
    playbook_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pb = get_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        playbook_id=playbook_id,
    )
    if not pb:
        raise HTTPException(404, "Playbook not found")
    if pb.is_builtin:
        raise HTTPException(403, "Built-in playbooks cannot be deleted")
    db.delete(pb)
    db.commit()
    return None


@router.post("/import-yaml", response_model=SingleResponse[PlaybookRead])
def import_yaml(
    data: PlaybookCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Same as POST /playbooks but semantically named for the UI's
    "Import YAML" button. Validates YAML and parses style_tokens."""
    style_tokens = _safe_parse(data.yaml_content)
    existing = (
        db.query(Playbook)
        .filter(
            Playbook.tenant_id == current_user.tenant_id,
            Playbook.name == data.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(409, f"Playbook with name {data.name!r} already exists")
    pb = Playbook(
        tenant_id=current_user.tenant_id,
        name=data.name,
        description=data.description,
        yaml_content=data.yaml_content,
        style_tokens=style_tokens,
        scope=data.scope,
        is_builtin=False,
        created_by=current_user.id,
    )
    db.add(pb)
    db.commit()
    db.refresh(pb)
    return SingleResponse(data=PlaybookRead.model_validate(pb))


def _safe_parse(yaml_text: str) -> dict:
    """Parse YAML, returning {} on any error so the API can save the
    raw text and the user can fix it later. Errors are surfaced on
    the create endpoint via the schema's pre-validation path."""
    from lumen_services.playbook_service import PlaybookValidationError
    try:
        return load_yaml(yaml_text)
    except PlaybookValidationError:
        return {}
