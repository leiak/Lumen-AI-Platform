"""为 15 个系统模板生成默认缩略图 (Pillow 直绘,不走 AI image-gen).

背景
----
M32 (2026-06-18) ship 时,15 套系统模板全部 ``thumbnail=None`` (seed 注释
明确说"需要 headless browser,out of scope for MVP")。 ``TemplateCard``
对 ``has_thumbnail=False`` 的模板显示 ``PictureOutlined`` 灰色图标占位,
导致 ``/dashboard/wx-publisher/templates`` 整页看起来"全是空的"。

M32.1 加了 ``POST /templates/{id}/generate-thumbnail`` 走 image-generation
AI 路径,但要求租户内有 ``is_image_generation=True`` 的 ModelConfig,
单张 ~60s (15 张 15 分钟)。dev 环境 + 多租户场景都不一定满足。

本脚本用 Pillow 直接画确定性缩略图 — 读 seed 里每个模板的
``css_variables`` (--bg / --accent) 取色, 画 600×400 风格卡, 把模板名 /
分类写上去。**0 依赖, <1s 出 15 张, idempotent**。M33 起,所有
``is_system=True`` 的模板都会有真实可见的 cover 图。

设计
----
- 600×400 (3:2) — 卡片 ``object-fit: cover`` 裁到 1:1 后标题仍可见
- 顶 8% 高度 ``--accent`` 强调条 + 底 8% 浅色 footer
- 主区 ``--bg`` 填底, 标题用 ``--accent`` 色, 副标题(分类)用 text-secondary
- 字体:Windows ``msyh.ttc`` 微软雅黑 (含 CJK), 失败 fallback
  ``ImageFont.load_default()`` (英文 only, CJK 会画方块)
- 输出 JPEG quality=85, 字节数典型 15-40KB << MEDIUMBLOB 16MB 上限

用法
----
::

    cd backend && python -m scripts.seed_wx_template_thumbnails           # 只填缺图
    cd backend && python -m scripts.seed_wx_template_thumbnails --force   # 覆盖已有
    cd backend && python -m scripts.seed_wx_template_thumbnails --dry-run # 只打印计划

集成
----
``init_dev_db.py`` 已 ship 阶段调用 ``seed_wx_templates()``, 本脚本作为
后续同位置调用 (``seed_wx_template_thumbnails()``), 让 docker reset 后
缩略图也自动恢复。
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from typing import List, Tuple

# Make ``app`` importable when invoked as a module.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from sqlalchemy import select  # noqa: E402

from lumen_core.database import SessionLocal  # noqa: E402
# Mirror seed_wx_templates.py: register every model so FK resolution works
# even when this script is run as ``python -m scripts.seed_wx_template_thumbnails``.
from lumen_models import (  # noqa: E401,F401
    tenant, user, role, settings, agent, agent_team, chat, knowledge,
    memory, mcp, model_config, notification, skill, skill_marketplace,
    workflow, workflow_template, image_generation, nlp_training,
    vision_training, external_app, wx_publisher,
    llm_call_log,           # LLMCallLog — FK target for WxTemplate FK paths
    embedding_call_log,     # EmbeddingCallLog — same
)
from lumen_models.wx_publisher import WxTemplate  # noqa: E402

logger = logging.getLogger("seed_wx_template_thumbnails")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDTH = 600
HEIGHT = 400

# Windows 微软雅黑 (CJK + Latin). 失败时 fallback 到 PIL default (Latin only,
# CJK 字符会画方块, 至少英文/数字 + 占位符仍能渲染)。
_CJK_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",         # Microsoft YaHei
    r"C:\Windows\Fonts\msyhbd.ttc",       # Microsoft YaHei Bold
    r"C:\Windows\Fonts\simhei.ttf",       # SimHei
    r"C:\Windows\Fonts\NotoSansSC-VF.ttf",  # Noto Sans SC (VF)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
    "/System/Library/Fonts/PingFang.ttc",  # macOS
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a CJK-capable font at ``size`` px, falling back to PIL default."""
    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


# Category label map (zh-CN display label for the thumbnail footer)
_CATEGORY_LABELS = {
    "minimal": "极简",
    "tech": "科技",
    "magazine": "杂志",
    "literary": "文艺",
    "business": "商务",
}


# ---------------------------------------------------------------------------
# Pillow rendering
# ---------------------------------------------------------------------------

