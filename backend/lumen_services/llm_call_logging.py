"""LLM call logging service + helpers.

M26 spec — three layers of helpers:

- ``extract_usage`` — pull token-usage out of an AIMessage across
  LangChain providers (Ollama, ChatOpenAI, etc.). Ollama returns None
  for ``usage_metadata``; ChatOpenAI populates it.
- ``serialize_messages`` / ``serialize_tools`` — convert LangChain
  BaseMessage / BaseTool objects into JSON-safe dicts for the
  ``messages`` / ``tools`` JSON columns.
- ``LLMCallLoggingService.log_call`` — write one row to ``llm_call_logs``
  inside an existing transaction (callers control commit).

The LoggingChatModel proxy in ``services/model_loader.py`` calls these
helpers on every invoke / astream so the streaming path doesn't need a
separate instrumented code path.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext
from lumen_models.llm_call_log import LLMCallLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage extraction
# ---------------------------------------------------------------------------

def extract_usage(response: Any) -> Optional[Dict[str, int]]:
    """Extract token-usage from a LangChain AIMessage.

    Two known shapes:

    - LangChain 1.0+ standard: ``response.usage_metadata`` is a dict with
      keys ``input_tokens`` / ``output_tokens`` / ``total_tokens``.
    - Some providers put usage inside ``response_metadata["usage"]`` or
      ``response_metadata["token_usage"]``.

    Ollama typically returns None for both — we propagate None so the
    caller can render "N/A" in the UI rather than guessing.
    """
    # 1) LangChain 1.0 standard
    usage_meta = getattr(response, "usage_metadata", None)
    if isinstance(usage_meta, dict) and usage_meta:
        return {
            "prompt_tokens": int(usage_meta.get("input_tokens") or 0),
            "completion_tokens": int(usage_meta.get("output_tokens") or 0),
            "total_tokens": int(usage_meta.get("total_tokens") or 0),
        }
    # 2) Provider-specific response_metadata
    response_meta = getattr(response, "response_metadata", None) or {}
    usage = response_meta.get("usage") or response_meta.get("token_usage")
    if isinstance(usage, dict) and usage:
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
    return None


def extract_finish_reason(response: Any) -> Optional[str]:
    """Read ``finish_reason`` from a LangChain response, with safe fallbacks.

    Sources, in priority order:

    1. ``response.response_metadata["finish_reason"]`` — provider-supplied
       (OpenAI, etc.); the canonical source.
    2. ``response.response_metadata["stop_reason"]`` — Anthropic-style.
    3. Inferred from tool_calls presence: if the AIMessage carries any
       tool_calls, the stop reason was effectively ``tool_calls``.
    4. ``None`` when the model didn't report one (Ollama is silent).
    """
    if response is None:
        return None
    response_meta = getattr(response, "response_metadata", None) or {}
    fr = response_meta.get("finish_reason") or response_meta.get("stop_reason")
    if fr:
        return str(fr)
    tool_calls = getattr(response, "tool_calls", None) or []
    if tool_calls:
        return "tool_calls"
    return None


# ---------------------------------------------------------------------------
# Message / tool serialization
# ---------------------------------------------------------------------------

def _message_role(msg: BaseMessage) -> str:
    """Map a LangChain BaseMessage to a stable role string."""
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, SystemMessage):
        return "system"
    if isinstance(msg, ToolMessage):
        return "tool"
    if isinstance(msg, AIMessage):
        return "assistant"
    # Unknown subclass — fall back to the langchain ``type`` attribute.
    return str(getattr(msg, "type", "unknown") or "unknown")


def serialize_message(msg: BaseMessage) -> Dict[str, Any]:
    """Convert a LangChain BaseMessage to a JSON-safe dict.

    Captures:

    - role (user / assistant / system / tool)
    - content (string or list-of-parts → flattened to string)
    - tool_calls (assistant only)
    - tool_call_id (tool only)
    - name (when present)
    - response_metadata (provider-specific extras, when present)
    """
    role = _message_role(msg)
    out: Dict[str, Any] = {"role": role}

    # Content: ``str`` or list-of-parts (Anthropic content blocks).
    content = getattr(msg, "content", "") or ""
    if isinstance(content, list):
        # Each item is typically {"type": "text"|"image", "text": "..."}.
        # Flatten to a string for the common case; preserve structured
        # parts as a sub-list so the UI can render them later.
        flat: List[str] = []
        for part in content:
            if isinstance(part, dict):
                t = part.get("text")
                if t:
                    flat.append(t)
                elif "image" in part:
                    flat.append("[image]")
            elif isinstance(part, str):
                flat.append(part)
            else:
                flat.append(str(part))
        content = "".join(flat) if flat else ""
    out["content"] = content if isinstance(content, str) else str(content)

    # Tool calls (assistant only — OpenAI-style).
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        out["tool_calls"] = [
            {
                "id": (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)),
                "name": (tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)),
                "args": (tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)),
            }
            for tc in tool_calls
        ]

    # Tool message identifier.
    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id and role == "tool":
        out["tool_call_id"] = tool_call_id

    # Optional name.
    name = getattr(msg, "name", None)
    if name:
        out["name"] = name

    # response_metadata: pass through provider-specific keys but strip
    # large blobs like raw HTTP request/response frames.
    response_meta = getattr(msg, "response_metadata", None)
    if isinstance(response_meta, dict) and response_meta:
        out["response_metadata"] = {
            k: v for k, v in response_meta.items()
            if k in ("model", "model_name", "finish_reason", "stop_reason", "usage", "token_usage")
        }

    return out


def serialize_messages(messages: Sequence[BaseMessage]) -> List[Dict[str, Any]]:
    return [serialize_message(m) for m in messages]


def serialize_tools(tools: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Convert a list of LangChain BaseTool (or compatible) into JSON-safe dicts."""
    if not tools:
        return []
    out: List[Dict[str, Any]] = []
    for t in tools:
        try:
            name = getattr(t, "name", None) or str(t)
            description = getattr(t, "description", None) or ""
            # args_schema → Pydantic model. We grab its JSON Schema.
            schema: Optional[Dict[str, Any]] = None
            schema_obj = getattr(t, "args_schema", None)
            if schema_obj is not None:
                try:
                    schema = schema_obj.model_json_schema()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    schema = None
            if schema is None and hasattr(t, "args"):
                # Fall back to the legacy ``args`` dict shape.
                args_dict = getattr(t, "args", None)
                if isinstance(args_dict, dict):
                    schema = {"type": "object", "properties": args_dict}
            out.append({
                "name": name,
                "description": description,
                "parameters_schema": schema,
            })
        except Exception as e:  # noqa: BLE001
            # Don't let a single broken tool abort the whole log write.
            logger.warning("serialize_tools: failed for %r: %s", t, e)
            continue
    return out


