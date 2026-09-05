"""Phase 1 Group B 4.4 Day 3 (2026-09-05):LLM 专用 span helper。

**为什么**:``@traced_span`` 装饰器对 invoke / ainvoke / sync 完美工作,
但 ``astream`` / ``stream`` 是 async generator,横跨 yield 期间需要
精确控制 span 关闭时机 — generator 已开始 yield 后再有错,装饰器
finally 仍会调 ``span.end()``,这是 OK 的;但**首 chunk 延迟 + tokens**
只能在 generator 内部收集,装饰器拿不到。

这两个 helper 解决"已知要写 span,但需要 generator 中途写 attribute"
的场景:**record_chat_span** 返 (span, t0) tuple,generator 自由写
``llm.ttfb_ms`` / ``llm.tokens``,**finish_chat_span** 在末尾关 span。

**API 约定**::

    from lumen_services.llm_tracing import record_chat_span, finish_chat_span

    span, t0 = record_chat_span(
        model="qwen2.5:7b",
        call_kind="astream",
        messages_count=len(messages),
    )
    try:
        first_chunk = True
        async for chunk in inner.astream(messages):
            if first_chunk:
                span.add_event("ttfb", {"llm.ttfb_ms": int((time.monotonic() - t0) * 1000)})
                first_chunk = False
            yield chunk
        # 调用方传 response 给 finish 抽 tokens
        finish_chat_span(span, t0, response=last_chunk)
    except Exception as e:
        finish_chat_span(span, t0, status="error", error=e)
        raise

**与 ``@traced_span`` 装饰器的关系**:helper 是装饰器的"低阶 API"。
装饰器内部用 ``start_span`` + 异常 catch + ``span.end()``;helper 把
这些手动化,让 caller 完全控制 attribute 写入时机。两者共用同一个
tracer (``lumen.manual``) 和相同的 contextvar bridge。

**复用**:
- ``LoggingChatModel.astream`` / ``stream``(model_loader.py)
- 任何需要在 yield 中途写 attribute 的 LLM 调用
- 未来 agent / agent_team 的 stream 路径也可直接用
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 共享内部辅助
# ---------------------------------------------------------------------------


def _start_chat_span(
    *,
    model: Optional[str],
    call_kind: str,
    messages_count: Optional[int],
) -> Tuple[Any, float]:
    """起 ``llm.chat`` span + contextvar bridge + 写静态 attribute。

    Args:
        model: 模型名,会写到 ``llm.model`` attribute。None 时跳过。
        call_kind: ``"invoke"`` / ``"ainvoke"`` / ``"astream"`` / ``"stream"``。
        messages_count: messages 列表长度,写到 ``llm.messages_count``。

    Returns:
        ``(span, t0)`` tuple。``t0`` 是 ``time.monotonic()`` 起点,用于
        后续计算 ttfb_ms / duration_ms。
    """
    from lumen_core.tracing_decorator import _start_span, _set_contextvar_from_span

    attrs: dict = {"llm.call_kind": call_kind}
    if model:
        attrs["llm.model"] = str(model)
    if messages_count is not None:
        attrs["llm.messages_count"] = int(messages_count)

    span = _start_span("llm.chat", attrs)
    _set_contextvar_from_span(span)
    return span, time.monotonic()


def _finish_chat_span(
    span: Any,
    t0: float,
    *,
    status: str = "success",
    error: Optional[BaseException] = None,
    response: Any = None,
    first_token_at: Optional[float] = None,
) -> None:
    """写 ttfb / duration / tokens,异常时 set_status + record,最后 end()。

    Args:
        span: ``record_chat_span`` 返回的 span object。
        t0: ``time.monotonic()`` 起点(``record_chat_span`` 同期返回)。
        status: ``"success"`` / ``"error"``。
        error: 异常时传,会被 ``record_exception`` 写到 span。
        response: 最后一个 chunk / response object,用于抽 ``usage_metadata``。
            None 时跳过 tokens 抽取。
        first_token_at: 首 chunk 的 ``time.monotonic()`` 时间戳。
            非 None 时写 ``llm.ttfb_ms`` attribute。
    """
    # 计算 metrics
    now = time.monotonic()
    duration_ms = int((now - t0) * 1000)
    ttfb_ms = (
        int((first_token_at - t0) * 1000) if first_token_at is not None else None
    )

    # 写 attribute(必须在 record_exception 之前,否则 set_status(ERROR) 后
    # 部分 backend 会 lock attribute)
    try:
        span.set_attribute("llm.duration_ms", duration_ms)
        span.set_attribute("llm.status", status)
        if ttfb_ms is not None:
            span.set_attribute("llm.ttfb_ms", ttfb_ms)
        # 抽 tokens(response.usage_metadata → dict)
        if response is not None and status == "success":
            try:
                from lumen_services.llm_call_logging import extract_usage

                usage = extract_usage(response)
                if isinstance(usage, dict) and usage:
                    for k, v in usage.items():
                        # usage key 例 input_tokens / output_tokens / total_tokens
                        span.set_attribute(f"llm.tokens.{k}", int(v) if v is not None else 0)
                    if "total_tokens" in usage:
                        span.set_attribute("llm.tokens", int(usage["total_tokens"]))
            except Exception:  # noqa: BLE001
                logger.debug("llm_tracing: extract_usage failed; tokens skipped", exc_info=True)
    except Exception:  # noqa: BLE001
        logger.debug("llm_tracing: set_attribute failed; ignored", exc_info=True)

    # 异常 / 状态
    if error is not None:
        try:
            span.record_exception(error)
            from opentelemetry.trace import Status, StatusCode
            span.set_status(Status(StatusCode.ERROR, str(error)[:200]))
        except Exception:  # noqa: BLE001
            logger.debug("llm_tracing: set_status raised; ignored", exc_info=True)

    # end span — 即使 set_attribute 失败也要 end,否则 span 永远 active
    try:
        span.end()
    except Exception:  # noqa: BLE001
        logger.debug("llm_tracing: span.end raised; ignored", exc_info=True)


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def record_chat_span(
    model: Optional[str],
    call_kind: str,
    messages_count: Optional[int] = None,
) -> Tuple[Any, float]:
    """起一个 ``llm.chat`` span,让 caller 在 yield 中途写 attribute。

    必须配对 ``finish_chat_span`` 用(caller 决定何时 end)。

    Returns:
        ``(span, t0)`` tuple。
    """
    return _start_chat_span(
        model=model,
        call_kind=call_kind,
        messages_count=messages_count,
    )


def finish_chat_span(
    span: Any,
    t0: float,
    *,
    status: str = "success",
    error: Optional[BaseException] = None,
    response: Any = None,
    first_token_at: Optional[float] = None,
) -> None:
    """收尾 ``llm.chat`` span(写 metrics + set_status + end)。

    必须跟 ``record_chat_span`` 配对。
    """
    _finish_chat_span(
        span,
        t0,
        status=status,
        error=error,
        response=response,
        first_token_at=first_token_at,
    )


__all__ = ["record_chat_span", "finish_chat_span"]
