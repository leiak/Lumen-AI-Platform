"""Tests for lumen_scripts.seed_m35_default_models — idempotency + structure.

Spec: docs-internal/superpowers/specs/M35-overview.md §2.1
"""
import sys
from pathlib import Path

import pytest

from lumen_core.database import SessionLocal
from lumen_models.playbook import Playbook
from lumen_models.model_config import ModelConfig


# Ensure backend/ is on the import path so `lumen_scripts` is importable
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _import_seed():
    """Import the seed module; idempotent across tests."""
    from lumen_scripts import seed_m35_default_models
    return seed_m35_default_models


def test_seed_helpers_importable():
    """upsert_playbook / upsert_model_config / PLAYBOOKS / TTS_MODELS exist."""
    seed = _import_seed()
    assert callable(getattr(seed, "upsert_playbook", None))
    assert callable(getattr(seed, "upsert_model_config", None))
    assert isinstance(seed.PLAYBOOKS, list) and len(seed.PLAYBOOKS) >= 3
    assert isinstance(seed.TTS_MODELS, list) and len(seed.TTS_MODELS) >= 2


def test_default_playbooks_each_have_useful_keys():
    """Each built-in playbook YAML has at least one useful key."""
    from lumen_services.playbook_service import load_yaml
    seed = _import_seed()
    for pb_def in seed.PLAYBOOKS:
        yaml_content = pb_def["yaml"]
        parsed = load_yaml(yaml_content)
        useful = {"keywords", "voice_direction", "palette", "avoid"}
        assert parsed.keys() & useful, (
            f"{pb_def['name']} lacks useful keys — got {list(parsed.keys())}"
        )


def test_default_tts_models_have_is_tts_or_subtitle_flag():
    """Seeded TTS / subtitle models carry the right capability flag.

    M35 ships two categories of seeded models:
    - TTS providers (edge/piper/openai) — is_tts=True
    - Subtitle provider (lumen_subtitle) — is_subtitle_generation=True
    """
    seed = _import_seed()
    # TTS_MODELS may include both TTS and subtitle models in M35
    for mc_def in seed.TTS_MODELS:
        is_tts = mc_def.get("is_tts")
        is_subtitle = mc_def.get("is_subtitle_generation")
        # Must be flagged as at least one of: TTS or subtitle
        assert is_tts or is_subtitle, f"{mc_def.get('name')} missing both is_tts and is_subtitle_generation"
        # TTS models go through one of the known TTS providers
        if is_tts:
            assert mc_def.get("model_type") in ("edge", "piper", "openai")


def test_upsert_playbook_idempotent():
    """Calling upsert_playbook twice for the same name produces 1 row."""
    seed = _import_seed()
    pb_def = seed.PLAYBOOKS[0]
    db = SessionLocal()
    try:
        # 1st run
        seed.upsert_playbook(
            db,
            name=f"test_upsert_{pb_def['name']}",
            description=pb_def["description"],
            scope=pb_def["scope"],
            yaml_text=pb_def["yaml"],
        )
        db.commit()
        # 2nd run — same name
        seed.upsert_playbook(
            db,
            name=f"test_upsert_{pb_def['name']}",
            description="updated desc",
            scope=pb_def["scope"],
            yaml_text=pb_def["yaml"],
        )
        db.commit()
        # Verify exactly 1 row with that name on BUILTIN_TENANT_ID
        count = db.query(Playbook).filter(
            Playbook.tenant_id == seed.BUILTIN_TENANT_ID,
            Playbook.name == f"test_upsert_{pb_def['name']}",
        ).count()
        assert count == 1, f"Expected 1 row after idempotent upsert, got {count}"

        # Cleanup
        db.query(Playbook).filter(
            Playbook.name == f"test_upsert_{pb_def['name']}"
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_upsert_model_config_idempotent():
    """Calling upsert_model_config twice produces 1 global row."""
    # Ensure the model_configs.is_tts / is_subtitle_generation columns
    # exist before we touch them (lumen_main runs this on startup).
    from lumen_core.database import ensure_model_configs_tts_subtitle_flags
    ensure_model_configs_tts_subtitle_flags()

    seed = _import_seed()
    mc_def = dict(seed.TTS_MODELS[0])  # copy to avoid mutation
    # Use a unique name so we don't collide with seeded built-ins
    mc_def["name"] = f"test_upsert_{mc_def.get('name', 'tts')}"
    mc_def["model_name"] = f"test_upsert_model_{mc_def.get('model_name', 'edge')}"
    db = SessionLocal()
    try:
        # 1st run
        seed.upsert_model_config(db, row=mc_def)
        db.commit()
        # 2nd run — same model_type+model_name
        seed.upsert_model_config(db, row=mc_def)
        db.commit()
        # Verify exactly 1 row with that (NULL tenant, type, model_name)
        count = db.query(ModelConfig).filter(
            ModelConfig.tenant_id.is_(None),
            ModelConfig.model_type == mc_def["model_type"],
            ModelConfig.model_name == mc_def["model_name"],
        ).count()
        assert count == 1, f"Expected 1 row after idempotent upsert, got {count}"

        # Cleanup
        db.query(ModelConfig).filter(
            ModelConfig.model_name == mc_def["model_name"]
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()