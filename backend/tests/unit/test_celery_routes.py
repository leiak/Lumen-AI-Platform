"""Phase 1 Group A 1.3 (2026-09-03): Celery 多 worker + task_routes +
trace_signals 单测。

覆盖范围:
- task_routes 决策矩阵(task_name → queue)
- task_default_queue + task_acks_late + task_reject_on_worker_lost 配置
- worker_init 信号装 trace_signals(Phase 0 ship 但未接入,本任务必修)
- trace_signals 端到端:producer 端 before_task_publish 写 headers →
  worker 端 task_prerun 读出 → task_postrun 清 ctx
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from celery.signals import worker_init


# ---------------------------------------------------------------------------
# celery_app 配置
# ---------------------------------------------------------------------------


def _reload_celery_app_module():
    """重新 load celery_app module,确保拿最新 conf(单测间隔离)。"""
    import importlib
    import sys
    # 先踢掉旧 module,避免 stale state
    sys.modules.pop("lumen_tasks.celery_app", None)
    import lumen_tasks.celery_app as ca
    importlib.reload(ca)
    return ca


def test_celery_app_has_task_routes():
    """task_routes 配置包含 3 个 module 命名空间路由。"""
    ca = _reload_celery_app_module()
    routes = ca.celery_app.conf.task_routes
    # routes 是 dict[pattern → dict(queue=...)]
    routes_str = {k: v.get("queue") if isinstance(v, dict) else v for k, v in routes.items()}
    assert routes_str.get("lumen_tasks.document_tasks.*") == "doc_parse"
    assert routes_str.get("lumen_tasks.ppt_task.*") == "ppt_gen"
    assert routes_str.get("lumen_tasks.eval_tasks.*") == "eval_run"


def test_celery_app_default_queue():
    """task_default_queue = "default"(兜底 queue 防止无路由任务死信)。"""
    ca = _reload_celery_app_module()
    assert ca.celery_app.conf.task_default_queue == "default"


def test_celery_app_acks_late_and_reject_on_lost():
    """任务**完成后**才 ack;worker 进程 lost 触发 requeue。"""
    ca = _reload_celery_app_module()
    assert ca.celery_app.conf.task_acks_late is True
    assert ca.celery_app.conf.task_reject_on_worker_lost is True


def test_celery_app_worker_send_events():
    """celery events 可观察(flower / celery events 命令行)。"""
    ca = _reload_celery_app_module()
    assert ca.celery_app.conf.worker_send_task_events is True


def test_celery_app_legacy_config_preserved():
    """Phase 0 ship 的关键 config 没退化。"""
    ca = _reload_celery_app_module()
    conf = ca.celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.accept_content == ["json"]
    assert conf.task_time_limit == 3600
    assert conf.worker_prefetch_multiplier == 1
    assert conf.worker_pool == "threads"
    assert conf.task_track_started is True


# ---------------------------------------------------------------------------
# task_routes 决策(走 Celery router 真实逻辑)
# ---------------------------------------------------------------------------


def test_task_route_document_task_resolves_to_doc_parse():
    """lumen_tasks.document_tasks.process_document → doc_parse queue。"""
    ca = _reload_celery_app_module()
    # Celery 内部用 app.amqp.router.route() 解析 route(签名 options, name)
    # route dict 里的 "queue" 值是 Queue 对象,通过 .name 属性取字符串。
    route = ca.celery_app.amqp.router.route(
        options={},
        name="lumen_tasks.document_tasks.process_document",
        args=(),
        kwargs={},
    )
    # route 可能是 None(default) 或 {"queue": Queue} dict
    assert route is not None
    assert route["queue"].name == "doc_parse"


def test_task_route_ppt_task_resolves_to_ppt_gen():
    """lumen_tasks.ppt_task.generate_ppt_task → ppt_gen queue。"""
    ca = _reload_celery_app_module()
    route = ca.celery_app.amqp.router.route(
        options={},
        name="lumen_tasks.ppt_task.generate_ppt_task",
        args=(),
        kwargs={},
    )
    assert route is not None
    assert route["queue"].name == "ppt_gen"


def test_task_route_eval_task_resolves_to_eval_run():
    """lumen_tasks.eval_tasks.run_eval_task → eval_run queue。"""
    ca = _reload_celery_app_module()
    route = ca.celery_app.amqp.router.route(
        options={},
        name="lumen_tasks.eval_tasks.run_eval_task",
        args=(),
        kwargs={},
    )
    assert route is not None
    assert route["queue"].name == "eval_run"


def test_task_route_unknown_falls_back():
    """未在 routes 的 task → None 或 default queue。"""
    ca = _reload_celery_app_module()
    route = ca.celery_app.amqp.router.route(
        options={},
        name="lumen_tasks.unknown.foo",
        args=(),
        kwargs={},
    )
    # Celery router 命中 default queue 时返 {"queue": Queue(default)}
    if route is not None:
        assert route["queue"].name == "default"


# ---------------------------------------------------------------------------
# worker_init signal: trace_signals 接入
# ---------------------------------------------------------------------------


def test_worker_init_installs_trace_signals():
    """worker_init 信号触发时 install_celery_signals 至少被调 1 次。

    注意:_on_worker_init 通过 @worker_init.connect 注册;reload module 会
    重复注册,send() 触发时所有 callback 都会跑。本测试只断言"被调过"
    (call_count >= 1),不限定次数 —— 多次 reload 的副作用不会污染 prod
    (worker 进程只 import 一次 module)。
    """
    ca = _reload_celery_app_module()

    with patch("lumen_tasks.trace_signals.install_celery_signals") as mock_install:
        # 触发 worker_init 信号
        worker_init.send(sender=ca.celery_app)
        assert mock_install.call_count >= 1, (
            f"expected install_celery_signals to be called at least once, "
            f"got {mock_install.call_count}"
        )


def test_trace_signals_prerun_injects_trace_id():
    """trace_signals.task_prerun_handler 注入 trace_id 到 ctx。"""
    from lumen_core.tracing import get_trace_id
    from lumen_tasks.trace_signals import task_prerun_handler

    # mock task with request.headers containing trace_id
    fake_task = MagicMock()
    fake_task.request.headers = {"X-Trace-Id": "abcd1234deadbeef"}
    fake_task.name = "test.task"

    task_prerun_handler(task_id="t1", task=fake_task)
    assert get_trace_id() == "abcd1234deadbeef"


def test_trace_signals_prerun_clears_when_no_header():
    """无 trace_id header 时清 ctx(避免串下一个 task)。"""
    from lumen_core.tracing import get_trace_id, set_trace_id
    from lumen_tasks.trace_signals import task_prerun_handler

    # 先放一个 trace_id 到 ctx(模拟上一个 task 残留)
    set_trace_id("residual_trace")

    fake_task = MagicMock()
    fake_task.request.headers = {}

    task_prerun_handler(task_id="t1", task=fake_task)
    assert get_trace_id() is None


def test_trace_signals_postrun_clears_ctx():
    """task_postrun_handler 清 ctx。"""
    from lumen_core.tracing import get_trace_id, set_trace_id
    from lumen_tasks.trace_signals import task_postrun_handler

    set_trace_id("doomed_to_clear")
    task_postrun_handler(task_id="t1", task=MagicMock())
    assert get_trace_id() is None


def test_trace_signals_before_publish_injects_header():
    """before_task_publish_handler 把 ctx trace_id 写到 headers。"""
    from lumen_core.tracing import set_trace_id
    from lumen_tasks.trace_signals import before_task_publish_handler

    set_trace_id("propagated_trace_xyz")

    mutable_headers = {}
    before_task_publish_handler(
        sender="test", headers=mutable_headers, body=None,
    )
    assert mutable_headers["X-Trace-Id"] == "propagated_trace_xyz"


def test_trace_signals_install_idempotent():
    """install_celery_signals() 多次调用不抛(Celery connect 默认允许多次)。"""
    from lumen_tasks.trace_signals import install_celery_signals

    # 第一次装 + 第二次装都 OK(Celery signals.connect weak=False 默认
    # 允许多次注册,handler 会被多次调用,但语义幂等因为 set_trace_id
    # 每次都设相同的值)
    install_celery_signals()
    install_celery_signals()  # 不抛异常即可


# ---------------------------------------------------------------------------
# Celery app.amqp + broker 配置完整性
# ---------------------------------------------------------------------------


def test_celery_app_includes_3_task_modules():
    """include 列表声明 3 个 task module(让 worker 启动时 import 它们)。"""
    ca = _reload_celery_app_module()
    # celery_app.conf.include 在新版本 celery 可能在 conf,也可能直接
    # 在 celery_app.include —— 兼容两种取法
    includes = (
        ca.celery_app.conf.include
        if hasattr(ca.celery_app.conf, "include")
        else getattr(ca.celery_app, "include", [])
    )
    assert "lumen_tasks.document_tasks" in includes
    assert "lumen_tasks.ppt_task" in includes
    assert "lumen_tasks.eval_tasks" in includes