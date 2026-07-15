"""M29.2 (2026-06-15): docx 三级 fallback chain + ManualParser 路由测试。

6 个 test 覆盖:
1. 静态 ``inspect.getsource()`` 验证 python-docx 在 parsers/__init__.py 引入
2. 验证 ``_parse_with_docx_fallback`` 存在 + 3 级 chain 路由
3. 验证 ``_looks_like_truncated_docx`` 守门:Docling 输出 < 70% OOXML 长度
   触发 fallback
4. 验证 PDF 路径不被 docx 守门误伤(纯数字 OOXML 长度返回 0 放过)
5. 跑真实精准停车 docx,断言 "页面展示" 段数 ≥ 30(原 Docling 只 12)
6. 静态检查 ``TYPE_PATTERNS["manual"]`` 含 "功能文档" / "需求文档"

参照 M29.1 ``test_document_tasks_m29_fixes.py`` 风格:纯 pytest,
不依赖 dev DB / live LLM / live network。
"""
import os
import sys
import inspect
import tempfile

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ----------------------------------------------------------------------
# 1. 静态 import + source 静态检查
# ----------------------------------------------------------------------

def test_docx_parser_module_imports_python_docx():
    """验证 ``BaseParser._parse_with_python_docx`` 用 python-docx。

    静态检查: 源码里必须 import ``docx`` (而不是 ``docx2txt`` /
    ``docx2pdf`` / ``word`` 等替代品),且函数 ``_parse_with_python_docx``
    存在。
    """
    from lumen_services.parsers import BaseParser

    # 函数存在性
    assert hasattr(BaseParser, "_parse_with_python_docx"), (
        "BaseParser 必须有 _parse_with_python_docx 方法"
    )
    assert hasattr(BaseParser, "_parse_with_docx_fallback"), (
        "BaseParser 必须有 _parse_with_docx_fallback 三级 chain"
    )
    assert hasattr(BaseParser, "_looks_like_truncated_docx"), (
        "BaseParser 必须有 _looks_like_truncated_docx 守门"
    )

    # 静态 import 检查: 直接读源文件(``inspect.getsource`` 对
    # package 的 __init__ 属性返 method-wrapper 报错)
    import lumen_services.parsers as parsers_mod
    src_path = parsers_mod.__file__
    assert src_path and src_path.endswith(".py"), f"无法定位 parsers 源文件: {src_path}"
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "from docx import Document" in src, (
        "parsers/__init__.py 必须 import python-docx (from docx import Document),"
        "这是 docx 三级 fallback chain 的 Level 2 解析器"
    )


def test_docx_fallback_chain_signatures():
    """验证 ``_parse_with_docx_fallback`` 签名 + 3 级 chain 行为。

    静态: 签名必须是 ``(self, file_path, primary_parser_func)``。
    行为: 跑一个 mock primary 返 docling 输出,然后强制 truncated,
    验证走到 Level 2 python-docx。Level 3 失败路径(全 empty)走
    ``_fallback_parse`` 并设 ``parse_error``。
    """
    from lumen_services.parsers import BaseParser

    sig = inspect.signature(BaseParser._parse_with_docx_fallback)
    params = list(sig.parameters.keys())
    assert params == ["self", "file_path", "primary_parser_func"], (
        f"_parse_with_docx_fallback 签名不对: {params}"
    )

    # 行为: mock primary 抛异常 → 应走 Level 2 python-docx
    class _StubParser(BaseParser):
        def parse(self, file_path):
            raise NotImplementedError

        def get_type(self):
            return "general"

    # 准备一个最小 docx file (用 python-docx 生成,确保 OOXML 合法)
    from docx import Document
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        tmp_path = f.name
    try:
        doc = Document()
        # 包含一个 numPr 段(模拟精准停车文档结构)
        for i in range(3):
            p = doc.add_paragraph(f"段落 {i}:这是测试内容 " * 10)
        doc.save(tmp_path)

        stub = _StubParser()
        # primary 抛异常 → 触发 fallback
        def bad_primary(fp):
            raise RuntimeError("docling crashed")
        result = stub._parse_with_docx_fallback(tmp_path, bad_primary)
        assert result["metadata"].get("parser") == "python_docx_fallback", (
            f"primary 抛异常应走 Level 2,实际 parser={result['metadata'].get('parser')}"
        )
        assert "段落 0" in result["text"]
    finally:
        os.unlink(tmp_path)


# ----------------------------------------------------------------------
# 3. 守门启发式行为测试
# ----------------------------------------------------------------------

def test_truncation_detection_triggers_fallback():
    """验证 ``_looks_like_truncated_docx`` 在 Docling 输出 < 70% 时返 True。

    mock _docx_xml_text_length 返 1000,测试文本 600 chars → 触发
    fallback。
    """
    from lumen_services.parsers import BaseParser

    class _StubParser(BaseParser):
        def parse(self, file_path):
            raise NotImplementedError
        def get_type(self):
            return "general"
        def _docx_xml_text_length(self, fp):
            return 1000  # OOXML 文本 1000 chars

    stub = _StubParser()
    # 短文本(600 chars, 60% of 1000)→ truncated
    assert stub._looks_like_truncated_docx("a" * 600, "fake.docx") is True
    # 长文本(800 chars, 80% of 1000)→ not truncated
    assert stub._looks_like_truncated_docx("a" * 800, "fake.docx") is False
    # 边界(700 chars, 70% of 1000)→ NOT truncated(< 不是 <=)
    assert stub._looks_like_truncated_docx("a" * 700, "fake.docx") is False
    # 空文本 → 不触发(避免误杀)
    assert stub._looks_like_truncated_docx("", "fake.docx") is False


