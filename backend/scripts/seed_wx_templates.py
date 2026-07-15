"""Seed the wx-publisher template library with 15 system templates.

M32 ship follow-up (2026-06-18): M32 shipped the templates gallery at
``frontend/app/dashboard/wx-publisher/templates/page.tsx`` with 5
category tabs (极简/科技/杂志/文艺/商务), but the dev DB had zero
``wx_templates`` rows — the page opened empty. The spec §3.2 calls
for "5 套内置" (5 system sets); the UI 5 categories × 3 templates per
category fills the gallery to a useful density (15 templates).

All 15 templates share the same 4 placeholder contract enforced by
``renderer.WxRenderer._apply_placeholders``:

  {{title}}  {{content}}  {{author}}  {{cover}}

Thumbnails are intentionally NOT generated in the seed (the spec §3.2
notes they require a headless browser render — out of scope for an
MVP seed). The UI shows a placeholder card for ``has_thumbnail=False``
rows; operators can attach a rendered preview later via the API.

Idempotent: re-running on a seeded DB is a no-op (templates are
matched by ``(tenant_id, name)``). Author is the first superuser
found in the DB (the bootstrap admin, id=1) with ``is_system=True``.
Templates are visible to every tenant (we attach them to the default
tenant id=1 — the spec convention for system seeds; multi-tenant
isolation still works because the frontend always filters by
``current_user.tenant_id``).

Run standalone:
    cd backend && python -m scripts.seed_wx_templates

Run from init_dev_db.py (called automatically on every Docker reset):
    from scripts.seed_wx_templates import seed_wx_templates
    seed_wx_templates()
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Tuple

# Make ``app`` importable when invoked as a module.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sqlalchemy import select  # noqa: E402

from lumen_core.database import SessionLocal  # noqa: E402
# Mirror init_dev_db.py: register every model so FK resolution works
# even when this script is run as `python -m scripts.seed_wx_templates`
# (uvicorn boot-time imports in main.py don't fire in that case).
from lumen_models import (  # noqa: E401,F401
    tenant, user, role, settings, agent, agent_team, chat, knowledge,
    memory, mcp, model_config, notification, skill, skill_marketplace,
    workflow, workflow_template, image_generation, nlp_training,
    vision_training, external_app, wx_publisher,
)
from lumen_models.user import User  # noqa: E402
from lumen_models.wx_publisher import WxTemplate  # noqa: E402

logger = logging.getLogger("seed_wx_templates")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# Shared HTML shell
# ---------------------------------------------------------------------------
# We use one base shell per category — a content-presentation strategy
# (minimal = plain serif, tech = monospace, magazine = drop-cap, etc.)
# driven by the CSS variables. The body HTML is the same shape across
# templates: <article> with the 4 placeholders. This keeps the seed
# readable (~80 lines per template instead of 200+) without sacrificing
# visual variety — the CSS does the work.
#
# M32.1 升级:借鉴 lark-to-markdown-main themes/* 的 11 维结构 — 元素级
# CSS(h1~h3 / p / blockquote / code / pre / table / list / a / hr /
# strong / em / img)写满, 之前只搭 layout 框架没元素样式,渲染产物
# 看上去跟 HTML 默认样式没区别。每个 body_class 可加少量覆写(如
# magazine-classic 首字下沉)。
# ---------------------------------------------------------------------------

def _shell(body_class: str) -> str:
    """Return the html_body template string for a category.

    Renderer will string-replace the 4 ``{{...}}`` placeholders.
    Note: ``<style>:root{...}</style>`` is injected by the renderer
    at render time from ``css_variables`` — we don't inline CSS here.

    Element-level CSS rules cover the 11 维度 (lark themes reference):
    base / headings / paragraph / image / code (block+inline) /
    table / blockquote / list / link / hr / emphasis.
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{{{title}}}}</title>
<style>
/* 模板样式 — 元素级 CSS + css_variables var(--*) 主题切换. */
body {{ background: var(--bg); color: var(--text); }}
.wx-article {{
  font-family: var(--font-family);
  font-size: var(--font-size);
  line-height: var(--line-height);
  padding: var(--padding);
  max-width: var(--max-width);
  margin: 0 auto;
  word-wrap: break-word;
  overflow-wrap: break-word;
}}
.wx-cover {{ margin: 0 0 1.2em 0; }}
.wx-cover img {{ width: 100%; border-radius: 6px; display: block; }}
.wx-title {{
  font-size: 1.6em;
  font-weight: 700;
  color: var(--accent);
  border-bottom: 2px solid var(--accent);
  padding-bottom: 0.5em;
  margin: 1em 0 0.5em;
  line-height: 1.3;
}}
.wx-author {{
  color: var(--text);
  opacity: 0.7;
  font-size: 0.9em;
  margin-bottom: 1.5em;
  text-align: right;
}}
.wx-content h1 {{
  font-size: 1.5em;
  color: var(--accent);
  border-left: 4px solid var(--accent);
  padding-left: 12px;
  margin: 2em 0 1em;
  font-weight: var(--heading-weight, 700);
}}
.wx-content h2 {{
  font-size: 1.3em;
  color: var(--accent);
  margin: 1.8em 0 0.8em;
  font-weight: 600;
}}
.wx-content h3 {{
  font-size: 1.15em;
  color: var(--accent);
  margin: 1.5em 0 0.6em;
  font-weight: 600;
}}
.wx-content h4, .wx-content h5, .wx-content h6 {{
  font-size: 1.05em;
  color: var(--accent);
  margin: 1.3em 0 0.5em;
  font-weight: 600;
}}
.wx-content p {{ margin: 1.2em 0; }}
.wx-content blockquote {{
  margin: 1.5em 0;
  padding: 1em 1.5em;
  background: var(--bg-secondary, rgba(0,0,0,0.03));
  border-left: 4px solid var(--accent);
  border-radius: 0 6px 6px 0;
  color: var(--text);
  opacity: 0.95;
}}
.wx-content code {{
  background: var(--code-bg);
  color: var(--code-text, var(--accent));
  padding: 0.2em 0.4em;
  border-radius: 3px;
  font-family: var(--code-font, monospace);
  font-size: 0.9em;
}}
.wx-content pre {{
  background: var(--code-bg);
  padding: 1.2em;
  margin: 1.5em 0;
  border-radius: 6px;
  overflow: auto;
  line-height: 1.5;
}}
.wx-content pre code {{
  background: none;
  padding: 0;
  color: var(--code-text);
  font-size: 0.9em;
}}
.wx-content ul, .wx-content ol {{
  margin: 1em 0;
  padding-left: 2em;
}}
.wx-content li {{
  margin: 0.4em 0;
  line-height: var(--line-height);
}}
.wx-content ul li {{ list-style-type: var(--list-marker, disc); }}
.wx-content ol li {{ list-style-type: decimal; }}
.wx-content ul ul, .wx-content ol ol,
.wx-content ul ol, .wx-content ol ul {{
  margin: 0.3em 0;
}}
.wx-content table {{
  width: 100%;
  border-collapse: collapse;
  margin: 1.5em 0;
  font-size: 0.95em;
}}
.wx-content th, .wx-content td {{
  border: 1px solid var(--table-border, #e2e8f0);
  padding: 8px 12px;
  text-align: left;
}}
.wx-content th {{
  background: var(--code-bg);
  font-weight: 600;
  color: var(--accent);
}}
.wx-content a {{
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent);
}}
.wx-content a:hover {{
  opacity: 0.8;
}}
.wx-content img {{
  max-width: 100%;
  border-radius: 6px;
  margin: 1.5em auto;
  display: block;
}}
.wx-content hr {{
  border: 0;
  border-top: 1px solid var(--table-border, #e2e8f0);
  margin: 2em 0;
}}
.wx-content strong {{ font-weight: 700; color: var(--accent); }}
.wx-content em {{ font-style: italic; color: var(--accent); }}
.wx-footer {{
  margin-top: 3em;
  padding-top: 1em;
  border-top: 1px solid var(--table-border, #e2e8f0);
  color: var(--text);
  opacity: 0.5;
  font-size: 0.85em;
  text-align: center;
}}
.{body_class} {{ /* per-template overrides go here */ }}
/* Magazine classic: 首字下沉 */
.{body_class}.wx-magazine-classic .wx-content > p:first-of-type::first-letter {{
  font-size: 3em;
  float: left;
  line-height: 1;
  margin-right: 8px;
  margin-top: 4px;
  color: var(--accent);
  font-weight: 700;
}}
/* Magazine interview: 引用块强化 */
.{body_class}.wx-magazine-interview .wx-content blockquote {{
  font-size: 1.1em;
  font-style: italic;
  text-align: center;
}}
/* Business data: 表格斑马纹 */
.{body_class}.wx-magazine-data .wx-content tbody tr:nth-child(even),
.{body_class}.wx-business-data .wx-content tbody tr:nth-child(even) {{
  background: var(--table-stripe, rgba(0,0,0,0.02));
}}
/* Tech terminal: 等宽字体贯穿 */
.{body_class}.wx-tech-terminal .wx-article {{
  font-family: var(--font-family);
}}
.{body_class}.wx-tech-terminal .wx-content code,
.{body_class}.wx-tech-terminal .wx-content pre {{
  font-family: var(--font-family);
}}
</style>
</head>
<body class="{body_class}">
<article class="wx-article">
  <header class="wx-cover">{{{{cover}}}}</header>
  <h1 class="wx-title">{{{{title}}}}</h1>
  <div class="wx-author">{{{{author}}}}</div>
  <section class="wx-content">{{{{content}}}}</section>
  <footer class="wx-footer">本文由公众号助手生成</footer>
</article>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Template definitions — 5 categories × 3 templates = 15
# ---------------------------------------------------------------------------
# Each entry: name, category, description, css_variables dict.
# The CSS classes (.wx-article / .wx-title / etc.) are styled by the
# CSS variables below — the body_class on the shell selects the
# presentation strategy. We picked a single shell per category to
# keep the seed maintainable.
# ---------------------------------------------------------------------------

_TEMPLATES: List[Dict[str, Any]] = [
    # --- minimal (极简) ---
    {
        "name": "极简白板",
        "category": "minimal",
        "description": "纯白底黑字,大留白,适合严肃长文与干货分享。",
        "body_class": "wx-minimal-light",
        "css_variables": {
            "bg": "#ffffff",
            "bg-secondary": "#fafafa",
            "text": "#222222",
            "accent": "#111111",
            "code-bg": "#f3f4f6",
            "code-text": "#1f2937",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#e5e7eb",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', 'Hiragino Sans GB', sans-serif",
            "font-size": "16px",
            "line-height": "1.85",
            "padding": "32px",
            "max-width": "680px",
        },
    },
    {
        "name": "极简灰调",
        "category": "minimal",
        "description": "浅灰底 + 蓝灰强调,适合职场、工具类内容。",
        "body_class": "wx-minimal-gray",
        "css_variables": {
            "bg": "#f7f7f8",
            "bg-secondary": "#ffffff",
            "text": "#2d3748",
            "accent": "#4a5568",
            "code-bg": "#edf2f7",
            "code-text": "#2d3748",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#e2e8f0",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "16px",
            "line-height": "1.8",
            "padding": "28px",
            "max-width": "700px",
        },
    },
    {
        "name": "极简夜读",
        "category": "minimal",
        "description": "深色底白字,夜读模式,适合小说、随笔、深度长文。",
        "body_class": "wx-minimal-dark",
        "css_variables": {
            "bg": "#1a1a1a",
            "bg-secondary": "#2a2a2a",
            "text": "#e8e8e8",
            "accent": "#f5f5f5",
            "code-bg": "#2a2a2a",
            "code-text": "#e8e8e8",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#3a3a3a",
            "heading-weight": "700",
            "font-family": "Georgia, 'Source Han Serif SC', serif",
            "font-size": "17px",
            "line-height": "1.9",
            "padding": "30px",
            "max-width": "680px",
        },
    },
    # --- tech (科技) ---
    {
        "name": "科技蓝调",
        "category": "tech",
        "description": "蓝色渐变 + 等宽代码块,适合 AI、互联网产品类内容。",
        "body_class": "wx-tech-blue",
        "css_variables": {
            "bg": "#f0f6ff",
            "bg-secondary": "#e0e7ff",
            "text": "#1e293b",
            "accent": "#2563eb",
            "code-bg": "#e0e7ff",
            "code-text": "#3730a3",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#c7d2fe",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "15px",
            "line-height": "1.75",
            "padding": "24px",
            "max-width": "720px",
        },
    },
    {
        "name": "科技黑曜",
        "category": "tech",
        "description": "终端风格深色主题 + 绿色高亮,适合技术教程、深度解析。",
        "body_class": "wx-tech-terminal",
        "css_variables": {
            "bg": "#0d1117",
            "bg-secondary": "#161b22",
            "text": "#c9d1d9",
            "accent": "#58a6ff",
            "code-bg": "#161b22",
            "code-text": "#7ee787",
            "code-font": "Menlo, Consolas, 'PingFang SC', monospace",
            "table-border": "#30363d",
            "heading-weight": "700",
            "font-family": "Menlo, Consolas, 'PingFang SC', monospace",
            "font-size": "15px",
            "line-height": "1.7",
            "padding": "24px",
            "max-width": "720px",
        },
    },
    {
        "name": "科技赛博",
        "category": "tech",
        "description": "霓虹紫粉配色 + 未来感,适合前沿科技、AGI、机器人主题。",
        "body_class": "wx-tech-cyber",
        "css_variables": {
            "bg": "#0f0a1e",
            "bg-secondary": "#1e1633",
            "text": "#e0d7ff",
            "accent": "#d946ef",
            "code-bg": "#1e1633",
            "code-text": "#f0abfc",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#3b2f5a",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "15px",
            "line-height": "1.75",
            "padding": "26px",
            "max-width": "720px",
        },
    },
    # --- magazine (杂志) ---
    {
        "name": "杂志经典",
        "category": "magazine",
        "description": "首字下沉 + 衬线字体 + 双栏布局,适合人物专访、长篇报道。",
        "body_class": "wx-magazine-classic",
        "css_variables": {
            "bg": "#fdfcf8",
            "bg-secondary": "#f5f1e8",
            "text": "#1a1a1a",
            "accent": "#b91c1c",
            "code-bg": "#f5f1e8",
            "code-text": "#7c2d12",
            "code-font": "Georgia, serif",
            "table-border": "#e7e0d0",
            "heading-weight": "700",
            "font-family": "Georgia, 'Source Han Serif SC', 'Songti SC', serif",
            "font-size": "17px",
            "line-height": "1.8",
            "padding": "32px",
            "max-width": "700px",
        },
    },
    {
        "name": "杂志时尚",
        "category": "magazine",
        "description": "多彩卡片 + 大图网格,适合生活方式、穿搭、美妆内容。",
        "body_class": "wx-magazine-fashion",
        "css_variables": {
            "bg": "#ffffff",
            "bg-secondary": "#fdf2f8",
            "text": "#18181b",
            "accent": "#ec4899",
            "code-bg": "#fdf2f8",
            "code-text": "#9d174d",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#fbcfe8",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "16px",
            "line-height": "1.7",
            "padding": "20px",
            "max-width": "720px",
        },
    },
    {
        "name": "杂志访谈",
        "category": "magazine",
        "description": "Q&A 高亮样式 + 引述块,适合人物对话、嘉宾对谈类文章。",
        "body_class": "wx-magazine-interview",
        "css_variables": {
            "bg": "#fafaf9",
            "bg-secondary": "#f5f5f4",
            "text": "#292524",
            "accent": "#0c4a6e",
            "code-bg": "#e0f2fe",
            "code-text": "#0c4a6e",
            "code-font": "Georgia, serif",
            "table-border": "#e7e5e4",
            "heading-weight": "700",
            "font-family": "Georgia, 'Songti SC', serif",
            "font-size": "17px",
            "line-height": "1.85",
            "padding": "30px",
            "max-width": "700px",
        },
    },
    # --- literary (文艺) ---
    {
        "name": "文艺书页",
        "category": "literary",
        "description": "仿纸质书页 + 衬线字体 + 段落首行缩进,适合散文、小说片段。",
        "body_class": "wx-literary-book",
        "css_variables": {
            "bg": "#f4ecd8",
            "bg-secondary": "#ebe1c8",
            "text": "#3d2914",
            "accent": "#7c2d12",
            "code-bg": "#ebe1c8",
            "code-text": "#7c2d12",
            "code-font": "Georgia, 'Songti SC', serif",
            "table-border": "#d4c8a8",
            "heading-weight": "700",
            "font-family": "'Songti SC', 'Source Han Serif SC', Georgia, serif",
            "font-size": "17px",
            "line-height": "2.0",
            "padding": "36px",
            "max-width": "680px",
        },
    },
    {
        "name": "文艺古风",
        "category": "literary",
        "description": "水墨配色 + 楷体,适合古文赏析、传统文化、非遗主题。",
        "body_class": "wx-literary-classic",
        "css_variables": {
            "bg": "#f8f4ec",
            "bg-secondary": "#ebe4d3",
            "text": "#2c1810",
            "accent": "#854d0e",
            "code-bg": "#ebe4d3",
            "code-text": "#854d0e",
            "code-font": "'KaiTi', 'STKaiti', serif",
            "table-border": "#d4c8b0",
            "heading-weight": "700",
            "font-family": "'KaiTi', 'STKaiti', 'Songti SC', serif",
            "font-size": "17px",
            "line-height": "2.1",
            "padding": "36px",
            "max-width": "680px",
        },
    },
    {
        "name": "文艺清新",
        "category": "literary",
        "description": "马卡龙配色 + 圆角,适合旅行、摄影、生活感悟类内容。",
        "body_class": "wx-literary-fresh",
        "css_variables": {
            "bg": "#fef7f0",
            "bg-secondary": "#fff1e6",
            "text": "#3f3f46",
            "accent": "#fb7185",
            "code-bg": "#fff1e6",
            "code-text": "#be123c",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#fed7aa",
            "heading-weight": "600",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "16px",
            "line-height": "1.85",
            "padding": "28px",
            "max-width": "700px",
        },
    },
    # --- business (商务) ---
    {
        "name": "商务正装",
        "category": "business",
        "description": "深蓝白底 + 严谨排版,适合行业分析、商业洞察、企业公告。",
        "body_class": "wx-business-formal",
        "css_variables": {
            "bg": "#ffffff",
            "bg-secondary": "#f1f5f9",
            "text": "#0f172a",
            "accent": "#1e40af",
            "code-bg": "#eff6ff",
            "code-text": "#1e3a8a",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#cbd5e1",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "15px",
            "line-height": "1.85",
            "padding": "28px",
            "max-width": "720px",
        },
    },
    {
        "name": "商务金典",
        "category": "business",
        "description": "金色点缀 + 暖白底,适合投资、财经、高端品牌内容。",
        "body_class": "wx-business-gold",
        "css_variables": {
            "bg": "#fdfaf2",
            "bg-secondary": "#f7eed8",
            "text": "#1c1917",
            "accent": "#a16207",
            "code-bg": "#fef3c7",
            "code-text": "#854d0e",
            "code-font": "Georgia, serif",
            "table-border": "#fde68a",
            "heading-weight": "700",
            "font-family": "Georgia, 'Songti SC', serif",
            "font-size": "16px",
            "line-height": "1.85",
            "padding": "30px",
            "max-width": "700px",
        },
    },
    {
        "name": "商务数据",
        "category": "business",
        "description": "表格 / 图表友好,适合研报、市场分析、数据解读类内容。",
        "body_class": "wx-business-data",
        "css_variables": {
            "bg": "#f8fafc",
            "bg-secondary": "#f1f5f9",
            "text": "#0f172a",
            "accent": "#0891b2",
            "code-bg": "#ecfeff",
            "code-text": "#155e75",
            "code-font": "Menlo, Consolas, monospace",
            "table-border": "#cbd5e1",
            "table-stripe": "#e2e8f0",
            "heading-weight": "700",
            "font-family": "-apple-system, 'PingFang SC', sans-serif",
            "font-size": "15px",
            "line-height": "1.75",
            "padding": "24px",
            "max-width": "740px",
        },
    },
]


# ---------------------------------------------------------------------------
# Seed driver
# ---------------------------------------------------------------------------

def seed_wx_templates(refresh: bool = False) -> Tuple[int, int]:
    """Insert the 15 curated starter templates into ``wx_templates``.

    Idempotent by default: re-running on a seeded DB is a no-op (templates
    are matched by ``(tenant_id, name)``). Author is the first superuser
    found in the DB (the bootstrap admin from step 4 of init_dev_db.py).
    Tenant is set to the default tenant (id=1) so the templates are
    visible cross-tenant within that single dev instance.

    Args:
        refresh: 若 True, 已存在的 15 套系统模板会被强制 UPDATE (覆盖
            ``html_body`` + ``css_variables`` + ``description`` 为新版本)。
            用于 M32.1 等模板 CSS 升级后, 把已有 dev DB 的系统模板
            拉到最新 (默认 False 保持 idempotent)。

    Returns:
        (inserted_or_updated, skipped) tuple — counts for the caller to log.
    """
    db = SessionLocal()
    try:
        # Author: first superuser. init_dev_db.py runs this AFTER
        # ensure_admin_user so the bootstrap admin (id=1) is present;
        # but if running standalone before that step, we just bail
        # with a clear message — running without an admin is the
        # caller's problem to solve.
        admin = db.execute(
            select(User).where(User.is_superuser == True).order_by(User.id).limit(1)  # noqa: E712
        ).scalar_one_or_none()
        if admin is None:
            logger.warning(
                "seed_wx_templates: no superuser found, skipping. "
                "Run ensure_admin_user first (or run via init_dev_db.py)."
            )
            return (0, 0)

        # Tenant: default tenant id=1. Templates are seeded into the
        # default tenant — multi-tenant isolation still works because
        # the renderer + list endpoint filter by ``current_user.tenant_id``
        # and the user always belongs to exactly one tenant.
        tenant_id = 1

        existing = {
            row.name: row
            for row in db.execute(
                select(WxTemplate).where(WxTemplate.tenant_id == tenant_id)
            ).scalars()
        }

        inserted = 0
        skipped = 0
        for tpl in _TEMPLATES:
            name = tpl["name"]
            existing_row = existing.get(name)
            if existing_row is not None:
                if refresh and existing_row.is_system:
                    # M32.1:升级时强制刷新系统模板的 CSS 框架 + variables。
                    # 仅刷新系统模板(is_system=True)避免覆盖用户改过的。
                    existing_row.html_body = _shell(tpl["body_class"])
                    existing_row.css_variables = tpl["css_variables"]
                    existing_row.description = tpl["description"]
                    existing_row.category = tpl["category"]
                    inserted += 1  # 用 inserted 槽记 UPDATE 数
                else:
                    skipped += 1
                continue
            row = WxTemplate(
                tenant_id=tenant_id,
                name=name,
                category=tpl["category"],
                description=tpl["description"],
                html_body=_shell(tpl["body_class"]),
                css_variables=tpl["css_variables"],
                preview_html=None,  # V2: render to thumbnail via headless browser
                thumbnail=None,     # V2: same — no PIL seed here
                is_system=True,
                created_by=admin.id,
                usage_count=0,
            )
            db.add(row)
            inserted += 1

        db.commit()
        if refresh and inserted > 0:
            logger.info(
                "seed_wx_templates (refresh): %d templates updated, %d skipped",
                inserted, skipped,
            )
        else:
            logger.info(
                "seed_wx_templates: %d inserted, %d skipped (already seeded)",
                inserted, skipped,
            )
        return (inserted, skipped)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    # 用法:python -m scripts.seed_wx_templates [--refresh]
    refresh = "--refresh" in sys.argv
    seed_wx_templates(refresh=refresh)