def _parse_hex(color: str, default: str = "#222222") -> str:
    """Normalize a css color string to ``#rrggbb`` (PIL accepts both, but
    we want predictable output for log diffs). Falls back to ``default`` on
    any parse error so a malformed css_variables row never breaks the
    whole batch.
    """
    if not color:
        return default
    c = color.strip().lower()
    if c.startswith("#") and len(c) in (4, 7):
        if len(c) == 4:  # #abc → #aabbcc
            c = "#" + "".join(ch * 2 for ch in c[1:])
        return c
    # rgb(255, 0, 0) / rgba(255, 0, 0, 0.5) — naive extract first 3 ints
    if c.startswith("rgb"):
        try:
            nums = [int(x.strip()) for x in c[c.find("(") + 1: c.find(")")].split(",")[:3]]
            return "#{:02x}{:02x}{:02x}".format(*nums)
        except Exception:
            return default
    return default


def _luminance(hex_color: str) -> float:
    """Approx relative luminance (0..1) so we can pick a readable text color
    on top of arbitrary bg. WCAG weights, no gamma for speed (thumbnail
    doesn't need color-management precision)."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return 0.5
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _text_color_for(bg_hex: str) -> str:
    """Pick near-black or near-white text based on bg luminance.
    Threshold 0.55 biases dark themes to white text (most "dark" hex colors
    sit just above 0.5 luminance due to blue boost)."""
    return "#f5f5f5" if _luminance(bg_hex) < 0.55 else "#1a1a1a"


def render_thumbnail(
    *,
    name: str,
    description: str,
    category: str,
    css_variables: dict,
) -> bytes:
    """Render a 600×400 JPEG thumbnail for a single WxTemplate.

    Args:
        name: 模板名 (e.g. ``"极简白板"``).
        description: 一句话描述,显示在副标题位置。
        category: 分类键 (e.g. ``"minimal"``).
        css_variables: 模板的 css_variables dict (从 DB 读). 至少要包含
            ``bg`` 和 ``accent``; 缺时 fallback 到中性灰 + 黑。

    Returns:
        JPEG bytes (~15-40KB).
    """
    bg = _parse_hex(css_variables.get("bg", ""), default="#f5f5f5")
    accent = _parse_hex(css_variables.get("accent", ""), default="#1a1a1a")
    text_color = _text_color_for(bg)
    subtle = "#00000022" if _luminance(bg) < 0.55 else "#ffffff22"  # overlay
    footer_bg = _parse_hex(css_variables.get("bg-secondary", ""), default=bg)
    category_label = _CATEGORY_LABELS.get(category, category)

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img, "RGBA")

    # 1) Top accent stripe (8% height)
    stripe_h = int(HEIGHT * 0.08)
    draw.rectangle([(0, 0), (WIDTH, stripe_h)], fill=accent)

    # 2) Footer band (10% height) using bg-secondary
    footer_h = int(HEIGHT * 0.12)
    draw.rectangle([(0, HEIGHT - footer_h), (WIDTH, HEIGHT)], fill=footer_bg)

    # 3) Subtle accent vertical bar on the left (mimics real article
    #    blockquote / h1 left-border, ties the thumbnail to actual
    #    rendered output)
    bar_w = 6
    draw.rectangle(
        [(40, stripe_h + 24), (40 + bar_w, HEIGHT - footer_h - 24)],
        fill=accent,
    )

    # 4) Title (template name) — large, top of body
    title_font = _load_font(46)
    title_x = 64
    title_y = stripe_h + 30
    draw.text((title_x, title_y), name, fill=text_color, font=title_font)

    # 5) Category pill (rounded rect with accent border, fill = bg)
    pill_font = _load_font(20)
    pill_text = f"  {category_label}  "
    # Use textbbox to size the pill (Pillow ≥ 8.0)
    try:
        l, t, r, b = draw.textbbox((0, 0), pill_text, font=pill_font)
        pill_w, pill_h = r - l + 14, b - t + 8
    except AttributeError:
        # very old Pillow fallback
        pill_w, pill_h = len(pill_text) * 14, 28
    pill_x = title_x
    pill_y = title_y + 70
    draw.rounded_rectangle(
        [(pill_x, pill_y), (pill_x + pill_w, pill_y + pill_h)],
        radius=pill_h // 2,
        outline=accent,
        width=2,
    )
    draw.text(
        (pill_x + 7, pill_y + 2),
        category_label,
        fill=accent,
        font=pill_font,
    )

    # 6) Description (clipped to 2 lines manually)
    desc_font = _load_font(18)
    desc_color = text_color + "cc"  # 80% alpha as hex suffix
    max_chars_per_line = 24
    lines: List[str] = []
    remaining = (description or "").strip()
    while remaining and len(lines) < 2:
        if len(remaining) <= max_chars_per_line:
            lines.append(remaining)
            break
        # break at nearest whitespace / punctuation to avoid mid-char split
        cut = max_chars_per_line
        for sep in (" ", "，", "、", "。", ","):
            idx = remaining.rfind(sep, 0, max_chars_per_line)
            if idx > max_chars_per_line // 2:
                cut = idx + 1
                break
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    for i, line in enumerate(lines):
        draw.text(
            (title_x, pill_y + pill_h + 18 + i * 30),
            line,
            fill=desc_color,
            font=desc_font,
        )

    # 7) Footer text — "公众号助手 · 默认预览" / category desc
    footer_font = _load_font(16)
    draw.text(
        (40, HEIGHT - footer_h + 12),
        f"公众号助手 · 默认预览",
        fill=accent,
        font=footer_font,
    )
    # right side: small tag
    right_text = f"WX-TPL · {category}"
    try:
        l, t, r, b = draw.textbbox((0, 0), right_text, font=footer_font)
        right_w = r - l
    except AttributeError:
        right_w = len(right_text) * 10
    draw.text(
        (WIDTH - right_w - 24, HEIGHT - footer_h + 12),
        right_text,
        fill=accent,
        font=footer_font,
    )

    # 8) Subtle diagonal accent in the corner (decorative, ties to accent color)
    draw.polygon(
        [(WIDTH, stripe_h), (WIDTH, stripe_h + 60), (WIDTH - 80, stripe_h)],
        fill=accent + "55",  # 33% alpha
    )

    # Encode to JPEG (quality 85, optimize). ``optimize`` enables Huffman
    # table optimization — typically saves 5-10% on gradient images.
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DB driver
# ---------------------------------------------------------------------------

def seed_wx_template_thumbnails(*, force: bool = False, dry_run: bool = False) -> Tuple[int, int, int]:
    """Generate (or refresh) thumbnails for the 15 system templates.

    Args:
        force: 若 True, 已存在 thumbnail 也覆盖 (重画一遍)。默认 False
            (跳过有 thumbnail 的行, 节省时间 + 保留已生成的更精细的图)。
        dry_run: 若 True, 不写 DB, 只打印每个模板的渲染计划。

    Returns:
        ``(rendered, skipped, failed)`` 三元组。
    """
    db = SessionLocal()
    rendered = skipped = failed = 0
    try:
        # Spec §3.2 + seed 注释: 系统模板属 tenant_id=1 (default tenant).
        # 全表拉一份, 但只处理 is_system=True (避免覆盖用户改过的).
        rows: List[WxTemplate] = list(
            db.execute(
                select(WxTemplate).where(WxTemplate.is_system == True)  # noqa: E712
            ).scalars()
        )
        if not rows:
            logger.warning(
                "No system templates found. Run seed_wx_templates() first."
            )
            return (0, 0, 0)

        for row in rows:
            if row.thumbnail and not force:
                logger.info(
                    "  skip id=%-3d %-12s  (%d bytes, already has thumbnail)",
                    row.id, row.name, len(row.thumbnail),
                )
                skipped += 1
                continue
            try:
                blob = render_thumbnail(
                    name=row.name,
                    description=row.description or "",
                    category=row.category,
                    css_variables=row.css_variables or {},
                )
                if dry_run:
                    logger.info(
                        "  [dry-run] id=%-3d %-12s  would write %d bytes",
                        row.id, row.name, len(blob),
                    )
                    rendered += 1
                    continue
                # 直接 UPDATE,避免 ORM 把整条 LONGTEXT html_body / css_variables
                # 拉进 identity map。
                db.query(WxTemplate).filter(WxTemplate.id == row.id).update(
                    {"thumbnail": blob},
                    synchronize_session=False,
                )
                db.commit()
                logger.info(
                    "  ✓ id=%-3d %-12s  %d bytes JPEG",
                    row.id, row.name, len(blob),
                )
                rendered += 1
            except Exception as e:
                db.rollback()
                logger.exception("  ✗ id=%-3d %s: %s", row.id, row.name, e)
                failed += 1
        return (rendered, skipped, failed)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Pillow-rendered default thumbnails for the "
                    "15 system WX templates. Idempotent by default.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing thumbnails (re-render all 15).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be rendered, don't touch the DB.",
    )
    args = parser.parse_args()

    logger.info(
        "seed_wx_template_thumbnails: force=%s dry_run=%s",
        args.force, args.dry_run,
    )
    rendered, skipped, failed = seed_wx_template_thumbnails(
        force=args.force, dry_run=args.dry_run,
    )
    logger.info(
        "done: %d rendered, %d skipped, %d failed",
        rendered, skipped, failed,
    )
    sys.exit(0 if failed == 0 else 1)
