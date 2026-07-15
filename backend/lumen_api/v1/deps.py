"""Shared FastAPI dependencies.

Currently houses ``get_current_external_app`` — the widget equivalent
of ``get_current_user``. Lives here so future cross-cutting deps
(auth rate limiter, request-id injector, etc.) have a home.
"""
from __future__ import annotations

from typing import Optional
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_models.external_app import ExternalApp
from lumen_services.external_auth_service import decode_external_token


external_token_scheme = HTTPBearer(auto_error=False)


class ExternalAppContext(BaseModel):
    """What every /external/* endpoint sees via Depends. Carries the
    decoded JWT claims + the resolved visitor/agent whitelists.

    Not a SQLAlchemy row — endpoints must not accidentally mutate it
    and persist the changes; the model instances are deliberately not
    attached.
    """
    app_id: int
    tenant_id: int
    visitor_id: int
    visitor_uuid: str
    allowed_agent_ids: list[int]
    allowed_team_ids: list[int]
    scopes: list[str]


def get_current_external_app(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(external_token_scheme),
    db: Session = Depends(get_db),
) -> ExternalAppContext:
    if creds is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    payload = decode_external_token(creds.credentials)
    if not payload or payload.get("iss") != "external-app":
        raise HTTPException(status_code=401, detail="invalid or expired token")
    # Reject tokens missing required claims (defense against token-issuance bugs
    # or future schema drift that would otherwise 500 instead of 401).
    for required in ("app_id", "visitor_id", "visitor_uuid"):
        if payload.get(required) is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
    # Re-check the app is still active. A JWT signed 5 minutes ago
    # should still be rejected if the admin disabled the app between
    # then and now. This is the kill-switch.
    app = db.get(ExternalApp, payload["app_id"])
    if app is None or not app.is_active:
        raise HTTPException(status_code=401, detail="app revoked")
    return ExternalAppContext(
        app_id=app.id,
        tenant_id=app.tenant_id,
        visitor_id=payload["visitor_id"],
        visitor_uuid=payload["visitor_uuid"],
        allowed_agent_ids=app.allowed_agent_ids or [],
        allowed_team_ids=app.allowed_team_ids or [],
        scopes=payload.get("scopes", []),
    )
