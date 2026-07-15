"""Markdown → PDF rendering service.

Used by the chat export feature to turn LLM-produced markdown into a
printable PDF. We use Playwright's headless Chromium as the rendering
engine because:

- It's already installed (other call sites do OCR via Playwright too),
  so we don't add a new system dep.
- Chromium honours the same CSS as a user's browser, so the PDF
  output matches what the chat UI shows on screen — including tables,
  fenced code blocks, and CJK characters.
- The text stays selectable in the resulting PDF (we don't rasterise).

The browser is launched lazily on first request and reused across
requests; one Playwright launch takes ~500ms so doing it per-request
would be unacceptable for chat-export UX.

We use Playwright's **async** API instead of sync. The sync API uses
greenlet to switch between event-loop contexts, and that breaks down
when FastAPI's TestClient recycles its threadpool workers across test
runs (greenlet.error: cannot switch to a different thread). Async
Playwright stays inside the FastAPI event loop and avoids the entire
class of bugs.
"""
from __future__ import annotations

import asyncio
import logging

import markdown as python_markdown
from playwright.async_api import (
    Browser,
    Playwright,
    async_playwright,
)

logger = logging.getLogger(__name__)


# Maximum markdown payload we will render. Anything bigger almost
# certainly means the caller pasted a document by accident — render
# time scales linearly and a 5MB markdown blob would take seconds to
# lay out. 5 MB of UTF-8 markdown is ~1-2M Chinese characters or ~1M
# English characters, which is well beyond any chat export.
MAX_MARKDOWN_BYTES = 5 * 1024 * 1024


# Singleton browser state. We keep a lock because the FastAPI app may
# serve concurrent requests (e.g. from multiple tabs or from tests).
# ``asyncio.Lock`` is the right primitive for async code.
_playwright: Playwright | None = None
_browser: Browser | None = None
_browser_lock: asyncio.Lock | None = None


async def _get_browser() -> Browser:
    """Return a shared headless Chromium instance, launching on first use.

    Raises:
        RuntimeError: if Chromium is not installed (caller should ask
            the operator to run ``playwright install chromium``).
    """
    global _playwright, _browser, _browser_lock
    if _browser is not None:
        return _browser
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _browser is not None:  # double-checked under the lock
            return _browser
        try:
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch()
        except Exception as e:
            # Most common cause on a fresh machine: Chromium binary
            # not downloaded. Surface a clear message instead of a
            # generic playwright traceback.
            raise RuntimeError(
                "Playwright Chromium is not available. "
                "Run `playwright install chromium` in the backend venv."
            ) from e
        logger.info("[ExportPdfService] Chromium launched (singleton)")
        return _browser


async def shutdown_browser() -> None:
    """Close the singleton browser — call from process-shutdown hooks
    or tests to release Chromium cleanly."""
    global _playwright, _browser
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _build_html(md_text: str, title: str) -> str:
    """Render markdown to a complete, self-contained HTML document.

    The HTML embeds its own print CSS (margins, CJK font stack, table
    borders, monospace code blocks) so Playwright can lay it out
    without a separate stylesheet roundtrip.
    """
    body_html = python_markdown.markdown(
        md_text,
        extensions=[
            "tables",  # GFM pipe tables
            "fenced_code",  # ``` blocks
            "codehilite",  # pygments syntax highlighting inside fenced_code
            "nl2br",  # single newlines → <br>
            "sane_lists",  # sane nested list behaviour
        ],
        output_format="html5",
    )

    # Escape the title so a markdown injection in the title field
    # can't break out of the <title> element.
    safe_title = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>{safe_title}</title>
