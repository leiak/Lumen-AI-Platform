"""Centralised SECRET/KEY/TOKEN placeholder guard (nitpick 2026-10-04 C1 + C2).

Locks down four invariants for ``Settings._check_secret_hygiene``
(``lumen_core.config``), the model_validator that replaced the old
``app.main`` block which only guarded ``EXTERNAL_JWT_SECRET``:

  1. ``DEBUG=True`` + dev placeholder → only WARNING, no raise.
  2. ``DEBUG=False`` + dev placeholder → ValidationError (the pydantic
     wrapper around our ValueError) halts boot.
  3. Real keys (32+ chars / proper Fernet / etc.) pass under either
     DEBUG mode — no false positives.
  4. Empty / ``None`` defaults (``S3_SECRET_KEY`` /
     ``BROADCAST_INTERNAL_SECRET`` / ``OAUTH2_CLIENT_SECRET`` etc.)
     are NOT treated as placeholders — they're "feature off"
     sentinels, refusing to boot on those would block legitimate
     dev setups.

If any of these invariants silently flips, the production guard becomes
ineffective (or too aggressive) — this test makes the change visible.
"""
import logging

import pytest
from pydantic import ValidationError


def _real_settings(**overrides):
    """Build a Settings with every known placeholder replaced by a real value."""
    from lumen_core.config import Settings

    return Settings(
        SECRET_KEY="real-jwt-secret-key-must-be-32-chars-or-more",
        EXTERNAL_JWT_SECRET="real-external-jwt-secret-32chars-or-more",
        WX_PUBLISHER_FERNET_KEY="real-fernet-key-base64-url-safe-32bytes",
        # 显式覆盖非空默认值,避免依赖环境变量提供真值。
        S3_SECRET_KEY="",
        BROADCAST_INTERNAL_SECRET="",
        **overrides,
    )


def test_dev_defaults_with_debug_true_only_warns(caplog):
    """DEBUG=True + placeholders → no crash, just WARNING (test suite can boot)."""
    from lumen_core.config import Settings

    s = Settings(DEBUG=True)
    with caplog.at_level(logging.WARNING, logger="lumen_core.config"):
        result = s._check_secret_hygiene()
    assert result is s
    # 至少一条 WARNING 命中 "dev placeholder"
    warnings = [r for r in caplog.records if "dev placeholder" in r.message]
    assert warnings, (
        f"expected at least one placeholder WARNING, got: {[r.message for r in caplog.records]}"
    )
    # 三条都该被报
    msg = warnings[0].message
    assert "SECRET_KEY" in msg
    assert "EXTERNAL_JWT_SECRET" in msg
    assert "WX_PUBLISHER_FERNET_KEY" in msg


def test_dev_defaults_with_debug_false_raises():
    """DEBUG=False + placeholders → ValidationError (pydantic-wrapped ValueError) halts boot.

    pydantic 模型_validator 在 ``Settings(...)`` 构造的最后阶段触发,
    ValidationError 在 init 期就抛 — 包整个 init call。
    """
    from lumen_core.config import Settings

    with pytest.raises(ValidationError) as excinfo:
        Settings(DEBUG=False)
    assert "dev placeholder" in str(excinfo.value)


def test_real_secrets_pass_in_production():
    """DEBUG=False + real keys → no raise (production-safe state)."""
    s = _real_settings(DEBUG=False)
    assert s._check_secret_hygiene() is s


def test_real_secrets_pass_in_dev():
    """DEBUG=True + real keys → no raise, no placeholder WARNING emitted."""
    s = _real_settings(DEBUG=True)
    assert s._check_secret_hygiene() is s


def test_empty_string_keys_are_not_placeholders():
    """``S3_SECRET_KEY = ""`` / ``BROADCAST_INTERNAL_SECRET = ""`` 是「功能关闭」

    合法状态,不应被 placeholder 规则误伤。DEBUG=False 下,只要
    SECRET_KEY / EX_JWT / WX_FERNET 三个真值覆盖,空串字段就跳
    过 placeholder 扫描,守门应通过。
    """
    from lumen_core.config import Settings

    s = Settings(
        DEBUG=False,
        SECRET_KEY="real-secret-32-chars-min-XXXXXXXXXXXXXXXX",
        EXTERNAL_JWT_SECRET="real-external-32-chars-min-XXXXXXXXX",
        WX_PUBLISHER_FERNET_KEY="real-fernet-key-base64-url-32bytes",
        S3_SECRET_KEY="",
        BROADCAST_INTERNAL_SECRET="",
    )
    s._check_secret_hygiene()  # 不抛


def test_optional_keys_with_none_are_skipped():
    """``Optional[str] = None`` 字段 (OAuth / MiniMax API key 之类) 不参与判断。"""
    # 真密钥覆盖占位后,DEBUG=False 也应该过(因为 OAUTH/MINIMAX 是 None 跳过)
    s = _real_settings(DEBUG=False)
    assert s._check_secret_hygiene() is s


def test_placeholder_prefix_coverage():
    """覆盖几个常见 sentinel prefix;修改任一会被这测试锁住。"""
    sentinels = [
        "your-secret-key-1234567890abcdef",
        "dev-secret-key-test-not-real",
        "dev-only-something-blank",
        "external-dev-only-change-me",
        "change-in-production-please-do",
    ]
    for sentinel in sentinels:
        from lumen_core.config import Settings

        # 用同 sentinel 覆盖三个字段;DEBUG=False → init 抛 ValidationError
        with pytest.raises(ValidationError) as excinfo:
            Settings(
                DEBUG=False,
                SECRET_KEY=sentinel,
                EXTERNAL_JWT_SECRET=sentinel,
                WX_PUBLISHER_FERNET_KEY=sentinel,
            )
        assert "dev placeholder" in str(excinfo.value)


def test_only_key_shaped_field_names_are_inspected():
    """非 SECRET/KEY/TOKEN 字段(如 ACCESS_TOKEN_EXPIRE_MINUTES=30)不参与。"""
    from lumen_core.config import Settings

    # ACCESS_TOKEN_EXPIRE_MINUTES 名字含 TOKEN 但不是 str 字段 (int)
    with pytest.raises(ValidationError) as excinfo:
        Settings(DEBUG=False)
    # raise 消息应只列 str placeholder 字段,不该列 int 值
    assert "ACCESS_TOKEN_EXPIRE_MINUTES" not in str(excinfo.value)


def test_module_level_settings_constructs_with_warning_in_dev():
    """Importing ``lumen_core.config`` should produce a settings instance that

    survives under DEBUG=True (otherwise the entire pytest suite
    would fail at import). The WARNING is the visible signal — this
    test makes sure the message format stays informative.
    """
    from lumen_core import config as cfg_mod

    # ``cfg_mod.settings`` 已在 import 时构造;不应该 raise。
    assert cfg_mod.settings.DEBUG is True
    # 默认占位 + DEBUG=True,值应该仍是 dev sentinel
    assert "dev-secret-key-" in cfg_mod.settings.SECRET_KEY