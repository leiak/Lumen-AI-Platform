from typing import Optional, List, Dict, Any, AsyncGenerator
import json
import logging
import time
from datetime import datetime

import httpx

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from lumen_core.llm_call_context import (
    LLMCallContext,
    get_call_context,
    set_call_context,
    reset_call_context,
)
from lumen_core.model_providers import get_openai_compatible_providers
from lumen_core.database import SessionLocal
from lumen_core.httpx_bypass import bypass_proxy_client_kwargs
from lumen_services.llm_call_logging import (
    extract_usage,
    extract_finish_reason,
    serialize_messages,
    serialize_tools,
)
from lumen_models.llm_call_log import LLMCallLog

# Derived from `MODEL_PROVIDERS` (filtered by `protocol="openai_compat"`).
# All entries go through the `langchain_openai.ChatOpenAI` client with a
# provider-specific `base_url`. Single source of truth lives in
# `app.core.model_providers`.
OPENAI_COMPATIBLE_PROVIDERS: tuple[str, ...] = get_openai_compatible_providers()


def _bypass_proxy_client_kwargs() -> dict:
    """Bypass Windows registry proxy for httpx clients (2026-08-31 fix).

    httpx with ``trust_env=True`` (the default) reads ``HKCU\\Software\\Microsoft\\
    Windows\\CurrentVersion\\Internet Settings\\ProxyServer`` and routes all
    outbound traffic through it. That proxy returns 502 Bad Gateway for
    localhost-bound requests (ollama on 11434) because httpx doesn't honor
    ``ProxyOverride``'s ``<local>`` token. curl isn't affected (it doesn't read
    the registry), so a healthy ``curl`` masks the underlying broken path.

    Workflow 1148 incident (2026-08-30): dev's system proxy was
    ``127.0.0.1:10793``; agent executor's ChatOllama got 502 while direct curl
    returned 200. Injecting ``proxy=None`` + ``trust_env=False`` forces httpx to
    connect directly. Same fix is applied to the OpenAI-compatible branch so
    that future M-series don't trip the same hidden bug.

    Returns a dict suitable for ``httpx.Client(**kwargs)`` /
    ``httpx.AsyncClient(**kwargs)`` and for ChatOllama's ``client_kwargs`` arg.
    """
    return {"proxy": None, "trust_env": False}


def _normalize_messages(messages: Any) -> List[BaseMessage]:
    """Accept a string / BaseMessage / List[Union[str, BaseMessage, dict]] and
    return a List[BaseMessage]. LangChain's BaseChatModel.invoke accepts any of
    these shapes; the M26 wrapper needs a concrete list for serialization.

    - str → wrapped as a single HumanMessage
    - list → walked item by item; strings become HumanMessage, dicts become
      HumanMessage(content=..., additional_kwargs=...) (best-effort), and
      BaseMessage instances pass through.
    """
    if messages is None:
        return []
    if isinstance(messages, str):
        return [HumanMessage(content=messages)]
    if isinstance(messages, BaseMessage):
        return [messages]
    if not isinstance(messages, list):
        return [HumanMessage(content=str(messages))]
    out: List[BaseMessage] = []
    for m in messages:
        if isinstance(m, BaseMessage):
            out.append(m)
        elif isinstance(m, str):
            out.append(HumanMessage(content=m))
        elif isinstance(m, dict):
            role = m.get("role") or m.get("type") or "human"
            content = m.get("content", "")
            if role in ("system",):
                out.append(SystemMessage(content=content))
            else:
                out.append(HumanMessage(content=content))
        else:
            out.append(HumanMessage(content=str(m)))
    return out


logger = logging.getLogger(__name__)


# ``bypass_proxy_client_kwargs`` 在 lumen_core.httpx_bypass 里定义,
# 这里是它的 thin re-export,避免逐个 caller 改 import 路径
# (也方便未来 grep 出"所有 bypass proxy 用法")。
_bypass_proxy_client_kwargs = bypass_proxy_client_kwargs


# ---------------------------------------------------------------------------
# LoggingChatModel proxy — wraps every chat model returned by create_chat_model
# ---------------------------------------------------------------------------

