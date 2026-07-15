"""Stub image provider — generates a placeholder PNG with the prompt as overlay.

Used by default until a real provider (openai/stability/ollama) is configured.
Spec: §7.1
"""
import io
import logging
from typing import List, Optional, Dict, Any

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)


class StubImageProvider:
    """Returns a 1024x1024 grey PNG with the prompt text centered.

    Always returns n=1 (caller passes n=1 from service loop).
    """

    def __init__(self, model_config=None):
        self.model_config = model_config

    async def generate(
        self,
        *,
        prompt: str,
        size: str = "1024x1024",
        n: int = 1,
        quality: Optional[str] = None,
        style: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[bytes]:
        log.warning(
            "StubImageProvider used — model_config_id=%s, model_type=%s. "
            "Configure a real provider (openai/stability/ollama) for actual generation.",
            getattr(self.model_config, "id", None),
            getattr(self.model_config, "model_type", None),
        )
        # Parse size
        try:
            w, h = (int(x) for x in size.split("x"))
        except (ValueError, AttributeError):
            w, h = 1024, 1024
        # Build placeholder
        img = Image.new("RGB", (w, h), color=(220, 220, 220))
        draw = ImageDraw.Draw(img)
        # Wrap text
        text = f"[STUB]\n{prompt[:200]}"
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        # Multi-line
        lines = text.split("\n")
        y = h // 2 - (len(lines) * 20)
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (w - tw) // 2
            draw.text((x, y), line, fill=(80, 80, 80), font=font)
            y += 24
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return [buf.getvalue()]
