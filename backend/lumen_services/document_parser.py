import os
import logging
from typing import Optional, Dict, Any, List, Tuple

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
            # M38.4 (2026-09-01) — multimodal formats. The downstream
            # dispatch (DocumentParserFactory.get_parser) maps these
            # extensions to ``excel`` / ``ppt`` / ``image`` parser
            # types. ``doc_format`` below is also passed to the parser
            # via ``result["metadata"]["format"]`` so chunk_metadata
            # can carry the MIME family alongside the parser's own
            # ``type`` field (which is the *parser* type, e.g. "excel").
            '.xlsx': 'xlsx',
            '.xls': 'xls',
            '.xlsm': 'xlsx',
            '.pptx': 'pptx',
            '.ppt': 'ppt',
            '.pptm': 'pptx',
            '.png': 'image',
            '.jpg': 'image',
            '.jpeg': 'image',
            '.webp': 'image',
            '.gif': 'image',
            '.bmp': 'image',
            '.tiff': 'image',
            '.tif': 'image',
        }

    def parse(
        self,
        file_path: str,
        file_type: str = None,
        doc_type: str = None,
        storage_key: str = None,
    ) -> Dict[str, Any]:
        """
        Parse document and extract text content.
        Falls back to raw text reading if specialized parsing fails.

        Args:
            file_path: Path to the document (legacy / local-mode path)
            file_type: MIME type (ignored, use ext instead)
            doc_type: Document type (general/paper/qa/table/manual/laws)
                     If None, auto-detects from filename
            storage_key: M38.1 storage key (preferred). When set, the
                parser resolves it through ``storage.resolve_to_local_path``
                so S3/MinIO mode works without breaking pdfplumber /
                docling which require a real filesystem path. Falls
                back to ``file_path`` if ``storage_key`` is missing
                or fails to resolve.

        Returns:
            Dict with keys: text (str), metadata (dict), chunks (list)

        ``metadata.parse_error`` is set when the underlying docling
        parser fell back to a raw text read. Downstream code reads this
        to decide whether to mark the ``Document`` row as failed.
        """
        # M38.1 follow-up: prefer storage_key over file_path so S3
        # mode works end-to-end. ``_resolve_parse_path`` returns a
        # local path and tracks whether we created a temp file that
        # needs cleanup afterwards.
        parse_path, temp_path, storage_key_used = self._resolve_parse_path(file_path, storage_key)
        ext = os.path.splitext(parse_path)[1].lower()
        doc_format = self.supported_formats.get(ext, 'unknown')

        # Get the appropriate parser
        from lumen_services.parsers import DocumentParserFactory
        parser = DocumentParserFactory.get_parser(doc_type=doc_type, file_path=parse_path)

        try:
            result = parser.parse(parse_path)

            # Add format info to metadata
            result["metadata"]["format"] = doc_format
            # ``metadata.file_path`` records the resolved local path
            # (helpful for debugging the parser chain). The original
            # ``storage_key`` (if any) is also surfaced so downstream
            # callers can map parsed text → storage object.
            result["metadata"]["file_path"] = parse_path
            if storage_key and storage_key_used:
                result["metadata"]["storage_key"] = storage_key

            # Extract chunks based on document type — but only if the
            # parser didn't already produce authoritative chunks.
            # M38.4 multimodal parsers (Excel/PPT/Image) carry their
            # own ``chunks`` + ``chunk_metadata`` lists with sheet /
            # slide / modality hints that the secondary text-split
            # pass would shred. ``preserves_chunks`` (BaseParser class
            # attr, default False) signals trust the parser's output.
            if getattr(parser, "preserves_chunks", False):
                logger.debug(
                    "parser %s marked preserves_chunks=True; skipping secondary split",
                    parser.get_type(),
                )
                # Defensive: if the multimodal parser forgot to populate
                # ``chunks`` (programmer error), fall back to the
                # legacy path so we never commit zero chunks.
                if not result.get("chunks"):
                    logger.warning(
                        "parser %s has preserves_chunks=True but returned no chunks; "
                        "falling back to legacy text-split",
                        parser.get_type(),
                    )
                    result["chunks"] = self._create_chunks(
                        result["text"], parser.get_type()
                    )
            else:
                result["chunks"] = self._create_chunks(result["text"], parser.get_type())

            return result
        except Exception as e:
            # Last-resort: the parser itself threw before it could call
            # its own _fallback_parse. Record the reason so the caller
            # can mark the Document as failed instead of committing
            # garbage chunks.
            reason = f"{type(e).__name__}: {e}"
            logger.warning("Document parsing failed for %s: %s", parse_path, reason)
            fallback = self._fallback_result(parse_path)
            fallback["metadata"]["parse_error"] = reason
            return fallback
        finally:
            # ``storage_key`` mode creates a temp file in the S3
            # backend's ``resolve_to_local_path``; clean it up.
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _resolve_parse_path(self, file_path: str, storage_key: Optional[str]) -> tuple[str, Optional[str], bool]:
        """Resolve a parser input path.

        Priority:
        1. ``storage_key`` → ``storage.resolve_to_local_path(key)``.
           On local backend this returns the existing file path; on
           S3/MinIO it downloads to a temp file.
        2. ``file_path`` (legacy / already-resolved) — return as-is.

        Returns ``(parse_path, temp_path_or_None, storage_key_used)``.
        ``storage_key_used`` is False when the resolver fell back to
        ``file_path`` (so the caller knows not to surface the key
        on the result metadata — keeps failure modes honest).
        """
        if storage_key:
            try:
                from lumen_services.storage import get_storage_backend
                backend = get_storage_backend()
                resolved = backend.resolve_to_local_path(storage_key)
                # ``temp_path`` cleanup needed iff the backend made a
                # copy. ``LocalBackend.resolve_to_local_path`` returns
                # the original file path so temp_path is None.
                temp = None if resolved == file_path else resolved
                # Sanity: if resolved differs from file_path and the
                # file_path was None, definitely a temp.
                if file_path is None:
                    temp = resolved
                return resolved, temp, True
            except FileNotFoundError:
                # Storage layer said the key doesn't exist — fall
                # through to the legacy ``file_path`` so the caller
                # gets a clearer error than "backend not configured".
                logger.warning(
                    "storage_key %r not found, falling back to file_path",
                    storage_key,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "storage.resolve_to_local_path(%r) failed (%s); using file_path",
                    storage_key, exc,
                )
        return file_path, None, False

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
            # M38.4 (2026-09-01) — multimodal parsers carry their own
            # chunks via ``preserves_chunks=True`` and never reach this
            # path. Listed here as a no-op fallback so a future caller
            # that bypasses the parser flag (e.g. unit tests) still
            # gets a sensible default rather than ``fixed``.
            "excel": "fixed",
            "ppt": "fixed",
            "image": "fixed",
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