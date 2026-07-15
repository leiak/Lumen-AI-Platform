"""Image generation provider abstraction.

Spec: §7.1
"""
from typing import Protocol, List, Optional, Dict, Any


class ImageProvider(Protocol):
    """Provider that turns (prompt, params) into a list of raw image bytes."""

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
    ) -> List[bytes]: ...
