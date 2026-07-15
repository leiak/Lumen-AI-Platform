"""MiniMax image generation provider.

Real HTTP call to MiniMax image API (api.minimaxi.com/v1/image_generation).
Spec: https://platform.minimaxi.com/docs/guides/image-generation

Endpoint differs from the LLM gateway (api.minimaxi.chat) — image generation
has its own base URL, no `/v1/images/generations` OpenAI-compatible route.

Request:
    POST https://api.minimaxi.com/v1/image_generation
    Authorization: Bearer <api_key>
    {
      "model": "image-01",
      "prompt": "...",
      "aspect_ratio": "16:9",        # "1:1" / "16:9" / "4:3" / etc.
      "subject_reference": [...],     # optional character reference
      "response_format": "base64",
      "n": 1
    }

Response:
    {"id": "...", "data": {"image_base64": ["<b64>", ...]}}

Decoded bytes are JPEG (format inferred by PIL downstream; the service
calls Image.open().format to set row.mime_type).
"""
import base64
import logging
import os
from math import gcd
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# Default endpoint — provider hardcodes the image platform URL because the
# project's main base_url (MINIMAX_BASE_URL) points at the LLM gateway
# (api.minimaxi.chat) which has no image route.
DEFAULT_IMAGE_BASE_URL = "https://api.minimaxi.com/v1/image_generation"
DEFAULT_TIMEOUT_S = 60.0


def _to_aspect_ratio(
    size: str,
    extra_params: Optional[Dict[str, Any]],
) -> str:
    """Resolve the MiniMax ``aspect_ratio`` field.

    Priority:
      1. ``extra_params.aspect_ratio`` (explicit override)
      2. ``size`` if already in ``"W:H"`` form (e.g. "16:9")
      3. ``size`` parsed as ``"WxH"`` and reduced by gcd (e.g. "1024x1024" → "1:1")
      4. Fallback "1:1"
    """
    if extra_params and extra_params.get("aspect_ratio"):
        return str(extra_params["aspect_ratio"])
    if ":" in size:
        return size
    try:
        w_str, h_str = size.lower().split("x", 1)
        w, h = int(w_str), int(h_str)
        if w <= 0 or h <= 0:
            return "1:1"
        g = gcd(w, h)
        return f"{w // g}:{h // g}"
    except Exception:
        return "1:1"


class MiniMaxImageProvider:
    """Real httpx-backed implementation for MiniMax image-01."""

    def __init__(self, model_config):
        self.model_config = model_config
        # base_url on the row may still point at the LLM gateway; allow
        # callers to override via env or model_config field for flexibility.
        env_url = os.getenv("MINIMAX_IMAGE_BASE_URL")
        if env_url:
            self.endpoint = env_url.rstrip("/")
        else:
            self.endpoint = DEFAULT_IMAGE_BASE_URL

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
        aspect_ratio = _to_aspect_ratio(size, extra_params)

        # MiniMax has no native negative_prompt field; append to prompt.
        full_prompt = prompt
        if negative_prompt:
            full_prompt = f"{prompt}\n\nNegative: {negative_prompt}"

        payload: Dict[str, Any] = {
            "model": self.model_config.model_name or "image-01",
            "prompt": full_prompt,
            "aspect_ratio": aspect_ratio,
            "response_format": "base64",
            "n": max(1, n),
        }
        # Optional character / subject reference
        if extra_params and extra_params.get("subject_reference"):
            payload["subject_reference"] = extra_params["subject_reference"]
        # Optional quality / style pass-through if the API supports them
        if quality:
            payload["quality"] = quality
        if style:
            payload["style"] = style

        api_key = self.model_config.api_key
        if not api_key:
            raise RuntimeError(
                "ModelConfig.api_key is empty for MiniMaxImageProvider — "
                "set MINIMAX_API_KEY or model_config.api_key."
            )
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = float(
            getattr(self.model_config, "timeout", None) or DEFAULT_TIMEOUT_S
        )

        log.info(
            "MiniMaxImageProvider.generate model=%s aspect_ratio=%s n=%d",
            payload["model"], aspect_ratio, payload["n"],
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
        if resp.status_code >= 400:
            # Surface API error message verbatim — MiniMax returns {"message": ...}
            try:
                err_body = resp.json()
            except Exception:
                err_body = {"raw": resp.text[:500]}
            raise RuntimeError(
                f"MiniMax image API HTTP {resp.status_code}: {err_body}"
            )
        data = resp.json()
        try:
            images_b64 = data["data"]["image_base64"]
        except (KeyError, TypeError) as e:
            raise RuntimeError(
                f"MiniMax image API returned unexpected shape: {data!r}"
            ) from e
        if not images_b64:
            raise RuntimeError("MiniMax image API returned empty image_base64 list")
        return [base64.b64decode(b) for b in images_b64]