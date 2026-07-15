"""
One-shot migration from legacy workflow definitions to the v2 schema.

Public API:
  - migrate_definition(definition) -> dict   (pure, returns the new dict)
  - migrate_all_workflows(db, dry_run=False) -> dict   (DB-iterating wrapper)

Idempotent: already-migrated nodes (have version="1" AND non-empty outputs) are skipped.

CLI:
  python -m app.scripts.migrate_workflow_to_v2 --dry-run
  python -m app.scripts.migrate_workflow_to_v2 --apply
"""
import copy
import hashlib
import re
from typing import Any, Dict, List

# Output presets — same as the BaseNode.outputs() declarations.
_NODE_OUTPUTS_PRESET: Dict[str, List[dict]] = {
    "input":     [{"name": "value", "type": "object", "description": "输入数据"}],
    "agent":     [
        {"name": "response", "type": "string"},
        {"name": "usage", "type": "object"},
    ],
    "llm":       [
        {"name": "response", "type": "string"},
        {"name": "model", "type": "string"},
        {"name": "finish_reason", "type": "string"},
        {"name": "usage", "type": "object"},
    ],
    "condition": [
        {"name": "result", "type": "boolean"},
        {"name": "selected_case_id", "type": "string"},
    ],
    "output":    [{"name": "value", "type": "object"}],
    "parallel":  [
        {"name": "results", "type": "object"},
        {"name": "status", "type": "string"},
    ],
    "fan_out":   [{"name": "results", "type": "array[object]"}],
    "fan_in":    [
        {"name": "result", "type": "object"},
        {"name": "count", "type": "number"},
    ],
    "start":     [],
    "end":       [],
}

_SIMPLE_CONDITION = re.compile(
    r"^\s*([a-zA-Z_][\w\.]*)\s*(==|!=|>=|<=|>|<|contains|not\s+contains|starts_with|ends_with)\s*(.+?)\s*$"
)

# Normalize legacy operator spellings to the v2 canonical form.
_OP_NORMALIZE = {
    "==": "=",
    "!=": "!=",
    ">=": ">=",
    "<=": "<=",
    ">": ">",
    "<": "<",
    "contains": "contains",
    "not contains": "not contains",
    "starts_with": "starts with",
    "ends_with": "ends with",
}


def _parse_simple_condition(expr: str) -> dict | None:
    """
    Try to parse 'foo == "bar"' / 'count > 5' into a Condition dict.
    Returns None if too complex (multi-clause, function calls, etc).
    """
    if not expr:
        return None
    # Reject compound expressions
    if re.search(r"\b(and|or|not\s*\()", expr):
        return None
    m = _SIMPLE_CONDITION.match(expr)
    if not m:
        return None
    left, op_raw, right = m.group(1), m.group(2).replace("  ", " "), m.group(3)
    op = _OP_NORMALIZE.get(op_raw, op_raw)
    right = right.strip()
    # Strip surrounding quotes
    if (right.startswith('"') and right.endswith('"')) or (
        right.startswith("'") and right.endswith("'")
    ):
        right = right[1:-1]
    # Try to coerce to number / bool
    if re.match(r"^-?\d+(\.\d+)?$", right):
        right = float(right) if "." in right else int(right)
    elif right == "True":
        right = True
    elif right == "False":
        right = False
    # Selector: 'a.b' → ['input', 'a', 'b']  (legacy templates assumed input namespace)
    selector = ["input", *left.split(".")]
    return {
        "variable_selector": selector,
        "comparison_operator": op,
        "value": right,
    }


def _stable_case_id(legacy_label: str) -> str:
    """Stable 8-char ID derived from legacy condition text — same input → same ID."""
    return hashlib.md5(legacy_label.encode()).hexdigest()[:8]


