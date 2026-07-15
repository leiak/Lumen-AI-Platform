"""POST /api/v1/external/chat/upload — parse an uploaded file to text.

Mirrors /chat/upload (see app/api/v1/chat.py:376) but goes through
the ExternalAppContext auth dep. Returns content_text only (not
persisted) — the widget keeps the parsed text in component state
and re-sends it via the stream request's attachments field.
"""
import asyncio
import os
import tempfile
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from lumen_api.v1.deps import ExternalAppContext, get_current_external_app
from lumen_schemas.common import SingleResponse
from lumen_schemas.chat import UploadResult
from lumen_services.document_parser import DocumentParser

router = APIRouter()

ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CONTENT_TEXT_BYTES = 5 * 1024 * 1024


@router.post("/chat/upload", response_model=SingleResponse[UploadResult])
async def upload_attachment(
    file: UploadFile = File(...),
    ctx: ExternalAppContext = Depends(get_current_external_app),
):
    if "chat:upload" not in ctx.scopes:
        raise HTTPException(status_code=403, detail="missing scope: chat:upload")

    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, detail=f"不支持的文件格式:{ext}")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail=f"文件过大({len(raw)} bytes)")

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        parser = DocumentParser()
        result = await asyncio.to_thread(parser.parse, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    content_text = ""
    if isinstance(result, dict):
        content_text = result.get("content") or result.get("text") or ""
        if not content_text and "chunks" in result:
            content_text = "\n\n".join(
                c.get("content", "") for c in result["chunks"] if c.get("content")
            )
    elif isinstance(result, str):
        content_text = result

    if not content_text:
        raise HTTPException(422, detail="文件解析失败:未提取到文本")
    if len(content_text.encode("utf-8")) > MAX_CONTENT_TEXT_BYTES:
        raise HTTPException(413, detail="解析后文本过大(>5MB)")

    return SingleResponse(data=UploadResult(
        file_id=str(uuid.uuid4()),
        name=filename,
        size=len(raw),
        mime_type=file.content_type or "application/octet-stream",
        content_text=content_text,
    ))
