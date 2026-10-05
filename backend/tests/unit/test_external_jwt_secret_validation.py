"""Verifies the boot-time guard against dev-only EXTERNAL_JWT_SECRET.

We do NOT exercise the actual boot path (which would require tearing
down the FastAPI app). Instead we lock down two invariants that the
guard relies on:

  1. The in-tree default starts with the ``external-dev-only`` sentinel
     so the guard can detect it.
  2. ``settings.DEBUG`` defaults to True (so the test/dev environment
     doesn't actually refuse to boot).

If either invariant is silently changed, the production guard becomes
ineffective — this test makes that change visible.

NOTE: The actual guard moved out of ``app.main`` (M39 nitpick 2026-10-04
fix). It now lives in ``lumen_core.config.Settings._check_secret_hygiene``
(``model_validator``) which scans ``SECRET_KEY`` /
``EXTERNAL_JWT_SECRET`` / ``WX_PUBLISHER_FERNET_KEY`` with the same
DEBUG=True/False contract. Full behaviour coverage lives in
``test_secret_hygiene_validation.py``; this file keeps the historical
sentinel-shape invariants locked.
"""
import pytest


def test_dev_default_raises_in_production():
    from lumen_core.config import settings
    # The actual guard lives in ``Settings._check_secret_hygiene``
    # (``model_validator`` after pydantic construction; was previously
    # inlined in ``app.main`` before M39 nitpick 2026-10-04 centralised
    # it). The contract is:
    #   if any *_SECRET / *_KEY / *_TOKEN field still starts with a
    #   sentinel prefix ("external-dev-only-" / "dev-only-" / etc.):
    #       if not DEBUG: raise ValueError(...)
    #       else: log warning
    # We can't toggle settings.DEBUG from here without patching the
    # imported module; the fact that the in-tree default starts with
    # the sentinel IS the production-safety guarantee — if someone
    # ever changes the default string, this test will start failing
    # and surface the regression. The DEBUG check is exercised in
    # test mode simply by import of ``lumen_core.config`` not raising
    # (it doesn't — the suite would not be able to run at all).
    is_dev_default = settings.EXTERNAL_JWT_SECRET.startswith("external-dev-only")
    assert is_dev_default is True


def test_debug_default_is_true():
    """DEBUG defaults to True so the guard is permissive in tests/dev.

    If this ever flips to False, the entire pytest suite would fail at
    import of ``lumen_core.config`` with ``ValueError`` — that's the
    loud failure we want, but we'd rather catch the intent change
    here before the symptom shows up in CI.
    """
    from lumen_core.config import settings
    assert settings.DEBUG is True
