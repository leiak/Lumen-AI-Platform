"""Platform-wide system KV config (M34 / 2026-06-30).

Stores operator-tunable platform settings that don't fit the per-tenant
``system_settings`` row (which is hard-coded columns for default
models / chat-history-days / branding). The first consumer is the M16
HTTP skill executor: ``HttpExecutor._resolve_allowed_domains`` reads
``skill_http_allowed_domains`` from this table on each call.

Rows are seeded idempotently by ``ensure_system_configs_table`` in
``lumen_core/database.py`` at uvicorn startup. Operators edit rows via
SQL or future admin UI; do NOT clobber a row on every startup or you
will silently overwrite manual domain additions / removals.

Pre-existing related tables (NOT to be confused):
- ``system_settings`` (per-tenant, fixed columns; ``lumen_models/settings.py``)
- ``security_settings`` (per-tenant password policy; same file)

Schema:
  id        INT  PK auto-increment
  key       VARCHAR(100) UNIQUE NOT NULL  — dot-separated, e.g.
                                          ``skill_http_allowed_domains``
  value     JSON NOT NULL                — typed payload (list / dict / scalar)
  created_at / updated_at                — inherited from BaseModel
"""
from sqlalchemy import Column, Integer, String, JSON
from lumen_models.base import BaseModel


class SystemConfig(BaseModel):
    """Platform-wide key-value configuration store.

    Distinct from ``SystemSettings`` which is *per-tenant* with hard
    columns (default_model / embedding_model / chat_history_days /
    system_name / system_description). SystemConfig is the catch-all
    for settings that are singleton-platform-wide and whose payloads
    vary in shape (a list of allowed domains, a feature flag map, etc.).
    """
    __tablename__ = "system_configs"

    key = Column(String(100), nullable=False, unique=True, index=True)
    value = Column(JSON, nullable=False)

    def __repr__(self) -> str:
        # Truncate value for repr safety — JSON payloads can be large
        # and noisy in test output.
        v = self.value
        if isinstance(v, str) and len(v) > 60:
            v = v[:57] + "..."
        return f"<SystemConfig(id={self.id}, key={self.key!r}, value={v!r})>"
