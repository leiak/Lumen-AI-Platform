"""Route ModelConfig.model_type to the right ImageProvider.

Spec: §7.1
"""
from lumen_services.image_providers.stub_provider import StubImageProvider
from lumen_services.image_providers.openai_provider import OpenAIImageProvider
from lumen_services.image_providers.stability_provider import StabilityImageProvider
from lumen_services.image_providers.ollama_provider import OllamaImageProvider
from lumen_services.image_providers.minimax_provider import MiniMaxImageProvider


def get_image_provider(model_config):
    t = (model_config.model_type or "").lower()
    if t == "openai":
        return OpenAIImageProvider(model_config)
    if t == "stability":
        return StabilityImageProvider(model_config)
    if t == "ollama":
        return OllamaImageProvider(model_config)
    if t == "minimax":
        return MiniMaxImageProvider(model_config)
    # default: unknown / unconfigured → stub
    return StubImageProvider(model_config)
