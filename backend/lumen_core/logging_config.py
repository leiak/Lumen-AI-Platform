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

from lumen_core.tracing import get_trace_id


# 默认日志级别(env override:`LOG_LEVEL=DEBUG`)
_DEFAULT_LEVEL = "INFO"


class _ContextFilter(logging.Filter):
    """logging.Filter 把 contextvar 的 trace_id 挂到每条 record 上。

    jsonlogger 后续会读 record.trace_id 加到 JSON 输出。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        tid = get_trace_id()
        if tid:
            # 不要直接 record.__dict__["trace_id"] = ...(Filter 是 logging
            # 内置 API,改 record 属性安全)
            record.trace_id = tid
        return True  # 不过滤任何 record


class _ContextJsonFormatter(jsonlogger.JsonFormatter):
    """JsonFormatter 子类,自动注入 contextvar 字段到 JSON 输出。

    为什么不直接用 Filter + rename_fields:
    - Filter 只能改 record 属性,JsonFormatter 默认字段集是 fixed
      (timestamp / level / logger / message)
    - 想让 trace_id / tenant_id / user_id / request_path / duration_ms
      出现在 JSON 里,需要在 add_fields() 里手动搬
    """

    # 这些字段由 4.3 middleware 注入到 record;有则搬进 JSON
    _CONTEXT_FIELDS = ("trace_id", "tenant_id", "user_id",
                       "request_path", "request_method", "duration_ms")

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


def setup_json_logging(level: Optional[str] = None) -> None:
    """把 root logger 配置为 JSON 单行输出到 stdout。

    - 清掉 root 旧 handler(uvicorn reloader 重复 setup 兜底)
    - 静默 noisy 库(httpx / httpcore / urllib3 默认 WARNING)
    - 让 uvicorn 的 3 个 logger 也走同一 handler(JSON 化 access log)

    幂等:多次调用安全,后一次覆盖前一次。
    """
    lvl = (level or _DEFAULT_LEVEL).upper()
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(_make_handler(lvl))
    root.setLevel(lvl)

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
    "make_capturing_handler",
]