def _migrate_node(node: dict) -> dict:
    ntype = node.get("type")
    cfg = dict(node.get("config") or {})
    # Idempotency: if already has version AND non-empty outputs, skip
    if cfg.get("version") == "1" and cfg.get("outputs"):
        return node
    cfg["version"] = cfg.get("version", "1")

    # Outputs
    if not cfg.get("outputs"):
        ntype_str = str(ntype) if ntype is not None else ""
        cfg["outputs"] = _NODE_OUTPUTS_PRESET.get(ntype_str, [])

    if ntype == "condition":
        legacy = cfg.get("condition")
        # Parse legacy condition string (preserve original in cfg for audit either way)
        if legacy and isinstance(legacy, str):
            parsed = _parse_simple_condition(legacy)
            if parsed:
                case_id = _stable_case_id(legacy)
                cfg["cases"] = [
                    {
                        "case_id": case_id,
                        "logical_operator": "and",
                        "conditions": [parsed],
                    }
                ]
            # else: complex — leave condition in place for runtime safe_eval
            # (already in cfg, no need to re-set)

    elif ntype == "output":
        # config.output.field → config.field
        if "output" in cfg and isinstance(cfg["output"], dict):
            cfg["field"] = cfg["output"].get("field", "current")
            # Keep legacy for audit
        cfg.setdefault("field", "current")

    elif ntype == "input":
        if not cfg.get("variables"):
            cfg["variables"] = [{"name": "value", "type": "object", "required": False}]

    return {**node, "config": cfg}


def _migrate_edge(edge: dict, nodes_by_id: dict) -> dict:
    e = dict(edge)
    if e.get("sourceHandle"):
        return e  # already migrated
    legacy = (e.get("condition") or "").strip()
    src_node = nodes_by_id.get(e["source"])
    if src_node and src_node.get("type") == "condition" and legacy:
        # Use the case's case_id (same hash function as the node migrator)
        if legacy in ("True", "true", "1", "yes"):
            # First case (or the synthesized one)
            cfg = (src_node.get("config") or {})
            cases = cfg.get("cases") or []
            if cases:
                e["sourceHandle"] = cases[0]["case_id"]
            else:
                e["sourceHandle"] = "true"
        elif legacy in ("False", "false", "0", "no"):
            e["sourceHandle"] = "false"
    e.setdefault("sourceHandle", "default")
    return e


def migrate_definition(definition: dict) -> dict:
    """Pure function: take a definition dict, return migrated dict."""
    out = copy.deepcopy(definition)
    nodes = out.get("nodes", [])
    edges = out.get("edges", [])
    new_nodes = [_migrate_node(n) for n in nodes]
    nodes_by_id = {n["id"]: n for n in new_nodes}
    new_edges = [_migrate_edge(e, nodes_by_id) for e in edges]
    out["nodes"] = new_nodes
    out["edges"] = new_edges
    return out


def migrate_all_workflows(db, dry_run: bool = False) -> dict:
    """Iterate the Workflow table, apply migrate_definition, persist changes."""
    from lumen_models.workflow import Workflow

    summary: dict[str, Any] = {
        "scanned": 0,
        "migrated": 0,
        "skipped": 0,
        "errors": [],
    }
    workflows = db.query(Workflow).all()
    for wf in workflows:
        summary["scanned"] += 1
        try:
            old_def = wf.definition or {"nodes": [], "edges": []}
            new_def = migrate_definition(old_def)
            if new_def == old_def:
                summary["skipped"] += 1
                continue
            if dry_run:
                summary["migrated"] += 1
                continue
            wf.definition = new_def
            db.add(wf)
            summary["migrated"] += 1
        except Exception as e:
            summary["errors"].append({"workflow_id": wf.id, "error": str(e)})
    if not dry_run:
        db.commit()
    return summary


def main():
    import argparse
    from lumen_core.database import SessionLocal

    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.apply):
        ap.error("Specify --dry-run or --apply")

    db = SessionLocal()
    try:
        result = migrate_all_workflows(db, dry_run=args.dry_run)
        print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
