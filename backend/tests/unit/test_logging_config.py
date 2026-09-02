"""Phase 0 Unit 5 4.1 (2026-09-02):JSON 结构化日志测试。

覆盖:
- 单行 JSON 格式(timestamp / level / logger / message 字段)
- contextvar trace_id 自动注入到 record
- 自定义字段(tenant_id / user_id / request_path / duration_ms)通过
  extra={} 传入后出现在 JSON
- 多次 setup 幂等(uvicorn reloader 兜底)
- uvicorn logger propagate=True(JSON 化 access log)
- noisy library 静默(httpx / httpcore WARNING)
"""
import io
import json
import logging
import sys

import pytest

from lumen_core import tracing
from lumen_core.logging_config import (
    _ContextFilter,
    _ContextJsonFormatter,
    make_capturing_handler,
    setup_default_logging,
    setup_json_logging,
)


@pytest.fixture(autouse=True)
def _reset_trace():
    """每个 test 后清 trace_id contextvar。"""
    tracing.reset_for_test()


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """每个 test 后还原 root logger 状态(避免污染后续 test)。"""
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    old_level = root.level
    old_propagate = {uv: logging.getLogger(uv).propagate for uv in
                     ("uvicorn", "uvicorn.access", "uvicorn.error")}
    old_levels = {uv: logging.getLogger(uv).level for uv in old_propagate}
    yield
    root.handlers = old_handlers
    root.setLevel(old_level)
    for uv, propagate in old_propagate.items():
        uv_logger = logging.getLogger(uv)
        uv_logger.propagate = propagate
        uv_logger.setLevel(old_levels[uv])
    tracing.reset_for_test()


# ===== JSON 单行输出 =====


def test_json_output_single_line_with_core_fields():
    """JSON formatter 输出含 timestamp / level / logger / message。"""
    handler = make_capturing_handler()
    logger = logging.getLogger("test_logger")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("DEBUG")
    logger.propagate = False  # 避免 root 干扰

    logger.info("hello world")

    record = handler.records[0]
    # 用 handler 自带的 formatter 渲染(已带 rename_fields)
    output = handler.formatter.format(record)
    parsed = json.loads(output)

    assert parsed["message"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test_logger"
    assert "timestamp" in parsed


def test_json_output_with_trace_id_from_contextvar():
    """trace_id 从 contextvar 取,自动注入到 JSON。"""
    tracing.set_trace_id("abc123trace")
    handler = make_capturing_handler()
    logger = logging.getLogger("test_with_trace")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("DEBUG")
    logger.propagate = False

    logger.info("with trace")

    record = handler.records[0]
    output = handler.formatter.format(record)
    parsed = json.loads(output)

    assert parsed["trace_id"] == "abc123trace"


def test_json_output_omits_trace_id_when_contextvar_empty():
    """contextvar 无 trace_id → JSON 不含 trace_id 字段。"""
    # 不调用 set_trace_id
    assert tracing.get_trace_id() is None

    handler = make_capturing_handler()
    logger = logging.getLogger("test_no_trace")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("DEBUG")
    logger.propagate = False

    logger.info("no trace")

    record = handler.records[0]
    output = handler.formatter.format(record)
    parsed = json.loads(output)

    assert "trace_id" not in parsed


def test_json_output_with_extra_context_fields():
    """extra={tenant_id: 42} 出现在 JSON 输出。"""
    handler = make_capturing_handler()
    logger = logging.getLogger("test_extra")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("DEBUG")
    logger.propagate = False

    logger.info("with extra", extra={"tenant_id": 42, "user_id": 7})

    record = handler.records[0]
    output = handler.formatter.format(record)
    parsed = json.loads(output)

    assert parsed["tenant_id"] == 42
    assert parsed["user_id"] == 7


def test_json_output_with_request_path_and_duration():
    """request_path / request_method / duration_ms 通过 extra 注入。"""
    handler = make_capturing_handler()
    logger = logging.getLogger("test_request")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("DEBUG")
    logger.propagate = False

    logger.info(
        "request done",
        extra={
            "request_path": "/api/v1/chat",
            "request_method": "POST",
            "duration_ms": 234,
        },
    )

    record = handler.records[0]
    output = handler.formatter.format(record)
    parsed = json.loads(output)

    assert parsed["request_path"] == "/api/v1/chat"
    assert parsed["request_method"] == "POST"
    assert parsed["duration_ms"] == 234


# ===== setup_json_logging =====


def test_setup_json_logging_clears_old_handlers():
    """setup_json_logging 清掉 root 旧 handler(uvicorn reloader 兜底)。"""
    root = logging.getLogger()
    initial_handler = logging.StreamHandler(sys.stdout)
    root.addHandler(initial_handler)
    assert initial_handler in root.handlers

    setup_json_logging()

    assert initial_handler not in root.handlers
    # 新 handler 至少 1 个
    assert len(root.handlers) >= 1


def test_setup_json_logging_idempotent():
    """多次调用安全(handler 列表只 1 个,不会重复日志)。"""
    setup_json_logging()
    handler_count_1 = len(logging.getLogger().handlers)

    setup_json_logging()
    handler_count_2 = len(logging.getLogger().handlers)

    assert handler_count_1 == handler_count_2 == 1


def test_setup_json_logging_silences_noisy_libraries():
    """noisy library 默认 WARNING(httpx / httpcore / urllib3 / asyncio)。"""
    setup_json_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_setup_json_logging_makes_uvicorn_propagate():
    """uvicorn 3 个 logger 走 propagate=True(让 root handler 接管)。"""
    setup_json_logging()
    for uv in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        assert logging.getLogger(uv).propagate is True


def test_setup_json_logging_respects_level_arg():
    """setup_json_logging(level="DEBUG") 把 root 设到 DEBUG。"""
    setup_json_logging(level="DEBUG")
    assert logging.getLogger().level == logging.DEBUG


# ===== setup_default_logging =====


def test_setup_default_logging_basic_format(capsys):
    """setup_default_logging 输出中文 string 格式(开发期友好)。"""
    setup_default_logging(level="INFO")
    logger = logging.getLogger("test_default")
    logger.info("测试中文 message")

    captured = capsys.readouterr()
    assert "测试中文 message" in captured.out
    assert "[INFO]" in captured.out
    assert "test_default" in captured.out


# ===== _ContextFilter 直接测 =====


def test_context_filter_injects_trace_id_when_present():
    """_ContextFilter 在 ctx 有 trace_id 时挂到 record。"""
    tracing.set_trace_id("filter-trace")

    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    f = _ContextFilter()
    f.filter(record)
    assert record.trace_id == "filter-trace"


def test_context_filter_skips_when_trace_id_absent():
    """_ContextFilter 在 ctx 无 trace_id 时不动 record(返回 True 但不挂)。"""
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=None, exc_info=None,
    )
    f = _ContextFilter()
    result = f.filter(record)
    assert result is True
    assert not hasattr(record, "trace_id")


# ===== 端到端:JSON output 真的能 parse =====


def test_json_output_parseable_per_line(capsys):
    """stdout 输出每行都是合法 JSON(ELK / Loki 直接吃)。"""
    setup_json_logging(level="INFO")
    logger = logging.getLogger("test_e2e")
    logger.info("first")
    logger.info("second with trace", extra={"tenant_id": 1})
    logger.warning("third warn")

    captured = capsys.readouterr()
    lines = [l for l in captured.out.splitlines() if l.startswith("{")]
    assert len(lines) == 3
    for line in lines:
        # 每行都是合法 JSON
        parsed = json.loads(line)
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "message" in parsed