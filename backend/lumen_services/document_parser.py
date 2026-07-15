import os
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class DocumentParser:
    def __init__(self):
        self.supported_formats = {
            '.pdf': 'pdf',
            '.docx': 'docx',
            '.doc': 'doc',
            '.txt': 'txt',
            '.md': 'markdown',
            '.html': 'html',
            '.htm': 'html',
        }

    def parse(
        self,
        file_path: str,
        file_type: str = None,
        doc_type: str = None
    ) -> Dict[str, Any]:
        """
        Parse document and extract text content.
        Falls back to raw text reading if specialized parsing fails.

        Args:
            file_path: Path to the document
            file_type: MIME type (ignored, use ext instead)
            doc_type: Document type (general/paper/qa/table/manual/laws)
                     If None, auto-detects from filename

        Returns:
            Dict with keys: text (str), metadata (dict), chunks (list)

        ``metadata.parse_error`` is set when the underlying docling
        parser fell back to a raw text read. Downstream code reads this
        to decide whether to mark the ``Document`` row as failed.
        """
        ext = os.path.splitext(file_path)[1].lower()
        doc_format = self.supported_formats.get(ext, 'unknown')

        # Get the appropriate parser
        from lumen_services.parsers import DocumentParserFactory
        parser = DocumentParserFactory.get_parser(doc_type=doc_type, file_path=file_path)

        try:
            result = parser.parse(file_path)

            # Add format info to metadata
            result["metadata"]["format"] = doc_format
            result["metadata"]["file_path"] = file_path

            # Extract chunks based on document type
            result["chunks"] = self._create_chunks(result["text"], parser.get_type())

            return result
        except Exception as e:
            # Last-resort: the parser itself threw before it could call
            # its own _fallback_parse. Record the reason so the caller
            # can mark the Document as failed instead of committing
            # garbage chunks.
            reason = f"{type(e).__name__}: {e}"
            logger.warning("Document parsing failed for %s: %s", file_path, reason)
            fallback = self._fallback_result(file_path)
            fallback["metadata"]["parse_error"] = reason
            return fallback

    def _fallback_result(self, file_path: str) -> Dict[str, Any]:
        """Fallback when parsing fails"""
        text = self._parse_text(file_path)
        return {
            "text": text,
            "metadata": {
                "type": "general",
                "format": "unknown",
                "file_path": file_path,
            },
            "chunks": self._create_chunks(text, "general")
        }

    def _create_chunks(self, text: str, doc_type: str) -> List[Dict[str, Any]]:
        """Create chunks based on document type"""
        from lumen_services.chunking_service import get_chunking_service

        service = get_chunking_service()

        # Use different default strategies based on doc type
        strategy_map = {
            "paper": "document_structure",
            "manual": "document_structure",
            "laws": "document_structure",
            "qa": "semantic",
            "table": "fixed",
            "general": "fixed",
        }

        strategy = strategy_map.get(doc_type, "fixed")

        return service.split_with_metadata(text, strategy_name=strategy)

    def _parse_pdf(self, file_path: str) -> str:
        """Parse PDF using Docling"""
        try:
            from docling.document_converter import DocumentConverter
            converter = DocumentConverter()
            result = converter.convert(file_path)
            return result.document.export_to_text()
        except Exception as e:
            logger.warning("Docling PDF parsing failed: %s", e)
            return self._parse_text(file_path)

    # M29.2 (2026-06-15): 删除 dead code _parse_docx — 它跟新
    # ``parsers/__init__.py`` 的 docx 三级 fallback chain 重复
    # (Docling → python-docx → _fallback_parse),实际 dispatch 在
    # ``DocumentParserFactory`` 各 parser 的 ``_parse_with_fallback``
    # 里。``DocumentParser`` 的 ``parse()`` 入口只走 factory,所以
    # 这条 fallback 永远不会触发。删除避免误导未来读者。

    def _parse_text(self, file_path: str) -> str:
        """Fallback: read raw text"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        return ""

    def _parse_html(self, file_path: str) -> str:
        """Simple HTML to text"""
        try:
            from bs4 import BeautifulSoup
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f.read(), 'html.parser')
                return soup.get_text(separator=' ', strip=True)
        except:
            return self._parse_text(file_path)

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract document metadata"""
        return {
            "filename": os.path.basename(file_path),
            "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        }