"""Tests for `app.core.model_providers`.

The catalog is consumed by two surfaces — `GET /models/providers/list`
(admin UI) and `create_chat_model()` (chat/agent runtime) — and the
loader derives its `OPENAI_COMPATIBLE_PROVIDERS` set from it via
`protocol`. These tests pin down:

- catalog shape (required keys, allowed protocol values)
- uniqueness of provider ids (a duplicate `value` would silently
  shadow one option in the admin UI)
- JSON-serializability (the catalog is served as JSON over HTTP)
- the derived `get_openai_compatible_providers()` set is in sync
  with the loader's import-time constant, and ollama is excluded
- `is_supported_provider` rejects unknown values
"""
import json

import pytest

from lumen_core.model_providers import (
    MODEL_PROVIDERS,
    get_openai_compatible_providers,
    is_supported_provider,
)
from lumen_services.model_loader import OPENAI_COMPATIBLE_PROVIDERS


# Expected provider ids in catalog order. If this set changes, the
# matching test below will fail and force a deliberate update to both
# the catalog and this list.
#
# History: this list previously tracked 13 ids including openai /
# azure_openai / mistral / groq / grok. Those 5 were removed from the
# catalog on 2026-06-15 because the project doesn't use them and the
# chat-model loader had no real implementations behind them — keeping
# them around was misleading UI surface area. Pinning the 8 that
# actually ship today.
EXPECTED_PROVIDER_IDS = {
    "ollama",
    "anthropic",
    "zhipu",
    "minimax",
    "deepseek",
    "qwen",
    "moonshot",
    "gemini",
}

# Subset of ids that go through the OpenAI-compatible ChatOpenAI path.
# Everything in MODEL_PROVIDERS except ollama.
EXPECTED_OPENAI_COMPAT_IDS = EXPECTED_PROVIDER_IDS - {"ollama"}

ALLOWED_PROTOCOLS = {"ollama", "openai_compat"}


def test_catalog_is_non_empty():
    assert len(MODEL_PROVIDERS) >= 5


def test_catalog_contains_expected_provider_ids():
    actual = {p["value"] for p in MODEL_PROVIDERS}
    assert actual == EXPECTED_PROVIDER_IDS, (
        f"Catalog drifted from EXPECTED_PROVIDER_IDS. "
        f"Missing: {EXPECTED_PROVIDER_IDS - actual}, "
        f"unexpected: {actual - EXPECTED_PROVIDER_IDS}"
    )


def test_provider_ids_are_unique():
    ids = [p["value"] for p in MODEL_PROVIDERS]
    assert len(ids) == len(set(ids)), f"Duplicate provider id: {ids}"


@pytest.mark.parametrize("entry", MODEL_PROVIDERS, ids=lambda p: p["value"])
def test_each_entry_has_required_keys(entry):
    # TypedDict only enforces types at static-check time; assert at
    # runtime too because the catalog is serialized to JSON and a
    # missing key would silently break the admin UI.
    for key in ("value", "label", "description", "base_url_hint", "protocol"):
        assert key in entry, f"{entry.get('value', '?')} missing key: {key}"


@pytest.mark.parametrize("entry", MODEL_PROVIDERS, ids=lambda p: p["value"])
def test_protocol_is_allowed_value(entry):
    assert entry["protocol"] in ALLOWED_PROTOCOLS, (
        f"{entry['value']} has unknown protocol: {entry['protocol']!r}"
    )


def test_non_ollama_entries_are_openai_compat():
    """All non-ollama entries must declare `protocol='openai_compat'`,
    otherwise the loader's `if model_type in OPENAI_COMPATIBLE_PROVIDERS`
    branch will reject them.
    """
    for entry in MODEL_PROVIDERS:
        if entry["value"] == "ollama":
            assert entry["protocol"] == "ollama"
        else:
            assert entry["protocol"] == "openai_compat", (
                f"{entry['value']} should be openai_compat, "
                f"got {entry['protocol']!r}"
            )


def test_openai_compat_set_excludes_ollama():
    compat = get_openai_compatible_providers()
    assert "ollama" not in compat, (
        "ollama goes through ChatOllama, not ChatOpenAI — must not appear "
        "in the openai_compat set"
    )


def test_openai_compat_set_contents():
    assert set(get_openai_compatible_providers()) == EXPECTED_OPENAI_COMPAT_IDS


def test_openai_compat_returns_tuple():
    """The loader does `model_type in OPENAI_COMPATIBLE_PROVIDERS` —
    a tuple (not a list/generator) makes that O(n) but stable, and is
    what `tuple(...)` produces.
    """
    result = get_openai_compatible_providers()
    assert isinstance(result, tuple)


def test_loader_derived_set_matches_helper():
    """The loader computes its support set from the helper at import
    time. Drift between the two means a provider is in the UI but
    unreachable at runtime (or vice versa).
    """
    assert OPENAI_COMPATIBLE_PROVIDERS == get_openai_compatible_providers()


def test_is_supported_provider_known_values():
    for value in EXPECTED_PROVIDER_IDS:
        assert is_supported_provider(value), f"{value!r} should be supported"


def test_is_supported_provider_rejects_unknown():
    for value in ("", "gpt-99", "OPENAI", "Ollama", "claude", "fake-provider"):
        assert not is_supported_provider(value), (
            f"{value!r} should not be a supported provider"
        )


def test_is_supported_provider_case_sensitive():
    """Provider ids are exact-match strings (e.g. 'anthropic' not 'Anthropic').
    A case-insensitive lookup would let admins save configs the loader
    can't instantiate.

    Was previously pinned to 'openai', which was removed from the
    catalog on 2026-06-15; re-pinned to 'anthropic' since both 'anthropic'
    and a varied-case probe are still in the catalog.
    """
    assert is_supported_provider("anthropic")
    assert not is_supported_provider("Anthropic")
    assert not is_supported_provider("ANTHROPIC")


def test_catalog_is_json_serializable():
    """The catalog is served as JSON from GET /models/providers/list
    and consumed by the admin UI. Any non-JSON-serializable value
    (datetime, set, custom object) would 500 the endpoint.
    """
    # Will raise TypeError if any entry contains a non-serializable value.
    payload = json.dumps(MODEL_PROVIDERS, ensure_ascii=False)
    # Round-trip sanity check.
    decoded = json.loads(payload)
    assert len(decoded) == len(MODEL_PROVIDERS)
    assert decoded[0]["value"] == MODEL_PROVIDERS[0]["value"]


def test_base_url_hint_is_string_or_none():
    """`base_url_hint` is shown to admins as a click-to-copy badge.
    Anything that isn't str/None either crashes the form (str
    expected) or renders poorly (None should become a hidden badge).
    """
    for entry in MODEL_PROVIDERS:
        hint = entry["base_url_hint"]
        assert hint is None or isinstance(hint, str), (
            f"{entry['value']} has non-str/None base_url_hint: {type(hint)}"
        )
