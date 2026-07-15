"""One-shot migration: link every knowledge_base / document to a
ModelConfig row for its embedding model.

For each ``KnowledgeBase`` whose ``embedding_model_config_id`` is NULL:

1. Try to find an existing ``ModelConfig`` matching
   ``(tenant_id, model_type='ollama', model_name=kb.embedding_model)``.
2. If not found, create one with ``is_embedding=True``, ``is_chat=False``,
   ``is_active=True``, ``name='Auto: {embedding_model}'``.
3. Set the KB's ``embedding_model_config_id`` to the resolved config's id.
4. Backfill every ``Document`` of that KB whose
   ``embedding_model_config_id`` is NULL with the same id.

The function is **idempotent** — re-running produces no writes. Safe to
call on every FastAPI startup.

CLI: ``python -m app.scripts.migrate_embedding_model_config``
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional

from sqlalchemy.orm import Session

from lumen_models.model_config import ModelConfig
from lumen_models.knowledge import KnowledgeBase, Document


@dataclass
class MigrationReport:
    kbs_scanned: int = 0
    kbs_already_linked: int = 0
    kbs_linked: int = 0
    kbs_skipped_no_name: int = 0
    configs_created: int = 0
    configs_reused: int = 0
    docs_backfilled: int = 0

    def as_dict(self) -> Dict[str, int]:
        return asdict(self)


def _find_config(db: Session, tenant_id: int, model_name: str) -> Optional[ModelConfig]:
    return (
        db.query(ModelConfig)
        .filter(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.model_type == "ollama",
            ModelConfig.model_name == model_name,
        )
        .first()
    )


def _create_config(db: Session, tenant_id: int, model_name: str) -> ModelConfig:
    cfg = ModelConfig(
        tenant_id=tenant_id,
        name=f"Auto: {model_name}",
        model_type="ollama",
        model_name=model_name,
        is_chat=False,
        is_embedding=True,
        is_active=True,
    )
    db.add(cfg)
    db.flush()  # populate cfg.id
    return cfg


def migrate_embedding_model_config(db: Session) -> MigrationReport:
    report = MigrationReport()

    # Snapshot KBs (we'll be mutating their embedding_model_config_id)
    kbs = db.query(KnowledgeBase).all()
    resolved_cache: dict = {}

    for kb in kbs:
        report.kbs_scanned += 1
        if kb.embedding_model_config_id is not None:
            report.kbs_already_linked += 1
            continue
        if not (kb.embedding_model or "").strip():
            report.kbs_skipped_no_name += 1
            continue
        key = (kb.tenant_id, kb.embedding_model)
        cfg = resolved_cache.get(key) or _find_config(db, kb.tenant_id, kb.embedding_model)
        if cfg is None:
            cfg = _create_config(db, kb.tenant_id, kb.embedding_model)
            report.configs_created += 1
        else:
            report.configs_reused += 1
        resolved_cache[key] = cfg
        kb.embedding_model_config_id = cfg.id
        report.kbs_linked += 1

    # Backfill documents in one pass per KB
    for kb in kbs:
        if kb.embedding_model_config_id is None:
            continue
        for doc in kb.documents:
            if doc.embedding_model_config_id is None:
                doc.embedding_model_config_id = kb.embedding_model_config_id
                report.docs_backfilled += 1

    db.commit()
    return report


def _cli() -> int:
    import logging
    from lumen_core.database import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("migrate_embedding_model_config")

    db = SessionLocal()
    try:
        report = migrate_embedding_model_config(db)
    finally:
        db.close()

    logger.info("Migration complete: %s", report.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
