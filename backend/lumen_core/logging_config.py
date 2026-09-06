"""Phase 0 Unit 5 4.1 (2026-09-02):JSON 结构化日志配置。

**为什么**:Phase 0 之前日志是中文 string 拼接,grep / ELK / Loki 解析困难。
现在统一为单行 JSON,每条 log 自动带 trace_id(由 tracing.py contextvar
注入);ELK / Loki 按字段聚合 / 告警。

**用法**(单进程):
    from lumen_core.logging_config import setup_json_logging
    setup_json_logging(level="INFO")

**用法**(lumen_main.py 启动期 + uvicorn reloader 兼容):
    # lumen_main.py 模块顶部 + startup_event 头部都调一次,
    # 第二次 clear() 旧 handler 后重建,避免重复日志。

**字段约定**(JSON 单行):
    {
      "timestamp": "2026-09-02T12:34:56.789Z",
      "level": "INFO",
      "logger": "lumen_api.v1.chat",
      "message": "用户 chat 流式响应",
      "trace_id": "abc123..."      # 从 contextvar 取,无则省略
      "tenant_id": 42,             # 未来由 auth middleware 注入
      "user_id": 7,                # 未来由 auth middleware 注入
      "request_path": "/api/v1/chat",  # 由 FastAPI middleware 注入
      "duration_ms": 1234          # 由 FastAPI middleware 注入
    }

**性能**:单行 JSON 格式化 + filter 注入 contextvar,每条 log < 100us。
比中文 f-string 略慢但 ELK / Loki 解析必须。Phase 0 接受这个开销。

**踩坑**:
- uvicorn 自己的 logger (`uvicorn` / `uvicorn.access` / `uvicorn.error`)
  默认有独立 handler,**不会**走 root logger。要让 uvicorn 也输出 JSON,
  必须给这 3 个 logger 显式 setHandler(下面 setup_json_logging 已做)。
- 测试场景不想污染日志,可以用 `_QuietHandler` 走 NullHandler。
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Optional

from pythonjsonlogger import jsonlogger

from lumen_core.tracing import get_span_id, get_trace_flags, get_trace_id


# 默认日志级别(env override:`LOG_LEVEL=DEBUG`)
_DEFAULT_LEVEL = "INFO"


class _ContextFilter(logging.Filter):
    """logging.Filter 把 contextvar 的 trace_id + OTel span 字段挂到 record。

    Phase 0 Unit 5 4.1 (2026-09-02) ship:trace_id 注入。
    Phase 1 Group B 4.4 Day 7 (2026-09-06) 加:span_id + trace_flags 从
    OTel current span 注入,让 JSON stdout 含完整 W3C trace context,运维
    在 Loki / Grafana 能直接 ``trace_id=<tid> span_id=<sid>`` 跳到 Jaeger
    对应 leaf span。

    jsonlogger 后续会读 record.{trace_id,span_id,trace_flags} 加到 JSON。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        tid = get_trace_id()
        if tid:
            # 不要直接 record.__dict__["trace_id"] = ...(Filter 是 logging
            # 内置 API,改 record 属性安全)
            record.trace_id = tid
        # Phase 1 Group B 4.4 Day 7 (2026-09-06):span_id + trace_flags。
        # 没 active span / OTel 没装 → helper 返 None,直接跳过(不写 None
        # 到 record,保持 record 默认属性集合干净)。
        sid = get_span_id()
        if sid:
            record.span_id = sid
        flags = get_trace_flags()
        if flags is not None:
            record.trace_flags = flags
        return True  # 不过滤任何 record


class _ContextJsonFormatter(jsonlogger.JsonFormatter):
    """JsonFormatter 子类,自动注入 contextvar 字段到 JSON 输出。

    为什么不直接用 Filter + rename_fields:
    - Filter 只能改 record 属性,JsonFormatter 默认字段集是 fixed
      (timestamp / level / logger / message)
    - 想让 trace_id / span_id / trace_flags / tenant_id / user_id /
      request_path / duration_ms 出现在 JSON 里,需要在 add_fields() 里
      手动搬
    """

    # 这些字段由 4.3 middleware + Day 7 tracing helper 注入到 record;
    # 有则搬进 JSON
    _CONTEXT_FIELDS = ("trace_id", "span_id", "trace_flags", "tenant_id",
                       "user_id", "request_path", "request_method",
                       "duration_ms")

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # 把 record 上的 context 字段搬到 JSON
        for key in self._CONTEXT_FIELDS:
            val = getattr(record, key, None)
            if val is not None:
                log_record[key] = val


