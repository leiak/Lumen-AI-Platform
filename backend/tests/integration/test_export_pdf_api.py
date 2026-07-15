"""Integration tests for POST /api/v1/export/pdf.

The endpoint delegates to ExportPdfService which uses Playwright's
headless Chromium. We hit the real service (not a mock) because:

1. The render path is the whole point of the test — a mock would
   hide any markdown→HTML→PDF regression.
2. Playwright + Chromium are already required dev deps, so the
   tests run in CI without new infrastructure.
3. We use a small fixture markdown so the first PDF render is fast
   (~1-2s on cold start, sub-100ms afterwards since the browser is
   reused as a module-level singleton).

Heavy payloads and font-rendering edge cases are intentionally NOT
covered here — they would slow the test suite down by minutes for
marginal coverage gain.
"""
import asyncio
import pytest
import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


SIMPLE_MD = "# Hello 中文\n\nWorld."
TABLE_MD = (
    "| 维度 | 一期现状 |\n"
    "|------|----------|\n"
    "| App 端 | 基础预约 |\n"
)
CODE_MD = "```python\nprint('hi')\n```\n"


class TestExportPdfAPI:
    @pytest.fixture
    def client(self):
        from lumen_main import app
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def _reset_playwright_browser(self):
        """Reset the singleton browser between tests.

        TestClient spins up a fresh asyncio event loop per test, and
        Playwright's connection object is bound to the loop it was
        launched in. Without this reset, the second test would try
        to reuse a browser whose underlying connection was made on
        a dead loop, surfacing as
        ``AttributeError: Browser.new_context: 'NoneType' object has no attribute 'send'``.
        """
        from lumen_services import export_pdf_service

        def _shutdown_sync():
            # shutdown_browser is async; run it in a one-shot loop
            # to reset module-level singleton state between tests.
            try:
                asyncio.run(export_pdf_service.shutdown_browser())
            except Exception:
                # If shutdown itself fails, swallow — the next test
                # will surface a clearer error than the teardown.
                pass

        _shutdown_sync()
        yield
        _shutdown_sync()

    @pytest.fixture
    def auth_headers(self, client):
        # /auth/login is OAuth2PasswordRequestForm — application/x-www-form-urlencoded,
        # not JSON. Tests that pass json={...} get a 422 instead of 200.
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        assert response.status_code == 200, response.text
        token = response.json()["data"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_requires_auth(self, client):
        """Anonymous request → 401, not 500 or 200."""
        response = client.post(
            "/api/v1/export/pdf",
            json={"markdown": SIMPLE_MD},
        )
        assert response.status_code == 401

    def test_empty_markdown_rejected(self, client, auth_headers):
        """Pydantic min_length=1 catches whitespace-only and empty strings."""
        # Pydantic v2 still validates min_length on the JSON body,
        # so empty body fails at 422 (validation) rather than 400
        # (handler ValueError).
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": ""},
        )
        assert response.status_code == 422

    def test_simple_markdown_returns_valid_pdf(self, client, auth_headers):
        """Happy path: small markdown → 200 application/pdf with %PDF- header."""
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": SIMPLE_MD, "title": "Hello Test"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        # Browsers trigger download when they see this header value.
        cd = response.headers["content-disposition"]
        assert cd.startswith("attachment;")
        assert ".pdf" in cd
        # Caching must be off so successive exports don't return stale data.
        assert response.headers.get("cache-control") == "no-store"
        body = response.content
        assert body.startswith(b"%PDF-"), (
            f"response body doesn't start with PDF magic: {body[:8]!r}"
        )
        # Real PDFs are at least a few KB even for empty-ish content.
        assert len(body) > 1000

    def test_table_markdown_renders(self, client, auth_headers):
        """Markdown with a GFM table must not crash the renderer."""
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": TABLE_MD},
        )
        assert response.status_code == 200, response.text
        body = response.content
        assert body.startswith(b"%PDF-")
        # Same PDF-size sanity check; table-bearing documents are
        # always at least a couple of KB once Chromium lays them out.
        assert len(body) > 1000

    def test_code_block_markdown_renders(self, client, auth_headers):
        """Markdown with a fenced code block (uses codehilite extension)."""
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": CODE_MD},
        )
        assert response.status_code == 200, response.text
        body = response.content
        assert body.startswith(b"%PDF-")
        assert len(body) > 1000

    def test_ascii_safe_filename_from_chinese_title(self, client, auth_headers):
        """Chinese-only title → Content-Disposition must use ASCII fallback.

        Starlette encodes header values as latin-1; non-ASCII chars
        raise UnicodeEncodeError before the response leaves FastAPI.
        The endpoint must therefore sanitise the title to ASCII for
        the filename while still accepting the original title in the
        PDF body.
        """
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": SIMPLE_MD, "title": "测试中文标题"},
        )
        assert response.status_code == 200, response.text
        cd = response.headers["content-disposition"]
        assert cd.startswith("attachment;")
        # No CJK characters survived in the filename (otherwise the
        # response would have 500'd before getting here).
        for ch in "测试中文":
            assert ch not in cd

    def test_oversize_markdown_rejected(self, client, auth_headers):
        """Payloads over MAX_MARKDOWN_BYTES → 413, no Chromium launch."""
        # 5MB is the configured cap; send 5MB + 1 of harmless text.
        from lumen_services.export_pdf_service import MAX_MARKDOWN_BYTES
        big = "x" * (MAX_MARKDOWN_BYTES + 1)
        response = client.post(
            "/api/v1/export/pdf",
            headers=auth_headers,
            json={"markdown": big},
        )
        assert response.status_code == 413