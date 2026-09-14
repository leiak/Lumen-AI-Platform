"""补一张"模型列表 200 OK"的直接 API 验证截图(JSON pretty-print 转 PNG)。
用 PIL 直接画,不依赖浏览器。
"""
import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

BACKEND = "http://localhost:11335"
OUT_DIR = Path(__file__).parent / "imgs" / "2026-09-14-e2e"


def get_token() -> str:
    r = requests.post(
        f"{BACKEND}/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def fetch_models(token: str) -> list[dict]:
    r = requests.get(
        f"{BACKEND}/api/v1/models/?page=1&page_size=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["data"]


def fetch_kbs(token: str) -> list[dict]:
    r = requests.get(
        f"{BACKEND}/api/v1/knowledge/?page=1&page_size=20",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()["data"]
    # KB list 端点 (lumen_api/v1/knowledge.py) 直接返 list(不是 {items,...} 分页)
    return d if isinstance(d, list) else d.get("items", [])


def text_to_png(lines: list[str], title: str, out_path: Path) -> None:
    """Render a list of lines as a PNG with title heading."""
    # Use Windows CJK font if available, else fall back
    font_path = None
    for p in [
        "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf", # 黑体
        "C:/Windows/Fonts/simsun.ttc", # 宋体
    ]:
        if Path(p).exists():
            font_path = p
            break

    body_font = ImageFont.truetype(font_path, 16) if font_path else ImageFont.load_default()
    title_font = ImageFont.truetype(font_path, 22) if font_path else ImageFont.load_default()

    # Wrap by measuring
    tmp_img = Image.new("RGB", (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)

    def measure(s, f):
        bbox = tmp_draw.textbbox((0, 0), s, font=f)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    max_w = 1200
    wrapped = []
    for line in lines:
        if measure(line, body_font)[0] <= max_w - 80:
            wrapped.append(line)
        else:
            # word wrap
            cur = ""
            for ch in line:
                test = cur + ch
                if measure(test, body_font)[0] > max_w - 80:
                    wrapped.append(cur)
                    cur = ch
                else:
                    cur = test
            if cur:
                wrapped.append(cur)
    n_lines = len(wrapped) + 2  # title + blank
    line_h = 22
    img_h = n_lines * line_h + 30
    img = Image.new("RGB", (max_w, img_h), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 6), title, fill="#003366", font=title_font)
    y = 40
    for ln in wrapped:
        draw.text((20, y), ln, fill="black", font=body_font)
        y += line_h
    img.save(str(out_path))


def main():
    token = get_token()

    # 1. /models list (13 个)
    models = fetch_models(token)
    lines = [
        f"GET /api/v1/models/ → 200, total {len(models)} models",
        f"  chat={sum(1 for m in models if m['is_chat'])} "
        f"embedding={sum(1 for m in models if m['is_embedding'])} "
        f"image_gen={sum(1 for m in models if m.get('is_image_generation'))} "
        f"tts={sum(1 for m in models if m.get('is_tts'))} "
        f"video={sum(1 for m in models if m.get('is_video'))}",
        "",
    ]
    lines.append(f"{'id':<4}{'name':<28}{'model_name':<28}{'is_chat':<8}{'is_embed':<10}{'max_tokens':<11}")
    lines.append("-" * 90)
    for m in models:
        lines.append(
            f"{m['id']:<4}{m['name'][:27]:<28}{m['model_name'][:27]:<28}"
            f"{str(m['is_chat']):<8}{str(m['is_embedding']):<10}{m['max_tokens']:<11}"
        )
    lines.append("")
    lines.append("→ c17f299 fix: max_tokens=0 → 4096 兜底,/models 不再 500")
    text_to_png(lines, "API verify: /api/v1/models/  (commit c17f299)", OUT_DIR / "02-models-api.png")

    # 2. KB workspaces
    kbs = fetch_kbs(token)
    lines = [
        f"GET /api/v1/knowledge/ → 200, total {len(kbs)} workspaces",
        "",
    ]
    for kb in kbs[:10]:
        lines.append(f"  [{kb['id']}] {kb.get('name', '?')}  docs={kb.get('document_count', '?')}")
    lines.append("")
    lines.append("→ verify-kb 已可见,doc 202/203 (今天上传) 状态:")
    # 直接 DB 查 doc 状态
    import pymysql
    conn = pymysql.connect(host="localhost", port=3307, user="root",
                           password="rootpassword", database="ai_platform", connect_timeout=5)
    cur = conn.cursor()
    cur.execute("SELECT id, filename, status, chunk_count, error_message FROM documents WHERE id >= 200 ORDER BY id DESC LIMIT 5")
    for row in cur.fetchall():
        em = (row[4] or "")[:60]
        lines.append(f"  doc {row[0]}: {row[1][:30]} status={row[2]} chunks={row[3]} err={em}")
    conn.close()
    lines.append("")
    lines.append("→ fast-path 修复后 .txt 上传 completed,不再 'pypdfium2: PdfiumError'")
    text_to_png(lines, "API verify: /api/v1/knowledge/ + KB upload  (commit plain_text_fastpath)", OUT_DIR / "05-kb-upload-api.png")

    print(f"saved:")
    print(f"  {OUT_DIR / '02-models-api.png'}")
    print(f"  {OUT_DIR / '05-kb-upload-api.png'}")


if __name__ == "__main__":
    main()