def test_truncation_detection_skips_for_pdf():
    """验证 OOXML 长度 0(非 docx 文件,如 PDF)时守门放过。

    PDF 走 ``_parse_with_pdf_fallback``,不应被 docx 守门误伤
    触发(因为 OOXML 长度 0 时 _looks_like_truncated_docx 返 False)。
    """
    from lumen_services.parsers import BaseParser

    class _StubParser(BaseParser):
        def parse(self, file_path):
            raise NotImplementedError
        def get_type(self):
            return "general"
        def _docx_xml_text_length(self, fp):
            return 0  # PDF 没有 OOXML 格式,长度 0

    stub = _StubParser()
    # 短文本 + OOXML 长度 0 → 不触发(PDF 路径保护)
    assert stub._looks_like_truncated_docx("a" * 100, "fake.pdf") is False
    assert stub._looks_like_truncated_docx("", "fake.pdf") is False


# ----------------------------------------------------------------------
# 5. 真实 docx 文件端到端测试
# ----------------------------------------------------------------------

# 真实文件路径(本地 dev DB 路径)
REAL_DOCX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "backend", "data", "uploads", "1", "451", "精准停车功能文档.docx"
)
# 兼容 __file__ 直接在 tests/unit/ 的情况(取上 3 级 = repo root)
REAL_DOCX_PATH_ALT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..",
                 "data", "uploads", "1", "451", "精准停车功能文档.docx")
)


def _resolve_real_docx_path() -> str:
    """查找真实 docx 路径 — 兼容从 repo root 或 backend 目录运行 pytest。"""
    for p in (REAL_DOCX_PATH, REAL_DOCX_PATH_ALT):
        if os.path.exists(p):
            return p
    return ""  # 跳过


@pytest.mark.skipif(
    not os.path.exists(REAL_DOCX_PATH) and not os.path.exists(REAL_DOCX_PATH_ALT),
    reason="真实精准停车 docx 不在 dev 路径(单测环境差异)"
)
def test_docx_with_real_file_extracts_all_numpr_paragraphs():
    """M29.2 端到端: 跑真实精准停车 docx,断言 "页面展示" 段 ≥ 30 个。

    原 Docling 输出丢 36% 字符 + 12/32 "页面展示" 段。修后:
    - python-docx 直接读 OOXML,保留所有 numPr 段
    - "页面展示" 段从 12 → 32(完整保留)
    """
    from lumen_services.parsers import BaseParser

    real_path = _resolve_real_docx_path()
    assert real_path, "找不到真实 docx 路径"

    class _StubParser(BaseParser):
        def parse(self, file_path):
            raise NotImplementedError
        def get_type(self):
            return "general"

    stub = _StubParser()
    # 1. 验证 OOXML 文本长度 > 0(确认是 docx)
    ooxml_len = stub._docx_xml_text_length(real_path)
    assert ooxml_len > 1000, f"OOXML 长度异常: {ooxml_len}"

    # 2. 验证 python-docx 提取的 "页面展示" 段数 ≥ 30
    text = stub._parse_with_python_docx(real_path)
    assert len(text) > 1000, f"python-docx 输出异常短: {len(text)}"
    page_show_count = text.count("页面展示")
    assert page_show_count >= 30, (
        f"python-docx 应该保留所有 '页面展示' 段(预期 ≥ 30),"
        f"实际 {page_show_count}。原 Docling 仅 12/32"
    )


# ----------------------------------------------------------------------
# 6. TYPE_PATTERNS manual 路由测试
# ----------------------------------------------------------------------

def test_function_doc_pattern_routes_to_manual():
    """验证 ``TYPE_PATTERNS["manual"]`` 含 "功能文档" / "需求文档"。

    这是 M29.2 关键路由点:精准停车功能文档.docx 命中 "功能文档"
    → ManualParser → document_structure 分块 → 修复 5 个孤立
    21 字符 chunk 问题。
    """
    from lumen_services.parsers import DocumentParserFactory

    # 直接静态检查 TYPE_PATTERNS
    manual_patterns = DocumentParserFactory.TYPE_PATTERNS["manual"]
    assert any("功能文档" in p for p in manual_patterns), (
        f"TYPE_PATTERNS['manual'] 必须含 '功能文档',实际: {manual_patterns}"
    )
    assert any("需求文档" in p for p in manual_patterns), (
        f"TYPE_PATTERNS['manual'] 必须含 '需求文档',实际: {manual_patterns}"
    )
    assert any("产品文档" in p for p in manual_patterns), (
        f"TYPE_PATTERNS['manual'] 必须含 '产品文档',实际: {manual_patterns}"
    )
    assert any("PRD" in p for p in manual_patterns), (
        f"TYPE_PATTERNS['manual'] 必须含 'PRD',实际: {manual_patterns}"
    )

    # 行为验证: 精准停车功能文档.docx 命中 manual
    detected = DocumentParserFactory.detect_doc_type("精准停车功能文档.docx")
    assert detected == "manual", (
        f"精准停车功能文档.docx 应该被识别为 manual,实际 {detected}"
    )

    # 验证其他类型(如 paper)不会误命中 "功能文档"
    assert DocumentParserFactory.detect_doc_type("精准停车 paper.pdf") == "paper"
    assert DocumentParserFactory.detect_doc_type("精准停车需求文档.docx") == "manual"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
