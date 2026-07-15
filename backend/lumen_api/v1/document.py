import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_services.document_generator import DocumentGenerator
import json

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/generate/word")
async def generate_word_document(
    title: str,
    content: str,
    current_user: User = Depends(get_current_user)
):
    """Generate a Word document"""
    try:
        # Sanitize title to prevent HTTP header injection
        safe_title = title.replace('"', '_').replace('\n', '').replace('\r', '')
        gen = DocumentGenerator()
        doc_bytes = gen.generate_word(title, content)
        return StreamingResponse(
            io.BytesIO(doc_bytes),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.docx"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/excel")
async def generate_excel_document(
    data: str,  # JSON string of array
    headers: str = None,  # JSON string of headers
    filename: str = "data",
    current_user: User = Depends(get_current_user)
):
    """Generate an Excel document"""
    try:
        data_list = json.loads(data)
        header_list = json.loads(headers) if headers else None
        # Sanitize filename to prevent HTTP header injection
        safe_filename = filename.replace('"', '_').replace('\n', '').replace('\r', '')

        gen = DocumentGenerator()
        doc_bytes = gen.generate_excel(data_list, header_list)
        return StreamingResponse(
            io.BytesIO(doc_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename}.xlsx"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))