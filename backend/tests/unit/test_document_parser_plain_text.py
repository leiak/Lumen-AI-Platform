"""DocumentParser plain-text fast-path 测试。

2026-09-14 dev 故障:用户上传 ``.txt`` / ``.md`` / ``.html`` 文件,
celery-doc worker 把它们路由给 Docling,Docling 把 ``.txt`` 当 PDF
解析,触发 ``pypdfium2: PdfiumError: Failed to load document
(PDFium: Data format error)`` → ``document.status='failed'``。

修法:``DocumentParser.parse()`` 在 extension 命中
``PLAIN_TEXT_FORMATS`` 时直接 ``open(..., 'r')`` 读 text,跳过
Docling + PDF fallback chain。

测试守住契约:
  1. ``.txt`` / ``.md`` / ``.html`` 走 fast-path(不进 Docling)
  2. fast-path 产出的 chunks 跟 general/fixed 500/50 一致
  3. ``.pdf`` 继续走 Docling 链
  4. ``PLAIN_TEXT_FORMATS`` 不误伤 ``.pdf`` / ``.docx``
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from lumen_services.document_parser import DocumentParser


# ---- helpers --------------------------------------------------------------

class _FakeDoclingConvertTracker:
    """替换 ``docling.document_converter.DocumentConverter``。

    ``parse()`` 内部用 ``from docling.document_converter import DocumentConverter``
    拉类,所以必须把模块注入到 ``sys.modules`` 才能生效。如果 fast-path
    真的 bypass 了 Docling,``convert()`` 调用计数应该 == 0。
    """
    def __init__(self):
        self.convert_calls: list[str] = []

    def install(self):
        calls = self.convert_calls

        class _Doc:
            def export_to_text(self_inner):
                return ""  # 空 text,_create_chunks 仍会切出 1 个空 chunk

            @property
            def metadata(self_inner):
                return {"title": ""}

        class _Result:
            def __init__(self, path):
                self.document = _Doc()

        class _Converter:
            def convert(self_inner, path):
                calls.append(path)
                return _Result(path)

        docling_mod = sys.modules.get("docling") or type(sys)("docling")
        docling_mod.document_converter = type(sys)("docling.document_converter")
        docling_mod.document_converter.DocumentConverter = _Converter
        sys.modules["docling"] = docling_mod
        sys.modules["docling.document_converter"] = docling_mod.document_converter
        return self

    def assert_not_called(self):
        assert self.convert_calls == [], (
            f"Docling 被错误调用了 ({len(self.convert_calls)} 次) — "
            "fast-path 没生效,plain-text 文件被错误路由到 PDF 解析链"
        )


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ---- tests ----------------------------------------------------------------

class TestPlainTextFastPath:
    """Plain-text formats 走 fast-path,产出 chunks + 正确 metadata。"""

    @pytest.mark.parametrize(
        "ext,body",
        [
            ("txt", "测试 txt 文本。\n第二行。\n\n第三段。"),
            ("md", "# 标题\n\nMarkdown 段落 **加粗**。\n\n## 二级\n\n内容。"),
            ("html", "<html><body><h1>标题</h1><p>段落。</p></body></html>"),
        ],
    )
    def test_plain_text_bypasses_docling(self, tmp_path, ext, body):
        """fast-path 不应触发 ``Docling.DocumentConverter.convert()``。"""
        tracker = _FakeDoclingConvertTracker().install()

        parser = DocumentParser()
        f = _write(tmp_path, f"sample.{ext}", body)

        result = parser.parse(str(f))

        tracker.assert_not_called()
        assert result["text"] == body, f"text 不匹配 for .{ext}"
        assert result["metadata"]["parser"] == "plain_text_fastpath", (
            f"metadata.parser 不是 plain_text_fastpath: {result['metadata']}"
        )
        assert result["metadata"]["format"] in {"txt", "markdown", "html"}
        # chunks 应该按 general → fixed 500/50 切,长度 >= 1
        assert len(result["chunks"]) >= 1

    def test_txt_long_body_chunks_correctly(self, tmp_path):
        """长 .txt → fixed 500/50 切出多段。"""
        _FakeDoclingConvertTracker().install()
        long_body = "plain text 测试段落 " * 100  # ~1600 chars

        parser = DocumentParser()
        f = _write(tmp_path, "long.txt", long_body)

        result = parser.parse(str(f))

        assert result["text"] == long_body
        # fixed 500 切 ~1600 chars → 至少 3 段
        assert len(result["chunks"]) >= 3

    def test_pdf_path_uses_docling_chain(self, tmp_path):
        """.pdf 必须继续走 Docling — fast-path 不能误伤 PDF。"""
        tracker = _FakeDoclingConvertTracker().install()

        # 写一个最小 fake .pdf 让 supported_formats 命中 .pdf
        fake_pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"
        f = tmp_path / "real.pdf"
        f.write_bytes(fake_pdf)

        parser = DocumentParser()
        result = parser.parse(str(f))

        assert len(tracker.convert_calls) == 1, (
            f".pdf 应该进 Docling chain,实际调用 {len(tracker.convert_calls)} 次"
        )
        assert result["metadata"].get("parser") != "plain_text_fastpath"
        assert result["metadata"]["format"] == "pdf"


class TestPlainTextFormatsContract:
    """``PLAIN_TEXT_FORMATS`` 集合本身守住 — 不能误伤 docx/pdf,必须含 txt/md/html。"""

    def test_docx_not_in_plain_text_formats(self):
        """docx 必须在 fast-path 之外 — Docling 提取 docx 比 plain-text 强太多。"""
        assert "docx" not in DocumentParser.PLAIN_TEXT_FORMATS

    def test_pdf_not_in_plain_text_formats(self):
        """pdf 必须继续走 PDF 三级 fallback chain。"""
        assert "pdf" not in DocumentParser.PLAIN_TEXT_FORMATS

    def test_required_plain_text_extensions_present(self):
        """txt / markdown / html 三种 plain-text 必须被覆盖。"""
        assert {"txt", "markdown", "html"}.issubset(DocumentParser.PLAIN_TEXT_FORMATS)
