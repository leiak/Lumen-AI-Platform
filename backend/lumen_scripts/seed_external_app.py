"""Seed a demo ExternalApp for local dev / manual testing.

Idempotent: if a row with the canonical dev app_key already exists,
we update its fields in place rather than creating a duplicate. Safe
to call on every uvicorn boot.
"""
import logging
from sqlalchemy import select
from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.external_app import ExternalApp
from lumen_models.tenant import Tenant
# ExternalApp.created_by FKs users.id; importing User registers it with
# SQLAlchemy Base so FK resolution succeeds when this script is invoked
# standalone (e.g. `python -c`). On uvicorn startup main.py already
# pre-imports every model so this would be a no-op there.
from lumen_models.user import User  # noqa: F401

DEV_APP_KEY = "lc_pub_dev_demo_only_replace_in_prod"
DEV_APP_SECRET_PLAIN = "sk_dev_only_replace_in_prod_NeverUseThisInProduction"
DEV_ORIGINS = [
    "http://localhost:11334",   # internal dashboard
    "http://localhost:11337",   # widget demo
    "http://127.0.0.1:11337",
]

logger = logging.getLogger(__name__)


def seed_dev_external_app() -> None:
    db = SessionLocal()
    try:
        # Use the first tenant (or skip if none exist).
        # Tenant.status is Boolean (default=True) and may be NULL for
        # legacy rows; we intentionally don't filter on it so the seed
        # works regardless of the bootstrap state.
        t = db.query(Tenant).order_by(Tenant.id.asc()).first()
        if t is None:
            logger.warning("No tenant found; skipping external_app seed")
            return
        existing = db.scalar(select(ExternalApp).where(ExternalApp.app_key == DEV_APP_KEY))
        if existing:
            existing.is_active = True
            existing.allowed_origins = DEV_ORIGINS
            existing.allowed_agent_ids = []
            existing.allowed_team_ids = []
            existing.rate_limit_per_min = 600  # generous in dev
            db.commit()
            logger.info(f"Updated dev ExternalApp id={existing.id}")
        else:
            new_app = ExternalApp(
                tenant_id=t.id,
                name="Dev Demo Widget",
                app_key=DEV_APP_KEY,
                app_secret_hash=get_password_hash(DEV_APP_SECRET_PLAIN),
                allowed_origins=DEV_ORIGINS,
                allowed_agent_ids=[],
                allowed_team_ids=[],
                scopes="chat:stream,chat:upload,conv:read",
                rate_limit_per_min=600,
                is_active=True,
                description="Auto-seeded for local dev. DO NOT USE IN PRODUCTION.",
            )
            db.add(new_app)
            db.commit()
            logger.info(f"Seeded dev ExternalApp id={new_app.id} key={DEV_APP_KEY}")
    finally:
        db.close()
