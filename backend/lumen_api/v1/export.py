"""Chat export endpoints — render markdown to PDF.

POST /api/v1/export/pdf
    Body:  ``{"markdown": str, "title"?: str}``
    Auth:  Bearer token (any logged-in user).
    Reply: ``application/pdf`` binary, Content-Disposition attachment.

The endpoint does NOT wrap the PDF in the project's usual
SingleResponse envelope — binary content doesn't fit the JSON envelope
contract, and the only "response" the client cares about is the
downloadable file. This matches the existing pattern in
``/api/v1/documents/generate/word``.
"""
from __future__ import annotations

import asyncio
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_services.export_pdf_service import (
    MAX_MARKDOWN_BYTES,
    markdown_to_pdf,
    shutdown_browser,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


class ExportPdfRequest(BaseModel):
    """Request body for /export/pdf.

    ``markdown`` is the raw markdown source from the chat message
    (typically ``Message.content``). ``title`` is plain text used as
    the PDF's document title — defaults to ``"Chat Export"`` if omitted.
    """

    markdown: str = Field(..., min_length=1)
    title: str = Field(default="Chat Export", max_length=200)


@router.post("/pdf")
async def export_pdf(
    body: ExportPdfRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Render the supplied markdown to a downloadable PDF.

    Returns the PDF bytes inline with ``Content-Disposition: attachment``
    so the browser triggers a download with a sensible filename.

    The handler is async and delegates the sync Playwright render to
    ``asyncio.to_thread`` so we don't block the event loop while
    Chromium is laying out the page. This also avoids the
    greenlet-state corruption that hits FastAPI's TestClient when
    sync handlers repeatedly call into Playwright's sync API from
    a recycled threadpool worker.
    """
    # Reject oversize payloads up-front so we don't waste a Playwright
    # launch on a request we already know we'll refuse.
    payload_bytes = len(body.markdown.encode("utf-8"))
    if payload_bytes > MAX_MARKDOWN_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"markdown payload too large: {payload_bytes} bytes "
                f"(max {MAX_MARKDOWN_BYTES})"
            ),
        )

    try:
        # markdown_to_pdf is async (uses Playwright async API to
        # avoid greenlet-state corruption under FastAPI's threadpool).
        pdf_bytes = await markdown_to_pdf(body.markdown, body.title)
    except ValueError as e:
        # Empty / whitespace-only markdown — the frontend should not
        # be sending this, but we surface a clean 400 instead of a
        # 500 if it does.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    except RuntimeError as e:
        # Chromium not installed (or any other Playwright bootstrap
        # failure). 503 because the server itself is misconfigured
        # — not the client's fault.
        logger.exception("[export/pdf] render failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Build a safe ASCII filename from the title so browsers don't
    # mangle non-ASCII characters in Content-Disposition. Starlette
    # encodes header values as latin-1, so non-ASCII chars raise
    # UnicodeEncodeError before the response even leaves FastAPI.
    # ``str.isalnum()`` returns True for CJK characters too, so we
    # restrict to the explicit ASCII range.
    safe_stem = "".join(
        c if ("a" <= c <= "z") or ("A" <= c <= "Z") or ("0" <= c <= "9") or c in "-_"
        else "_"
        for c in body.title
    )
    safe_stem = safe_stem.strip("_") or "chat-export"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_stem}.pdf"',
            "Content-Length": str(len(pdf_bytes)),
            # Disable caching so successive exports don't accidentally
            # return the previous response if the browser caches.
            "Cache-Control": "no-store",
        },
    )


@router.on_event("shutdown")
def _shutdown_export_browser():
    """Close the shared Chromium instance on FastAPI shutdown.

    Without this, ``uvicorn`` reloads / restarts leak Chromium
    subprocesses that hold the port 11335 socket pattern can hide.
    """
    shutdown_browser()