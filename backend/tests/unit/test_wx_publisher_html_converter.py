"""Unit tests for M32.1 HTML → Markdown converter.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md (M32.1 升级)
Reference: lark-to-markdown-main/utils/markdownConverter.ts 思路,独立实现。

覆盖 10 个 case (计划列了 10,这里分得稍细):
- 强元素合并(相邻 strong 避免 '****')
- 表格对齐识别(3 种)
- code block 围栏 + 语言识别
- 图片尺寸保留(2 种)
- span/div 解嵌套
- 空 HTML
- 飞书典型结构(标题 + 列表 + 表格 + 图片 + 代码块)
"""
from __future__ import annotations

import pytest

from lumen_services.wx_publisher.html_converter import HtmlToMarkdownConverter


@pytest.fixture
def conv() -> HtmlToMarkdownConverter:
    return HtmlToMarkdownConverter()


# ---- strong/b 合并 ---------------------------------------------------------

def test_strong_merge_adjacent(conv: HtmlToMarkdownConverter):
    """相邻 <strong> 应该合并,避免 '**a** **b**' 中间空格."""
    html = "<p><strong>a</strong><strong>b</strong></p>"
    out = conv.convert(html)
    assert "**ab**" in out
    assert "** **" not in out  # 无多余空格


def test_strong_split_by_text(conv: HtmlToMarkdownConverter):
    """strong 之间有文本时,正常加空格."""
    html = "<p><strong>a</strong> and <strong>b</strong></p>"
    out = conv.convert(html)
    assert "**a**" in out and "**b**" in out


def test_italic_basic(conv: HtmlToMarkdownConverter):
    """<em> → *text*"""
    html = "<p><em>italic</em></p>"
    out = conv.convert(html)
    assert "*italic*" in out


# ---- table alignment --------------------------------------------------------

def test_table_alignment_center(conv: HtmlToMarkdownConverter):
    """text-align: center → :---:"""
    html = (
        "<table>"
        "<thead><tr><th>name</th><th style='text-align: center'>value</th></tr></thead>"
        "<tbody><tr><td>x</td><td style='text-align: center'>1</td></tr></tbody>"
        "</table>"
    )
    out = conv.convert(html)
    assert "| :---: |" in out


def test_table_alignment_right(conv: HtmlToMarkdownConverter):
    """text-align: right → ---:"""
    html = (
        "<table>"
        "<tr><th>name</th><th style='text-align: right'>value</th></tr>"
        "<tr><td>x</td><td style='text-align: right'>1</td></tr>"
        "</table>"
    )
    out = conv.convert(html)
    assert "---:" in out


def test_table_alignment_default_left(conv: HtmlToMarkdownConverter):
    """无 text-align → 默认 --- (左对齐)"""
    html = (
        "<table>"
        "<tr><th>name</th><th>value</th></tr>"
        "<tr><td>x</td><td>1</td></tr>"
        "</table>"
    )
    out = conv.convert(html)
    assert "| --- |" in out


# ---- code block -------------------------------------------------------------

def test_code_block_fenced_with_lang(conv: HtmlToMarkdownConverter):
    """language-python class → ```python"""
    html = '<pre><code class="language-python">print("hi")</code></pre>'
    out = conv.convert(html)
    assert "```python" in out
    assert 'print("hi")' in out
    assert out.rstrip().endswith("```")


def test_code_block_no_lang(conv: HtmlToMarkdownConverter):
    """无 language class → ```"""
    html = "<pre><code>plain code</code></pre>"
    out = conv.convert(html)
    assert "```" in out
    assert "plain code" in out
    # 不应出现 "```\n" 后还有 language 字样
    assert "```\nplain" in out or "```plain" in out


def test_code_block_lang_prefix_variants(conv: HtmlToMarkdownConverter):
    """支持 lang- 和 highlight-source- 两种前缀 (feishu/GitHub 高亮样式)"""
    html1 = '<pre><code class="lang-js">var x = 1;</code></pre>'
    out1 = conv.convert(html1)
    assert "```js" in out1

    html2 = '<pre><code class="highlight-source-python">x = 1</code></pre>'
    out2 = conv.convert(html2)
    assert "```python" in out2


# ---- image ------------------------------------------------------------------

def test_image_with_size_preserved(conv: HtmlToMarkdownConverter):
    """有 width/height 时保留 <img> HTML 标签(微信公众号粘贴支持 style)."""
    html = '<img src="https://x.com/a.png" width="300" alt="x" />'
    out = conv.convert(html)
    assert "<img" in out
    assert "width: 300px" in out
    assert 'src="https://x.com/a.png"' in out


def test_image_size_from_style(conv: HtmlToMarkdownConverter):
    """从 inline style 提取 width/height"""
    html = '<img src="x.png" style="width: 50%; height: 200px" />'
    out = conv.convert(html)
    assert "<img" in out
    assert "width: 50%" in out
    assert "height: 200px" in out


