"""Phase 1 Group B 2.4.5 (2026-09-04):Celery 队列深度监控任务测试。

覆盖:
- lumen_celery_queue_depth Gauge 类型 / labels
- update_queue_depths() 拉 llen 并写 Gauge(用 mock redis.asyncio)
- celery_queue_monitor_loop() tick 一次后等,shutdown Event 触发立即退出
- redis 不可达时不抛,改把 gauge 置 -1(看板可画"未知"色)
"""
from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lumen_core.celery_queue_monitor import (
    MONITORED_QUEUES,
    TICK_INTERVAL_SECONDS,
    celery_queue_monitor_loop,
    update_queue_depths,
)
from lumen_core.metrics import lumen_celery_queue_depth, reset_metrics_for_test


# ===== fixture =====


@pytest.fixture(autouse=True)
def _reset_metrics():
    """每个 test 完 reset Gauge 避免 sample 串。"""
    yield
    reset_metrics_for_test()


# ===== Gauge sanity =====


def test_lumen_celery_queue_depth_is_gauge():
    """lumen_celery_queue_depth 是 Gauge,labels=[queue]。"""
    assert lumen_celery_queue_depth._type == "gauge"
    assert set(lumen_celery_queue_depth._labelnames) == {"queue"}


def test_monitored_queues_list():
    """MONITORED_QUEUES 包含 4 个核心 queue(跟 celery_app task_routes 对齐)。"""
    assert "doc_parse" in MONITORED_QUEUES
    assert "ppt_gen" in MONITORED_QUEUES
    assert "eval_run" in MONITORED_QUEUES
    assert "default" in MONITORED_QUEUES


def test_tick_interval_is_30s():
    """30s tick — 至少覆盖一次 Prometheus 15s scrape。"""
    assert TICK_INTERVAL_SECONDS == 30.0


# ===== update_queue_depths =====


@pytest.mark.asyncio
async def test_update_queue_depths_calls_llen_for_each_queue():
    """update_queue_depths 对每个 queue 调一次 llen 并写 gauge。"""
    # mock redis.asyncio.from_url 返一个 client,llen 返固定深度
    mock_client = AsyncMock()
    mock_client.llen = AsyncMock(side_effect=lambda q: 5 if q == "doc_parse" else 0)
    mock_client.aclose = AsyncMock()

    # aioredis 是 update_queue_depths 内部 local import,所以 patch "redis.asyncio.from_url" 即可
    with patch(
        "redis.asyncio.from_url",
        return_value=mock_client,
    ):
        await update_queue_depths("redis://localhost:26380/0", ["doc_parse", "default"])

    # doc_parse → 5
    assert lumen_celery_queue_depth.labels(queue="doc_parse")._value.get() == 5
    # default → 0
    assert lumen_celery_queue_depth.labels(queue="default")._value.get() == 0
    # 未传入的 queue(ppt_gen)mock_client.llen 根本不应被调
    called_queues = [c.args[0] for c in mock_client.llen.await_args_list]
    assert "ppt_gen" not in called_queues
    assert "eval_run" not in called_queues
    # 确认 doc_parse / default 被问过
    assert "doc_parse" in called_queues
    assert "default" in called_queues

    # client.aclose 必被调
    mock_client.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_update_queue_depths_closes_client_on_error():
    """llen 抛错时仍 aclose 客户端(避免连接泄漏)。"""
    mock_client = AsyncMock()
    mock_client.llen = AsyncMock(side_effect=ConnectionError("redis down"))
    mock_client.aclose = AsyncMock()

    # aioredis 是 update_queue_depths 内部 local import,patch 真实模块路径
    with patch(
        "redis.asyncio.from_url",
        return_value=mock_client,
    ):
        with pytest.raises(ConnectionError):
            await update_queue_depths("redis://localhost:26380/0", ["doc_parse"])

    # 即使抛错也 aclose
    mock_client.aclose.assert_called_once()


# ===== celery_queue_monitor_loop =====


@pytest.mark.asyncio
async def test_monitor_loop_ticks_then_exits_on_shutdown():
    """loop 跑一次 update 后 wait_for shutdown_event,触发即退出。"""
    # mock update_queue_depths 立刻返(不连 Redis)
    update_mock = AsyncMock()

    shutdown = asyncio.Event()
    with patch(
        "lumen_core.celery_queue_monitor.update_queue_depths",
        update_mock,
    ):
        # 启动 task → 100ms 后 set shutdown
        task = asyncio.create_task(
            celery_queue_monitor_loop("redis://x", shutdown)
        )
        await asyncio.sleep(0.1)  # 让 loop 至少跑一次 update
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)

    # 至少被调 1 次
    assert update_mock.await_count >= 1


@pytest.mark.asyncio
async def test_monitor_loop_sets_gauge_minus_one_on_redis_error():
    """Redis 不可达时 update_queue_depths 抛错,loop 捕获后把 gauge 置 -1。"""
    shutdown = asyncio.Event()

    async def fake_update(*args, **kwargs):
        # 模拟 redis 抛错,然后模拟 loop 的 except 分支
        raise ConnectionError("redis down")

    with patch(
        "lumen_core.celery_queue_monitor.update_queue_depths",
        fake_update,
    ):
        task = asyncio.create_task(
            celery_queue_monitor_loop("redis://x", shutdown)
        )
        await asyncio.sleep(0.1)  # 让 loop 跑一次失败
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)

    # 所有 MONITORED_QUEUES gauge 应被置 -1
    for q in MONITORED_QUEUES:
        # set -1 后 _value.get() 是 -1(不是 None,因为 Gauge 初始化时 set 0 后改 -1)
        assert lumen_celery_queue_depth.labels(queue=q)._value.get() == -1


@pytest.mark.asyncio
async def test_monitor_loop_uses_wait_for_so_shutdown_is_prompt():
    """shutdown 触发后应在 ~0 内退出,不必等满 30s tick。"""
    update_mock = AsyncMock()
    shutdown = asyncio.Event()

    with patch(
        "lumen_core.celery_queue_monitor.update_queue_depths",
        update_mock,
    ):
        task = asyncio.create_task(
            celery_queue_monitor_loop("redis://x", shutdown)
        )
        # 等 50ms 模拟"还没到 tick"状态
        await asyncio.sleep(0.05)
        shutdown.set()
        # 如果 wait_for 不生效,这个 await 会等 30s —— 应该远小于 1s
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(task, timeout=2.0)
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 1.0, f"loop took {elapsed}s to exit after shutdown, expected < 1s"
