"""M29.2 (2026-06-15): docx parser 修复的 4 个静态 source-level 回归测试。

M29.1 的 ``test_document_tasks_m29_fixes.py`` 验证
``document_tasks.process_document_task`` 路径 bug。这边同等模式
验证 M29.2 在 ``parsers/__init__.py`` 和 ``chunking_service.py``
里加的 4 个修复是否还在:

1. python-docx 在 ``parsers/__init__.py`` 引入
2. ``_parse_with_docx_fallback`` 在 ``parsers/__init__.py``
3. ``chunking_service.is_heading`` 含 ``（\d+）`` 正则(覆盖中文括号包数字)
4. ``TYPE_PATTERNS["manual"]`` 含 "功能文档" / "需求文档"

风格: 纯 ``inspect.getsource()`` 静态检查,无 dev DB / live LLM 依赖。
"""
import sys
import os
import inspect

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_parsers_module_imports_python_docx():
    """Bug #1 回归: ``parsers/__init__.py`` 必须 import python-docx。

    M29.2 引入 ``from docx import Document`` 作为 Level 2 fallback
    解析器(``_parse_with_python_docx``)。如果未来 refactor 把
    python-docx 移除,docx 三级 chain 的 Level 2 解析器就空了
    — Docling 截断时直接走到 Level 3 ``_fallback_parse``(只读
    文本),丢失段落结构。
    """
    import lumen_services.parsers as parsers_mod

    # 直接读源文件 — ``inspect.getsource`` 对 package 的 __init__
    # 属性返 method-wrapper 报错
    src_path = parsers_mod.__file__
    assert src_path and src_path.endswith(".py"), (
        f"无法定位 parsers 源文件: {src_path}"
    )
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    assert "from docx import Document" in src, (
        "parsers/__init__.py 必须有 'from docx import Document' — "
        "M29.2 docx 三级 fallback chain 的 Level 2 解析器依赖"
    )


def test_parsers_module_has_docx_fallback_chain():
    """Bug #2 回归: ``_parse_with_docx_fallback`` 必须在
    ``parsers/__init__.py``。

    同样不能少 ``_parse_with_python_docx`` 和 ``_looks_like_truncated_docx``。
    """
    from lumen_services.parsers import BaseParser

    # 方法在 BaseParser 上(供所有 6 个 parser 继承)
    for method_name in (
        "_parse_with_docx_fallback",
        "_parse_with_python_docx",
        "_looks_like_truncated_docx",
        "_docx_xml_text_length",
    ):
        assert hasattr(BaseParser, method_name), (
            f"BaseParser 必须有 {method_name} 方法(M29.2 docx 三级 chain)"
        )


def test_chunking_is_heading_has_parenthesis_regex():
    """Bug #3 回归: ``chunking_service.DocumentStructureChunking.is_heading``
    必须识别 ``（一）`` / ``（1）`` / ``（a）`` 格式。

    静态检查: 源码里必须有 4 条新正则:
    - ``r'^[一二三四五六七八九十]+[）)]'``(汉字 + 闭括号)
    - ``r'^[（(][一二三四五六七八九十]+[）)]'``(左括号 + 汉字 + 右括号)
    - ``r'^[（(]\d+[）)]'``(左括号 + 数字 + 右括号)
    - ``r'^[（(][a-zA-Z]+[）)]'``(左括号 + 字母 + 右括号)
    """
    from lumen_services.chunking_service import DocumentStructureChunking

    src = inspect.getsource(DocumentStructureChunking)
    # 4 条新正则必须存在
    assert r"^[一二三四五六七八九十]+[）)]" in src, (
        "DocumentStructureChunking.is_heading 必须含 "
        r"r'^[一二三四五六七八九十]+[）)]' — 覆盖 一）/二） 格式"
    )
    assert r"^[（(][一二三四五六七八九十]+[）)]" in src, (
        "DocumentStructureChunking.is_heading 必须含 "
        r"r'^[（(][一二三四五六七八九十]+[）)]' — 覆盖 （一）/(二) 格式"
    )
    assert r"^[（(]\d+[）)]" in src, (
        "DocumentStructureChunking.is_heading 必须含 "
        r"r'^[（(]\d+[）)]' — 覆盖 (1)/(2) 格式"
    )
    assert r"^[（(][a-zA-Z]+[）)]" in src, (
        "DocumentStructureChunking.is_heading 必须含 "
        r"r'^[（(][a-zA-Z]+[）)]' — 覆盖 (a)/(b) 格式"
    )


def test_type_patterns_manual_has_function_doc_keywords():
    """Bug #4 回归: ``TYPE_PATTERNS["manual"]`` 必须含 "功能文档" /
    "需求文档" / "产品文档" / "PRD"。

    这是 M29.2 关键路由点:精准停车功能文档.docx 命中 "功能文档"
    → ManualParser → document_structure 分块(替换原 general →
    fixed_size_500_50),修复 5 个孤立 21 字符 chunk 问题。
    """
    from lumen_services.parsers import DocumentParserFactory

    manual_patterns = DocumentParserFactory.TYPE_PATTERNS["manual"]
    expected = ["功能文档", "需求文档", "产品文档", "PRD"]
    for keyword in expected:
        assert any(keyword in p for p in manual_patterns), (
            f"TYPE_PATTERNS['manual'] 必须含 '{keyword}' 模式,"
            f"M29.2 修复精准停车功能文档.docx → manual 路由"
            f"实际: {manual_patterns}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