<style>
  @page {{
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
  }}
  html, body {{
    margin: 0;
    padding: 0;
    /* CJK + Latin font stack: PingFang SC for macOS, Microsoft YaHei
       for Windows, Source Han Sans / Noto Sans CJK for Linux.
       The browser will fall through to the first one it has. */
    font-family: "PingFang SC", "Microsoft YaHei", "Hiragino Sans GB",
                 "Source Han Sans CN", "Noto Sans CJK SC",
                 -apple-system, BlinkMacSystemFont, "Segoe UI",
                 Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.55;
    color: #222;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  h1, h2, h3, h4 {{
    color: #111;
    line-height: 1.25;
    margin-top: 1.2em;
    margin-bottom: 0.5em;
    page-break-after: avoid;
  }}
  h1 {{ font-size: 1.6em; border-bottom: 1px solid #ddd; padding-bottom: 0.2em; }}
  h2 {{ font-size: 1.3em; }}
  h3 {{ font-size: 1.1em; }}
  p {{ margin: 0.6em 0; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  ul, ol {{ padding-left: 1.6em; }}
  li {{ margin: 0.2em 0; }}
  table {{
    border-collapse: collapse;
    margin: 0.8em 0;
    width: 100%;
    page-break-inside: avoid;
  }}
  th, td {{
    border: 1px solid #999;
    padding: 5pt 7pt;
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background: #f0f0f0;
    font-weight: 600;
  }}
  /* codehilite emits <div class="codehilite"><pre>...</pre></div>;
     style both the wrapper and the raw <pre><code> for sites that
     don't go through codehilite. */
  pre, div.codehilite {{
    background: #f5f5f5;
    border: 1px solid #e0e0e0;
    border-radius: 3px;
    padding: 8pt 10pt;
    overflow-x: auto;
    font-family: "Cascadia Code", "JetBrains Mono", Consolas,
                 "Liberation Mono", Menlo, monospace;
    font-size: 9.5pt;
    line-height: 1.45;
    page-break-inside: avoid;
  }}
  pre {{ margin: 0.6em 0; }}
  code {{
    font-family: "Cascadia Code", "JetBrains Mono", Consolas,
                 "Liberation Mono", Menlo, monospace;
    font-size: 0.92em;
    background: transparent;
  }}
  p code, li code {{
    background: #f5f5f5;
    padding: 1px 4px;
    border-radius: 2px;
  }}
  blockquote {{
    border-left: 3px solid #ccc;
    margin: 0.6em 0;
    padding: 0.1em 1em;
    color: #555;
    font-style: italic;
  }}
  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 1em 0;
  }}
  img {{ max-width: 100%; height: auto; }}
</style>
</head>
<body>
{body_html}
</body>
</html>
"""


async def markdown_to_pdf(md_text: str, title: str = "Chat Export") -> bytes:
    """Render markdown text to PDF bytes.

    Args:
        md_text: Raw markdown source from the chat message.
        title: Document title — used for the PDF's ``<title>`` metadata
            and embedded PDF /Title field. Plain text only.

    Returns:
        PDF file contents as bytes. Starts with the ``%PDF-`` magic.

    Raises:
        ValueError: if the markdown payload is empty or exceeds
            :data:`MAX_MARKDOWN_BYTES`.
        RuntimeError: if Chromium is not installed.
    """
    if not md_text or not md_text.strip():
        raise ValueError("markdown payload is empty")
    encoded_size = len(md_text.encode("utf-8"))
    if encoded_size > MAX_MARKDOWN_BYTES:
        raise ValueError(
            f"markdown payload too large: {encoded_size} bytes "
            f"(max {MAX_MARKDOWN_BYTES})"
        )

    html = _build_html(md_text, title)
    browser = await _get_browser()
    # Each request gets its own context so concurrent renders don't
    # race on the same page object. Contexts are cheap to create.
    context = await browser.new_context()
    try:
        page = await context.new_page()
        # wait_until="load" is enough — there are no external scripts
        # or fonts to wait for (everything is inline). networkidle
        # would only delay us if Chromium kept a devtools socket open.
        await page.set_content(html, wait_until="load")
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,
            margin={
                "top": "0",
                "bottom": "0",
                "left": "0",
                "right": "0",
            },
            # Header / footer via display_header_footer would add a
            # timestamp; users asked for clean export, so leave them
            # out. The @page CSS handles actual margins.
        )
    finally:
        await context.close()
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(
            f"Playwright produced an unexpected PDF payload "
            f"(len={len(pdf_bytes) if pdf_bytes else 0})"
        )
    logger.info(
        "[ExportPdfService] rendered PDF: md=%d bytes → pdf=%d bytes",
        encoded_size,
        len(pdf_bytes),
    )
    return pdf_bytes