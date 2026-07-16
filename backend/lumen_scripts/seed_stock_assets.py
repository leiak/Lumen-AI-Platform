"""M36.2.1 seed: 30 built-in stock assets.

为 ``/dashboard/videos`` 的 ComposeModal 准备"开箱即用"的图片素材，避免冷
启动时用户没图可合。脚本使用 Pillow 在磁盘上生成 5 个分类、30 张
1024×1024 PNG（风景 / 抽象 / 商务 / 人物 / 产品），然后写入
``stock_assets`` 表，``tenant_id=NULL`` 表示全局可见。

Idempotent: 已存在的素材按 ``(name, tenant_id)`` 跳过。

Usage:
    cd backend && python -m lumen_scripts.seed_stock_assets
"""
import io
import os
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from lumen_core.config import settings  # noqa: E402
from lumen_core.database import SessionLocal, ensure_stock_assets_table  # noqa: E402
from lumen_models.stock_asset import StockAsset  # noqa: E402


CATEGORIES: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "风景",
        [
            ("金色日落山景", "sunset mountain"),
            ("清晨雾林", "foggy forest"),
            ("海浪礁石", "sea waves"),
            ("雪山倒影", "snow mountain"),
            ("秋日枫林", "autumn forest"),
            ("星空沙漠", "starry desert"),
        ],
    ),
    (
        "抽象",
        [
            ("蓝绿渐变", "blue green gradient"),
            ("橙色烟雾", "orange smoke"),
            ("紫色波纹", "purple ripple"),
            ("金色粒子", "gold particles"),
            ("冷色几何", "cool geometry"),
            ("暖色晕染", "warm diffusion"),
        ],
    ),
    (
        "商务",
        [
            ("办公桌面", "office desk"),
            ("会议室", "meeting room"),
            ("城市天际线", "city skyline"),
            ("笔记本电脑", "laptop"),
            ("咖啡与笔记本", "coffee notebook"),
            ("白板贴纸", "whiteboard"),
        ],
    ),
    (
        "人物",
        [
            ("商务人物剪影", "business silhouette"),
            ("微笑女性", "smiling woman"),
            ("团队合影", "team photo"),
            ("专注阅读", "focused reading"),
            ("运动人物", "sport portrait"),
            ("亲子互动", "parent and child"),
        ],
    ),
    (
        "产品",
        [
            ("白色背景产品", "white product"),
            ("化妆品瓶", "cosmetics"),
            ("鞋类展示", "shoes"),
            ("耳机特写", "headphones"),
            ("手表细节", "watch"),
            ("食物特写", "food closeup"),
        ],
    ),
]


PALETTE = {
    "风景": [
        ("#F4A261", "#264653"),
        ("#2A9D8F", "#E9C46A"),
        ("#264653", "#2A9D8F"),
        ("#A8DADC", "#457B9D"),
        ("#E76F51", "#F4A261"),
        ("#003049", "#D62828"),
    ],
    "抽象": [
        ("#1A535C", "#4ECDC4"),
        ("#FF9F1C", "#FFBF69"),
        ("#7209B7", "#F72585"),
        ("#FFD60A", "#003566"),
        ("#06AED5", "#086788"),
        ("#EF476F", "#FFD166"),
    ],
    "商务": [
        ("#0F4C81", "#3B7BB5"),
        ("#495057", "#ADB5BD"),
        ("#212529", "#6C757D"),
        ("#1971C2", "#A5D8FF"),
        ("#5C940D", "#F08C00"),
        ("#E9ECEF", "#495057"),
    ],
    "人物": [
        ("#264653", "#E9C46A"),
        ("#F4A261", "#2A9D8F"),
        ("#6A4C93", "#1982C4"),
        ("#8AC926", "#FFCA3A"),
        ("#FF595E", "#FFCA3A"),
        ("#FFBF69", "#2EC4B6"),
    ],
    "产品": [
        ("#F8F9FA", "#212529"),
        ("#FFE8D6", "#B08968"),
        ("#D8E2DC", "#FFE5D9"),
        ("#1D3557", "#A8DADC"),
        ("#3D405B", "#F4F1DE"),
        ("#E63946", "#F1FAEE"),
    ],
}


def _pick_font(size: int) -> ImageFont.ImageFont:
    """Prefer a CJK-capable font for the label; fall back to default."""
    for candidate in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_png(label: str, primary: str, secondary: str) -> bytes:
    """Render a 1024×1024 placeholder PNG with the given two-color gradient
    and a centered label so the gallery has visually distinct tiles."""
    size = 1024
    img = Image.new("RGB", (size, size), primary)
    draw = ImageDraw.Draw(img)
    for y in range(size):
        ratio = y / size
        r1, g1, b1 = int(primary[1:3], 16), int(primary[3:5], 16), int(primary[5:7], 16)
        r2, g2, b2 = (
            int(secondary[1:3], 16), int(secondary[3:5], 16), int(secondary[5:7], 16),
        )
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (size, y)], fill=(r, g, b))
    overlay = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.ellipse(
        [(size * 0.2, size * 0.2), (size * 0.8, size * 0.8)],
        fill=(255, 255, 255, 48),
    )
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _pick_font(56)
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(
        ((size - text_w) / 2, (size - text_h) / 2 - 10),
        label,
        font=font,
        fill=(255, 255, 255),
        stroke_width=2,
        stroke_fill=(0, 0, 0),
    )
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def upsert_stock_asset(db, *, name: str, category: str, palette: Tuple[str, str]) -> StockAsset:
    """Insert or update one global built-in stock row, rewriting the
    on-disk PNG so the seed re-render is fully idempotent."""
    existing = (
        db.query(StockAsset)
        .filter(StockAsset.tenant_id.is_(None), StockAsset.name == name)
        .first()
    )
    rel_path = f"stock/{category}/{name}.png"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    png_bytes = render_png(name, palette[0], palette[1])
    abs_path.write_bytes(png_bytes)
    tags = [category, "builtin"]
    description = f"Built-in stock asset ({category}) — {name}."
    if existing:
        existing.category = category  # type: ignore[assignment]
        existing.tags = tags  # type: ignore[assignment]
        existing.file_path = rel_path  # type: ignore[assignment]
        existing.mime_type = "image/png"  # type: ignore[assignment]
        existing.file_size = len(png_bytes)  # type: ignore[assignment]
        existing.source = "builtin"  # type: ignore[assignment]
        existing.pexels_id = None  # type: ignore[assignment]
        existing.tenant_id = None  # type: ignore[assignment]
        existing.description = description  # type: ignore[assignment]
        return existing
    row = StockAsset(
        name=name,
        category=category,
        tags=tags,
        file_path=rel_path,
        mime_type="image/png",
        file_size=len(png_bytes),
        source="builtin",
        pexels_id=None,
        tenant_id=None,
        description=description,
    )
    db.add(row)
    return row


def main() -> None:
    ensure_stock_assets_table()
    print("M36.2.1 seed — writing 30 built-in stock assets...")
    db = SessionLocal()
    try:
        total = 0
        for category, items in CATEGORIES:
            palette = PALETTE[category]
            for idx, (name, _description) in enumerate(items):
                row = upsert_stock_asset(
                    db,
                    name=name,
                    category=category,
                    palette=palette[idx % len(palette)],
                )
                if row.id is None:
                    db.flush()
                total += 1
        db.commit()
        print(f"OK — committed {total} stock assets (storage={settings.STORAGE_DIR / 'stock'}).")
    except Exception as exc:
        db.rollback()
        print(f"FAILED: {type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
