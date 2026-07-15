#!/usr/bin/env python3
"""
M35 seed: 5 built-in playbooks + 3 default TTS ModelConfigs.

- Playbooks: tenant_id=1 (shared built-in tenant), is_builtin=True
  (protected from edit/delete by the API).
- TTS ModelConfigs: tenant_id=NULL (global, like the M22 image-gen
  configs). Edge TTS / Piper are zero-cost; OpenAI tts-1-hd is
  opt-in paid (is_active defaults to True so admins can flip it off
  in the UI).

Idempotent: re-running produces no errors and same row counts.
Pattern mirrors lumen_scripts.publish_builtin_skills.py.

Usage:
    cd backend && python -m lumen_scripts.seed_m35_default_models
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
from lumen_core.database import SessionLocal
from lumen_models.model_config import ModelConfig
from lumen_models.playbook import Playbook

# Built-in playbooks live on tenant_id=1. All other tenants see them
# (the API allows reading is_builtin=True rows) but cannot edit/delete.
BUILTIN_TENANT_ID = 1


# ──────────────────────────────────────────────────────────────────────
# 5 built-in playbooks
# ──────────────────────────────────────────────────────────────────────

PLAYBOOKS = [
    {
        "name": "clean-professional",
        "description": "商务干净风格 — 冷色蓝灰调,适合企业演示与产品图。",
        "scope": ["image", "tts"],
        "yaml": """
# clean-professional — 商务干净风格
# 适用:企业 PPT、产品图、年度报告

palette:
  primary: ["#0F4C81", "#3B7BB5", "#A6C8E5"]
  accent: ["#F5A623", "#FF6B6B"]
  background: ["#FFFFFF", "#F5F7FA"]
  avoid: ["#FF00FF", "#00FF00", "neon"]

typography:
  font_family: "Inter, PingFang SC, sans-serif"
  weight: 400
  spacing: "loose"

keywords:
  - clean
  - professional
  - minimalist
  - corporate
  - modern
  - structured

avoid:
  - noise
  - clutter
  - cartoonish
  - over-saturated

voice_direction: "calm, clear, neutral, business tone, measured pacing"
voice_speed: 1.0
voice_tone: "professional"
""",
    },
    {
        "name": "anime-ghibli",
        "description": "宫崎骏动漫风 — 暖色手绘,适合儿童内容与故事化场景。",
        "scope": ["image", "tts"],
        "yaml": """
# anime-ghibli — 宫崎骏动漫风
# 适用:儿童绘本、故事插画、动画分镜

palette:
  primary: ["#87CEEB", "#98D8C8", "#F4D35E"]
  accent: ["#EE6C4D", "#E07A5F"]
  background: ["#F7F4E9", "#E8F1F2"]
  avoid: ["#000000", "grayscale"]

typography:
  font_family: "Comic Sans MS, rounded sans-serif"
  weight: 500
  spacing: "comfortable"

keywords:
  - Studio Ghibli style
  - hand-drawn
  - watercolor
  - whimsical
  - dreamlike
  - soft lighting

avoid:
  - photorealistic
  - gritty
  - dark
  - sharp edges

voice_direction: "warm, gentle, narrative, story-telling, slightly playful"
voice_speed: 0.9
voice_tone: "narrative"
""",
    },
    {
        "name": "cinematic-dark",
        "description": "电影暗调 — 深黑+橙青对比,适合剧情片与惊悚场景。",
        "scope": ["image", "tts"],
        "yaml": """
# cinematic-dark — 电影暗调
# 适用:电影海报、悬疑短片、剧情封面

palette:
  primary: ["#0B0B0F", "#1C1C24", "#2D2D3A"]
  accent: ["#FF6B35", "#00B4D8"]
  background: ["#000000", "#0A0A0A"]
  avoid: ["pastel", "light pink", "baby blue"]

typography:
  font_family: "Playfair Display, serif"
  weight: 700
  spacing: "tight"

keywords:
  - cinematic
  - dark moody
  - dramatic lighting
  - film grain
  - 35mm
  - anamorphic
  - chiaroscuro

