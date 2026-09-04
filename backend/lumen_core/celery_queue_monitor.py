"""Phase 1 Group B 2.4.5 (2026-09-04):Celery 队列深度后台监控任务。

**做什么**:每 30s 一次,从 Redis ``llen <queue>`` 拉每个 Celery 队列的
当前任务数,更新 ``lumen_celery_queue_depth{queue=...}`` Gauge。

**为什么需要**:
Prometheus 不会自己数 Celery queue —— Redis backend 把任务 push 到 list,
Prometheus 没法看到 list 长度。要么用 celery-exporter sidecar,要么
backend 主动 ``llen`` 上报。后者更轻(无额外容器),且 B2a Grafana Overview
看板"Celery 任务堆积"panel + B2c Alertmanager ``lumen_celery_queue_depth_high``
告警都要这个 metric。

**生命周期**:uvicorn lifespan startup 起 asyncio task,shutdown cancel。
**重试**:Redis 暂时不可用时 ``except`` + log,不抛(避免健康检查挂掉);
下次 tick 自然会重试。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable, List

from lumen_core.metrics import lumen_celery_queue_depth

logger = logging.getLogger(__name__)


# 监控的队列集合 —— 跟 lumen_tasks/celery_app.py task_routes 对齐。
# ``default`` 是兜底 queue,任何无路由 task 都走它(防死信)。
MONITORED_QUEUES: List[str] = [
    "doc_parse",
    "ppt_gen",
    "eval_run",
    "default",
]

# 30s tick —— Prometheus scrape interval 默认 15s,所以两次 tick 至少覆盖一次 scrape。
TICK_INTERVAL_SECONDS = 30.0


async def update_queue_depths(redis_url: str, queues: Iterable[str]) -> None:
    """拉一次所有 queue 深度,更新 gauge。

    用 ``redis.asyncio``(Redis 官方 asyncio client),已在 requirements 里
    (lumen_tasks 用 sync redis,这里另外 import 异步版)。

    Args:
        redis_url: e.g. ``redis://localhost:26380/0``
        queues: 待扫描的 queue 列表

    Raises:
        redis.exceptions.RedisError: Redis 不可达时 —— 调用方应 catch,
            不要让后台 task 死掉。
    """
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url, decode_responses=True)
    try:
        for queue in queues:
            depth = await client.llen(queue)
            lumen_celery_queue_depth.labels(queue=queue).set(depth)
    finally:
        await client.aclose()


async def celery_queue_monitor_loop(redis_url: str, shutdown_event: asyncio.Event) -> None:
    """无限循环 + 30s tick + shutdown 优雅退出。

    Args:
        redis_url: Redis 连接串
        shutdown_event: uvicorn lifespan 传进来的 shutdown 事件,
            设了之后 task 退出 while 循环。
    """
    while not shutdown_event.is_set():
        try:
            await update_queue_depths(redis_url, MONITORED_QUEUES)
        except Exception as e:  # noqa: BLE001 — 任何异常都吞,后台任务不挂
            logger.warning("celery_queue_monitor: update failed (%s); retry in %ss", e, TICK_INTERVAL_SECONDS)
            # 失败时把 gauge 置 -1,看板可以画"未知"色;0 会被误读成"队列空"
            for queue in MONITORED_QUEUES:
                try:
                    lumen_celery_queue_depth.labels(queue=queue).set(-1)
                except Exception:  # noqa: BLE001
                    pass
        # 用 wait_for 让 shutdown_event 触发时立即退出,不必等满 TICK_INTERVAL_SECONDS
        try:
            await asyncio.wait_for(
                shutdown_event.wait(),
                timeout=TICK_INTERVAL_SECONDS,
            )
            # 如果没超时,说明 shutdown 被 set 了
            break
        except asyncio.TimeoutError:
            # 超时 = 正常 tick,继续下一轮
            continue


__all__ = [
    "MONITORED_QUEUES",
    "TICK_INTERVAL_SECONDS",
    "update_queue_depths",
    "celery_queue_monitor_loop",
]
