"""Pydantic schemas for the admin ``/api/v1/external-apps`` namespace.

CRUD bodies; the response shape includes a denormalized
``app_secret_plain`` ONLY on POST /external-apps and on
POST /external-apps/{id}/regenerate-secret — never on GET / PATCH.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field, field_validator
import re


# Origin pattern accepts:
#   * https?://localhost(:port)?         — dev hosts (seed_external_app.py uses this)
#   * https?://A.B.C.D(:port)?           — IPv4 dotted quad, also for dev (e.g. 127.0.0.1)
#   * https?://(*.)?fqdn.tld(:port)?     — standard FQDN with optional wildcard subdomain
#
# NOTE: the plan-text version only accepted FQDNs, which rejected the dev
# seed origins (http://localhost:11334, http://localhost:11337,
# http://127.0.0.1:11337). The dev seed bypasses Pydantic via direct ORM
# insert, but the admin POST /external-apps endpoint would reject the same
# values. The extended pattern below keeps the FQDN/wildcard rules intact
# while permitting localhost + IPv4 for development convenience.
_ORIGIN_RE = re.compile(
    r"^https?://("
    r"localhost"
    r"|(\d{1,3}\.){3}\d{1,3}"
    r"|(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}"
    r")(:\d+)?$",
    re.IGNORECASE,
)


def _validate_origins(v: list[str]) -> list[str]:
    for o in v:
        if not _ORIGIN_RE.match(o):
            raise ValueError(f"invalid origin pattern: {o!r} (expected https://host or https://*.host)")
    return v


class ExternalAppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    allowed_origins: list[str] = Field(default_factory=list)
    allowed_agent_ids: list[int] = Field(default_factory=list)
    allowed_team_ids: list[int] = Field(default_factory=list)
    scopes: str = "chat:stream,chat:upload,conv:read"
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000)

    @field_validator("allowed_origins")
    @classmethod
    def _check_origins(cls, v):
        return _validate_origins(v)


class ExternalAppUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    allowed_origins: Optional[list[str]] = None
    allowed_agent_ids: Optional[list[int]] = None
    allowed_team_ids: Optional[list[int]] = None
    scopes: Optional[str] = None
    rate_limit_per_min: Optional[int] = Field(None, ge=1, le=10000)
    is_active: Optional[bool] = None

    @field_validator("allowed_origins")
    @classmethod
    def _check_origins(cls, v):
        return _validate_origins(v) if v is not None else v


class ExternalAppResponse(BaseModel):
    id: int
    tenant_id: int
    name: str
    app_key: str
    allowed_origins: list[str]
    allowed_agent_ids: list[int]
    allowed_team_ids: list[int]
    scopes: str
    rate_limit_per_min: int
    is_active: bool
    description: Optional[str]
    created_by: Optional[int]
    last_used_at: Optional[str]
    created_at: str
    updated_at: str
    # Joined for list/detail views; absent on create response
    allowed_agent_names: list[str] = Field(default_factory=list)
    allowed_team_names: list[str] = Field(default_factory=list)


class ExternalAppCreated(ExternalAppResponse):
    """Returned ONLY at create / regenerate-secret. The plain secret
    is shown to the admin once and never again — losing it means
    clicking "regenerate" to issue a new pair.
    """
    app_secret_plain: str


class ExternalAppUsage(BaseModel):
    last_used_at: Optional[str]
    active_visitors_7d: int
    total_conversations: int
    token_issues_7d: int  # simple counter — bumped on each /auth/token
    last_7d_daily: list[int]  # 7 ints, oldest first