avoid:
  - bright
  - cheerful
  - flat lighting
  - high-key

voice_direction: "deep, slow, dramatic, suspense, whisper-to-shout dynamic range"
voice_speed: 0.85
voice_tone: "cinematic"
""",
    },
    {
        "name": "tech-minimalist",
        "description": "极客极简 — 单色+霓虹点缀,适合科技产品与开发者场景。",
        "scope": ["image", "tts"],
        "yaml": """
# tech-minimalist — 极客极简
# 适用:科技产品介绍、开发者工具、API 文档封面

palette:
  primary: ["#0A0A0A", "#1A1A1A", "#2D2D2D"]
  accent: ["#00FF88", "#00D4FF"]
  background: ["#FAFAFA", "#0E0E0E"]
  avoid: ["warm colors", "earthy tones", "decorative"]

typography:
  font_family: "JetBrains Mono, monospace"
  weight: 500
  spacing: "compact"

keywords:
  - futuristic
  - minimal
  - geometric
  - clean lines
  - tech aesthetic
  - blueprint
  - schematic

avoid:
  - organic
  - decorative
  - vintage
  - ornate

voice_direction: "precise, measured, technical, no flourish, information-dense"
voice_speed: 1.05
voice_tone: "technical"
""",
    },
    {
        "name": "warm-storytelling",
        "description": "温暖叙事 — 暖黄柔光,适合纪录短片与人物访谈。",
        "scope": ["image", "tts"],
        "yaml": """
# warm-storytelling — 温暖叙事
# 适用:纪录短片、人物访谈、回忆向 Vlog

palette:
  primary: ["#F4A261", "#E9C46A", "#E76F51"]
  accent: ["#264653"]
  background: ["#FAEDCD", "#FEFAE0"]
  avoid: ["cold blue", "neon", "high-contrast"]

typography:
  font_family: "Source Serif Pro, serif"
  weight: 400
  spacing: "comfortable"

keywords:
  - warm
  - nostalgic
  - soft light
  - intimate
  - storytelling
  - golden hour
  - film photography

avoid:
  - cold
  - harsh
  - industrial
  - over-processed

voice_direction: "warm, intimate, conversational, slow, reflective, slight smile"
voice_speed: 0.92
voice_tone: "narrative"
""",
    },
]


# ──────────────────────────────────────────────────────────────────────
# 3 default TTS ModelConfigs
# ──────────────────────────────────────────────────────────────────────

TTS_MODELS = [
    {
        "name": "Edge TTS - 晓晓(免费)",
        "model_type": "edge",
        "model_name": "edge-tts",
        "base_url": None,
        "api_key": None,
        "description": "微软 Edge TTS 引擎,零成本、零 API key。中文晓晓 + 英文 Jenny 等 8 个常用 voice。",
        "is_chat": False,
        "is_embedding": False,
        "is_image_generation": False,
        "is_tts": True,
        "is_subtitle_generation": False,
        "is_default": True,
    },
    {
        "name": "Piper TTS - Amy(本地离线)",
        "model_type": "piper",
        "model_name": "en_US-amy-medium",
        "base_url": None,
        "api_key": None,
        "description": "Piper 本地 TTS,完全离线,需要 onnx 模型文件。零 API key。",
        "is_chat": False,
        "is_embedding": False,
        "is_image_generation": False,
        "is_tts": True,
        "is_subtitle_generation": False,
        "is_default": False,
    },
    {
        "name": "OpenAI TTS-1-HD(付费)",
        "model_type": "openai",
        "model_name": "tts-1-hd",
        "base_url": "https://api.openai.com/v1",
        "api_key": None,  # user fills in the admin UI
        "description": "OpenAI 高清 TTS 引擎,需 API key。MP3/Opus/WAV,6 种 voice(nova/alloy/echo/fable/onyx/shimmer)。",
        "is_chat": False,
        "is_embedding": False,
        "is_image_generation": False,
        "is_tts": True,
        "is_subtitle_generation": False,
        "is_default": False,
    },
    # One default subtitle generation model — pure Python, no provider.
    {
        "name": "Lumen SRT 字幕生成(纯 Python)",
        "model_type": "lumen_subtitle",
        "model_name": "lumen-srt-v1",
        "base_url": None,
        "api_key": None,
        "description": "M35 内置字幕生成器,纯 Python SRT 排版(按标点切分 + 字符密度时间戳)。无 API key,无外部依赖。",
        "is_chat": False,
        "is_embedding": False,
        "is_image_generation": False,
        "is_tts": False,
        "is_subtitle_generation": True,
        "is_default": True,
    },
]


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _parse_style_tokens(yaml_text: str) -> dict:
    """Parse YAML into a flat style_tokens dict. Falls back to raw yaml
    on parse error so a bad builtin doesn't break the entire seed run."""
    try:
        return yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError:
        return {}


