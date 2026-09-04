"""Phase 0 Unit 5 4.3 (2026-09-02):Prometheus 指标定义 + /metrics 端点。

**指标体系**:

内置(由 prometheus_client 自动注册):
- ``process_cpu_seconds_total`` — CPU 时间累计
- ``process_resident_memory_bytes`` — RSS
- ``python_gc_*`` — GC 计数 / 耗时

HTTP(由 PrometheusMiddleware 自动记录):
- ``http_requests_total{method, path, status}`` — 请求计数
- ``http_request_duration_seconds{method, path}`` — 请求延迟直方图

Lumen 业务指标(各服务主动 .labels(...).inc() / .observe()):
- ``lumen_active_connections{type=mysql|redis|es|s3}`` — 活跃连接数
- ``lumen_rate_limit_rejections_total{endpoint}`` — 限流拒绝计数
- ``lumen_llm_calls_total{model, status}`` — LLM 调用计数(在 chat / agent service 里 .inc())
- ``lumen_llm_tokens_total{model, type=prompt|completion}`` — token 用量
- ``lumen_embedding_calls_total{model, status}`` — embedding 调用计数
- ``lumen_doc_processing_duration_seconds{status}`` — 文档处理耗时
- ``lumen_celery_tasks_total{queue, status}`` — celery 任务计数

**Endpoint**:``GET /metrics`` 返 Prometheus 文本格式(Content-Type:
text/plain; version=0.0.4; charset=utf-8),Prometheus scrape 用。

**Cardinality 防护**:
- path 用 starlette route template(``/users/{user_id}``)而非实际 URL
  (避免 ``/users/1`` / ``/users/2`` ... 无限 label 增长)
- high-cardinality 字段(trace_id / request_id / user_id)绝不进 label

**踩坑**:
- prometheus_client 默认 registry 是全局单例;测试时要 reset,避免
  跨测试污染 → 用 ``prometheus_client.REGISTRY`` 直接 clear
- Histogram bucket 选 [5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s,
  2.5s, 5s, 10s] 覆盖 chat streaming / doc upload / admin 等场景
"""
from __future__ import annotations

import logging
from typing import Optional

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

logger = logging.getLogger(__name__)


# ---- HTTP metrics (middleware 自动记录) ----


http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests handled by FastAPI.",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
    buckets=(
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    ),
)


# ---- Lumen 业务 metrics (服务主动 inc/observe) ----


lumen_active_connections = Gauge(
    "lumen_active_connections",
    "Active connections to external systems by type.",
    ["type"],  # mysql / redis / es / s3
)

lumen_rate_limit_rejections_total = Counter(
    "lumen_rate_limit_rejections_total",
    "Total rate limit rejections (HTTP 429 or 503).",
    ["endpoint"],  # 路由模板,不是具体 path
)

lumen_llm_calls_total = Counter(
    "lumen_llm_calls_total",
    "Total LLM model invocations.",
    ["model", "status"],  # status: success / error / timeout
)

lumen_llm_tokens_total = Counter(
    "lumen_llm_tokens_total",
    "Total LLM tokens consumed.",
    ["model", "type"],  # type: prompt / completion
)

lumen_embedding_calls_total = Counter(
    "lumen_embedding_calls_total",
    "Total embedding model invocations.",
    ["model", "status"],
)

lumen_doc_processing_duration_seconds = Histogram(
    "lumen_doc_processing_duration_seconds",
    "Document processing duration in seconds (parse + chunk + embed).",
    ["status"],  # success / error
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
)

lumen_celery_tasks_total = Counter(
    "lumen_celery_tasks_total",
    "Total Celery task outcomes.",
    ["queue", "status"],  # status: success / error / retry
)


# Phase 1 Group B 2.4.5 (2026-09-04): Celery 各队列任务堆积深度 Gauge。
# 由 lumen_core.celery_queue_monitor 背景任务每 30s 跑 ``redis llen(queue)``
# 更新 —— Prometheus 不会自己数 Celery 队列长度,得 backend 主动上报。
# Grafana Overview 看板 + B2c Alertmanager ``lumen_celery_queue_depth_high``
# 告警共用。
lumen_celery_queue_depth = Gauge(
    "lumen_celery_queue_depth",
    "Number of pending tasks in a Celery queue (redis llen).",
    ["queue"],  # doc_parse / ppt_gen / eval_run / default
)


