"""M32 公众号助手 - 渲染 service (Markdown → HTML + 模板应用).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.2 / §7.2

CP3 范围 (T16):
- ``render``:把 draft.content_markdown(或 sections 拼出的 md) → 应用
  模板(html_body + 占位符替换) → 写 draft.content_html + status="ready"
- ``build_cover_prompt``:基于 draft.title + summary 拼出英文 prompt,
  给 M22 ImageGenerationService.create() 用(V2 才接 cover endpoint,
  本方法暂不直接调 ImageGenerationService — 留接口)

Markdown 渲染安全:
- 用 ``markdown`` lib (3.10),``extensions=['extra']`` 支持表格/代码块
  /列表/标题/链接/图片。``markdown`` 3.x 默认不执行 HTML 标签(等同
  safe_mode),不需要 ``safe_mode`` 参数(2.x 才有)。
- 模板 ``html_body`` 内的占位符用 ``str.replace``(只替 4 个固定 key,
  不会被 prompt 注入影响)。

CSS variables 应用:
- 模板的 ``css_variables`` JSON dict 渲染成 ``:root { --key: val; }`` style block,
  注入 ``<head>`` 顶端。
- 用 ``html.escape`` 转义 key 和 value(防注入),但项目约定 CSS 变量值
  是颜色/尺寸/字体名等受控输入,本层只防意外字符。
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, Optional

import markdown as markdown_lib
from sqlalchemy.orm import Session

from lumen_models.wx_publisher import WxDraft, WxTemplate
from lumen_services.wx_publisher.draft_service import WxDraftService

log = logging.getLogger(__name__)


# 模板支持的 4 个占位符(spec §4.2 / §7.2)
_PLACEHOLDER_TITLE = "{{title}}"
_PLACEHOLDER_CONTENT = "{{content}}"
_PLACEHOLDER_AUTHOR = "{{author}}"
_PLACEHOLDER_COVER = "{{cover}}"


class WxRenderer:
    """Markdown → 应用模板 CSS variables → HTML。

    无状态、可复用。Service 内部调 ``draft_service.get_full_markdown``
    把 sections 拼成单 md(若有 sections),无 sections 时 fallback
    ``draft.content_markdown``。
    """

    def __init__(self, db: Session):
        self.db = db

    def render(self, draft: WxDraft, template: WxTemplate) -> str:
        """渲染 draft + template → 写 ``draft.content_html`` + ``status='ready'``。

        Returns:
            最终 HTML 字符串(同时写库)。

        Raises:
            ValueError: 模板占位符不全(开发期失误)
        """
        # 1. 把 sections 拼成单 md(若有 sections 走这个;否则走 draft.content_markdown)
        draft_service = WxDraftService()
        full_md = draft_service.get_full_markdown(
            self.db, current_user=_FakeUser(draft), draft_id=draft.id,
        )
        # 2. md → html(safe)
        content_html = self._markdown_to_html(full_md)
        # 3. 应用模板占位符
        final_html = self._apply_placeholders(
            template=template,
            title=draft.title or "",
            content=content_html,
            author=draft.author or "",
            cover=draft.cover_url or "",
        )
        # 4. 写库
        draft.content_html = final_html
        draft.status = "ready"
        self.db.commit()
        self.db.refresh(draft)
        return final_html

    def build_cover_prompt(self, draft: WxDraft) -> str:
        """基于 draft.title + summary 拼出英文 prompt(给 ImageGenerationService 用)。

        中文标题做最少翻译:保持中文 + 加英文风格修饰词。
        例: 标题="AI Agent 在企业知识管理中的应用" →
            "A modern flat illustration of AI Agent applied to enterprise
             knowledge management, minimalist style, professional color
             palette, suitable for WeChat public account cover image,
             no text overlay"
        """
        title = (draft.title or "").strip()
        summary = (draft.summary or "").strip()
        # 拼英文 prompt(模板化)
        pieces = [
            "A modern flat illustration for a WeChat public account cover image.",
        ]
        if title:
            # 保留中文标题作为"主题"
            pieces.append(
                f"Theme (Chinese): {title}. Translate the idea visually into a clean, modern composition."
            )
        if summary:
            pieces.append(f"Content focus: {summary[:200]}")
        pieces.extend([
            "Style: minimalist, professional, vibrant but not saturated.",
            "Composition: 900x383 aspect ratio, focal element on the right third.",
            "No text overlay, no watermarks, no logos.",
        ])
        return " ".join(pieces)

    # ---- helpers ----

    @staticmethod
    def _markdown_to_html(md_text: str) -> str:
        """Markdown → HTML(不执行 HTML 标签的安全模式)。"""
        if not md_text:
            return ""
        # markdown 3.x 默认 safe(不执行 inline HTML)。``extensions=['extra']``
        # 启用表格 / 围栏代码块 / 删除线 / 脚注 / 缩写等。
        return markdown_lib.markdown(
            md_text,
            extensions=["extra"],
            output_format="html",
        )

    @staticmethod
    def _apply_placeholders(
        *,
        template: WxTemplate,
        title: str,
        content: str,
        author: str,
        cover: str,
    ) -> str:
        """把 4 个占位符替换进 ``template.html_body``。

        顺序无关 — 4 个 key 互不重叠(都带 ``{{ }}``)。未提供的占位符
        留空字符串(避免残余 ``{{title}}`` 字面量)。
        """
        body = template.html_body or ""
        # 校验所有 4 个占位符都存在(开发期失误显式报错)
        for ph in (
            _PLACEHOLDER_TITLE,
            _PLACEHOLDER_CONTENT,
            _PLACEHOLDER_AUTHOR,
            _PLACEHOLDER_COVER,
        ):
            if ph not in body:
                raise ValueError(
                    f"Template (id={template.id}) html_body is missing placeholder {ph}"
                )
        body = body.replace(_PLACEHOLDER_TITLE, title)
        body = body.replace(_PLACEHOLDER_CONTENT, content)
        body = body.replace(_PLACEHOLDER_AUTHOR, author)
        body = body.replace(_PLACEHOLDER_COVER, cover)
        # 注入 CSS variables(:root 块)
        css_block = _build_css_variables_block(template.css_variables or {})
        # 把 css_block 注入到 <head> 顶端(若有);没有 <head> 时插到 body 顶端
        body = _inject_style_block(body, css_block)
        return body


def _build_css_variables_block(css_variables: Dict[str, Any]) -> str:
    """``{ "primary": "#000", "font-size": 16 }`` → ``:root { --primary: #000; --font-size: 16; }`` 包裹的 ``<style>`` 块。

    全部 value/key 走 ``html.escape`` 防意外字符(尤其是 ``<`` / ``>`` /
    ``"`` 破坏 HTML 解析)。
    """
    if not css_variables:
        return ""
    decls: list[str] = []
    for key, val in css_variables.items():
        if not isinstance(key, str):
            continue
        safe_key = html.escape(key.strip().lstrip("--"), quote=True)
        # var key 约定: ``--primary``。加 ``--`` 前缀
        var_name = f"--{safe_key}" if not safe_key.startswith("--") else safe_key
        safe_val = html.escape(str(val), quote=True)
        decls.append(f"  {var_name}: {safe_val};")
    if not decls:
        return ""
    inner = "\n".join(decls)
    return f"\n<style>:root {{\n{inner}\n}}</style>\n"


def _inject_style_block(html_text: str, style_block: str) -> str:
    """把 ``<style>...</style>`` 注入 ``<head>`` 顶端;无 head 时插到 body 顶端。"""
    if not style_block:
        return html_text
    lower = html_text.lower()
    head_idx = lower.find("<head")
    if head_idx != -1:
        # 找到 <head> 的结束 > 位置
        head_close = lower.find(">", head_idx)
        if head_close != -1:
            return (
                html_text[: head_close + 1]
                + style_block
                + html_text[head_close + 1 :]
            )
    # 无 head 标签:插到 body 顶端(若有 body)或文档顶端
    body_idx = lower.find("<body")
    if body_idx != -1:
        body_close = lower.find(">", body_idx)
        if body_close != -1:
            return (
                html_text[: body_close + 1]
                + style_block
                + html_text[body_close + 1 :]
            )
    return style_block + html_text


class _FakeUser:
    """``draft_service.get_full_markdown`` 要 ``current_user``,但渲染 service
    在 router 之外调它(没有 FastAPI Request)。

    拿 ``draft`` 的 ``tenant_id`` 当 ``current_user.tenant_id`` 即可 —
    ``get_full_markdown`` 内 ``get_draft`` 校验 ``row.tenant_id ==
    current_user.tenant_id`` 用这个,渲染 service 是同租户操作(同
    API endpoint 触发),所以 fake 即可。

    这是私有内部 helper,不走 Pydantic / DB 持久化。
    """

    def __init__(self, draft: WxDraft):
        self.tenant_id = draft.tenant_id
        self.id = draft.user_id
        self.username = f"render_fake_for_draft_{draft.id}"
        # 不需要其他字段(get_full_markdown 只读 tenant_id)