def _make_handler(level: str) -> logging.Handler:
    """构造 stdout JSON handler。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _ContextJsonFormatter(
            # 格式串只用作占位(影响默认字段顺序);真字段由 add_fields 决定
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
            timestamp=True,
        )
    )
    handler.addFilter(_ContextFilter())
    handler.setLevel(level)
    return handler


# ---------------------------------------------------------------------------
# Phase 1 Group B 4.4 Day 7 (2026-09-06): stdlib logging → OTel Logger bridge。
# ---------------------------------------------------------------------------

# stdlib level → OTel SeverityNumber 映射(OTel semantic conventions)。
# DEBUG → DEBUG / INFO → INFO / WARNING → WARN / ERROR → ERROR /
# CRITICAL → FATAL。stdlib 没 NOTSET 的对应,fallback INFO(默认)。
_LEVEL_TO_SEVERITY: dict[int, Any] = {}  # lazy init(避免 import 时 OTel 未装)


class OTelLogBridgeHandler(logging.Handler):
    """stdlib logging → OTel Logger bridge。

    同一 ``LogRecord`` **同时**走 stdout JSON(既有路径,Phase 0 Phase 1
    主通道)和 OTel ``logger.emit()``(新通道,Day 7 默认 disabled,运维
    按需开)。不挂时不创建 OTel logger;挂上后每条 record 同步 emit。

    设计要点:
    - **Severity 映射**:stdlib level → OTel ``SeverityNumber`` enum,
      W3C semantic conventions 一致(DEBUG / INFO / WARN / ERROR / FATAL)。
    - **Attributes 抽取**:`trace_id` / `span_id` / `trace_flags` / `tenant_id` /
      `user_id` 5 个 W3C + 业务 context 字段走 OTel LogRecord attributes,
      collector 端能按字段聚合。
    - **异常 swallow**:emit 失败走 stdlib ``Handler.handleError()`` 默认
      silent 行为,不污染后续 log。
    - **Lazy import**:`get_logger` + ``LogRecord`` / ``SeverityNumber`` 走
      函数内 import,OTel 未装时不阻塞 stdlib log 主通道。
    """

    # emit 时把这几个 record attribute 搬到 OTel LogRecord.attributes。
    # 跟 _ContextJsonFormatter._CONTEXT_FIELDS 子集对齐(trace / span /
    # tenant / user),JSON + OTel log record 两边字段集合一致便于 Loki 聚合。
    _BRIDGE_ATTR_KEYS = ("trace_id", "span_id", "trace_flags",
                         "tenant_id", "user_id")

    def __init__(self, level: int = logging.NOTSET) -> None:
        super().__init__(level=level)
        # lazy:handler 创建时不立即 import OTel 模块(测试 / dev console
        # 模式不需要),第一次 emit 时才走 OTel SDK。
        self._otel_logger: Any = None

    def _get_otel_logger(self) -> Any:
        if self._otel_logger is None:
            from opentelemetry._logs import get_logger

            # logger name 固定为 "lumen.logging.bridge",collector 端按
            # instrumentation_scope.name="lumen.logging.bridge" 聚合。
            self._otel_logger = get_logger("lumen.logging.bridge")
        return self._otel_logger

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Phase 1 Group B 4.4 Day 7 (2026-09-06): 用 SDK ``LogRecord`` 而非
            # API ``LogRecord`` —— OTel SDK 1.36 ``Logger.emit(API_LogRecord)``
            # 内部直接 ``LogData(record, scope)`` 不做 API→SDK 转换,导致
            # OTLP exporter 访问 ``log_record.resource`` AttributeError(API
            # LogRecord 没 ``.resource``)。SDK LogRecord(``opentelemetry.sdk._logs._internal.LogRecord``)
            # 有 ``.resource`` + 通过 ``context`` 拿 current span 拿到 trace_id/
            # span_id/trace_flags(W3C trace context 自动 join)。
            from opentelemetry import context as _otel_context
            from opentelemetry.sdk._logs._internal import LogRecord as OtelLogRecord
            from opentelemetry._logs import SeverityNumber

            # 懒初始化 level → severity 映射表
            global _LEVEL_TO_SEVERITY
            if not _LEVEL_TO_SEVERITY:
                _LEVEL_TO_SEVERITY = {
                    logging.DEBUG: SeverityNumber.DEBUG,
                    logging.INFO: SeverityNumber.INFO,
                    logging.WARNING: SeverityNumber.WARN,
                    logging.ERROR: SeverityNumber.ERROR,
                    logging.CRITICAL: SeverityNumber.FATAL,
                }
            severity = _LEVEL_TO_SEVERITY.get(
                record.levelno, SeverityNumber.INFO,
            )

            # 抽 5 个 context 字段到 attributes(全转 str,OTel attribute
            # value 必须是 primitive — 不支持 int / bool 直接进)
            attrs: dict[str, str] = {}
            for key in self._BRIDGE_ATTR_KEYS:
                val = getattr(record, key, None)
                if val is not None:
                    attrs[key] = str(val)

            # SDK LogRecord 用 ``context`` 参数(替代 deprecated trace_id/
            # span_id/trace_flags 三个独立参数,1.35.0 起 deprecated)。current
            # context 已被 OTel SDK middleware 设为 active span 的 context,
            # 进去后 SDK 自动抽 trace_id / span_id / trace_flags 到 LogRecord。
            otel_record = OtelLogRecord(
                # OTel timestamp 用 ns int;record.created 是 float 秒
                timestamp=int(record.created * 1e9),
                observed_timestamp=int(record.created * 1e9),
                context=_otel_context.get_current(),
                severity_number=severity,
                severity_text=record.levelname,
                body=record.getMessage(),
                attributes=attrs,
            )
            self._get_otel_logger().emit(otel_record)
        except Exception:
            # 走 stdlib Handler.handleError 默认 silent(写到 stderr 一行
            # traceback 后继续,不影响后续 log)。emit 失败不污染业务。
            self.handleError(record)


def setup_json_logging(level: Optional[str] = None) -> None:
    """把 root logger 配置为 JSON 单行输出到 stdout。

    - 清掉 root 旧 handler(uvicorn reloader 重复 setup 兜底)
    - 静默 noisy 库(httpx / httpcore / urllib3 默认 WARNING)
    - 让 uvicorn 的 3 个 logger 也走同一 handler(JSON 化 access log)
    - **Phase 1 Group B 4.4 Day 7 (2026-09-06)**:如果当前进程已 setup
      OTel log signal(``lumen_core.otel_logs.is_initialized()``),挂
      ``OTelLogBridgeHandler`` 到 root 让每条 log record 双写到 OTel
      Logger(走 collector → 未来 Loki)。默认 disabled,不开 log signal
      时**不挂**(避免 OTel 依赖增加 + 测试 fixture 污染)。

    幂等:多次调用安全,后一次覆盖前一次(handler.clear 兜底)。
    """
    lvl = (level or _DEFAULT_LEVEL).upper()
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(_make_handler(lvl))
    root.setLevel(lvl)

    # Phase 1 Group B 4.4 Day 7 (2026-09-06):OTel log signal 双通道桥。
    # 默认 disabled,运维按需 ``OTEL_LOG_EXPORTER=otlp`` 启(见
    # ``lumen_core.otel_logs.setup_logs``)。挂上后每条 record 同时走
    # stdout JSON(主通道,Phase 0 兼容)+ OTel Logger(新通道,Day 8 接 Loki)。
    try:
        from lumen_core.otel_logs import is_initialized as _otel_log_initialized

        if _otel_log_initialized():
            # ``OTelLogBridgeHandler`` 父类是 stdlib ``logging.Handler``,
            # ``__init__`` 参数是 int level;``lvl`` 上面是 str,转 int。
            root.addHandler(OTelLogBridgeHandler(level=getattr(logging, lvl)))
    except Exception as e:  # noqa: BLE001
        # OTel 模块未装 / setup 失败 → 静默跳过,不影响主通道
        logging.getLogger(__name__).debug(
            "OTelLogBridgeHandler attach skipped: %s", e,
        )

    # 静默 noisy library(hhtpx 调 Ollama 时刷大量 INFO 日志)
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # uvicorn 自己的 logger 默认有 handler(propagate=False),
    # 不会走 root。显式重定向到 root handler。
    for uv in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uv)
        uv_logger.handlers.clear()
        uv_logger.propagate = True  # 走 root 的 JSON handler
        uv_logger.setLevel(lvl)


def setup_default_logging(level: Optional[str] = None) -> None:
    """stdout 中文日志(开发默认,生产 / 测试用 setup_json_logging)。

    保留中文字符串格式(开发期 grep / tail 直读友好)。
    """
    lvl = (level or _DEFAULT_LEVEL).upper()
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


# ---- 测试 helpers ----


class _CapturingHandler(logging.Handler):
    """测试用:capture log record 到 list(不走 stdout)。"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def make_capturing_handler(level: str = "DEBUG") -> _CapturingHandler:
    """测试 fixture:capture log record 到 .records 列表。

    - 不打 stdout(capture 到 .records)
    - 带 _ContextFilter(自动注入 trace_id 到 record)
    - 用 _ContextJsonFormatter(rename_fields 标准化字段名)
    """
    h = _CapturingHandler()
    h.setLevel(level)
    h.addFilter(_ContextFilter())  # 把 ctx 的 trace_id 挂到 record
    h.setFormatter(_ContextJsonFormatter(
        # 格式串决定哪些 LogRecord 属性进 JSON(必须含字段名,
        # 否则 python-json-logger 不会搬)。rename_fields 把字段名
        # 改成 ELK / Loki 习惯(timestamp / level / logger)。
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
    ))
    return h


__all__ = [
    "setup_json_logging",
    "setup_default_logging",
    "_ContextFilter",
    "_ContextJsonFormatter",
    "OTelLogBridgeHandler",
    "make_capturing_handler",
]