class LoggingChatModel:
    """Proxy that wraps a real ``BaseChatModel`` and writes one
    ``llm_call_logs`` row per ``invoke`` / ``ainvoke`` / ``astream`` /
    ``stream`` call.

    M26 spec: this is the high-leverage single seam that covers modules 1
    (chat), 2 (widget), 3 (agent_team — the create_chat_model call inside
    AgentService.chat) and 4 (workflow LLM node). The agent_team state
    graph wraps ``AgentService.chat`` with a ``LoggedChat`` helper for the
    extra ``call_type`` / parent_call_id metadata; the model_loader proxy
    catches every other call site.

    ``bind_tools`` returns a NEW LoggingChatModel whose ``_inner`` is
    already the bound real model — so tool-calling round trips still
    route through the proxy.

    The streaming paths accumulate the full response_content inside the
    generator (chunk by chunk) and write a SINGLE row at the end. This
    matches the MVP design choice "tool loop rounds → 1 LLMCallLog with
    tool_calls JSON containing all rounds".
    """

    def __init__(
        self,
        inner: Any,
        *,
        model_type: Optional[str],
        model_name: str,
        temperature: Optional[float] = None,
        model_config_id: Optional[int] = None,
    ):
        self._inner = inner
        self._model_type = model_type
        self._model_name = model_name
        self._temperature = temperature
        self._model_config_id = model_config_id

    # ---- factory ----

    def bind_tools(self, tools: List[Any]):
        return LoggingChatModel(
            self._inner.bind_tools(tools),
            model_type=self._model_type,
            model_name=self._model_name,
            temperature=self._temperature,
            model_config_id=self._model_config_id,
        )

    # ---- sync invoke ----

    def invoke(self, messages: Any, **kwargs) -> Any:
        ctx = get_call_context()
        normalized = _normalize_messages(messages)
        if ctx is None:
            return self._inner.invoke(messages, **kwargs)

        started = datetime.utcnow()
        t0 = time.monotonic()
        try:
            response = self._inner.invoke(messages, **kwargs)
            self._write_log(
                ctx=ctx,
                messages=normalized,
                response=response,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            return response
        except Exception as e:
            self._write_log(
                ctx=ctx,
                messages=normalized,
                response=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            raise

    # ---- async ainvoke ----

    async def ainvoke(self, messages: Any, **kwargs) -> Any:
        ctx = get_call_context()
        normalized = _normalize_messages(messages)
        if ctx is None:
            return await self._inner.ainvoke(messages, **kwargs)

        started = datetime.utcnow()
        t0 = time.monotonic()
        try:
            response = await self._inner.ainvoke(messages, **kwargs)
            self._write_log(
                ctx=ctx,
                messages=normalized,
                response=response,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            return response
        except Exception as e:
            self._write_log(
                ctx=ctx,
                messages=normalized,
                response=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            raise

    # ---- streaming ----

    async def astream(self, messages: Any, **kwargs) -> AsyncGenerator[Any, None]:
        """Accumulate chunks → write 1 row at end.

        The wrapper yields each chunk UNCHANGED so callers see the same
        BaseMessageChunk stream they would have seen without logging.
        Inside the generator, we collect ``content`` + ``tool_calls`` so
        we have a complete picture to persist.
        """
        ctx = get_call_context()
        normalized = _normalize_messages(messages)
        if ctx is None:
            async for chunk in self._inner.astream(messages, **kwargs):
                yield chunk
            return

        started = datetime.utcnow()
        t0 = time.monotonic()
        first_token_at: Optional[float] = None
        accumulated_content: List[str] = []
        accumulated_tool_calls: List[Dict[str, Any]] = []
        last_response: Optional[Any] = None
        error: Optional[BaseException] = None

        try:
            async for chunk in self._inner.astream(messages, **kwargs):
                if first_token_at is None and getattr(chunk, "content", None):
                    first_token_at = time.monotonic()
                content = getattr(chunk, "content", None)
                if content:
                    accumulated_content.append(content if isinstance(content, str) else str(content))
                tool_calls = getattr(chunk, "tool_calls", None) or []
                for tc in tool_calls:
                    accumulated_tool_calls.append({
                        "id": (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)),
                        "name": (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)),
                        "args": (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)),
                    })
                # LangChain AIMessageChunk can also carry accumulated tool_call_chunks
                # that we want to fold into the final shape — we don't try to
                # reconstruct here; the legacy .tool_calls field above is enough
                # for the MVP. The final row stores what we accumulated.
                last_response = chunk
                yield chunk
        except Exception as e:
            error = e

        # Build a synthetic "response" for extraction purposes.
        # For finish_reason, prefer last chunk's response_metadata if any.
        synthetic = last_response
        if synthetic is None and accumulated_content:
            # No chunk ever produced content — still log what we have.
            class _Fake:
                pass
            synthetic = _Fake()
            synthetic.content = ""  # type: ignore[attr-defined]
            synthetic.tool_calls = []  # type: ignore[attr-defined]
            synthetic.usage_metadata = None  # type: ignore[attr-defined]
            synthetic.response_metadata = {}  # type: ignore[attr-defined]

        # Merge accumulated tool_calls onto the synthetic response so
        # serialize_* helpers see them.
        if synthetic is not None and accumulated_tool_calls:
            existing = list(getattr(synthetic, "tool_calls", None) or [])
            merged = existing + [
                tc for tc in accumulated_tool_calls
                if not any(e.get("id") == tc.get("id") for e in existing)
            ]
            try:
                setattr(synthetic, "tool_calls", merged)
            except Exception:
                pass

        full_content = "".join(accumulated_content)
        self._write_log_streaming(
            ctx=ctx,
            messages=normalized,
            full_content=full_content,
            synthetic_response=synthetic,
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
            first_token_latency_ms=(
                int((first_token_at - t0) * 1000) if first_token_at is not None else None
            ),
            status="failure" if error is not None else "success",
            error_type=type(error).__name__ if error is not None else None,
            error_message=str(error)[:1000] if error is not None else None,
        )
        if error is not None:
            raise error

    def stream(self, messages: Any, **kwargs):
        """Sync streaming variant — same shape as astream but blocking."""
        ctx = get_call_context()
        normalized = _normalize_messages(messages)
        if ctx is None:
            yield from self._inner.stream(messages, **kwargs)
            return

        started = datetime.utcnow()
        t0 = time.monotonic()
        first_token_at: Optional[float] = None
        accumulated_content: List[str] = []
        accumulated_tool_calls: List[Dict[str, Any]] = []
        last_response: Optional[Any] = None
        error: Optional[BaseException] = None

        try:
            for chunk in self._inner.stream(messages, **kwargs):
                if first_token_at is None and getattr(chunk, "content", None):
                    first_token_at = time.monotonic()
                content = getattr(chunk, "content", None)
                if content:
                    accumulated_content.append(content if isinstance(content, str) else str(content))
                tool_calls = getattr(chunk, "tool_calls", None) or []
                for tc in tool_calls:
                    accumulated_tool_calls.append({
                        "id": (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)),
                        "name": (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)),
                        "args": (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)),
                    })
                last_response = chunk
                yield chunk
        except Exception as e:
            error = e

        full_content = "".join(accumulated_content)
        self._write_log_streaming(
            ctx=ctx,
            messages=normalized,
            full_content=full_content,
            synthetic_response=last_response,
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
            first_token_latency_ms=(
                int((first_token_at - t0) * 1000) if first_token_at is not None else None
            ),
            status="failure" if error is not None else "success",
            error_type=type(error).__name__ if error is not None else None,
            error_message=str(error)[:1000] if error is not None else None,
        )
        if error is not None:
            raise error

    # ---- write helpers ----

    def _write_log(
        self,
        *,
        ctx: LLMCallContext,
        messages: List[BaseMessage],
        response: Any,
        started_at: datetime,
        duration_ms: int,
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        from lumen_services.llm_call_logging import get_llm_call_logging_service

        sys_msgs = [
            {"role": "system", "content": m.content}
            for m in messages if getattr(m, "type", None) == "system"
        ]
        # Build user_message from the last user message in the list, if any.
        user_msg_text: Optional[str] = None
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                user_msg_text = m.content if isinstance(m.content, str) else str(m.content)
                break

        token_usage = extract_usage(response) if response is not None else None
        finish_reason = extract_finish_reason(response) if response is not None else None
        tool_calls = None
        if response is not None and getattr(response, "tool_calls", None):
            tool_calls = [
                {
                    "id": (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)),
                    "name": (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)),
                    "args": (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)),
                }
                for tc in (response.tool_calls or [])
            ]
        response_content = None
        if response is not None and getattr(response, "content", None):
            response_content = response.content if isinstance(response.content, str) else str(response.content)

        # Open a fresh DB session — the caller's session may be in the
        # middle of a write transaction and we don't want to entangle.
        db = SessionLocal()
        try:
            get_llm_call_logging_service().log_call(
                db,
                ctx=ctx,
                model_type=self._model_type,
                model_name=self._model_name,
                temperature=self._temperature,
                max_tokens=None,
                system_messages=sys_msgs or None,
                user_message=user_msg_text,
                messages=serialize_messages(messages),
                tools=ctx.extra.get("tools") if isinstance(ctx.extra, dict) else None,
                extra_params=None,
                response_content=response_content,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                token_usage=token_usage,
                started_at=started_at,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                first_token_latency_ms=None,
                status=status,
                error_type=error_type,
                error_message=error_message,
                model_config_id=self._model_config_id,
            )
        finally:
            db.close()

    def _write_log_streaming(
        self,
        *,
        ctx: LLMCallContext,
        messages: List[BaseMessage],
        full_content: str,
        synthetic_response: Any,
        started_at: datetime,
        duration_ms: int,
        first_token_latency_ms: Optional[int],
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        from lumen_services.llm_call_logging import get_llm_call_logging_service

        sys_msgs = [
            {"role": "system", "content": m.content}
            for m in messages if getattr(m, "type", None) == "system"
        ]
        user_msg_text: Optional[str] = None
        for m in reversed(messages):
            if getattr(m, "type", None) == "human":
                user_msg_text = m.content if isinstance(m.content, str) else str(m.content)
                break

        token_usage = extract_usage(synthetic_response) if synthetic_response is not None else None
        finish_reason = extract_finish_reason(synthetic_response) if synthetic_response is not None else None
        tool_calls = None
        if synthetic_response is not None and getattr(synthetic_response, "tool_calls", None):
            tool_calls = [
                {
                    "id": (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)),
                    "name": (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)),
                    "args": (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)),
                }
                for tc in (synthetic_response.tool_calls or [])
            ]

        db = SessionLocal()
        try:
            get_llm_call_logging_service().log_call(
                db,
                ctx=ctx,
                model_type=self._model_type,
                model_name=self._model_name,
                temperature=self._temperature,
                max_tokens=None,
                system_messages=sys_msgs or None,
                user_message=user_msg_text,
                messages=serialize_messages(messages),
                tools=ctx.extra.get("tools") if isinstance(ctx.extra, dict) else None,
                extra_params=None,
                response_content=full_content or None,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                token_usage=token_usage,
                started_at=started_at,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                first_token_latency_ms=first_token_latency_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
                model_config_id=self._model_config_id,
            )
        finally:
            db.close()


