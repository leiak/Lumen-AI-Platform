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


def _redact_url(url: str) -> str:
    """把 DSN 里的密码段替换成 ***,保留 host:port/db 用于诊断。

    PostgresSaver 初始化日志会 print 完整 URL,含明文密码;这个 helper
    把 ``scheme://user:pass@host:port/db`` 改成 ``scheme://user:***@...``,
    让 log 可贴到 issue / Slack 不泄密。
    """
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    userinfo, hostpart = rest.split("@", 1)
    if ":" in userinfo:
        user, _ = userinfo.split(":", 1)
        return f"{scheme}://{user}:***@{hostpart}"
    return url


class CheckpointerService:
    """Lifespan-managed singleton PostgresSaver wrapper with health check.

    单例 + health check + lifespan hook 集成。长生命周期 ConnectionPool
    (psycopg_pool)+ PostgresSaver 复用该 pool,每次 save 从 pool 取一条连接、
    用完归还。lifespan startup 调 setup() 建 LangGraph 表,shutdown 调 close()
    关 pool 释放连接。
    """

    _saver: Optional[PostgresSaver] = None
    _pool: Optional[ConnectionPool] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> PostgresSaver:
        """Lazily build ConnectionPool + PostgresSaver and return the singleton saver.

        懒初始化,首次调用建 ConnectionPool + PostgresSaver,后续返回单例。
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
                    # 注意:不要传 kwargs={"autocommit": True} —— PostgresSaver
                    # 一次 save 会写 checkpoints / checkpoint_writes /
                    # checkpoint_blobs 三张表的多条 INSERT,需要单事务保证
                    # 原子性;开了 autocommit 会让每条 INSERT 各自提交,中途
                    # 连接被 recycle 可能留下半写状态。
                    pool = ConnectionPool(
                        settings.POSTGRES_URL,
                        min_size=settings.CHECKPOINTER_POOL_MIN_SIZE,
                        max_size=settings.CHECKPOINTER_POOL_MAX_SIZE,
                    )
                    try:
                        # 先把 pool 挂到 cls,再 PostgresSaver(pool);这样若
                        # PostgresSaver.__init__ 抛错,pool 还有引用可走
                        # finally 显式 close,不会泄漏 socket / fd。
                        cls._pool = pool
                        cls._saver = PostgresSaver(pool)
                    except Exception:
                        # 清理半构造状态,不让下次 get() 看到 stale 引用
                        cls._pool = None
                        cls._saver = None
                        try:
                            pool.close()
                        except Exception:  # noqa: BLE001
                            pass
                        raise
                    logger.info(
                        "PostgresSaver initialized url=%s pool_min=%d pool_max=%d",
                        _redact_url(settings.POSTGRES_URL),
                        cls._pool.min_size,
                        cls._pool.max_size,
                    )
        return cls._saver

    @classmethod
    def health(cls) -> bool:
        """真打 PG 一次 SELECT 1,验证连接 + 服务可达;失败返 False,不抛。

        早期实现用 ``get_next_version()``,但那是纯算术,不读 PG —— PG 真
        down 时 health 永远 True。改用 pool.connection() 拿一条连接 round-trip
        ``SELECT 1``;能拿到 ``(1,)`` 说明 TCP 通 + auth 通 + 服务在跑。
        """
        try:
            if cls._pool is None:
                # Pool 还没建(首次 health 早于 get()),按 get() 同路径初始化
                cls.get()
            with cls._pool.connection() as conn:  # type: ignore[union-attr]
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return cur.fetchone() == (1,)
        except Exception as exc:  # noqa: BLE001
            logger.warning("CheckpointerService.health check failed: %s", exc)
            return False

    @classmethod
    def setup(cls) -> None:
        """Create LangGraph checkpoint tables via PostgresSaver.setup() (idempotent).

        lifespan startup hook — 建 checkpoints / checkpoint_writes /
        checkpoint_blobs 三表。失败时主动 close 释放半构造 pool,让下次
        startup 重试是干净的初始化(而不是拿到 stale state 反复失败)。
        """
        try:
            cls.get().setup()
            logger.info("PostgresSaver.setup() done — LangGraph tables created")
        except Exception as exc:  # noqa: BLE001
            logger.error("PostgresSaver.setup() failed: %s", exc)
            cls.close()
            raise

    @classmethod
    def close(cls) -> None:
        """Close the ConnectionPool and release all in-flight connections.

        lifespan shutdown hook — 关连接池释放所有 in-flight 连接。失败时
        改记 warning,不再静默吞(便于排查 PG 在 shutdown 时 hang 的根因)。
        """
        if cls._pool is not None:
            try:
                # pool.close() 等所有 in-flight 连接归还再返回,graceful 关闭。
                cls._pool.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "CheckpointerService.close() pool close failed: %s", exc
                )
            cls._pool = None
        cls._saver = None