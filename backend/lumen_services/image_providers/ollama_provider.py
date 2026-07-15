"""Ollama image generation provider. Stub for now (no local image model configured).

Spec: §7.1
"""
import logging
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)


class OllamaImageProvider:
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
        log.warning("OllamaImageProvider is a stub — local Ollama has no image models.")
        raise NotImplementedError("OllamaImageProvider not yet wired.")
