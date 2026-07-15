"""
Regression tests for the celery_app <-> document_tasks circular import.

Historical context
------------------
``celery_app.py`` originally did
``from lumen_tasks.document_tasks import process_document_task`` at module
bottom to register the task, and ``document_tasks.py:5`` did
``from lumen_tasks.celery_app import celery_app`` at module top to use
``@celery_app.task``. Together they formed a cycle that resolved only
when ``celery_app`` was loaded FIRST (the partial ``celery_app`` module
exposed the ``celery_app`` Celery instance from line 5 early enough for
``document_tasks:5``'s import to succeed).

The first endpoint that lazy-imported ``process_document_task`` after a
fresh uvicorn start — for example
``POST /api/v1/knowledge/documents/{id}/rechunk`` (see
``knowledge.py:527``) — would crash with::

    ImportError: cannot import name 'process_document_task' from
    partially initialized module 'lumen_tasks.document_tasks'

until some side path happened to break the cycle. The first
``rechunk_document`` call after a fresh uvicorn start on 2026-06-08 hit
exactly that and returned 500.

Two layered fixes shipped
-------------------------
1. ``commit 0a58910c`` (``app/main.py`` preload): importing
   ``app.tasks.celery_app`` at module top forces ``celery_app`` to be
   fully loaded BEFORE any endpoint handler runs, breaking the cycle
   at uvicorn startup. The same workaround is already applied in
   ``tests/unit/conftest.py`` for the test environment.
2. ``commit fc21a548`` / **M29.2.1** (``celery_app.py`` root fix):
   deleted the line-31 module-level import and switched to
   ``Celery(..., include=["lumen_tasks.document_tasks"])``. ``celery_app``
   no longer depends on ``document_tasks`` to load, so the cycle
   cannot form in the first place.

What these tests check
----------------------
- ``test_main_preloads_celery_app_to_break_circular_import`` keeps the
  ``app/main.py`` preload source-level contract from 0a58910c. After
  M29.2.1 the preload is technically redundant (no cycle to break),
  but it is harmless and the source-level contract documents the
  intent. Leaving it in place.
- ``test_import_chain_in_fresh_process[with_preload_succeeds]`` checks
  the ``with_preload`` path still works.
- ``test_import_chain_in_fresh_process[without_preload_fails]`` is
  marked **xfail** after M29.2.1: the underlying cycle no longer
  exists, so a fresh-process import without the preload no longer
  raises ``ImportError``. If this case starts failing again, it means
  a NEW circular import was introduced — re-enable it as a real
  failure and find the new cycle.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# 1. Source-level contract on app/main.py
# ---------------------------------------------------------------------------

def test_main_preloads_celery_app_to_break_circular_import():
    """``lumen_main.py`` must preload ``lumen_tasks.celery_app``.

    The cycle (``celery_app`` -> ``document_tasks`` -> ``celery_app``)
    only resolves cleanly when ``celery_app`` is loaded FIRST, because
    at that point the partial ``celery_app`` module already exposes the
    ``celery_app`` Celery instance from line 5. See
    ``tests/unit/test_knowledge_user_id_in_task_params.py:14-28`` for
    the same rationale in test fixtures.
    """
    main_py = (
        Path(__file__).parent.parent.parent / "lumen_main.py"
    )
    assert main_py.exists(), f"lumen_main.py not found at {main_py}"
    content = main_py.read_text(encoding="utf-8")
    assert "import lumen_tasks.celery_app" in content, (
        "lumen_main.py must preload lumen_tasks.celery_app at import time "
        "to break the celery_app <-> document_tasks circular import "
        "BEFORE any endpoint lazy-imports process_document_task "
        "(see knowledge.py:527 rechunk, :180 upload, :386 retry). "
        "Without this preload, the first such endpoint call after a "
        "fresh uvicorn start fails with ImportError and the API "
        "returns 500. The same workaround is already applied in "
        "tests/unit/conftest.py for the test environment."
    )


# ---------------------------------------------------------------------------
# 2. Behavioral: in a fresh Python process, the import chain works
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "preload_cmd, expect_ok",
    [
        # WITHOUT preload: in a fresh process, lazy-importing
        # process_document_task directly hits the cycle and fails.
        #
        # XFAIL after M29.2.1 (commit fc21a548): celery_app.py no
        # longer imports document_tasks at module level, so the
        # cycle is broken at the source. The "no preload should
        # fail" contract from 0a58910c is obsolete — a fresh-process
        # import without the preload now succeeds (prints "OK").
        # If this case starts failing again, a NEW circular import
        # was introduced; re-enable as a real failure and find the
        # cycle.
        pytest.param(
            "",
            False,
            marks=pytest.mark.xfail(
                reason="M29.2.1 root fix (celery_app include=[...]) "
                "broke the cycle at the source; this case's contract "
                "is now obsolete. Re-enable if a new cycle appears.",
                strict=False,
            ),
            id="without_preload_fails",
        ),
        # WITH preload: importing celery_app first resolves the cycle.
        ("import lumen_tasks.celery_app; ", True),
    ],
    ids=["without_preload_fails", "with_preload_succeeds"],
)
def test_import_chain_in_fresh_process(preload_cmd: str, expect_ok: bool):
    """Subprocess import test: contract the preload really matters.

    Pytest's own conftest already preloads celery_app, so we can't
    reproduce the bug in-process. A subprocess gives us the fresh
    sys.modules the real uvicorn startup sees.
    """
    backend_dir = Path(__file__).parent.parent.parent
    code = (
        "import sys\n"
        f"{preload_cmd}"
        "from lumen_tasks.document_tasks import process_document_task\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(backend_dir),
        timeout=30,
    )
    if expect_ok:
        assert "OK" in result.stdout, (
            f"expected import success, got stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
    else:
        # Without the preload, the cycle must surface as an ImportError
        # in the subprocess — that's the bug we're protecting against.
        assert "partially initialized" in result.stderr or (
            "ImportError" in result.stderr
        ), (
            "expected the celery_app <-> document_tasks cycle to fail "
            f"in a fresh process, got stdout={result.stdout!r} "
            f"stderr={result.stderr!r}. If this is now passing without "
            "the preload, the underlying cycle has been fixed "
            "elsewhere and this test should be retired."
        )