def upsert_playbook(db, *, name: str, description: str, scope, yaml_text: str):
    """Idempotent insert/update of a built-in playbook. The built-in
    tenant (id=1) holds one row per name; re-runs update the yaml and
    re-parse style_tokens so admin edits to the seed file propagate on
    the next deploy."""
    existing = (
        db.query(Playbook)
        .filter(Playbook.tenant_id == BUILTIN_TENANT_ID, Playbook.name == name)
        .first()
    )
    style_tokens = _parse_style_tokens(yaml_text)
    if existing:
        existing.description = description  # type: ignore[assignment]
        existing.yaml_content = yaml_text  # type: ignore[assignment]
        existing.style_tokens = style_tokens  # type: ignore[assignment]
        existing.scope = scope  # type: ignore[assignment]
        existing.is_builtin = True  # type: ignore[assignment]
        print(f"  [UPDATED] playbook: {name} (id={existing.id})")
        return existing
    p = Playbook(
        tenant_id=BUILTIN_TENANT_ID,
        name=name,
        description=description,
        yaml_content=yaml_text,
        style_tokens=style_tokens,
        scope=scope,
        is_builtin=True,
        created_by=None,
    )
    db.add(p)
    db.flush()
    print(f"  [INSERT] playbook: {name} (id={p.id})")
    return p


def upsert_model_config(db, *, row: dict):
    """Idempotent insert/update of a global ModelConfig.

    Global configs have tenant_id=NULL. Match key: (NULL, model_type,
    model_name). Re-runs update flags (is_tts/is_subtitle_generation/
    is_default) so an admin can flip a builtin on/off via the seed
    file alone (re-deploy propagates).
    """
    existing = (
        db.query(ModelConfig)
        .filter(
            ModelConfig.tenant_id.is_(None),
            ModelConfig.model_type == row["model_type"],
            ModelConfig.model_name == row["model_name"],
        )
        .first()
    )
    if existing:
        # Update mutable flags but NEVER clobber an admin-set api_key
        # (would be devastating if seed runs as part of a deploy).
        for k in (
            "name", "base_url", "description",
            "is_chat", "is_embedding", "is_image_generation",
            "is_tts", "is_subtitle_generation", "is_default",
        ):
            if k in row:
                setattr(existing, k, row[k])
        print(f"  [UPDATED] model: {row['name']} (id={existing.id})")
        return existing
    mc = ModelConfig(tenant_id=None, **row)
    db.add(mc)
    db.flush()
    print(f"  [INSERT] model: {row['name']} (id={mc.id})")
    return mc


def main():
    print("M35 seed — writing 5 built-in playbooks + 4 default model configs...")

    db = SessionLocal()
    try:
        # Playbooks
        for p in PLAYBOOKS:
            upsert_playbook(
                db,
                name=p["name"],
                description=p["description"],
                scope=p["scope"],
                yaml_text=p["yaml"],
            )
        # Model configs (3 TTS + 1 subtitle)
        for m in TTS_MODELS:
            upsert_model_config(db, row=m)
        db.commit()
        print("OK — commit succeeded.")
    except Exception as e:
        db.rollback()
        print(f"FAILED: {type(e).__name__}: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