# Phase 1 Group A 2.3 (2026-09-03): 熔断器状态 Gauge。
# 每个 (breaker, state) label 对一个 0/1 值,只有当前态 = 1,其他 = 0。
# closed=0 / half_open=1 / open=2 是 state code 常量,在
# lumen_services.circuit_breaker.STATE_* 里定义。
lumen_circuit_breaker_state = Gauge(
    "lumen_circuit_breaker_state",
    "Circuit breaker state by name. closed/half_open/open labels, 1=current, 0=other.",
    ["breaker", "state"],
)


# ---- /metrics 端点 helper ----


def render_metrics() -> tuple[bytes, str]:
    """返 Prometheus text format 文本 + Content-Type。

    用法:
        @app.get("/metrics", include_in_schema=False)
        async def metrics():
            body, content_type = render_metrics()
            return Response(content=body, media_type=content_type)
    """
    return generate_latest(), CONTENT_TYPE_LATEST


def get_metric_value(
    metric_name: str,
    labels: Optional[dict] = None,
) -> Optional[float]:
    """查询某个 counter / gauge / histogram 的当前值(测试 / debug 用)。

    Args:
        metric_name: e.g. ``http_requests_total``
        labels: e.g. ``{"method": "GET", "path": "/health", "status": "200"}``

    Returns:
        float 值。无匹配返 None(不是 0 — 0 表示真的为 0,None 表示 metric 不存在)。
    """
    from prometheus_client import REGISTRY

    labels = labels or {}
    try:
        for fam in REGISTRY.collect():
            for sample in fam.samples:
                if sample.name == metric_name:
                    sample_labels = sample.labels
                    if all(sample_labels.get(k) == v for k, v in labels.items()):
                        return sample.value
    except Exception as e:  # noqa: BLE001
        logger.warning("get_metric_value(%s) failed: %s", metric_name, e)
    return None


# ---- 测试 helpers ----


def reset_metrics_for_test() -> None:
    """重置所有 lumen 自定义 metric 的 sample 数据(测试间隔离用)。

    实现:遍历本模块定义的 Counter / Gauge / Histogram,清空它们内部
    ``_metrics`` dict —— 即所有 (label_values → sample) 映射,但保留
    metric 在 REGISTRY 中的注册。下次 ``.labels(...).inc()`` 重新创建 sample。

    **为什么不清空 platform / process / gc collector**:那些是
    prometheus_client 自动注册的内置 metric,跟 lumen 业务无关,留着
    不影响测试断言(测试只查 lumen 命名空间的 metric)。

    pytest fixture 推荐:
        @pytest.fixture(autouse=True)
        def _reset_metrics():
            yield
            reset_metrics_for_test()
    """
    # 本模块所有 metric instance(模块加载时已 register 到全局 REGISTRY)
    _LUMEN_METRICS = (
        http_requests_total,
        http_request_duration_seconds,
        lumen_active_connections,
        lumen_rate_limit_rejections_total,
        lumen_llm_calls_total,
        lumen_llm_tokens_total,
        lumen_embedding_calls_total,
        lumen_doc_processing_duration_seconds,
        lumen_celery_tasks_total,
        lumen_circuit_breaker_state,
        lumen_celery_queue_depth,
    )
    for metric in _LUMEN_METRICS:
        try:
            # Counter / Gauge / Histogram 都继承 MetricWrapperBase,
            # 内部 _metrics dict 存 label_values → 子 metric 实例。
            # 清空它等价于"丢掉所有 sample,保留 metric 声明"。
            metric._metrics.clear()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


__all__ = [
    "http_requests_total",
    "http_request_duration_seconds",
    "lumen_active_connections",
    "lumen_rate_limit_rejections_total",
    "lumen_llm_calls_total",
    "lumen_llm_tokens_total",
    "lumen_embedding_calls_total",
    "lumen_doc_processing_duration_seconds",
    "lumen_celery_tasks_total",
    "lumen_circuit_breaker_state",
    "lumen_celery_queue_depth",
    "render_metrics",
    "get_metric_value",
    "reset_metrics_for_test",
]