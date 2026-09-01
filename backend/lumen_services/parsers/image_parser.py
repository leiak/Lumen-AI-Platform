"""M38.4 — Image parser.

Each uploaded image file (.png / .jpg / .webp / .gif / .bmp / .tiff per
spec §"开放问题 7") becomes a single ``DocumentChunk`` with
``modality="image"``. The chunk's ``content`` is a *caption* — for MVP
this is the filename with separators replaced by spaces (spec §"开放
问题 2" — LLM-generated captions are v2). The caption is the multimodal
embedder's text input; its quality directly drives cross-modal recall.

The parser is **authoritative** for chunking (one image → exactly one
chunk). It also records width / height / mime so the caller can write
an ``ImageAsset`` row when the doc lands. The bytes themselves are
**not** duplicated into the parser output — the caller already has
``file_path`` and can read from disk / storage as needed.
"""
from __future__ import annotations

import os
from typing import Any, Dict

from . import BaseParser


# File extensions we claim to handle. Anything outside this set gets
# routed to ``_fallback_parse`` (which reads raw bytes as latin-1 text
# and emits a no-op chunk) — better than crashing the upload.
IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


class ImageParser(BaseParser):
    """Image (.png / .jpg / .webp / …) parser — one chunk per image."""

    preserves_chunks: bool = True

    def get_type(self) -> str:
        return "image"

    def parse(self, file_path: str) -> Dict[str, Any]:
        ext = os.path.splitext(file_path)[1].lower()
        mime = IMAGE_EXTENSIONS.get(ext)
        if mime is None:
            return self._fallback_parse(
                file_path,
                reason=f"unsupported image extension: {ext}",
            )

        # PIL is the project's Pillow dependency. If for some reason
        # it's missing we still emit a chunk with the filename-derived
        # caption — better than a hard failure on a single dependency
        # miss (the user can still see the image in the KB UI).
        width: int | None = None
        height: int | None = None
        try:
            from PIL import Image  # local import — Pillow is heavy at import time

            with Image.open(file_path) as img:
                width, height = img.size
        except Exception as exc:
            # PIL missing / corrupt image — keep going with the caption
            # and let downstream surface the parse error.
            return self._make_result(
                file_path, mime, width, height, reason=f"pillow: {type(exc).__name__}: {exc}"
            )

        return self._make_result(file_path, mime, width, height)

    def _make_result(
        self,
        file_path: str,
        mime: str,
        width: int | None,
        height: int | None,
        reason: str = "",
    ) -> Dict[str, Any]:
        caption = _caption_from_filename(file_path)

        chunk_record: Dict[str, Any] = {
            "content": caption,
            "chunk_index": 0,
            "length": len(caption),
            "strategy": "image_caption",
            "modality": "image",
            "sheet_name": None,
            "page_number": None,
            "image_caption": caption,
            "chunk_metadata": {
                "kind": "image",
                "caption": caption,
                "width": width,
                "height": height,
                "mime": mime,
            },
        }
        if reason:
            chunk_record["chunk_metadata"]["pillow_error"] = reason

        # Mirror BaseParser._fallback_parse's metadata contract: when
        # there's a parse_error, set ``fallback=True`` so the
        # downstream Document row ends up in the failed state (see
        # ``document_tasks.py:222-240`` — it reads
        # ``metadata.parse_error`` to decide whether to fail the doc
        # instead of committing garbage chunks). Keeping the legacy
        # contract consistent across parsers means
        # ``document_tasks`` doesn't need a special branch for
        # multimodal files that errored.
        meta: Dict[str, Any] = {
            "type": self.get_type(),
            "format": mime.split("/")[-1],
            "width": width,
            "height": height,
            "mime": mime,
            "file_path": file_path,
            "caption": caption,
            "chunk_count": 1,
        }
        if reason:
            meta["fallback"] = True
            meta["pillow_error"] = reason
            meta["parse_error"] = reason

        return {
            "text": caption,
            "metadata": meta,
            "chunks": [chunk_record],
            "chunk_metadata": [chunk_record["chunk_metadata"]],
        }


def _caption_from_filename(file_path: str) -> str:
    """Derive a caption from the filename.

    Spec §"开放问题 2" — MVP uses the filename as the caption, with
    underscores / dashes / multiple whitespace collapsed to a single
    space. ``"product_logo_v2.png"`` → ``"product logo v2"``. Future
    v2 will swap this for an LLM-generated caption via GPT-4V.

    The intent: a user searching "logo" must find a file named
    ``product_logo.png`` even without an LLM captioner wired up.
    """
    stem = os.path.splitext(os.path.basename(file_path))[0]
    if not stem:
        return "image"
    return stem.replace("_", " ").replace("-", " ").strip() or "image"


__all__ = ["ImageParser"]
