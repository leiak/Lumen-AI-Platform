"""Single source of truth for supported LLM providers.

Both the admin API (`GET /models/providers/list`) and the chat model
loader (`app.services.model_loader.create_chat_model`) consume this
catalog. Add a new provider here and both surfaces pick it up
automatically.

To add a provider:
1. Append an entry to `MODEL_PROVIDERS` with `protocol="ollama"` or
   `protocol="openai_compat"` depending on which loader branch should
   handle it.
2. That's it — the API exposes it, the loader instantiates it, and the
   admin UI renders it on next page load.

`base_url_hint` is a UI-only affordance shown next to the Base URL
input on the admin form. It is never read on the request path.
"""
from typing import Literal, Optional, TypedDict


class ModelProvider(TypedDict):
    value: str
    label: str
    description: str
    base_url_hint: Optional[str]
    protocol: Literal["ollama", "openai_compat"]


MODEL_PROVIDERS: list[ModelProvider] = [
    {
        "value": "ollama",
        "label": "Ollama (本地)",
        "description": "本地运行的 Llama / Qwen / Mistral 等开源模型",
        "base_url_hint": "http://localhost:11434",
        "protocol": "ollama",
    },
    {
        "value": "openai",
        "label": "OpenAI",
        "description": "OpenAI 官方 / 任何 OpenAI 兼容端点(MiniMax、DeepSeek 自建等)",
        "base_url_hint": "https://api.openai.com/v1",
        "protocol": "openai_compat",
    },
    {
        "value": "anthropic",
        "label": "Anthropic",
        "description": "Claude 3.5 / 3.7 / Sonnet / Haiku 系列",
        "base_url_hint": "https://api.anthropic.com",
        "protocol": "openai_compat",
    },
    {
        "value": "zhipu",
        "label": "智谱 GLM",
        "description": "GLM-4 / GLM-4-Plus / GLM-Z1 国产大模型",
        "base_url_hint": "https://open.bigmodel.cn/api/paas/v4",
        "protocol": "openai_compat",
    },
    {
        "value": "minimax",
        "label": "MiniMax",
        "description": "MiniMax 大模型",
        "base_url_hint": None,
        "protocol": "openai_compat",
    },
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "description": "DeepSeek-V3 / R1 / Coder, OpenAI 兼容",
        "base_url_hint": "https://api.deepseek.com/v1",
        "protocol": "openai_compat",
    },
    {
        "value": "qwen",
        "label": "通义千问 (DashScope)",
        "description": "Qwen-Plus / Qwen-Max / Qwen-Coder, 兼容模式",
        "base_url_hint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "protocol": "openai_compat",
    },
    {
        "value": "moonshot",
        "label": "月之暗面 Moonshot / Kimi",
        "description": "moonshot-v1-8k / 32k / 128k, OpenAI 兼容",
        "base_url_hint": "https://api.moonshot.cn/v1",
        "protocol": "openai_compat",
    },
    {
        "value": "gemini",
        "label": "Google Gemini",
        "description": "Gemini 2.0 / 1.5 Pro / Flash, OpenAI 兼容端点",
        "base_url_hint": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "protocol": "openai_compat",
    }
]


def get_openai_compatible_providers() -> tuple[str, ...]:
    """Return the provider ids that go through the OpenAI-compatible HTTP path.

    Computed once at call time from `MODEL_PROVIDERS`, so adding a new
    `protocol="openai_compat"` entry is sufficient — no separate list
    to maintain.
    """
    return tuple(
        p["value"] for p in MODEL_PROVIDERS if p["protocol"] == "openai_compat"
    )


def is_supported_provider(value: str) -> bool:
    """True if `value` is a known provider id in `MODEL_PROVIDERS`."""
    return any(p["value"] == value for p in MODEL_PROVIDERS)
