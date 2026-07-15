"""
Integration tests for BaseParser._parse_with_fallback.

The 3-level PDF parsing chain:

    Docling (primary) → pdfplumber → pypdfium2 → _fallback_parse

is what saves the day when Docling returns PDF byte stream as
"extracted text" (the bug fixed by this commit — see
``_looks_like_pdf_byte_stream`` for the detection layer). These tests
exercise the chain end-to-end on the real buggy PDF plus mock-based
deterministic checks for the primary path and the all-fail path.
"""
import os
from pathlib import Path
import pytest

from lumen_services.parsers import GeneralParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CHROME_PDF = FIXTURES_DIR / "sample_chrome_print.pdf"


# ---------------------------------------------------------------------------
# 1. Real-world: Chrome-headless PDF that Docling can't decode properly
# ---------------------------------------------------------------------------

def test_chrome_print_pdf_falls_back_to_pdfplumber():
    """The bug fixture (Chrome headless PDF) must be rescued by pdfplumber.

    We force docling_primary to fail (simulating the original M16
    bug where Docling returned the PDF byte stream as "text" — see
    ``_looks_like_pdf_byte_stream``). The fallback chain detects
    this and falls through to pdfplumber, which produces readable
    Chinese text for the same input.

    We mock the primary to a controlled failure rather than call
    real Docling because recent Docling versions can sometimes
    parse this particular PDF directly, which would short-circuit
    the fallback path and make the test flaky. By forcing the
    failure mode we deterministically exercise the fallback chain.
    """
    assert CHROME_PDF.exists(), f"fixture missing: {CHROME_PDF}"

    parser = GeneralParser()

    def docling_primary_buggy(fp):
        # Simulate the original M16 bug: Docling returns the PDF
        # byte stream as the "text" field. _parse_with_fallback
        # detects this via _looks_like_pdf_byte_stream and falls
        # through to pdfplumber.
        return {
            "text": "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n...garbage byte stream...",
            "metadata": {
                "type": parser.get_type(),
                "title": "",
            },
        }

    result = parser._parse_with_fallback(str(CHROME_PDF), docling_primary_buggy)

    # Must not carry a parse error — pdfplumber should have saved us
    assert result["metadata"].get("parse_error") is None, (
        f"unexpected parse_error: {result['metadata'].get('parse_error')!r}"
    )

    # Must have actually used the fallback chain
    assert result["metadata"].get("parser") == "pdfplumber_fallback", (
        f"expected pdfplumber_fallback, got: {result['metadata']!r}"
    )

    text = result["text"]

    # Sanity: text is actually extracted, not the original garbage
    assert text, "fallback returned empty text"
    assert not text.lstrip().startswith("%PDF-"), "still looks like PDF byte stream"
    assert "FlateDecode" not in text, "still contains PDF object markers"
    assert "endobj" not in text, "still contains PDF object markers"

    # The doc is "表设计" (table design) — must contain some CJK
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    assert cjk_chars > 20, f"expected CJK content, got {cjk_chars} CJK chars in: {text[:200]!r}"


# ---------------------------------------------------------------------------
# 2. Primary path: when Docling returns good text, fallbacks must NOT run
# ---------------------------------------------------------------------------

def test_legit_pdf_uses_docling_primary(monkeypatch):
    """When the primary parser returns clean text, fallbacks must not run.

    We can't easily fabricate a "legit" PDF that Docling handles well
    (no reportlab/fpdf in the test env), so we mock the primary to
    return clean text and assert neither fallback parser is invoked.
    """
    parser = GeneralParser()

    pdfplumber_called = False
    pypdfium2_called = False

    def fake_pdfplumber(fp):
        nonlocal pdfplumber_called
        pdfplumber_called = True
        return "should not be called"

    def fake_pypdfium2(fp):
        nonlocal pypdfium2_called
        pypdfium2_called = True
        return "should not be called"

    monkeypatch.setattr(parser, "_parse_with_pdfplumber", fake_pdfplumber)
    monkeypatch.setattr(parser, "_parse_with_pypdfium2", fake_pypdfium2)

    def docling_primary(fp):
        return {
            "text": "产品表: 产品id, 产品名称, 价格, 库存。这是一个正常的中文文档。",
            "metadata": {"type": "general", "title": "Test Doc"},
        }

    result = parser._parse_with_fallback(str(CHROME_PDF), docling_primary)

    # Primary path preserved
    assert result["text"].startswith("产品表"), result["text"][:100]
    assert result["metadata"].get("title") == "Test Doc"
    # No fallback marker — primary result returned as-is
    assert "parser" not in result["metadata"] or result["metadata"].get("parser") is None, (
        f"unexpected parser marker on primary path: {result['metadata']!r}"
    )
    # Fallbacks not invoked
    assert pdfplumber_called is False, "pdfplumber fallback was called despite primary success"
    assert pypdfium2_called is False, "pypdfium2 fallback was called despite primary success"


# ---------------------------------------------------------------------------
# 3. All parsers fail → _fallback_parse with parse_error set
# ---------------------------------------------------------------------------

def test_all_parsers_fail_returns_parse_error(monkeypatch):
    """When primary, pdfplumber, and pypdfium2 all fail, _fallback_parse
    must run and set ``metadata.parse_error`` so the downstream
    document state is set to FAILED (not silently committed as empty).
    """
    parser = GeneralParser()

    def boom_docling(fp):
        raise RuntimeError("simulated docling failure")

    def boom_pdfplumber(fp):
        raise RuntimeError("simulated pdfplumber failure")

    def boom_pypdfium2(fp):
        raise RuntimeError("simulated pypdfium2 failure")

    monkeypatch.setattr(parser, "_parse_with_pdfplumber", boom_pdfplumber)
    monkeypatch.setattr(parser, "_parse_with_pypdfium2", boom_pypdfium2)

    result = parser._parse_with_fallback(str(CHROME_PDF), boom_docling)

    # _fallback_parse sets fallback=True and records the last error
    assert result["metadata"].get("fallback") is True
    parse_error = result["metadata"].get("parse_error", "")
    assert parse_error, "parse_error should be set when all parsers fail"
    # The most-recent failure was pypdfium2 (third in the chain)
    assert "pypdfium2" in parse_error, f"expected pypdfium2 in parse_error, got: {parse_error!r}"
    assert "RuntimeError" in parse_error