# ---------------------------------------------------------------------------
# create_chat_model — public factory
# ---------------------------------------------------------------------------

def create_chat_model(
    model_type: str,
    model_name: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.7,
    timeout: int = 120,
    **kwargs
):
    """Create a chat model based on type, wrapped in ``LoggingChatModel``.

    The wrapper writes one ``llm_call_logs`` row per invocation when an
    ``LLMCallContext`` is active (set by the request entrypoint). Without
    an active context the wrapper is transparent — same invoke / ainvoke
    / astream semantics as the underlying model.

    Args:
        model_type: provider id from `app.core.model_providers.MODEL_PROVIDERS`.
        model_name: Model identifier. For Azure OpenAI this is the
            *deployment name*, not the underlying model id.
        base_url: API base URL. Required for everything except ollama.
        api_key: API key. Required for everything except ollama.
        temperature: Sampling temperature
        timeout: Request timeout in seconds
    """
    # Model config rows in the DB sometimes have a leading/trailing space in
    # base_url or api_key (typically introduced by copy-paste in the admin UI).
    # The OpenAI/Anthropic client passes these straight to httpx, which fails
    # with a generic "Connection error" on a URL like " https://...". Strip
    # defensively here so all callers (chat stream, agent chat, etc.) benefit.
    if base_url:
        base_url = base_url.strip() or None
    if api_key:
        api_key = api_key.strip() or None

    model_config_id = kwargs.pop("model_config_id", None)
    inner: Any
    if model_type == "ollama":
        # Resolve base_url for Ollama: host.docker.internal (from DB model config)
        # is only reachable from inside Docker. When running on the host (uvicorn),
        # replace it with localhost so the host's Ollama is used.
        resolved_base_url = base_url
        if resolved_base_url and "host.docker.internal" in resolved_base_url:
            import socket
            try:
                sock = socket.create_connection(("host.docker.internal", 11434), timeout=1)
                sock.close()
            except (socket.error, OSError):
                # host.docker.internal not reachable → use localhost instead
                resolved_base_url = resolved_base_url.replace(
                    "host.docker.internal", "localhost"
                )
        inner = ChatOllama(
            model=model_name,
            base_url=resolved_base_url,
            temperature=temperature,
            timeout=timeout,
            client_kwargs=_bypass_proxy_client_kwargs(),
        )
    elif model_type in OPENAI_COMPATIBLE_PROVIDERS:
        if not base_url:
            raise ValueError(f"base_url is required for {model_type}")
        if not api_key:
            raise ValueError(f"api_key is required for {model_type}")

        # Bypass Windows registry proxy (see _bypass_proxy_client_kwargs).
        # Both sync + async clients must get the bypass — openai SDK uses
        # sync for ``invoke`` and async for ``ainvoke``; missing one would
        # leave the other half exposed to the registry proxy.
        _bypass = _bypass_proxy_client_kwargs()
        inner = ChatOpenAI(
            model=model_name,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            http_client=httpx.Client(**_bypass),
            http_async_client=httpx.AsyncClient(**_bypass),
            **kwargs
        )
        # Force HTTP/1.1 on Windows: after the client is built, replace its
        # underlying AsyncHTTPTransport with one that has HTTP/2 disabled.
        # This avoids the ALPN handshake hang that httpx's default HTTP/2-first
        # negotiation causes on some Windows network configurations.
        try:
            inner._client._transport = httpx.AsyncHTTPTransport(http2=False)
        except Exception:
            pass
    else:
        raise ValueError(f"Unsupported model type: {model_type}")

    return LoggingChatModel(
        inner,
        model_type=model_type,
        model_name=model_name,
        temperature=temperature,
        model_config_id=model_config_id,
    )