"""M32.1 — 公众号助手 — HTML → Markdown 转换器.

借鉴 ``lark-to-markdown-main`` (Next.js, MIT) 的 markdownConverter.ts 思路,
不引新依赖, 用项目已有的 beautifulsoup4 (requirements.txt:61) 实现。
不复用 lark 源码(跨项目版权/依赖管理问题),独立实现,功能等价。

设计要点(借鉴 lark):
1. **<strong>/<b> 合并相邻** — 避免 ``**a** **b**`` 输出多余空格。
2. **表格对齐识别** — ``text-align: center`` → ``:---:``, ``right`` → ``---:``。
3. **图片尺寸保留** — 有 width/height 时输出 ``<img>`` HTML 标签(微信公众号
   粘贴器会保留 style width,普通 markdown image 不会)。
4. **code block** — ``<pre><code class="language-X">`` → fenced ```` ```X\n...\n``` ````。
5. **span/div 解嵌套** — 飞书/网页常用 ``<span style="font-weight:bold">``
   嵌套 inline 标签,递归解嵌套只取内容 + 内层标签。
6. **块级元素前后空行** — 防止两个相邻段落挤成一行。

不在本模块范围(M32 spec V2+):
- 飞书特有的 ``data-origin-src`` 优先(我们只支持普通 ``src``)。
- 复制到公众号 Clipboard(本项目走真微信 API publish)。
- 复杂 list-style 转换(只识别 ``<ul>/<ol>/<li>``)。
"""
from __future__ import annotations

import re
from typing import Any, List

from bs4 import BeautifulSoup, NavigableString, Tag


