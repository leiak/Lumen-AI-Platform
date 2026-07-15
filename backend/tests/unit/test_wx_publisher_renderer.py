"""M32 wx_publisher renderer tests (T18).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.2 / §7.2 / §8.1

3+ tests:

- test_markdown_to_html_basic
  ``# h1`` / ``**bold**`` / ``* item`` 转成 <h1>/<strong>/<ul>
- test_apply_placeholders_replaces_all_4_keys
  ``{{title}}`` / ``{{content}}`` / ``{{author}}`` / ``{{cover}}`` 都替换
- test_apply_placeholders_raises_on_missing
  模板 body 缺占位符时抛 ValueError
- test_build_css_variables_block_renders_root_style
  ``{ "primary": "#000" }`` → ``:root { --primary: #000; }``
- test_inject_style_block_into_head
  ``<head>...</head>`` 模板注入 style 到 head 顶端
- test_build_cover_prompt_uses_title_and_summary
  ``build_cover_prompt`` 含 draft.title 字面 + 风格修饰词
- test_render_writes_content_html_and_ready_status
  end-to-end: render 写 db content_html + status='ready'

不依赖 LLM(纯模板 + markdown lib)。
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import List

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models import (  # noqa: F401
    agent as _agent,
    image_generation as _image_generation,
    knowledge as _knowledge,
    model_config as _model_config,
    user as _user_model,
)
from lumen_models.wx_publisher import WxDraft, WxTemplate

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_draft,
    make_template,
    make_tenant,
    make_user,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    db = fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def track_tenant_ids():
    return []


@pytest.fixture
def track_user_ids():
    return []


@pytest.fixture
def track_template_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def cleanup_rows(
    track_tenant_ids, track_user_ids, track_template_ids, track_draft_ids,
):
    yield
    cleanup_tracked(
        tenant_ids=track_tenant_ids, user_ids=track_user_ids,
        template_ids=track_template_ids, draft_ids=track_draft_ids,
    )


@pytest.fixture
def setup(db_session, track_tenant_ids, track_user_ids):
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    return tenant, user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_markdown_to_html_basic():
    """基础 markdown 转 html — h1 / 粗体 / 列表 / 段落。"""
    from lumen_services.wx_publisher.renderer import WxRenderer
    r = WxRenderer._markdown_to_html("# 标题\n\n**加粗** 的段落。\n\n- 列表项")
    assert "<h1>" in r and "标题" in r
    assert "<strong>" in r and "加粗" in r
    assert "<ul>" in r and "<li>" in r and "列表项" in r


def test_apply_placeholders_replaces_all_4_keys():
    """4 个占位符 ``{{title}}``/``{{content}}``/``{{author}}``/``{{cover}}`` 都替换。"""
    from lumen_services.wx_publisher.renderer import WxRenderer

    body = (
        "<html><head></head><body>"
        "<h1>{{title}}</h1>"
        "<article>{{content}}</article>"
        "<div>by {{author}}</div>"
        "<img src='{{cover}}'/>"
        "</body></html>"
    )
    css_variables = {"primary": "#000", "font-size": 16}
    template = _FakeTemplate(id=1, html_body=body, css_variables=css_variables)
    out = WxRenderer._apply_placeholders(
        template=template,
        title="T1",
        content="<p>C1</p>",
        author="A1",
        cover="https://x/cover.png",
    )
    # 所有占位符都被替换(无残余 ``{{...}}``)
    assert "{{" not in out
    assert "T1" in out
    assert "C1" in out
    assert "A1" in out
    assert "https://x/cover.png" in out
    # CSS variables 注入
    assert "<style>" in out
    assert "--primary" in out
    assert "#000" in out


def test_apply_placeholders_raises_on_missing_placeholder():
    """模板 body 缺 1 个占位符时抛 ValueError(开发期显式错)。"""
    from lumen_services.wx_publisher.renderer import WxRenderer

    body = "<html><body><h1>{{title}}</h1>{{content}}</body></html>"  # 缺 author / cover
    template = _FakeTemplate(id=1, html_body=body, css_variables={})
    with pytest.raises(ValueError, match="missing placeholder"):
        WxRenderer._apply_placeholders(
            template=template, title="t", content="c", author="a", cover="cv",
        )


def test_build_css_variables_block_renders_root_style():
    """``{primary, font-size}`` → ``<style>:root { --primary: #000; --font-size: 16; }</style>``。"""
    from lumen_services.wx_publisher.renderer import _build_css_variables_block
    block = _build_css_variables_block({"primary": "#000", "font-size": 16})
    assert block.startswith("\n<style>")
    assert "</style>" in block
    assert ":root" in block
    assert "--primary" in block
    assert "#000" in block
    assert "--font-size" in block
    assert "16" in block


def test_inject_style_block_into_head():
    """``<head>...</head>`` 模板把 style 插到 head 顶端(``>`` 之后)。"""
    from lumen_services.wx_publisher.renderer import _inject_style_block
    html_text = "<html><head><meta charset='utf-8'></head><body>hi</body></html>"
    style = "<style>:root{--p:#fff}</style>"
    out = _inject_style_block(html_text, style)
    # style 出现在 <head> 结束 > 之后,</head> 之前
    head_idx = out.find("<head>")
    head_close_idx = out.find(">", head_idx)
    style_idx = out.find("<style>")
    end_head_idx = out.find("</head>")
    assert head_idx != -1
    assert head_close_idx != -1
    assert style_idx != -1
    assert end_head_idx != -1
    # style 必须在 <head> 关闭 > 之后 且 </head> 之前
    assert head_close_idx < style_idx < end_head_idx


def test_build_cover_prompt_uses_title_and_summary():
    """``build_cover_prompt`` 含 draft.title 字面 + 风格修饰词(900x383 等)。"""
    from lumen_services.wx_publisher.renderer import WxRenderer
    draft = _FakeDraft(title="AI Agent 应用", summary="企业知识管理")
    renderer = WxRenderer(db=None)  # type: ignore[arg-type]
    prompt = renderer.build_cover_prompt(draft)
    assert "AI Agent 应用" in prompt
    assert "企业知识管理" in prompt
    assert "900x383" in prompt
    assert "minimalist" in prompt.lower() or "modern" in prompt.lower()


def test_render_writes_content_html_and_ready_status(
    db_session, setup, cleanup_rows, track_draft_ids, track_template_ids,
):
    """end-to-end: render(draft, template) 写 content_html + status='ready'。"""
    from lumen_services.wx_publisher.renderer import WxRenderer

    tenant, user = setup
    body = (
        "<html><head></head><body>"
        "<h1>{{title}}</h1>"
        "<article>{{content}}</article>"
        "<div>by {{author}}</div>"
        "<img src='{{cover}}'/>"
        "</body></html>"
    )
    template = make_template(
        db_session, tenant_id=tenant.id, user_id=user.id,
    )
    # 覆盖默认的 html_body / css_variables
    template.html_body = body
    template.css_variables = {"primary": "#333", "font-size": 17}
    db_session.commit()
    db_session.refresh(template)
    track_template_ids.append(template.id)

    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        content_markdown="# 标题\n\n**段落** 内容。",
    )
    track_draft_ids.append(draft.id)

    renderer = WxRenderer(db_session)
    final_html = renderer.render(draft=draft, template=template)

    # 1. 返 HTML 字符串
    assert isinstance(final_html, str)
    assert "{{" not in final_html  # 无残余占位符
    assert "<h1>" in final_html or "标题" in final_html
    # 2. db 写库
    db_session.expire_all()
    draft_now = db_session.query(WxDraft).filter(WxDraft.id == draft.id).first()
    assert draft_now.content_html is not None
    assert draft_now.status == "ready"
    assert "{{" not in draft_now.content_html
    # 3. CSS variables 注入
    assert "<style>" in draft_now.content_html
    assert "--primary" in draft_now.content_html


# ---------------------------------------------------------------------------
# Internal fakes
# ---------------------------------------------------------------------------

class _FakeTemplate:
    """测试用 template fake(只读 ``id``/``html_body``/``css_variables``)。"""

    def __init__(self, *, id: int, html_body: str, css_variables: dict):
        self.id = id
        self.html_body = html_body
        self.css_variables = css_variables


class _FakeDraft:
    """测试用 draft fake(只读 title/summary 等)for build_cover_prompt 单测。"""

    def __init__(self, *, title: str = "", summary: str = ""):
        self.id = 0
        self.title = title
        self.summary = summary
        self.content_markdown = ""
        self.content_html = None
        self.cover_url = None
        self.author = None
        self.tenant_id = 1
        self.user_id = 1
        self.status = "draft"
