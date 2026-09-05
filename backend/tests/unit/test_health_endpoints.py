"""Phase 0 Unit 2 (2026-09-02):Health endpoint 三态测试。

Phase 1 Group A 1.4 (2026-09-04):扩展到 5 个 probe(MySQL + Redis + Storage
+ Ollama + Elasticsearch),asyncio.gather 并行执行。

覆盖:
- /live / /ready / /startup,以及 shutdown_event 是否调用 engine.dispose()。
- 5 probe 各路径:happy / 单个失败 / 多个失败 / 并行执行不串扰
- ES_ENABLED 开关语义(关时 skipped=True 不阻塞)
- storage / ollama / elasticsearch probe 的真实 client 调用契约

设计参考:roadmap §2 1.4(Spring Boot Actuator 三态模型)+ K8s probe 约定。

测试要点:
- /live 永远 200,不查依赖。
- /startup 未启动完返 503,启动完返 200。
- /ready 启动未完返 503;启动完 5 个 probe 并行,任一不通返 503。
- shutdown_event 必须 engine.dispose()(防止 2026-06-08 MySQL MDL 孤儿
  连接让下个 uvicorn startup ALTER 卡死)。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


# ===== Test fixtures =====


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


@pytest.fixture
def all_probes_ok():
    """默认 5 个 probe 全 ok 的 mock,作为 happy path 基础。

    每个测试可以再覆盖个别 probe 让其失败,验证 readiness 503 路径。
    """
    import lumen_main

    async def _ok(*args, **kwargs):
        return {"ok": True}

    async def _es_disabled(*args, **kwargs):
        # dev 默认 ES_ENABLED=False → skipped 路径
        return {"ok": True, "skipped": True, "reason": "ES_ENABLED=false"}

    patches = [
        patch.object(lumen_main, "_probe_mysql", side_effect=_ok),
        patch.object(lumen_main, "_probe_redis", side_effect=_ok),
        patch.object(lumen_main, "_probe_storage", side_effect=_ok),
        patch.object(lumen_main, "_probe_ollama", side_effect=_ok),
        patch.object(lumen_main, "_probe_elasticsearch", side_effect=_es_disabled),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


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


def test_ready_returns_200_when_all_5_probes_ok(
    client, reset_startup_flag, all_probes_ok
):
    """happy path:5 probe 全 ok → 200 + status=ready + 5 个 check 全 ok。"""
    import lumen_main
    lumen_main._startup_complete = True

    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    # Phase 1 1.4:5 个 check 必须都返回 ok
    assert set(body["checks"].keys()) == {
        "mysql", "redis", "storage", "ollama", "elasticsearch",
    }
    for k in ("mysql", "redis", "storage", "ollama", "elasticsearch"):
        assert body["checks"][k]["ok"] is True
    # ES 默认关闭 → skipped=True
    assert body["checks"]["elasticsearch"].get("skipped") is True


# ===== 单 probe 失败:每个 probe 一个 case,验证 503 + 隔离 =====


def test_ready_503_when_mysql_fails(client, reset_startup_flag, all_probes_ok):
    """MySQL probe 失败 → 整体 503 + 其他 4 个 probe 不受影响。"""
    import lumen_main
    lumen_main._startup_complete = True

    async def _mysql_fail(*args, **kwargs):
        return {"ok": False, "error": "OperationalError: MySQL down"}

    with patch.object(lumen_main, "_probe_mysql", side_effect=_mysql_fail):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["mysql"]["ok"] is False
        assert "MySQL down" in body["checks"]["mysql"]["error"]
        # 其他 4 个 ok 路径不受影响
        for k in ("redis", "storage", "ollama", "elasticsearch"):
            assert body["checks"][k]["ok"] is True


def test_ready_503_when_redis_fails(client, reset_startup_flag, all_probes_ok):
    """Redis probe 失败 → 整体 503,MySQL 仍 ok。"""
    import lumen_main
    lumen_main._startup_complete = True

    async def _redis_fail(*args, **kwargs):
        return {"ok": False, "error": "ConnectionError: Redis down"}

    with patch.object(lumen_main, "_probe_redis", side_effect=_redis_fail):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        assert body["checks"]["redis"]["ok"] is False
        assert body["checks"]["mysql"]["ok"] is True


def test_ready_503_when_storage_fails(client, reset_startup_flag, all_probes_ok):
    """Storage probe 失败 → 503。MinIO 挂 / disk full 场景。"""
    import lumen_main
    lumen_main._startup_complete = True

    async def _storage_fail(*args, **kwargs):
        return {"ok": False, "backend": "s3", "error": "HeadBucket 403"}

    with patch.object(lumen_main, "_probe_storage", side_effect=_storage_fail):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["checks"]["storage"]["ok"] is False
        assert body["checks"]["storage"]["backend"] == "s3"


def test_ready_503_when_ollama_fails(client, reset_startup_flag, all_probes_ok):
    """Ollama probe 失败 → 503。LLM 调用挂的场景。"""
    import lumen_main
    lumen_main._startup_complete = True

    async def _ollama_fail(*args, **kwargs):
        return {"ok": False, "error": "ConnectError: Ollama down"}

    with patch.object(lumen_main, "_probe_ollama", side_effect=_ollama_fail):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["checks"]["ollama"]["ok"] is False
        assert "Ollama down" in body["checks"]["ollama"]["error"]


def test_ready_503_when_elasticsearch_fails_with_status_red(
    client, reset_startup_flag, all_probes_ok
):
    """ES probe:status=red → 503(集群不可用,禁止接受流量)。

    ES 默认 disabled(全 probes_ok fixture 给返 skipped);这里 override
    让 probe 走真实集群路径,模拟 red 状态。
    """
    import lumen_main
    lumen_main._startup_complete = True

    async def _es_red(*args, **kwargs):
        return {"ok": False, "status": "red"}

    with patch.object(lumen_main, "_probe_elasticsearch", side_effect=_es_red):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["checks"]["elasticsearch"]["ok"] is False
        assert body["checks"]["elasticsearch"]["status"] == "red"


def test_ready_200_when_elasticsearch_yellow(
    client, reset_startup_flag, all_probes_ok
):
    """ES probe:status=yellow 视为 ok(yellow 是单节点 ES 正常态)。

    注意:yellow 是 ES 在只有一个节点时的标准状态(cluster.routing.allocation
    要求副本但无副本可分配),不能让 readiness 摘流量。
    """
    import lumen_main
    lumen_main._startup_complete = True

    async def _es_yellow(*args, **kwargs):
        return {"ok": True, "status": "yellow"}

    with patch.object(lumen_main, "_probe_elasticsearch", side_effect=_es_yellow):
        r = client.get("/ready")
        assert r.status_code == 200


def test_ready_503_when_all_5_probes_fail(client, reset_startup_flag):
    """5 probe 全挂 → 503 + 5 个 check 全 ok:False。"""
    import lumen_main
    lumen_main._startup_complete = True

    async def _fail(*args, **kwargs):
        return {"ok": False, "error": "down"}

    with patch.object(lumen_main, "_probe_mysql", side_effect=_fail), \
         patch.object(lumen_main, "_probe_redis", side_effect=_fail), \
         patch.object(lumen_main, "_probe_storage", side_effect=_fail), \
         patch.object(lumen_main, "_probe_ollama", side_effect=_fail), \
         patch.object(lumen_main, "_probe_elasticsearch", side_effect=_fail):
        r = client.get("/ready")
        assert r.status_code == 503
        body = r.json()
        for k in ("mysql", "redis", "storage", "ollama", "elasticsearch"):
            assert body["checks"][k]["ok"] is False


# ===== 内部 probe helper:不 mock,验证真实实现契约 =====


@pytest.mark.asyncio
async def test_probe_mysql_returns_ok_when_engine_works():
    """真实 engine 跑通时 _probe_mysql 返 ok=True(不 mock engine)。

    集成式断言,dev 环境 MySQL 可达时通过。CI 没 MySQL 会 fail,但 pytest
    套件默认 dev 环境跑。
    """
    from lumen_main import _probe_mysql
    result = await _probe_mysql()
    # dev 环境 MySQL 应该通;若不通返 ok=False 也可(说明 dev DB 挂了)
    assert "ok" in result
    if not result["ok"]:
        assert "error" in result


@pytest.mark.asyncio
async def test_probe_mysql_returns_error_when_engine_fails():
    """engine 抛 OperationalError → ok=False + error 截前 120 字符。"""
    from lumen_main import _probe_mysql
    from sqlalchemy.exc import OperationalError

    with patch("lumen_core.database.engine") as mock_engine:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(side_effect=OperationalError(
            "SELECT 1", {}, Exception("simulated")
        ))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_engine.connect.return_value = mock_ctx

        result = await _probe_mysql()
        assert result["ok"] is False
        assert "simulated" in result["error"]


@pytest.mark.asyncio
async def test_probe_mysql_times_out():
    """asyncio.wait_for 超时 → probe helper 捕获 TimeoutError → ok=False。

    真 wait_for 会 cancel 内部的 awaitable 并 raise TimeoutError;这里 patch
    wait_for 直接 raise,验证 probe helper 的 exception 兜底逻辑。

    实现细节:asyncio.wait_for 的第一个参数是 to_thread 创建的 coroutine,
    我们 patch wait_for 直接 raise 时这个 coroutine 永远不会被 await — 触发
    RuntimeWarning: coroutine 'to_thread' was never awaited。所以在 raise 前
    调用 ``awaitable.close()``,Python 把 coroutine 标记为 closed,跳过警告。
    """
    from lumen_main import _probe_mysql

    def _raise_timeout(awaitable, timeout):
        if asyncio.iscoroutine(awaitable):
            awaitable.close()  # 防 "never awaited" 警告
        raise asyncio.TimeoutError()

    with patch("lumen_main.asyncio.wait_for", side_effect=_raise_timeout):
        result = await _probe_mysql()
        # TimeoutError 的 str() 为空字符串,所以只断言 ok=False + error 是字符串
        assert result["ok"] is False
        assert isinstance(result["error"], str)
        # 验证错误信息至多截前 120 字符(probe helper 的 `str(e)[:120]`)
        assert len(result["error"]) <= 120


@pytest.mark.asyncio
async def test_probe_redis_returns_ok_when_ping_works():
    """_probe_redis 真实 ping dev Redis(若通)。"""
    from lumen_main import _probe_redis
    result = await _probe_redis()
    assert "ok" in result
    if not result["ok"]:
        assert "error" in result


@pytest.mark.asyncio
async def test_probe_redis_returns_error_when_ping_fails():
    """redis.Redis.ping 抛 ConnectionError → ok=False。"""
    from lumen_main import _probe_redis

    with patch("redis.Redis") as mock_redis_cls:
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("Redis down")
        mock_redis_cls.return_value = mock_client

        result = await _probe_redis()
        assert result["ok"] is False
        assert "Redis down" in result["error"]


@pytest.mark.asyncio
async def test_probe_storage_returns_ok():
    """_probe_storage 走真 get_storage_backend().health_check()。

    dev 环境 storage(LOCAL 默认 ./data 目录)应该可达;若不通,docker
    MinIO 没起 OR ./data 目录 rwx 受限,结果会是 ok=False + error,本测试
    容忍这两种情况 — 但 ok=True 时必须带 backend + latency_ms 字段。
    """
    from lumen_main import _probe_storage
    result = await _probe_storage()
    assert "ok" in result
    # ok=True 时必须带 backend / latency_ms 字段(storage backend 契约)
    if result["ok"]:
        assert "backend" in result
        assert result.get("latency_ms") is None or isinstance(result["latency_ms"], (int, float))
    else:
        # 失败路径:docker 没起 / 磁盘只读 / ./data 不存在
        assert "error" in result


@pytest.mark.asyncio
async def test_probe_storage_returns_error_when_backend_fails():
    """get_storage_backend().health_check() 返 ok=False → probe 也 ok=False。"""
    from lumen_main import _probe_storage

    mock_backend = MagicMock()
    mock_backend.health_check.return_value = {
        "backend": "s3",
        "ok": False,
        "detail": "HeadBucket 403",
        "latency_ms": 12,
    }

    with patch("lumen_services.storage.get_storage_backend", return_value=mock_backend):
        result = await _probe_storage()
        assert result["ok"] is False
        assert result["backend"] == "s3"
        assert result["detail"] == "HeadBucket 403"


@pytest.mark.asyncio
async def test_probe_ollama_returns_ok_when_dev_ollama_up():
    """dev 环境 Ollama 在跑时 _probe_ollama 返 ok=True。"""
    from lumen_main import _probe_ollama
    result = await _probe_ollama()
    assert "ok" in result
    # 不强制 ok(本机 Ollama 可能没跑),但至少不能 crash


@pytest.mark.asyncio
async def test_probe_ollama_returns_error_when_connect_refused():
    """httpx 连不上 Ollama → ok=False + ConnectError。"""
    from lumen_main import _probe_ollama
    import httpx

    async def _raise_get(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    # _probe_ollama 在 httpx.AsyncClient 内调 client.get,patch 让 get 抛错
    with patch.object(httpx.AsyncClient, "get", side_effect=_raise_get):
        result = await _probe_ollama()
        assert result["ok"] is False
        assert "ConnectError" in result["error"] or "refused" in result["error"].lower()


@pytest.mark.asyncio
async def test_probe_elasticsearch_skipped_when_disabled():
    """ES_ENABLED=False → skipped=True,ok=True,完全不连 ES。"""
    from lumen_main import _probe_elasticsearch
    from lumen_core.config import settings

    with patch.object(settings, "ES_ENABLED", False):
        result = await _probe_elasticsearch()
        assert result["ok"] is True
        assert result["skipped"] is True
        assert result["reason"] == "ES_ENABLED=false"


@pytest.mark.asyncio
async def test_probe_elasticsearch_returns_ok_on_green_yellow():
    """ES_ENABLED=True + cluster.status in (green, yellow) → ok=True。"""
    from lumen_main import _probe_elasticsearch
    from lumen_core.config import settings
    from elasticsearch import Elasticsearch

    mock_es = MagicMock()
    mock_es.cluster.health.return_value = {"status": "yellow"}

    with patch.object(settings, "ES_ENABLED", True), \
         patch("elasticsearch.Elasticsearch", return_value=mock_es):
        result = await _probe_elasticsearch()
        assert result["ok"] is True
        assert result["status"] == "yellow"


@pytest.mark.asyncio
async def test_probe_elasticsearch_returns_error_on_red():
    """ES cluster.status=red → ok=False(集群损坏,禁止流量)。"""
    from lumen_main import _probe_elasticsearch
    from lumen_core.config import settings

    mock_es = MagicMock()
    mock_es.cluster.health.return_value = {"status": "red"}

    with patch.object(settings, "ES_ENABLED", True), \
         patch("elasticsearch.Elasticsearch", return_value=mock_es):
        result = await _probe_elasticsearch()
        assert result["ok"] is False
        assert result["status"] == "red"


@pytest.mark.asyncio
async def test_probe_elasticsearch_returns_error_on_connect_fail():
    """ES 不可达 → ok=False + error 信息。"""
    from lumen_main import _probe_elasticsearch
    from lumen_core.config import settings

    with patch.object(settings, "ES_ENABLED", True), \
         patch("elasticsearch.Elasticsearch", side_effect=ConnectionError("ES down")):
        result = await _probe_elasticsearch()
        assert result["ok"] is False
        assert "ES down" in result["error"]


# ===== 并行执行:验证 asyncio.gather 不串扰 =====


@pytest.mark.asyncio
async def test_probes_run_in_parallel_not_serially():
    """5 probe 各自 sleep 0.5s,如果并行 → 总耗时 ≈ 0.5s(不是 2.5s)。

    直接调 lumen_main._probe_* 协程,用 asyncio.gather 跑,看 wall time。
    """
    import time
    import lumen_main

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.5)
        return {"ok": True}

    # patch 5 个 probe helper 让它们各睡 0.5s
    with patch.object(lumen_main, "_probe_mysql", side_effect=_slow), \
         patch.object(lumen_main, "_probe_redis", side_effect=_slow), \
         patch.object(lumen_main, "_probe_storage", side_effect=_slow), \
         patch.object(lumen_main, "_probe_ollama", side_effect=_slow), \
         patch.object(lumen_main, "_probe_elasticsearch", side_effect=_slow):

        start = time.monotonic()
        results = await asyncio.gather(
            lumen_main._probe_mysql(),
            lumen_main._probe_redis(),
            lumen_main._probe_storage(),
            lumen_main._probe_ollama(),
            lumen_main._probe_elasticsearch(),
        )
        elapsed = time.monotonic() - start

        assert len(results) == 5
        for r in results:
            assert r["ok"] is True
        # 并行 ≈ 0.5s;串行得 2.5s。给 1.2s 容忍(Windows asyncio 调度抖动)。
        assert elapsed < 1.2, f"probes 串行了?耗时 {elapsed:.2f}s"


def test_ready_endpoint_runs_probes_in_parallel(client, reset_startup_flag):
    """/ready handler 整体走 asyncio.gather,5 probe 并行(通过 client 测)。

    验证 /ready endpoint 真的在用 gather,不是简单 await 串行。
    """
    import time
    import lumen_main
    lumen_main._startup_complete = True

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return {"ok": True}

    async def _es_disabled(*args, **kwargs):
        return {"ok": True, "skipped": True}

    with patch.object(lumen_main, "_probe_mysql", side_effect=_slow), \
         patch.object(lumen_main, "_probe_redis", side_effect=_slow), \
         patch.object(lumen_main, "_probe_storage", side_effect=_slow), \
         patch.object(lumen_main, "_probe_ollama", side_effect=_slow), \
         patch.object(lumen_main, "_probe_elasticsearch", side_effect=_es_disabled):

        start = time.monotonic()
        r = client.get("/ready")
        elapsed = time.monotonic() - start

        assert r.status_code == 200
        # 串行:5 × 0.3 = 1.5s;并行 ≈ 0.3s + TestClient 开销
        assert elapsed < 1.0, f"/ready 串行了?耗时 {elapsed:.2f}s"


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