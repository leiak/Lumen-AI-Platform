"""
One-shot migration: rewrite workflow LLM-node ``model_name`` strings to
``model_config_id`` FKs against the ``model_configs`` table.

Resolution order per LLM node:
  1. Exact match on ``ModelConfig.model_name`` (active, tenant-scoped or global).
  2. Substring match via the same ``type_map`` the executor uses
     (e.g. ``"glm"`` -> ``model_type="zhipu"``) — picks the first active
     row of that type.
  3. No match -> leave ``model_config_id=None``, keep ``model_name``.
     Executor will fall back to a literal ``ollama`` invocation.

The function is **idempotent**: nodes with an existing ``model_config_id``
are skipped. Re-running produces no writes for already-migrated rows.

A CLI entrypoint is provided at the bottom for manual runs:
    python -m app.scripts.migrate_workflow_model_refs
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from lumen_models.model_config import ModelConfig
from lumen_models.workflow import Workflow


# Mirrors the type_map in workflow_executor._handle_llm and
# agent_service._get_model_config. Keep in sync.
_TYPE_MAP: list[tuple[str, str]] = [
    ("minimax", "minimax"),
    ("gpt", "openai"),
    ("openai", "openai"),
    ("claude", "anthropic"),
    ("anthropic", "anthropic"),
    ("glm", "zhipu"),
    ("zhipu", "zhipu"),
    ("ollama", "ollama"),
]


@dataclass
class MigrationReport:
    workflows_scanned: int = 0
    llm_nodes_seen: int = 0
    exact_matched: int = 0
    substring_matched: int = 0
    unmatched: int = 0
    skipped_already_migrated: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "workflows_scanned": self.workflows_scanned,
            "llm_nodes_seen": self.llm_nodes_seen,
            "exact_matched": self.exact_matched,
            "substring_matched": self.substring_matched,
            "unmatched": self.unmatched,
            "skipped_already_migrated": self.skipped_already_migrated,
        }


def _is_llm_node(node: Dict[str, Any]) -> bool:
    return (node.get("type") or "").lower() == "llm"


def _get_node_data(node: Dict[str, Any]) -> Dict[str, Any]:
    data = node.get("data")
    return data if isinstance(data, dict) else {}


def _lookup_exact(db: Session, tenant_id: int, model_name: str) -> Optional[ModelConfig]:
    return (
        db.query(ModelConfig)
        .filter(
            ModelConfig.model_name == model_name,
            ModelConfig.is_active.is_(True),
            (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None)),
        )
        .first()
    )


def _lookup_by_type(db: Session, tenant_id: int, model_lower: str) -> Optional[ModelConfig]:
    for needle, mtype in _TYPE_MAP:
        if needle in model_lower:
            cfg = (
                db.query(ModelConfig)
                .filter(
                    ModelConfig.model_type == mtype,
                    ModelConfig.is_active.is_(True),
                    (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None)),
                )
                .first()
            )
            if cfg is not None:
                return cfg
    return None


def migrate_workflow_model_refs(
    db: Session,
    *,
    workflows: Optional[Iterable[Workflow]] = None,
) -> MigrationReport:
    """Run the migration. If ``workflows`` is None, scans all rows in the
    ``workflows`` table. Returns a :class:`MigrationReport` summary.
    """
    report = MigrationReport()

    if workflows is None:
        workflows = db.query(Workflow).all()
    workflows = list(workflows)
    report.workflows_scanned = len(workflows)

    for wf in workflows:
        definition = getattr(wf, "definition", None)
        if not isinstance(definition, dict):
            continue
        nodes = definition.get("nodes") or []
        if not isinstance(nodes, list):
            continue
        tenant_id = getattr(wf, "tenant_id", None) or 0

        for node in nodes:
            if not isinstance(node, dict) or not _is_llm_node(node):
                continue
            report.llm_nodes_seen += 1
            data = _get_node_data(node)
            if data.get("model_config_id") is not None:
                report.skipped_already_migrated += 1
                continue

            model_name = (data.get("model_name") or "").strip()
            if not model_name:
                report.unmatched += 1
                continue

            resolved = _lookup_exact(db, tenant_id, model_name)
            if resolved is not None:
                data["model_config_id"] = resolved.id
                data["model_name"] = resolved.model_name
                report.exact_matched += 1
                continue

            resolved = _lookup_by_type(db, tenant_id, model_name.lower())
            if resolved is not None:
                data["model_config_id"] = resolved.id
                data["model_name"] = resolved.model_name
                report.substring_matched += 1
                continue

            data.setdefault("model_config_id", None)
            report.unmatched += 1

    db.commit()
    return report


def _cli() -> int:
    import logging

    from lumen_core.database import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("migrate_workflow_model_refs")

    db = SessionLocal()
    try:
        report = migrate_workflow_model_refs(db)
    finally:
        db.close()

    logger.info("Migration complete: %s", report.as_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
