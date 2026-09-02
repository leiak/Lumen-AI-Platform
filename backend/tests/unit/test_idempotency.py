"""Phase 0 Unit 4.3.1 (2026-09-02):Idempotency-Key 中间件测试。

覆盖:
- POST 带 Idempotency-Key → 第一次处理 + 缓存 response
- 第二次同 key 重复请求 → 返缓存(即使 body 不同)
- POST 不带 Idempotency-Key → 放行,不缓存
- GET / PUT 不挂中间件
- 5 秒内同 key in-progress → 409
- 超过 5 秒 stale → 重新占位 + 正常处理
- 4xx / 5xx response 不缓存(允许客户端重试)
- 非 JSON 2xx response(纯文本)不缓存
- Redis 挂时 fail-open,请求继续
- tenant_id Phase 0 走 '__anon__' 子命名空间
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


# ---- Mock Redis client ----


class _FakeRedis:
    """最小 Redis mock,只支持 IdempotencyMiddleware 用的命令。

    - hgetall(key) -> dict
    - hsetnx(key, field, value) -> 0/1
    - hset(key, mapping=...) -> count
    - delete(key) -> 0/1
    - expire(key, sec) -> True
    - pipeline().hsetnx().hsetnx().expire().execute()
    """

    def __init__(self):
        self._store: dict = {}
        self._expire_log: list = []  # 记录 expire 调用,供 TTL 测试断言

    def hgetall(self, key):
        return dict(self._store.get(key, {}))

    def hsetnx(self, key, field, value):
        h = self._store.setdefault(key, {})
        if field in h:
            return 0
        h[field] = value
        return 1

    def hset(self, key, mapping=None, field=None, value=None):
        h = self._store.setdefault(key, {})
        if mapping is None:
            mapping = {field: value}
        for f, v in mapping.items():
            h[f] = v
        return len(mapping)

    def delete(self, key):
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    def expire(self, key, sec):
        self._expire_log.append((key, sec))
        return True

    def pipeline(self):
        outer = self

        class _Pipe:
            def __init__(self):
                self._ops = []

            def hsetnx(self, key, field, value):
                self._ops.append(("hsetnx", key, field, value))
                return self

            def hset(self, key, mapping=None):
                self._ops.append(("hset", key, dict(mapping or {})))
                return self

            def expire(self, key, sec):
                self._ops.append(("expire", key, sec))
                return self

            def execute(self):
                results = []
                for op in self._ops:
                    if op[0] == "hsetnx":
                        _, k, f, v = op
                        h = outer._store.setdefault(k, {})
                        if f in h:
                            results.append(0)
                        else:
                            h[f] = v
                            results.append(1)
                    elif op[0] == "hset":
                        _, k, m = op
                        h = outer._store.setdefault(k, {})
                        for f, v in m.items():
                            h[f] = v
                        results.append(len(m))
                    elif op[0] == "expire":
                        _, exp_key, exp_sec = op
                        outer._expire_log.append((exp_key, exp_sec))
                        results.append(True)
                self._ops = []
                return results

        return _Pipe()


# ---- App factory + fixtures ----


def _build_app(status_code=200, response_body=None):
    """构造一个挂 IdempotencyMiddleware 的 Starlette app。

    - GET /probe -> {"probe": True}
    - POST /echo  -> JSONResponse(status_code, response_body)
    - POST /text  -> PlainTextResponse("hello world")(测非 JSON)
    """
    from lumen_api.middleware.idempotency import IdempotencyMiddleware

    body = response_body if response_body is not None else {"echo": True}

    async def probe(request):
        return JSONResponse({"probe": True})

    async def echo(request):
        await request.body()  # 消费 body,验证 middleware 不影响下游
        return JSONResponse(status_code=status_code, content=body)

    async def text_endpoint(request):
        return PlainTextResponse("hello world", status_code=status_code)

    app = Starlette(
        routes=[
            Route("/probe", probe, methods=["GET"]),
            Route("/echo", echo, methods=["POST"]),
            Route("/text", text_endpoint, methods=["POST"]),
        ]
    )
    app.add_middleware(IdempotencyMiddleware)
    return app


@pytest.fixture
def fake_redis():
    return _FakeRedis()


@pytest.fixture
def patched_get_default_client(fake_redis, monkeypatch):
    """monkeypatch idempotency.get_default_client 返 fake_redis。"""
    from lumen_api.middleware import idempotency

    monkeypatch.setattr(idempotency, "get_default_client", lambda: fake_redis)
    return fake_redis


# ===== Happy path: 缓存 + 重放 =====


def test_post_with_idem_key_caches_and_replays(patched_get_default_client, fake_redis):
    """第一次 POST 写 cache,第二次同 key 返缓存(即使 body 不同)。"""
    app = _build_app()
    c = TestClient(app)

    r1 = c.post("/echo", content=b'{"a":1}', headers={"Idempotency-Key": "key-1"})
    assert r1.status_code == 200
    body1 = r1.json()

    # 同 key 第二次,body 不同 → 应返缓存的 r1 body
    r2 = c.post(
        "/echo",
        content=b'{"completely":"different"}',
        headers={"Idempotency-Key": "key-1"},
    )
    assert r2.status_code == 200
    assert r2.json() == body1

    # cache 里 status=complete + response_body
    redis_key = "lumen:idem:__anon__:key-1"
    h = fake_redis.hgetall(redis_key)
    assert h.get("status") == "complete"
    assert h.get("response_status") == "200"


def test_different_keys_have_independent_caches(patched_get_default_client, fake_redis):
    """不同 Idempotency-Key 各自独立 cache,互不影响。"""
    app = _build_app()
    c = TestClient(app)

    c.post("/echo", content=b'{"k":"a"}', headers={"Idempotency-Key": "key-a"})
    c.post("/echo", content=b'{"k":"b"}', headers={"Idempotency-Key": "key-b"})

    assert fake_redis.hgetall("lumen:idem:__anon__:key-a").get("status") == "complete"
    assert fake_redis.hgetall("lumen:idem:__anon__:key-b").get("status") == "complete"


def test_idempotency_key_header_case_insensitive(patched_get_default_client, fake_redis):
    """header 名大小写不敏感(`idempotency-key` vs `Idempotency-Key`)。"""
    app = _build_app()
    c = TestClient(app)

    r1 = c.post("/echo", content=b'{}', headers={"idempotency-key": "case-key"})
    r2 = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "case-key"})

    # 两次应该命中同一 cache
    assert r1.json() == r2.json()


# ===== 旁路:无 key / 非 POST =====


def test_post_without_idem_key_passes_through(patched_get_default_client, fake_redis):
    """没 Idempotency-Key header → 直接放行,不写 cache。"""
    app = _build_app()
    c = TestClient(app)

    r1 = c.post("/echo", content=b'{"a":1}')
    r2 = c.post("/echo", content=b'{"b":2}')

    assert r1.status_code == 200
    assert r2.status_code == 200
    # Redis store 应为空(没 cache)
    assert fake_redis._store == {}


def test_get_request_skips_middleware(patched_get_default_client, fake_redis):
    """GET 请求不挂 idempotency 中间件(method != POST 直接放行)。"""
    app = _build_app()
    c = TestClient(app)

    # 加 Idempotency-Key 但 method=GET → 跳过中间件
    r = c.get("/probe", headers={"Idempotency-Key": "ignored-on-get"})
    assert r.status_code == 200
    assert r.json() == {"probe": True}
    # Redis store 应为空
    assert fake_redis._store == {}


def test_put_request_skips_middleware(patched_get_default_client, fake_redis):
    """PUT 不挂 idempotency 中间件(method != POST)。"""
    app = _build_app()
    c = TestClient(app)

    # /echo 只 POST → PUT 会 405,说明 method filter 工作
    r = c.put("/echo", content=b'{}', headers={"Idempotency-Key": "put-key"})
    assert r.status_code == 405
    # 没 cache
    assert fake_redis._store == {}


# ===== In-progress / Stale =====


def test_in_progress_within_5s_returns_409(patched_get_default_client, fake_redis):
    """5 秒内同 key 重复请求 → 409 in_progress(防止前端并发抢)。"""
    redis_key = "lumen:idem:__anon__:in-progress"
    fake_redis.hsetnx(redis_key, "status", "processing")
    # created_at = now(不 stale)
    fake_redis.hset(redis_key, field="created_at", value=str(time.time()))

    app = _build_app()
    c = TestClient(app)
    r = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "in-progress"})

    assert r.status_code == 409
    body = r.json()
    assert "processing" in body.get("message", "").lower()


def test_stale_processing_over_5s_allows_reacquire(patched_get_default_client, fake_redis):
    """processing 状态超过 5 秒 → stale,放过 + 走正常处理路径。"""
    redis_key = "lumen:idem:__anon__:stale-key"
    fake_redis.hsetnx(redis_key, "status", "processing")
    # created_at 6 秒前(> 5s stale 阈值)
    fake_redis.hset(redis_key, field="created_at", value=str(time.time() - 6))

    app = _build_app()
    c = TestClient(app)
    r = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "stale-key"})

    # 不应返 409,正常处理 → 200
    assert r.status_code == 200


# ===== Non-2xx 不缓存 =====


def test_4xx_response_not_cached(patched_get_default_client, fake_redis):
    """4xx response 不缓存(让客户端重试可能成功)。"""
    app = _build_app(status_code=400, response_body={"err": "bad"})
    c = TestClient(app)

    r = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "err-key"})
    assert r.status_code == 400

    # cache 应被清掉(失败 response 不缓存)
    redis_key = "lumen:idem:__anon__:err-key"
    h = fake_redis.hgetall(redis_key)
    assert h.get("status") != "complete"


def test_5xx_response_not_cached(patched_get_default_client, fake_redis):
    """5xx response 不缓存(同 4xx,允许客户端重试)。"""
    app = _build_app(status_code=500, response_body={"err": "internal"})
    c = TestClient(app)

    r = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "500-key"})
    assert r.status_code == 500

    redis_key = "lumen:idem:__anon__:500-key"
    h = fake_redis.hgetall(redis_key)
    assert h.get("status") != "complete"


def test_non_json_response_not_cached(patched_get_default_client, fake_redis):
    """非 JSON 2xx response(纯文本)不缓存 — json.loads 失败保护。"""
    from lumen_api.middleware.idempotency import IdempotencyMiddleware

    async def text_endpoint(request):
        return PlainTextResponse("hello world", status_code=200)

    app = Starlette(routes=[Route("/text", text_endpoint, methods=["POST"])])
    app.add_middleware(IdempotencyMiddleware)
    c = TestClient(app)

    r = c.post("/text", content=b'{}', headers={"Idempotency-Key": "text-key"})
    assert r.status_code == 200
    assert r.text == "hello world"

    # 纯文本不应 cache(json.loads 失败 → 走 delete 路径)
    redis_key = "lumen:idem:__anon__:text-key"
    h = fake_redis.hgetall(redis_key)
    assert h.get("status") != "complete"


# ===== Fail-open: Redis 挂时让请求穿过 =====


def test_redis_unreachable_fails_open(monkeypatch):
    """Redis 挂时 → fail-open,请求继续(不挡 POST 业务)。"""
    from lumen_api.middleware.idempotency import IdempotencyMiddleware
    from lumen_api.middleware import idempotency

    class _DeadRedis:
        """所有命令抛 ConnectionError。"""

        def hgetall(self, *a, **kw):
            raise ConnectionError("redis down")

        def pipeline(self):
            raise ConnectionError("redis down")

        def hsetnx(self, *a, **kw):
            raise ConnectionError("redis down")

        def hset(self, *a, **kw):
            raise ConnectionError("redis down")

        def expire(self, *a, **kw):
            raise ConnectionError("redis down")

        def delete(self, *a, **kw):
            raise ConnectionError("redis down")

    monkeypatch.setattr(idempotency, "get_default_client", lambda: _DeadRedis())

    async def echo(request):
        return JSONResponse({"echo": True})

    app = Starlette(routes=[Route("/echo", echo, methods=["POST"])])
    app.add_middleware(IdempotencyMiddleware)
    c = TestClient(app)

    r = c.post("/echo", content=b'{}', headers={"Idempotency-Key": "redis-down"})
    # fail-open:POST 仍正常处理
    assert r.status_code == 200
    assert r.json() == {"echo": True}


# ===== Tenant 命名空间 =====


def test_tenant_id_phase0_uses_anon(patched_get_default_client, fake_redis):
    """Phase 0 简化:_extract_tenant_id 返 None → '__anon__' 子命名空间。

    Phase 1 改:从 JWT sub claim 拿真 tenant_id。
    """
    app = _build_app()
    c = TestClient(app)

    c.post("/echo", content=b'{}', headers={"Idempotency-Key": "anon-key"})

    expected_key = "lumen:idem:__anon__:anon-key"
    assert fake_redis.hgetall(expected_key).get("status") == "complete"


# ===== _make_key helper =====


def test_make_key_anonymous():
    """_make_key(None, ...) 走 __anon__ namespace。"""
    from lumen_api.middleware.idempotency import _make_key

    assert _make_key(None, "abc") == "lumen:idem:__anon__:abc"


def test_make_key_with_tenant():
    """_make_key(42, ...) 走 '42' namespace,避免跨用户碰撞。"""
    from lumen_api.middleware.idempotency import _make_key

    assert _make_key(42, "abc") == "lumen:idem:42:abc"
    assert _make_key(0, "xyz") == "lumen:idem:0:xyz"


def test_make_key_tenant_isolation():
    """不同 tenant_id 走不同 keyspace,同 idem_key 不冲突。"""
    from lumen_api.middleware.idempotency import _make_key

    assert _make_key(1, "same-key") != _make_key(2, "same-key")


# ===== TTL 设置 =====


def test_processing_sets_ttl(patched_get_default_client, fake_redis):
    """SETNX 占位时设 30 分钟 TTL(防止 Redis 内存涨)。"""
    from lumen_api.middleware.idempotency import _TTL_SECONDS

    app = _build_app()
    c = TestClient(app)

    c.post("/echo", content=b'{}', headers={"Idempotency-Key": "ttl-key"})

    # expire 被调用过,值 = _TTL_SECONDS
    expected = ("lumen:idem:__anon__:ttl-key", _TTL_SECONDS)
    assert expected in fake_redis._expire_log


# ===== Integration: middleware 装到 ASGI app 后流走完 =====


def test_middleware_does_not_break_request_body(patched_get_default_client, fake_redis):
    """下游 handler 仍能读 request body(middleware 不消费)。"""
    app = _build_app()
    c = TestClient(app)

    # echo handler 调 await request.body() — 如果 middleware 偷读会报错
    r = c.post("/echo", content=b'{"x":42}', headers={"Idempotency-Key": "body-key"})
    assert r.status_code == 200