class HtmlToMarkdownConverter:
    """HTML → Markdown 转换器。无状态,可复用。

    用法:
        converter = HtmlToMarkdownConverter()
        md = converter.convert("<p><strong>hello</strong></p>")
        # → "**hello**"
    """

    # 块级元素 — 这些元素之前/之后强制换行,避免相邻元素挤在一起。
    _BLOCK_TAGS = frozenset({
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li", "blockquote", "pre",
        "table", "thead", "tbody", "tr", "hr",
        "br", "img",
    })

    # Whitespace normalization — 多个空白压成单个空格(行内)
    _WS_RE = re.compile(r"[ \t\f\v]+")
    _NEWLINE_RE = re.compile(r"\n{3,}")

    def convert(self, html: str) -> str:
        """Convert an HTML fragment to Markdown.

        Args:
            html: HTML 字符串(可含片段/不闭合标签)— 飞书/网页粘贴常见。

        Returns:
            Markdown 字符串。空输入返空字符串。
        """
        if not html or not html.strip():
            return ""
        soup = BeautifulSoup(html, "html.parser")
        return self._render_children(soup).strip() + "\n"

    # --- 块级 / 行内 dispatch ---------------------------------------------

    def _render_children(self, node: Any) -> str:
        """递归渲染 node 的所有子节点,按顺序拼接成 md。

        自动在块级元素前后补换行。合并相邻 strong/em 兄弟节点(避免
        ``<strong>a</strong><strong>b</strong>`` → ``**a****b**``)。
        """
        out: List[str] = []
        # 先收集子节点 list (避免 generator 多次迭代)
        children = list(node.children)
        i = 0
        while i < len(children):
            child = children[i]
            # 合并相邻同类型 emphasis 兄弟
            if isinstance(child, Tag) and child.name in ("strong", "b", "em", "i"):
                marker = "**" if child.name in ("strong", "b") else "*"
                merged_text = self._children_md(child)
                j = i + 1
                # 向后合并相同 emphasis 类型
                while j < len(children):
                    nxt = children[j]
                    if isinstance(nxt, Tag) and (
                        (marker == "**" and nxt.name in ("strong", "b"))
                        or (marker == "*" and nxt.name in ("em", "i"))
                    ):
                        merged_text += self._children_md(nxt)
                        j += 1
                    elif isinstance(nxt, NavigableString) and not str(nxt).strip():
                        # 空白跳过(避免 "a   b" 变 "a b" 多个空格)
                        j += 1
                    else:
                        break
                piece = self._wrap_emphasis(merged_text, marker)
                if piece:
                    out.append(piece)
                i = j
                continue
            piece = self._render_node(child)
            if piece:
                out.append(piece)
            i += 1
        # 块级元素前后加空行分隔 — 防相邻段落挤一起
        text = "".join(out)
        text = self._NEWLINE_RE.sub("\n\n", text)
        return text

    def _render_node(self, node: Any) -> str:
        """单节点 dispatch。

        - NavigableString(text) — escape + trim
        - Tag(block) — 走 _render_block
        - Tag(inline) — 走 _render_inline
        """
        if isinstance(node, NavigableString):
            return self._escape_text(str(node))
        if not isinstance(node, Tag):
            return ""
        name = (node.name or "").lower()
        if name in self._BLOCK_TAGS or name == "body":
            return self._render_block(node)
        # emphasis 节点由 _render_children 处理合并,这里不再走 _render_inline
        if name in ("strong", "b", "em", "i"):
            return self._render_inline(node)
        return self._render_inline(node)

    # --- 块级渲染 ---------------------------------------------------------

    def _render_block(self, node: Tag) -> str:
        name = (node.name or "").lower()
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            return f"\n\n{'#' * level} {self._children_md(node).strip()}\n\n"
        if name == "p":
            inner = self._children_md(node).strip()
            return f"\n\n{inner}\n\n" if inner else ""
        if name == "br":
            return "  \n"  # markdown line break
        if name == "hr":
            return "\n\n---\n\n"
        if name == "blockquote":
            inner = self._children_md(node).strip()
            # 每行前缀 "> "
            quoted = "\n".join(f"> {line}" for line in inner.split("\n"))
            return f"\n\n{quoted}\n\n"
        if name == "pre":
            return f"\n\n{self._render_pre(node)}\n\n"
        if name == "ul":
            return f"\n\n{self._render_list(node, ordered=False)}\n\n"
        if name == "ol":
            return f"\n\n{self._render_list(node, ordered=True)}\n\n"
        if name == "li":
            # 通常被 _render_list 调用;单飞时给 "  - "
            return f"\n  - {self._children_md(node).strip()}"
        if name == "table":
            return f"\n\n{self._render_table(node)}\n\n"
        if name in ("thead", "tbody"):
            return self._children_md(node)
        if name == "tr":
            cells = [self._children_md(c).strip() for c in node.find_all(["td", "th"], recursive=False)]
            return "\n| " + " | ".join(cells) + " |"
        if name in ("td", "th"):
            # 单 cell 由 _render_table 处理;tr fallback 留空
            return self._children_md(node).strip()
        if name == "img":
            return self._render_img(node)
        if name == "div":
            # div 当块容器,递归子节点
            return f"\n\n{self._children_md(node).strip()}\n\n"
        if name == "body":
            return self._children_md(node)
        # 未识别的块元素 — 当容器递归
        return f"\n\n{self._children_md(node).strip()}\n\n"

    # --- 行内渲染 ---------------------------------------------------------

    def _render_inline(self, node: Tag) -> str:
        name = (node.name or "").lower()
        inner = self._children_md(node)
        if name in ("strong", "b"):
            return self._wrap_emphasis(inner, "**")
        if name in ("em", "i"):
            return self._wrap_emphasis(inner, "*")
        if name in ("del", "s", "strike"):
            return f"~~{inner}~~"
        if name == "code":
            # inline code — 替换内部换行(单行)
            text = inner.replace("\n", " ").strip()
            return f"`{text}`"
        if name == "a":
            href_raw = node.get("href", "")
            href = str(href_raw) if href_raw else ""
            text = inner.strip() or href
            return f"[{text}]({href})" if href else text
        if name == "img":
            return self._render_img(node)
        if name == "span":
            # span 解嵌套 — 飞书常用 <span style="font-weight:bold"><span>x</span></span>
            return inner
        # 未识别 inline — 当容器递归(常见 font/label)
        return inner

    def _wrap_emphasis(self, inner: str, marker: str) -> str:
        """包强调标记,空 inner 不包(避免 '****')。

        同时 trim 内部首尾空白 — ** ** 看上去像 markup 错误。
        """
        text = inner.strip()
        if not text:
            return ""
        return f"{marker}{text}{marker}"

    # --- 表格渲染 ---------------------------------------------------------

    def _render_table(self, node: Tag) -> str:
        """渲染 <table> → Markdown table。

        处理:
        - 表头(``<thead>`` / 第一行 ``<th>``)
        - 对齐识别 — ``text-align: center`` → ``:---:``, ``right`` → ``---:``
        - 空单元格(``<br>`` 残留)→ 用单空格占位
        """
        rows: List[List[str]] = []
        for tr in node.find_all("tr"):
            cells: List[str] = []
            for c in tr.find_all(["td", "th"], recursive=False):
                cell_text = self._children_md(c).strip().replace("\n", " ").replace("|", "\\|")
                cells.append(cell_text or " ")
            if cells:
                rows.append(cells)

        if not rows:
            return ""

        # 判定 header — thead 或 第一行全 th
        first_row = rows[0]
        thead = node.find("thead")
        first_tr = node.find("tr")
        has_header = thead is not None or (
            first_tr is not None
            and all(
                (c.name == "th")
                for c in first_tr.find_all(["td", "th"], recursive=False)
            )
        )

        # 对齐识别 — 按每列第一个数据 cell 的 style
        n_cols = max(len(r) for r in rows)
        alignments: List[str] = ["---"] * n_cols
        # 直接遍历 tr 子节点找 td/th(避免 tr.find_all 在 td/th 上无 child)
        for tr in node.find_all("tr"):
            tr_cells = tr.find_all(["td", "th"], recursive=False)
            for col_idx, c in enumerate(tr_cells):
                if col_idx >= n_cols:
                    continue
                raw_style = c.get("style") or ""
                style = str(raw_style).lower()
                style_compact = style.replace(" ", "")
                if "text-align:center" in style_compact:
                    alignments[col_idx] = ":---:"
                elif "text-align:right" in style_compact:
                    alignments[col_idx] = "---:"

        # 输出
        lines: List[str] = []
        if has_header:
            header = first_row
            body_rows = rows[1:]
        else:
            header = [" "] * n_cols
            body_rows = rows

        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(alignments[:len(header)]) + " |")
        for r in body_rows:
            # 补齐短行
            padded = r + [" "] * (len(header) - len(r))
            lines.append("| " + " | ".join(padded[:len(header)]) + " |")

        return "\n".join(lines)

    # --- 列表渲染 ---------------------------------------------------------

    def _render_list(self, node: Tag, *, ordered: bool) -> str:
        """渲染 <ul>/<ol> → markdown list。

        支持 2 级 nested(飞书常见)。
        """
        items: List[str] = []
        idx = 1
        for li in node.find_all("li", recursive=False):
            # 嵌套 list 需要剥出来单独处理(li 内的 children 包含嵌套 ul)
            nested_html: List[str] = []
            inline_parts: List[str] = []
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    nested_html.append(self._render_list(child, ordered=child.name == "ol"))
                elif isinstance(child, Tag) and child.name == "p":
                    # 飞书 li 内常套 <p>;把它当 inline 内容
                    inline_parts.append(self._children_md(child).strip())
                elif isinstance(child, NavigableString):
                    inline_parts.append(self._escape_text(str(child)))
                elif isinstance(child, Tag):
                    inline_parts.append(self._render_node(child))
            marker = f"{idx}." if ordered else "-"
            inline_text = "".join(inline_parts).strip()
            items.append(f"{marker} {inline_text}")
            # 嵌套 list 缩进 2 空格
            for nested in nested_html:
                items.append("\n".join(f"  {line}" for line in nested.strip().split("\n")))
            if ordered:
                idx += 1
        return "\n".join(items)

    # --- code block -------------------------------------------------------

    def _render_pre(self, node: Tag) -> str:
        """渲染 ``<pre><code class="language-X">…</code></pre>`` → fenced code block。

        语言识别:class="language-python" / "lang-python" / "highlight-source-python"。
        """
        code = node.find("code")
        if code is None:
            # 纯 pre 没 code — 用 text content
            text = node.get_text()
            return f"```\n{text.rstrip()}\n```"

        # 语言识别
        raw_classes: Any = code.get("class") or []
        # bs4 typing: class attribute is `str | list[str] | None`
        if isinstance(raw_classes, list):
            classes: List[str] = [str(c) for c in raw_classes]
        elif isinstance(raw_classes, str):
            classes = [raw_classes]
        else:
            classes = []
        lang = ""
        for cls_str in classes:
            for prefix in ("language-", "lang-", "highlight-source-"):
                if cls_str.startswith(prefix):
                    lang = cls_str[len(prefix):]
                    break
            if lang:
                break

        # 处理嵌套 line-number / highlight 飞书结构 — 只取 text content
        text = code.get_text().rstrip()
        return f"```{lang}\n{text}\n```"

    # --- image ------------------------------------------------------------

    def _render_img(self, node: Tag) -> str:
        """渲染 <img>。

        借鉴 lark 思路 — 有 width/height/style size 时保留 ``<img>`` HTML 标签,
        否则输出 ``![](url)`` 普通 markdown。

        src 优先级(飞书粘贴):
        - ``data-origin-src`` (飞书原始 URL) > ``data-src`` (CDN) > ``src``
        """
        src = (
            node.get("data-origin-src")
            or node.get("data-src")
            or node.get("src")
            or ""
        )
        alt = node.get("alt") or ""
        width = node.get("width")
        height = node.get("height")
        style = node.get("style") or ""

        # 提取 inline style 中的 width/height(支持 width:300px / width:50%)
        inline_props: dict[str, str] = {}
        style_str = str(style) if style else ""
        for prop in ("width", "height"):
            m = re.search(rf"{prop}\s*:\s*([^;\"']+)", style_str)
            if m:
                inline_props[prop] = m.group(1).strip()

        has_size = bool(width or height or inline_props)

        if has_size:
            parts: List[str] = []
            if "width" in inline_props and not width:
                parts.append(f"width: {inline_props['width']}")
            elif width:
                parts.append(f"width: {width}px")
            if "height" in inline_props and not height:
                parts.append(f"height: {inline_props['height']}")
            elif height:
                parts.append(f"height: {height}px")
            style_str = "; ".join(parts)
            return f'<img src="{src}" alt="{alt}" style="{style_str}" />'
        return f"![{alt}]({src})"

    # --- 文本工具 ---------------------------------------------------------

    def _children_md(self, parent: Tag) -> str:
        """递归渲染 parent 的 children — 委托 _render_children 处理 sibling 合并。

        注: 此方法不加块级前后换行,因为它是给 block 元素内部用的(块已
        处理过换行)。inline 合并(strong/em 相邻合并)由 _render_children 处理。
        """
        return self._render_children(parent)

    @staticmethod
    def _escape_text(text: str) -> str:
        """行内文本 escape — Markdown 特殊字符。"""
        # 不 escape * / _ / [ 避免破坏 inline 标签的内容(后续 inline 渲染时
        # 会自己加 markup)。只 normalize whitespace。
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 行内多个空白压成单个(防止飞书源码意外空格影响 markdown)
        text = re.sub(r"[ \t\f\v]+", " ", text)
        return text