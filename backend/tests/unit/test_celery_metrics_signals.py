"""2.1 C.5: Celery task_success / task_failure / task_retry 信号 handler
把 ``lumen_celery_tasks_total{queue, status}`` Prometheus Counter 真正写入。

Phase 1 Group B 2.4.5 ship 了 Counter 定义但没连 Celery 信号,Prometheus
一直 0,Grafana ``slo:celery_success:sli_5m`` 走 clamp_min 兜底永远 100%
(``monitoring/slo_definitions.yaml:99-101`` TODO 注释)。本测试验
handler 安装 + 真实 inc + 容错 + queue 标签从 delivery_info 拿。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.metrics import (
    get_metric_value,
    lumen_celery_tasks_total,
    reset_metrics_for_test,
)


@pytest.fixture(autouse=True)
def _reset():
    """每个 test 前清空 Counter,避免上次 inc 残留影响断言。"""
    reset_metrics_for_test()
    yield
    reset_metrics_for_test()


def _make_task(routing_key: str | None = "doc_parse", name: str = "process_document"):
    """构造 Celery 任务 instance 的最小化替身。

    Celery 真实 task object 有 ``.request.delivery_info.routing_key``;
    handler 内部通过 ``_resolve_queue`` 读这个属性。我们用 SimpleNamespace
    拼出同样的属性层级,handler 不知道是 mock。
    """
    delivery_info = {"routing_key": routing_key} if routing_key else {}
    request = SimpleNamespace(delivery_info=delivery_info)
    task = SimpleNamespace(request=request, name=name)
    return task


# ===== _resolve_queue =====


def test_resolve_queue_from_delivery_info_routing_key():
    """happy path: task.request.delivery_info.routing_key 存在 → 用它。"""
    from lumen_tasks.metrics_signals import _resolve_queue

    task = _make_task(routing_key="doc_parse")
    assert _resolve_queue(task) == "doc_parse"


def test_resolve_queue_falls_back_to_unknown_when_no_delivery_info():
    """task.request 不存在 / delivery_info 缺 routing_key → "unknown"。"""
    from lumen_tasks.metrics_signals import _resolve_queue

    # 没有任何 attribute 的替身
    task = SimpleNamespace()
    assert _resolve_queue(task) == "unknown"


def test_resolve_queue_does_not_raise_when_attribute_access_blows_up():
    """metrics 路径不能挂:即使 task.request.delivery_info 访问抛异常,
    _resolve_queue 也要 swallow + 返 "unknown"。
    """
    from lumen_tasks.metrics_signals import _resolve_queue

    class BrokenTask:
        @property
        def request(self):
            raise RuntimeError("simulated access bug")

    assert _resolve_queue(BrokenTask()) == "unknown"


# ===== _on_task_success / _on_task_failure / _on_task_retry =====


def test_on_task_success_increments_counter_with_correct_labels():
    """task_success handler inc success + queue label 来自 delivery_info。"""
    from lumen_tasks.metrics_signals import _on_task_success

    task = _make_task(routing_key="doc_parse")
    _on_task_success(sender=task)

    val = get_metric_value(
        "lumen_celery_tasks_total", {"queue": "doc_parse", "status": "success"},
    )
    assert val == 1.0


def test_on_task_failure_increments_error_counter():
    """task_failure handler inc error + queue label。"""
    from lumen_tasks.metrics_signals import _on_task_failure

    task = _make_task(routing_key="ppt_gen")
    _on_task_failure(sender=task)

    val = get_metric_value(
        "lumen_celery_tasks_total", {"queue": "ppt_gen", "status": "error"},
    )
    assert val == 1.0


def test_on_task_retry_increments_retry_counter():
    """task_retry handler inc retry。retry 后续 task_failure 会再 inc error,
    dashboard 上 success+error+retry 叠加 = 任务总数。
    """
    from lumen_tasks.metrics_signals import _on_task_retry

    task = _make_task(routing_key="eval_run")
    _on_task_retry(sender=task)

    val = get_metric_value(
        "lumen_celery_tasks_total", {"queue": "eval_run", "status": "retry"},
    )
    assert val == 1.0


def test_handler_swallows_exceptions_and_does_not_propagate():
    """handler 内部 try/except 兜住 metrics 路径异常,绝不让 Celery 主流程挂。

    Simulate 拿不到 queue(走 "unknown" 兜底)+ Counter labels 抛错(handler
    内层 try/except)。最坏情况:写不进去,handler 不抛。
    """
    from lumen_tasks.metrics_signals import _on_task_failure, _on_task_success

    broken_task = SimpleNamespace()  # 无 .request,.name → _resolve_queue 走 fallback

    # 模拟 labels() 抛错(罕见,但要验证兜底)
    with patch.object(
        lumen_celery_tasks_total, "labels", side_effect=RuntimeError("boom"),
    ):
        # 两个 handler 都不抛
        _on_task_success(sender=broken_task)
        _on_task_failure(sender=broken_task)


def test_handler_uses_unknown_when_queue_not_resolvable():
    """handler 在 queue 拿不到时仍 inc,只是 queue="unknown"。metrics 拿不到
    queue 比丢数好(dashboard 标 "unknown" 让运维知道是 routing 没生效)。
    """
    from lumen_tasks.metrics_signals import _on_task_success

    task = SimpleNamespace()  # 无 .request
    _on_task_success(sender=task)

    val = get_metric_value(
        "lumen_celery_tasks_total", {"queue": "unknown", "status": "success"},
    )
    assert val == 1.0


# ===== install_metrics_signals 装到 Celery 信号 =====


def test_install_metrics_signals_connects_to_celery_signals():
    """install_metrics_signals 调一次后,task_success / task_failure /
    task_retry 都 connect 了我们的 handler。
    """
    from celery import signals

    from lumen_tasks.metrics_signals import (
        _on_task_failure,
        _on_task_retry,
        _on_task_success,
        install_metrics_signals,
    )

    # Celery signal 在 in-process 测试下是 mutable global,先清,避免重复 connect
    try:
        signals.task_success.disconnect(_on_task_success)
        signals.task_failure.disconnect(_on_task_failure)
        signals.task_retry.disconnect(_on_task_retry)
    except (ValueError, TypeError):
        pass  # 没连过的 signal disconnect 抛 ValueError,吞掉

    install_metrics_signals()

    # Celery signals 用 sender 当 hash key dispatch receiver,所以 sender
    # 必须是 class(可 hash),不能用 SimpleNamespace instance。我们直接
    # 调 3 个 handler(已在 install 后 connect),不走 Celery 的 signal dispatch,
    # 等价验证 handler 真接了 Counter。
    signals.task_success.send(sender=_FakeTask)  # _FakeTask 是 hashable class
    signals.task_failure.send(sender=_FakeTask)
    signals.task_retry.send(sender=_FakeTask)

    # Celery 在没有注册 task 时,_resolve_queue 走 fallback → "unknown"。
    # 我们的目标是验证 handler 真的连到 signal(inc 计数),不验证 routing。
    assert get_metric_value(
        "lumen_celery_tasks_total", {"queue": "unknown", "status": "success"},
    ) == 1.0
    assert get_metric_value(
        "lumen_celery_tasks_total", {"queue": "unknown", "status": "error"},
    ) == 1.0
    assert get_metric_value(
        "lumen_celery_tasks_total", {"queue": "unknown", "status": "retry"},
    ) == 1.0


class _FakeTask:
    """hashable class 给 Celery signal sender 用。

    Celery signals 用 sender 当 dispatch key,SimpleNamespace instance 是
    unhashable 会抛 TypeError。真实 task 那边 Celery 传 task class 本身
    (可 hash),所以用个 dummy class 即可。
    """

    request = None  # _resolve_queue 走 fallback → "unknown"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
