"""Phase 0 Unit 2 (2026-09-02):Health endpoint 三态测试。

覆盖 /live / /ready / /startup,以及 shutdown_event 是否调用 engine.dispose()。

设计参考:roadmap §2 1.4(Spring Boot Actuator 三态模型)+ K8s probe 约定。

测试要点:
- /live 永远 200,不查依赖。
- /startup 未启动完返 503,启动完返 200。
- /ready 启动未完返 503;启动完查 MySQL + Redis,任一不通返 503。
- shutdown_event 必须 engine.dispose()(防止 2026-06-08 MySQL MDL 孤儿
  连接让下个 uvicorn startup ALTER 卡死)。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def client():
    """FastAPI TestClient — 不跑 startup_event(只测试 endpoint 行为)。

    TestClient 默认会 trigger startup_event,这会跑 40+ ensure_* 迁移
    跟 dev DB。Phase 0 健康检查测试用 lifespan="off" 跳过 startup,
    直接测 endpoint 逻辑。
    """
    from fastapi.testclient import TestClient
    from lumen_main import app

    # TestClient(app) 会跑 lifespan(events);对 health endpoints 我们只想
    # 验证路由 + handler 行为,不依赖真实 migration 完成。手动 reset
    # _startup_complete 来模拟不同启动期。
    return TestClient(app)


@pytest.fixture
def reset_startup_flag():
    """确保每个 test 后 _startup_complete 回到默认 False,免污染。"""
    import lumen_main
    original = lumen_main._startup_complete
    yield
    lumen_main._startup_complete = original


# ===== /live:永远 200 =====


def test_live_returns_200_even_when_startup_incomplete(client, reset_startup_flag):
    """livenessProbe 用,/live 必须跟 dependency 健康度解耦。"""
    import lumen_main
    lumen_main._startup_complete = False  # 模拟 startup 期

    r = client.get("/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "alive"


def test_live_returns_200_after_startup(client, reset_startup_flag):
    import lumen_main
    lumen_main._startup_complete = True

    r = client.get("/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


# ===== /startup:启动期 503,完成 200 =====


def test_startup_returns_503_when_not_complete(client, reset_startup_flag):
    """K8s startupProbe:启动期返 503,K8s 不要急着 readinessProbe。"""
    import lumen_main
    lumen_main._startup_complete = False

    r = client.get("/startup")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "starting"
    assert body["migrations_complete"] is False


def test_startup_returns_200_when_complete(client, reset_startup_flag):
    """启动完成 → 200,K8s 切到 readinessProbe 阶段。"""
    import lumen_main
    lumen_main._startup_complete = True

    r = client.get("/startup")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


# ===== /ready:启动未完 503;启动完查依赖,任一不通 503 =====


def test_ready_returns_503_when_startup_incomplete(client, reset_startup_flag):
    """避免 K8s 在 startup 期间就把流量打进来。"""
    import lumen_main
    lumen_main._startup_complete = False

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "starting"


def test_ready_returns_200_when_all_deps_ok(client, reset_startup_flag):
    """happy path:MySQL 通 + Redis 通 → 200 + status=ready。"""
    import lumen_main
    lumen_main._startup_complete = True

    # dev 环境真 MySQL/Redis 应该都通(本测试依赖 backend/.env 配置)
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["mysql"]["ok"] is True
    assert body["checks"]["redis"]["ok"] is True


def test_ready_returns_503_when_mysql_fails(client, reset_startup_flag):
    """MySQL 挂 → readiness 503,K8s 摘流量。"""
    import lumen_main
    lumen_main._startup_complete = True

    # patch engine.connect 抛 OperationalError
    from sqlalchemy.exc import OperationalError
    with patch("lumen_core.database.engine") as mock_engine:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=OperationalError(
            "SELECT 1", {}, Exception("MySQL down")
        ))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_ctx

        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["mysql"]["ok"] is False
        # Redis 不受影响
        assert body["checks"]["redis"]["ok"] is True


def test_ready_returns_503_when_redis_fails(client, reset_startup_flag):
    """Redis 挂 → readiness 503。"""
    import lumen_main
    lumen_main._startup_complete = True

    with patch("redis.Redis") as mock_redis_cls:
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("Redis down")
        mock_redis_cls.return_value = mock_client

        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["redis"]["ok"] is False
        # MySQL 不受影响(走真 engine)
        assert body["checks"]["mysql"]["ok"] is True


def test_ready_returns_503_when_both_fail(client, reset_startup_flag):
    """MySQL + Redis 同时挂 → 503 + 两条都报失败。"""
    import lumen_main
    lumen_main._startup_complete = True

    from sqlalchemy.exc import OperationalError
    with patch("lumen_core.database.engine") as mock_engine:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=OperationalError(
            "SELECT 1", {}, Exception("MySQL down")
        ))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_ctx

        with patch("redis.Redis") as mock_redis_cls:
            mock_client = MagicMock()
            mock_client.ping.side_effect = ConnectionError("Redis down")
            mock_redis_cls.return_value = mock_client

            r = client.get("/ready")
            assert r.status_code == 503
            body = r.json()
            assert body["checks"]["mysql"]["ok"] is False
            assert body["checks"]["redis"]["ok"] is False


# ===== shutdown_event:必须 engine.dispose() =====
#
# Phase 1 Group A 1.1 (2026-09-03):shutdown_event 函数被整合进 _lifespan
# async context manager 的 finally 块,通过 _shutdown_cleanup(starter=...)
# helper 单独可测。整 lifespan 太重(40+ ensure_* + DB 迁移),不能像
# shutdown_event() 那样直接 await 验证。


@pytest.mark.asyncio
async def test_shutdown_event_disposes_engine():
    """防止 2026-06-08 复现的 MySQL MDL 孤儿连接场景。

    lifespan finally 块(_shutdown_cleanup)必须调 engine.dispose() 让
    SQLAlchemy QueuePool 关闭所有 checked-in 连接;否则 taskkill /F 后
    MySQL Sleep 连接仍持 MDL,下个 uvicorn startup ALTER 卡死(2026-06-08
    第 5 次重启踩到)。
    """
    from lumen_main import _shutdown_cleanup

    with patch("lumen_core.database.engine") as mock_engine:
        with patch("lumen_services.workflow_scheduler.get_scheduler_service") as mock_get:
            mock_svc = MagicMock()
            mock_get.return_value = mock_svc

            await _shutdown_cleanup(started_scheduler=True)

            mock_svc.stop.assert_called_once()
            mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_cleanup_no_scheduler_still_disposes():
    """多 worker 模式 rank!=0 worker 启 lifespan 但不启 scheduler →
    退出时 stop() 不该被调(否则空 stop 抛错),但 dispose 必须触发。
    """
    from lumen_main import _shutdown_cleanup

    with patch("lumen_core.database.engine") as mock_engine:
        with patch("lumen_services.workflow_scheduler.get_scheduler_service") as mock_get:
            mock_svc = MagicMock()
            mock_get.return_value = mock_svc

            await _shutdown_cleanup(started_scheduler=False)

            mock_svc.stop.assert_not_called()
            mock_engine.dispose.assert_called_once()


# ===== 不破坏旧 /health endpoint =====


def test_legacy_health_still_works(client):
    """Phase 0 不破坏裸 /health(虽然前端没用,但 K8s/部署脚本可能依赖)。"""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}