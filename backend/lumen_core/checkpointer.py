"""Lifespan-managed singleton PostgresSaver for LangGraph checkpoints.

Lumen TeamRunner 用 LangGraph 官方 PostgresSaver 持久化每条 team
conversation 的 graph state,支持 HiTL resume + 时间旅行。

Spec 决策见 docs-internal/superpowers/specs/2026-09-29-multi-agent-team-upgrade-design.md §4.1。
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from lumen_core.config import settings

logger = logging.getLogger(__name__)


class CheckpointerService:
    """单例 + health check + lifespan hook 集成。

    长生命周期 ConnectionPool(psycopg_pool)+ PostgresSaver 复用该 pool,
    每次 save 从 pool 取一条连接、用完归还。lifespan startup 调 setup() 建
    LangGraph 表,shutdown 调 close() 关 pool 释放连接。
    """

    _saver: Optional[PostgresSaver] = None
    _pool: Optional[ConnectionPool] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> PostgresSaver:
        """懒初始化,首次调用建 ConnectionPool + PostgresSaver,后续返回单例。

        POSTGRES_URL 为空时抛 RuntimeError(让 lifespan startup 显式失败,
        比 PostgresSaver 内部静默 AttributeError 更清楚)。
        """
        if not settings.POSTGRES_URL:
            raise RuntimeError(
                "POSTGRES_URL is empty — check LANGGRAPH_CHECKPOINT_ENABLED flag "
                "or .env / .env.docker.example configuration"
            )
        if cls._saver is None:
            with cls._lock:
                if cls._saver is None:
                    # 长生命周期 ConnectionPool,单条连接获取即可完成每次 save。
                    # autocommit=True 配 PostgresSaver 的语义(LangGraph 自己控事务)。
                    cls._pool = ConnectionPool(
                        settings.POSTGRES_URL,
                        min_size=1,
                        max_size=10,
                        kwargs={"autocommit": True},
                    )
                    cls._saver = PostgresSaver(cls._pool)
                    logger.info(
                        "PostgresSaver initialized url=%s pool_min=1 pool_max=10",
                        settings.POSTGRES_URL,
                    )
        return cls._saver

    @classmethod
    def health(cls) -> bool:
        """健康检查 — 调 get_next_version() 触发一次 PG 往返,失败返 False。"""
        try:
            cls.get().get_next_version(None, None)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("CheckpointerService health check failed: %s", exc)
            return False

    @classmethod
    def setup(cls) -> None:
        """lifespan startup hook — 建 checkpoints / checkpoint_writes / checkpoint_blobs 三表。"""
        try:
            cls.get().setup()
            logger.info("PostgresSaver.setup() done — LangGraph tables created")
        except Exception as exc:  # noqa: BLE001
            logger.error("PostgresSaver.setup() failed: %s", exc)
            raise

    @classmethod
    def close(cls) -> None:
        """lifespan shutdown hook — 关连接池释放所有 in-flight 连接。"""
        if cls._pool is not None:
            try:
                # pool.close() 等所有 in-flight 连接归还再返回,graceful 关闭。
                cls._pool.close()
            except Exception:  # noqa: BLE001
                pass
            cls._pool = None
            cls._saver = None
