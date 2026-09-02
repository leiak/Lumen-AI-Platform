"""Shared httpx client kwargs for bypassing Windows registry proxy.

The Windows ``HKCU\Software\Microsoft\Windows\CurrentVersion\Internet
Settings\ProxyServer`` registry key is read by Python's ``urllib.getproxies``
(httpx ``trust_env=True`` defaults to it) and routes ALL outbound
traffic through whatever proxy the user has configured. For dev
workstations with a system proxy like ``127.0.0.1:10793``, that proxy
returns 502 for localhost-bound requests (e.g. ``localhost:11434`` for
ollama) because httpx does not honour ``ProxyOverride``'s ``<local>``
token. curl isn't affected (it doesn't read the registry), so a
healthy ``curl http://localhost:11434`` masks the underlying broken
httpx path.

Originally surfaced in the workflow 1148 incident (2026-08-30) for
the agent executor's ``ChatOllama``; the fix was applied inside
``lumen_services/model_loader.create_chat_model``. The same root
cause hits:

- ``OllamaEmbeddings`` — KB RAG embed calls (``embedding_factory.py``)
- ``OpenAIEmbeddings`` — KB RAG embed calls for OpenAI-compatible
  providers (``embedding_factory.py``)
- ``httpx.Client`` / ``httpx.AsyncClient`` passed into the ``openai``
  SDK's ``http_client`` / ``http_async_client`` parameters.

Importing this helper from one place keeps the bypass policy in sync
across chat and embedding paths.

Workflow 1148 incident timeline (for context):
- 2026-08-30: dev's system proxy ``127.0.0.1:10793``; agent executor
  ``ChatOllama`` got 502 from ``localhost:11434`` (ollama) while direct
  curl returned 200.
- 2026-08-31: ``model_loader.create_chat_model`` shipped with
  ``_bypass_proxy_client_kwargs()`` returning ``{"proxy": None,
  "trust_env": False}`` and applied to the ChatOllama + ChatOpenAI
  branches. Agent 247 e2e went from 502 to "2".
- 2026-09-02 (this fix): same helper extracted to ``lumen_core`` and
  applied to ``OllamaEmbeddings`` + ``OpenAIEmbeddings`` in
  ``embedding_factory``. Without this fix the embedding path silently
  produced 502 / empty results during KB ingest on proxy-equipped
  dev boxes, and pre-existing ``nomic-embed-text`` embeddings inside
  an already-built index (committed by the host machine before the
  proxy was turned on) stayed searchable from search but never
  refreshed on retry/rechunk.

Returns a dict suitable for:

- ``httpx.Client(**kwargs)`` / ``httpx.AsyncClient(**kwargs)``
- ``OllamaEmbeddings(client_kwargs=...)``
- ``OpenAIEmbeddings(http_client=..., http_async_client=...)`` (pass
  ``**kwargs`` directly)

Note: the ``openai`` SDK only exposes ``trust_env`` on its internal
httpx client, not ``proxy`` — the proxy is read via
``_get_proxy_map`` at request time. Passing ``proxy=None`` to the
underlying httpx clients still disables the proxy for embeddings
because the SDK's transport is the same httpx Client we passed in.
The helper returns both keys so the caller can pass the whole dict
through ``**`` without cherry-picking.
"""
from __future__ import annotations

from typing import Any, Dict


def bypass_proxy_client_kwargs() -> Dict[str, Any]:
    """Return kwargs that disable httpx's Windows-registry proxy read.

    Combine with ``httpx.Client(**bypass_proxy_client_kwargs())``,
    ``httpx.AsyncClient(**bypass_proxy_client_kwargs())``, or pass as
    the ``client_kwargs`` arg of ``OllamaEmbeddings``.
    """
    return {"proxy": None, "trust_env": False}