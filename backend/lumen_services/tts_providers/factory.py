"""M35: route ModelConfig.model_type to the right TTSProvider.

Mirror of lumen_services.image_providers.factory — dispatcher keyed by
lowercase model_type. Unknown types fall through to the stub provider
so a misconfigured row never 500s.
"""
from lumen_services.tts_providers.stub_provider import StubTTSProvider
from lumen_services.tts_providers.edge_provider import EdgeTTSProvider
from lumen_services.tts_providers.piper_provider import PiperTTSProvider
from lumen_services.tts_providers.openai_provider import OpenAITTSProvider


def get_tts_provider(model_config):
    """Return the right TTSProvider for the given ModelConfig.

    `model_type` follows the convention used elsewhere — lowercase
    provider tag (edge / piper / openai / lumen_subtitle).
    """
    t = (model_config.model_type or "").lower()
    if t == "edge":
        return EdgeTTSProvider(model_config)
    if t == "piper":
        return PiperTTSProvider(model_config)
    if t == "openai":
        return OpenAITTSProvider(model_config)
    # default: unknown / unconfigured → stub (returns silence WAV)
    return StubTTSProvider(model_config)