# ---------------------------------------------------------------------------
# Char / token estimation
# ---------------------------------------------------------------------------

def total_chars(items: Sequence[Dict[str, Any]]) -> int:
    return sum(len(str(it.get("content") or "")) for it in items)


# ---------------------------------------------------------------------------
# LoggingChatModel — proxy that wraps a real chat model
# ---------------------------------------------------------------------------

# Keep import local to avoid a circular dependency at module import time
# (model_loader imports from us, but the agent_team / workflow nodes import
# model_loader at function call time). Defer the proxy class definition
# into model_loader.py; here we only expose the write helpers.


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

class LLMCallLoggingService:
    """Persist a single LLMCallLog row.

    The caller controls the transaction (typically ``db.add(log); db.commit()``
    inside the same scope as the LLM invocation). For streaming paths,
    call ``log_call`` once at the END of the stream with the accumulated
    response_content / tool_calls.
    """

    def log_call(
        self,
        db: Session,
        *,
        ctx: LLMCallContext,
        model_type: Optional[str],
        model_name: str,
        temperature: Optional[float],
        max_tokens: Optional[int],
        system_messages: Optional[List[Dict[str, Any]]],
        user_message: Optional[str],
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        response_content: Optional[str],
        finish_reason: Optional[str],
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        token_usage: Optional[Dict[str, int]] = None,
        started_at: Any,
        finished_at: Any,
        duration_ms: int,
        first_token_latency_ms: Optional[int] = None,
        status: str = "success",
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
        model_config_id: Optional[int] = None,
    ) -> Optional[LLMCallLog]:
        """Insert a single LLMCallLog row.

        Returns the persisted row, or None on a hard failure (logged).
        Failure to write a log row MUST NOT bubble up to the caller —
        observability should not break the actual LLM response stream.
        """
        try:
            input_chars = total_chars(messages or []) + sum(
                len(sm.get("content") or "") for sm in (system_messages or [])
            )
            output_chars = len(response_content or "")
            # Rough token estimate (chars / 4) — used only when no real
            # token_usage is available. Display this as "≈ N tokens" in
            # the UI so users can tell it's an estimate.
            input_tokens_estimate = max(1, input_chars // 4) if input_chars > 0 else 0
            output_tokens_estimate = max(1, output_chars // 4) if output_chars > 0 else 0

            row = LLMCallLog(
                call_id=ctx.call_id,
                parent_call_id=ctx.parent_call_id,
                trace_id=ctx.trace_id,
                call_type=ctx.call_type,
                call_index=ctx.call_index,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                username=ctx.username,
                client_app=ctx.client_app,
                conversation_id=ctx.conversation_id,
                message_id=ctx.message_id,
                agent_id=ctx.agent_id,
                team_id=ctx.team_id,
                team_member_id=ctx.team_member_id,
                workflow_id=ctx.workflow_id,
                workflow_run_id=ctx.workflow_run_id,
                workflow_node_id=ctx.workflow_node_id,
                image_id=ctx.image_id,
                model_type=model_type,
                model_name=model_name,
                model_config_id=model_config_id,
                temperature=temperature,
                max_tokens=max_tokens,
                system_messages=system_messages,
                user_message=user_message,
                messages=messages,
                tools=tools,
                extra_params=extra_params,
                input_chars=input_chars,
                input_tokens_estimate=input_tokens_estimate,
                response_content=response_content,
                finish_reason=finish_reason,
                tool_calls=tool_calls,
                output_chars=output_chars,
                output_tokens_estimate=output_tokens_estimate,
                token_usage=token_usage,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                first_token_latency_ms=first_token_latency_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
                retry_count=retry_count,
                request_ip=ctx.request_ip,
                user_agent=ctx.user_agent,
                extra=ctx.extra,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        except Exception:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception("LLMCallLoggingService.log_call failed; observability row skipped")
            return None


_singleton: Optional[LLMCallLoggingService] = None


def get_llm_call_logging_service() -> LLMCallLoggingService:
    global _singleton
    if _singleton is None:
        _singleton = LLMCallLoggingService()
    return _singleton