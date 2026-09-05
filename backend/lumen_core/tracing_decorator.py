"""Phase 1 Group B 4.4 Day 3 (2026-09-05):manual span 装饰器基础设施。

**为什么**:Day 1/2 ship 了 OTel SDK + FastAPI/httpx/SQLAlchemy/Celery/Pymysql
自动 instrumentation,但**业务路径本身没有 span** — 运维在 trace UI 里看到
``GET /chat/stream`` + 一堆 httpx 出站 span + 几十条 SQL span,看不出
"chat → LLM → tools"的语义结构。

Day 3 给 5 个最关键业务路径加 manual span:
1. chat stream
2. embedding call(4 方法)
3. RAG retrieval
4. workflow executor(双层:run root + per-node child)
5. chat endpoint root

这个文件提供项目**第一个 manual span 范式**(命名约定 + attribute schema
+ decorator API),给后续 auth / KB upload / agent 等路径复用。

**装饰器 API**::

    from lumen_core.tracing_decorator import traced_span

    @traced_span("chat.stream", attributes={"chat.model": "qwen2.5:7b"})
    async def stream_chat_messages(self, messages, tools=None):
        ...

    @traced_span(
        "retrieval.search",
        attributes_fn=lambda query, k=5, **_: {"retrieval.k": k},
    )
    def search(self, query: str, k: int = 5):
        ...

**Span 命名约定**(项目首个 manual span 范式):
- Span name: ``domain.operation`` — 例 ``chat.stream`` / ``embedding.generate``
- Attribute key: ``domain.field`` — 例 ``chat.conversation_id`` / ``llm.model``

**PII 安全**:装饰器默认**不读 args**(避免误把消息内容写进 span)。
``attributes_fn`` 是 caller 显式选择记录哪些字段的唯一入口。
``exclude_keys`` 是文档化 hint,不自动生效。

**ContextVar bridge**:span 开启后,自动把 OTel span trace_id 同步到
``lumen_core.tracing._trace_id_var``,back-compat 老 ``LLMCallLog.trace_id``
/ ``EmbeddingCallLog.trace_id`` 仍是 32-hex,14 个老 trace_id test 不回归。

**异常处理**:``except Exception: span.record_exception(e);
span.set_status(Status(StatusCode.ERROR)); raise``(reraise 不 swallow,
可观测性不该改变业务行为)。

**支持 3 种函数形态**:
- sync 普通函数
- async coroutine
- async generator(``async def f(): yield ...``)

async generator 跨 yield 保持 span active,generator 退出时关闭 span。
这是 chat_service.stream_chat_messages 和 LoggingChatModel.astream 的
关键需求 — async generator 一旦开始 yield,整个流的生命周期都在 span 内。
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, Dict, FrozenSet, Optional

logger = logging.getLogger(__name__)


def _set_contextvar_from_span(span: Any) -> None:
    """把 OTel span trace_id 同步到 lumen_core.tracing contextvar。

    关键:back-compat 14 个老 trace_id test 假设 ``get_trace_id()`` 返回
    contextvar 真值。这个 bridge 让 manual span + 老 X-Trace-Id 共存 —
    老代码读 contextvar,新代码读 OTel span,两边拿到的 trace_id 一致。

    OTel 任何异常 swallow — 可观测性 bridge 永远不应该让业务挂掉。
    """
    try:
        from lumen_core.tracing import _trace_id_var
        sc = span.get_span_context()
        if sc.is_valid:
            _trace_id_var.set(format(sc.trace_id, "032x"))
    except Exception:  # noqa: BLE001
        logger.debug("traced_span: set_trace_id contextvar bridge failed", exc_info=True)


def _build_attributes(
    static_attrs: Optional[Dict[str, Any]],
    dynamic_fn: Optional[Callable[..., Dict[str, Any]]],
    args: tuple,
    kwargs: dict,
) -> Dict[str, Any]:
    """合并静态 + 动态 attributes。

    静态先,动态后覆盖同名 key — 允许 dynamic_fn 覆盖 static_attrs。
    """
    out: Dict[str, Any] = {}
    if static_attrs:
        out.update(static_attrs)
    if dynamic_fn is not None:
        try:
            extra = dynamic_fn(*args, **kwargs)
            if isinstance(extra, dict):
                out.update(extra)
            else:
                logger.warning(
                    "traced_span: attributes_fn returned %s, expected dict — ignored",
                    type(extra).__name__,
                )
        except Exception:  # noqa: BLE001
            logger.exception("traced_span: attributes_fn raised; ignored")
    return out


def _record_exception_and_status(span: Any, exc: BaseException) -> None:
    """span.record_exception + set_status(ERROR) — 失败时让 trace UI 标红。"""
    try:
        span.record_exception(exc)
        from opentelemetry.trace import Status, StatusCode
        span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
    except Exception:  # noqa: BLE001
        # OTel set_status 偶尔抛 type error(空 exc info 等),swallow 不影响 reraise
        logger.debug("traced_span: span.set_status raised; ignored", exc_info=True)


def _start_span(name: str, attributes: Dict[str, Any]) -> Any:
    """起一个 manual span。任何 setup_tracing 之前的进程里都是 NoOp。

    Returns:
        ``opentelemetry.trace.Span`` 实例。退出 ``with`` 块自动 end。
    """
    from opentelemetry import trace

    tracer = trace.get_tracer("lumen.manual")
    span = tracer.start_span(name, attributes=attributes or None)
    return span


# ---------------------------------------------------------------------------
# 装饰器工厂
# ---------------------------------------------------------------------------


def traced_span(
    name: Optional[str] = None,
    *,
    attributes: Optional[Dict[str, Any]] = None,
    attributes_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    exclude_keys: Optional[FrozenSet[str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """通用 manual span 装饰器。自动判断 sync / async / async generator。

    Args:
        name: Span 名称(默认 ``func.__name__``)。建议 ``domain.operation``
            命名,例 ``chat.stream`` / ``embedding.generate`` /
            ``retrieval.search``。
        attributes: 静态 attribute dict(decorator 编译期就确定的值)。
        attributes_fn: 动态 attribute 函数,签名跟被装饰函数一致(``*args, **kwargs``),
            返 dict。允许从 args 派生 attribute 而不读整个 args。
        exclude_keys: 文档化 hint — 当前装饰器不自动读 args,故此参数
            只是为 caller 留个显式表达"我有意排除 X"的钩子,不影响实际行为。
            **永远不会自动生效**(避免"安全错觉")。

    Returns:
        装饰后的函数,签名与原函数一致(sync / async 自动判断)。

    Raises:
        异常 reraise + span.record_exception + span.set_status(ERROR),
        业务异常正常向上抛,可观测性 bridge 不改变业务行为。

    Examples:
        >>> @traced_span("chat.stream", attributes={"chat.has_tools": False})
        ... async def stream_chat_messages(self, messages, tools=None):
        ...     ...

        >>> @traced_span(
        ...     "retrieval.search",
        ...     attributes_fn=lambda query, k=5, **_: {"retrieval.k": k},
        ... )
        ... def search(self, query, k=5):
        ...     ...
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or func.__name__

        # async generator:async def f(): yield ...
        if inspect.isasyncgenfunction(func):

            @functools.wraps(func)
            async def async_gen_wrapper(*args: Any, **kwargs: Any) -> Any:
                attrs = _build_attributes(attributes, attributes_fn, args, kwargs)
                span = _start_span(span_name, attrs)
                _set_contextvar_from_span(span)
                # 用 start_as_current_span 进入 ctx,这样 yield 期间 span 是 active
                from opentelemetry import trace as _otel_trace
                with _otel_trace.use_span(span, end_on_exit=False):
                    try:
                        async for item in func(*args, **kwargs):
                            yield item
                    except Exception as e:  # noqa: BLE001
                        _record_exception_and_status(span, e)
                        raise
                    finally:
                        try:
                            span.end()
                        except Exception:  # noqa: BLE001
                            pass

            return async_gen_wrapper

        # async coroutine
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                attrs = _build_attributes(attributes, attributes_fn, args, kwargs)
                span = _start_span(span_name, attrs)
                _set_contextvar_from_span(span)
                try:
                    return await func(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    _record_exception_and_status(span, e)
                    raise
                finally:
                    try:
                        span.end()
                    except Exception:  # noqa: BLE001
                        pass

            return async_wrapper

        # sync 普通函数
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            attrs = _build_attributes(attributes, attributes_fn, args, kwargs)
            span = _start_span(span_name, attrs)
            _set_contextvar_from_span(span)
            try:
                return func(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                _record_exception_and_status(span, e)
                raise
            finally:
                try:
                    span.end()
                except Exception:  # noqa: BLE001
                    pass

        return sync_wrapper

    return decorator


__all__ = ["traced_span"]