def test_image_no_size_use_markdown(conv: HtmlToMarkdownConverter):
    """无尺寸时用 markdown image 格式."""
    html = '<img src="https://x.com/a.png" alt="x" />'
    out = conv.convert(html)
    assert "![x](https://x.com/a.png)" in out
    assert "<img" not in out


def test_image_data_origin_src(conv: HtmlToMarkdownConverter):
    """飞书 data-origin-src 优先"""
    html = '<img data-origin-src="https://feishu/x.png" src="placeholder.png" alt="a" />'
    out = conv.convert(html)
    # 没有 size → markdown
    assert "![a](https://feishu/x.png)" in out


# ---- span / inline unwrap --------------------------------------------------

def test_nested_inline_unwrap_span(conv: HtmlToMarkdownConverter):
    """<span> 包 inline 标签 → 解嵌套,只留内层."""
    html = "<p><span><strong>x</strong></span></p>"
    out = conv.convert(html)
    assert "**x**" in out
    # span 本身不应残留
    assert "<span" not in out


def test_nested_div_unwrap(conv: HtmlToMarkdownConverter):
    """<div> 当容器 — 嵌套内容正常出现."""
    html = "<div><p>hello <em>world</em></p></div>"
    out = conv.convert(html)
    assert "hello" in out
    assert "*world*" in out


# ---- headings --------------------------------------------------------------

def test_heading_levels(conv: HtmlToMarkdownConverter):
    """h1~h3 → # / ## / ###"""
    html = "<h1>T1</h1><h2>T2</h2><h3>T3</h3>"
    out = conv.convert(html)
    assert "# T1" in out
    assert "## T2" in out
    assert "### T3" in out


# ---- lists ------------------------------------------------------------------

def test_unordered_list(conv: HtmlToMarkdownConverter):
    html = "<ul><li>a</li><li>b</li></ul>"
    out = conv.convert(html)
    assert "- a" in out
    assert "- b" in out


def test_ordered_list(conv: HtmlToMarkdownConverter):
    html = "<ol><li>a</li><li>b</li></ol>"
    out = conv.convert(html)
    assert "1. a" in out
    assert "2. b" in out


# ---- blockquote -------------------------------------------------------------

def test_blockquote(conv: HtmlToMarkdownConverter):
    html = "<blockquote><p>quoted text</p></blockquote>"
    out = conv.convert(html)
    assert "> quoted text" in out


# ---- edge cases -------------------------------------------------------------

def test_empty_html_returns_empty(conv: HtmlToMarkdownConverter):
    assert conv.convert("") == ""
    assert conv.convert("   ") == ""
    assert conv.convert(None or "") == ""  # type: ignore[arg-type]


def test_complex_paste_from_feishu(conv: HtmlToMarkdownConverter):
    """模拟一段典型飞书文档结构 — 标题 + 列表 + 表格 + 图片 + 代码块."""
    html = """
<h2>背景介绍</h2>
<p>这是飞书粘贴的典型场景,包含 <strong>强调</strong> 和 <em>斜体</em>.</p>
<ul>
  <li>第一项</li>
  <li>第二项</li>
</ul>
<table>
  <thead><tr><th>字段</th><th style="text-align: center">类型</th></tr></thead>
  <tbody>
    <tr><td>id</td><td style="text-align: center">int</td></tr>
    <tr><td>name</td><td style="text-align: center">string</td></tr>
  </tbody>
</table>
<pre><code class="language-python">print("hello world")</code></pre>
<p><img src="https://x.com/diagram.png" width="500" alt="diagram" /></p>
"""
    out = conv.convert(html)
    # 关键元素全在
    assert "## 背景介绍" in out
    assert "**强调**" in out
    assert "*斜体*" in out
    assert "- 第一项" in out
    assert "| 字段 |" in out
    assert "| :---: |" in out
    assert "```python" in out
    assert 'print("hello world")' in out
    assert '<img src="https://x.com/diagram.png"' in out
    assert "width: 500px" in out


def test_link_with_href(conv: HtmlToMarkdownConverter):
    """<a href> → [text](href)"""
    html = '<p>visit <a href="https://x.com">our site</a></p>'
    out = conv.convert(html)
    assert "[our site](https://x.com)" in out


def test_inline_code_in_paragraph(conv: HtmlToMarkdownConverter):
    """行内 <code> 不应破坏段落."""
    html = "<p>call <code>func()</code> to start</p>"
    out = conv.convert(html)
    assert "`func()`" in out
    assert "call" in out and "to start" in out


def test_strikethrough(conv: HtmlToMarkdownConverter):
    html = "<p><del>old</del> new</p>"
    out = conv.convert(html)
    assert "~~old~~" in out