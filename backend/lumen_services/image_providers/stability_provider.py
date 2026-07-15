"""Stability AI image generation provider (SD3 / SDXL). Stub for now.

Spec: §7.1
"""
import logging
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)


class StabilityImageProvider:
    def __init__(self, model_config):
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
            "StabilityImageProvider is a stub — see OpenAIImageProvider for wiring plan."
        )
        raise NotImplementedError("StabilityImageProvider not yet wired.")
