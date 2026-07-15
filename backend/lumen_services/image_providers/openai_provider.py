"""OpenAI image generation provider (DALL·E 3 / gpt-image-1).

NOTE: This is a stub that raises NotImplementedError for the actual HTTP call.
The class is shipped so the factory route exists; real call wiring is V2 work.
Spec: §7.1
"""
import logging
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)


class OpenAIImageProvider:
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
        # Real call would be:
        #   import httpx
        #   resp = await httpx.AsyncClient(...).post(
        #     f"{self.model_config.base_url}/images/generations",
        #     headers={"Authorization": f"Bearer {self.model_config.api_key}"},
        #     json={"model": self.model_config.model_name, "prompt": prompt, ...},
        #   )
        #   return [httpx.get(url).content for url in [d["url"] for d in resp.json()["data"]]]
        log.warning(
            "OpenAIImageProvider is a stub — falling through to NotImplementedError. "
            "Configure is_image_generation=False to use StubImageProvider instead."
        )
        raise NotImplementedError(
            "OpenAIImageProvider not yet wired. Set is_image_generation=False on the model."
        )
