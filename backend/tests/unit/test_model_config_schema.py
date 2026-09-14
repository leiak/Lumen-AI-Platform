"""Tests for ``lumen_schemas.model_config.ModelConfigResponse`` default coercion.

2026-09-14 修复 dev DB 里 ``nomic-embed-text`` (id=4) ``max_tokens=0``
触发的 ``GET /models/`` 500。schema 既要拒绝明确的 0(语义上不该 0),
又要给历史 row 一个 fallback 路径 —— 否则任何漏填 max_tokens 的
seed / fixture 都会让前端 agent 编辑下拉整个加载不出来。

测试守住:``max_tokens=0`` / ``max_tokens=None`` / ``timeout=0`` 都
会被兜底成 schema 默认 4096 / 120。
"""
import pytest
from pydantic import ValidationError

from lumen_schemas.model_config import ModelConfigBase, ModelConfigResponse


def _ok_kwargs(**overrides):
    """Return a baseline of valid kwargs; caller overrides per field."""
    base = dict(
        name="t",
        model_type="ollama",
        model_name="nomic-embed-text",
        temperature=0.7,
        max_tokens=4096,
        timeout=120,
        is_default=False,
        is_chat=False,
        is_embedding=True,
    )
    base.update(overrides)
    return base


def test_max_tokens_zero_coerced_to_default():
    """``max_tokens=0`` 是 init_dev_db seed 漏字段的场景 —— schema
    必须兜底成 4096,否则 ``Field(gt=0)`` 触发 ValidationError → 500。
    """
    cfg = ModelConfigBase(**_ok_kwargs(max_tokens=0))
    assert cfg.max_tokens == 4096


def test_max_tokens_none_coerced_to_default():
    """None 兜底(line 46-52 旧行为)。"""
    cfg = ModelConfigBase(**_ok_kwargs(max_tokens=None))
    assert cfg.max_tokens == 4096


def test_timeout_zero_coerced_to_default():
    """同 max_tokens,timeout=0 也兜底成 120。"""
    cfg = ModelConfigBase(**_ok_kwargs(timeout=0))
    assert cfg.timeout == 120


def test_temperature_zero_is_preserved():
    """temperature=0 是合法值(精确模式),**不要**兜底 —— 只兜 None。"""
    cfg = ModelConfigBase(**_ok_kwargs(temperature=0))
    assert cfg.temperature == 0


def test_max_tokens_positive_value_preserved():
    """显式给的合法值不被动。"""
    cfg = ModelConfigBase(**_ok_kwargs(max_tokens=2048))
    assert cfg.max_tokens == 2048


def test_response_schema_accepts_zero_max_tokens():
    """ModelConfigResponse.from_attributes(ORM 模式)也要兜底 0,
    因为 admin UI / agent 编辑下拉走的是 Response。"""
    from datetime import datetime
    from types import SimpleNamespace
    now = datetime(2026, 9, 14, 12, 0, 0)
    obj = SimpleNamespace(
        id=4,
        is_active=True,
        tenant_id=None,
        created_at=now,
        updated_at=now,
        **_ok_kwargs(max_tokens=0),
    )
    resp = ModelConfigResponse.model_validate(obj)
    assert resp.max_tokens == 4096
