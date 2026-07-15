"""M35: Playbook service — YAML loader, prompt injector, scope validator.

A Playbook is a tenant-scoped (or built-in) bundle of style tokens
(palette / typography / keywords / avoid / voice_direction) that
gets injected into image-gen prompts and TTS voice direction.

This service is the single source of truth for:
- YAML validation (raises PlaybookValidationError on bad input)
- Style-token extraction (parsed dict cached on the row)
- Prompt enrichment (used by TTSService + ImageGenerationService)
- Scope validation (refuses a tts-targeted playbook for an image call)

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import yaml
from sqlalchemy.orm import Session

from lumen_models.playbook import Playbook

# Recognized top-level keys in a Playbook YAML. Unknown keys are
# allowed but ignored — keeps the schema forward-compatible (M36+
# can add keys without breaking old playbooks).
_KNOWN_KEYS = {
    "palette", "typography", "keywords", "avoid",
    "voice_direction", "voice_speed", "voice_tone",
    "background", "mood", "aspect_ratio",
}

# Target identifier for inject_into_prompt. The string is part of the
# service contract; callers pass one of these constants.
Target = Literal["image_prompt", "tts_prompt"]


class PlaybookValidationError(ValueError):
    """Raised when YAML fails to parse or required keys are missing.

    The first arg is a human-readable message; the optional ``field``
    attribute points at the offending YAML path (e.g. "palette.primary").
    """

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(message)
        self.field = field


def load_yaml(yaml_text: str) -> Dict[str, Any]:
    """Parse a Playbook YAML string into a validated dict.

    Rules:
    - Must be valid YAML (yaml.YAMLError → PlaybookValidationError).
    - Top-level must be a mapping (not a list / scalar).
    - At least one of ``keywords``, ``voice_direction``, ``palette``,
      ``avoid`` must be present (otherwise the playbook is a no-op
      and the API refuses to save it).
    """
    if not yaml_text or not yaml_text.strip():
        raise PlaybookValidationError("Playbook YAML is empty", field="yaml_content")
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise PlaybookValidationError(f"Invalid YAML: {e}", field="yaml_content")
    if not isinstance(parsed, dict):
        raise PlaybookValidationError(
            f"Playbook root must be a mapping, got {type(parsed).__name__}",
            field="yaml_content",
        )
    useful = {"keywords", "voice_direction", "palette", "avoid"}
    if not (parsed.keys() & useful):
        raise PlaybookValidationError(
            f"Playbook must contain at least one of: {sorted(useful)}",
            field="yaml_content",
        )
    # keywords / avoid must be lists of strings when present
    for list_key in ("keywords", "avoid"):
        if list_key in parsed and not isinstance(parsed[list_key], list):
            raise PlaybookValidationError(
                f"`{list_key}` must be a list, got {type(parsed[list_key]).__name__}",
                field=list_key,
            )
        if list_key in parsed:
            for i, item in enumerate(parsed[list_key]):
                if not isinstance(item, str):
                    raise PlaybookValidationError(
                        f"`{list_key}[{i}]` must be a string, got {type(item).__name__}",
                        field=f"{list_key}[{i}]",
                    )
    return parsed


def validate_scope(playbook: Dict[str, Any] | Playbook, target: str) -> bool:
    """Return True if the playbook's ``scope`` includes the given target.

    ``target`` is one of ``"image"`` / ``"tts"`` / ``"video"`` (M36+).
    Built-in playbooks default to ``["image", "tts"]`` if no scope is set.
    """
    if isinstance(playbook, Playbook):
        scope = playbook.scope or []
    else:
        scope = (playbook or {}).get("scope") or []
    if not scope:
        # Default: applies to both
        return True
    return target in scope


def inject_into_prompt(
    playbook: Dict[str, Any] | Playbook,
    base_text: str,
    target: Target,
) -> str:
    """Append the playbook's style tokens to ``base_text``.

    For ``image_prompt``: appends ``keywords`` (as comma-separated tags)
    and the first few ``palette`` primary colors (as visual hints). The
    avoid list is appended as "avoid: ..." so providers that support
    negative prompts can pass it through.
    For ``tts_prompt``: appends ``voice_direction`` + ``voice_tone`` +
    ``voice_speed`` so the caller can pass them as TTS voice params.
    """
    if isinstance(playbook, Playbook):
        tokens = playbook.style_tokens or {}
    else:
        tokens = playbook or {}
    if not tokens:
        return base_text

    parts: List[str] = [base_text.strip()] if base_text else [""]
    if target == "image_prompt":
        keywords = tokens.get("keywords") or []
        if keywords:
            parts.append("Style: " + ", ".join(keywords))
        palette = tokens.get("palette") or {}
        primary = palette.get("primary") if isinstance(palette, dict) else None
        if primary:
            parts.append("Color: " + ", ".join(primary[:3]))
        avoid = tokens.get("avoid") or []
        if avoid:
            parts.append("Avoid: " + ", ".join(avoid))
    elif target == "tts_prompt":
        direction = tokens.get("voice_direction")
        if direction:
            parts.append(f"Voice direction: {direction}")
        tone = tokens.get("voice_tone")
        if tone:
            parts.append(f"Tone: {tone}")
        speed = tokens.get("voice_speed")
        if isinstance(speed, (int, float)):
            parts.append(f"Speed: {speed}x")
    else:
        raise ValueError(f"Unknown inject target: {target!r}")
    return " | ".join(p for p in parts if p)


# ──────────────────────────────────────────────────────────────────────
# DB-backed helpers (used by the API router in CP3-T9)
# ──────────────────────────────────────────────────────────────────────

def get_for_tenant(
    db: Session,
    *,
    tenant_id: int,
    playbook_id: int,
    include_builtin: bool = True,
) -> Optional[Playbook]:
    """Load a playbook by id, tenant-scoped.

    Built-in playbooks (``is_builtin=True``) live on ``tenant_id=1`` and
    are visible to ALL tenants when ``include_builtin=True`` (default).
    Per-tenant custom playbooks are visible only to their own tenant.
    """
    q = db.query(Playbook)
    if include_builtin:
        q = q.filter(
            (Playbook.tenant_id == tenant_id)
            | ((Playbook.tenant_id == 1) & (Playbook.is_builtin.is_(True)))
        )
    else:
        q = q.filter(Playbook.tenant_id == tenant_id)
    return q.filter(Playbook.id == playbook_id).first()


def list_for_tenant(
    db: Session,
    *,
    tenant_id: int,
    scope: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[Playbook], int]:
    """List playbooks visible to the tenant. Optional ``scope`` filter
    (e.g. ``"image"``) limits to playbooks whose ``scope`` list includes
    that value. Built-ins default to scope = ["image", "tts"].
    """
    q = db.query(Playbook).filter(
        (Playbook.tenant_id == tenant_id)
        | ((Playbook.tenant_id == 1) & (Playbook.is_builtin.is_(True)))
    )
    # JSON scope filter is awkward in MySQL JSON_CONTAINS; do it
    # in-Python after the page query to keep SQL simple. Tenant
    # playbooks lists are bounded (10-50 typical), so the in-memory
    # pass is fine.
    total = q.count()
    rows = (
        q.order_by(Playbook.is_builtin.desc(), Playbook.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    if scope:
        rows = [r for r in rows if validate_scope(r, scope)]
    return rows, total
