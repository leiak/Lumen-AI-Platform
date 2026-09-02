"""Phase 0 Unit 4.3.1 (2026-09-02):Idempotency-Key 中间件。

**为什么**:Phase 0 之前前端断网重发 / 用户双击 / 重试都可能导致
双创建(同一草稿 / 同一 agent / 同一 wx-publisher draft)。后端
无幂等保护,DB 多 row 冲突后才返 500,前端用户体验差。

**用法**(客户端):
    POST /api/v1/wx-publisher/drafts
    Headers:
        Authorization: Bearer <token>
        Idempotency-Key: <uuid4>     # 关键 — 同一 key 多次请求只处理 1 次

**实现**(服务端):
- SETNX `idem:<tenant>:<key>` 占位 → 处理请求 → cache response body
- 同 key 30 分钟内重复请求 → 返缓存的 response
- 同 key 在 > 5s 内仍在 processing → 409 Conflict(防止前端并发抢)
- Redis 挂时 fail-closed:不挡业务,只记 warning(让用户能继续
  创建,即使可能双创建)

**作用域**:只挂 POST endpoint(PUT/DELETE 自带幂等或需要特殊语义)。
GET / HEAD / OPTIONS 直接放行。

**存储**:Redis hash 字段:
  - status: "processing" | "complete"
  - response_status: HTTP status code(complete 时填)
  - response_body: JSON 字符串(complete 时填)
  - created_at: 浮点 epoch

**性能**:
- 每次 POST 多 2 次 Redis round-trip(SETNX + 后续 status update)。
  接受范围内 — POST 本来就慢(写 DB / 派任务)。
- 30 分钟 TTL 防止 Redis 内存涨。

**踩坑预警**:
- 前端必须用 uuid4 / 强随机,不要用 timestamp(并发场景冲突)。
- 不能让 idempotency 缓存把非幂等响应(比如 500)也缓存太久 —
  Phase 0 只缓存 2xx response,4xx/5xx 不缓存,允许客户端重试。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Awaitable, Callable, Optional

import redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


# Redis key prefix:跟 ratelimit / dist_lock 隔离 keyspace。
# tenant_id 走 sub claim 或 query,不挂在 query 里(防泄漏)。
_KEY_PREFIX = "lumen:idem"

# TTL:30 分钟内同 key 重复请求复用结果
_TTL_SECONDS = 30 * 60

# "processing" 超过这个秒数认为是 stale,允许抢占(防止孤儿请求卡死)
_STALE_PROCESSING_SECONDS = 5


_default_client: Optional[redis.Redis] = None


def get_default_client() -> redis.Redis:
    """懒加载默认 Redis 客户端(走 .env REDIS_*)。

    跟 dist_lock 共用模式;测试可注入 mock client。
    """
    global _default_client
    if _default_client is None:
        from lumen_core.config import settings
        _default_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
            decode_responses=True,
        )
    return _default_client


def reset_default_client() -> None:
    """测试 teardown 用。"""
    global _default_client
    _default_client = None


def _make_key(tenant_id: Optional[int], idem_key: str) -> str:
    """Redis key 格式:``lumen:idem:<tenant>:<key>``。

    匿名用户(无 tenant)走 "__anon__" 子命名空间,避免跨用户碰撞。
    """
    tenant_part = str(tenant_id) if tenant_id is not None else "__anon__"
    return f"{_KEY_PREFIX}:{tenant_part}:{idem_key}"


def _try_get_cached(client: redis.Redis, key: str) -> Optional[dict]:
    """查已 cache 的 response;complete 时返 body + status。"""
    try:
        raw = client.hgetall(key)
    except Exception as e:  # noqa: BLE001
        logger.warning("idempotency: Redis hgetall failed (%s); fail-open", e)
        return None

    if not raw:
        return None

    status = raw.get("status")
    if status == "complete":
        try:
            return {
                "status_code": int(raw.get("response_status", "200")),
                "body": json.loads(raw.get("response_body", "{}")),
            }
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("idempotency: cache decode failed (%s); treat as miss", e)
            return None
    if status == "processing":
        # 检查是否 stale(>5s 没动)— stale 视为可抢占
        try:
            created_at = float(raw.get("created_at", "0"))
        except ValueError:
            created_at = 0
        if time.time() - created_at > _STALE_PROCESSING_SECONDS:
            # 过期 →  让它穿过(假装 miss),让新请求重新 SETNX
            return {"_stale_processing": True}
        return {
            "_in_progress": True,
            "status_code": 409,
            "body": {
                "code": 409,
                "message": "Idempotency-Key request still processing (retry shortly)",
                "data": None,
            },
        }
    return None


def _try_set_processing(client: redis.Redis, key: str) -> bool:
    """SETNX status=processing。成功返 True,失败(别人已占)返 False。"""
    try:
        # Hash structure: status / created_at
        pipe = client.pipeline()
        pipe.hsetnx(key, "status", "processing")
        pipe.hsetnx(key, "created_at", str(time.time()))
        pipe.expire(key, _TTL_SECONDS)
        results = pipe.execute()
        # hsetnx 返 1 表示真设上(原来是空),0 表示别人已设
        return bool(results[0])
    except Exception as e:  # noqa: BLE001
        logger.warning("idempotency: SETNX failed (%s); fail-open", e)
        return False  # fail-open:让请求穿过(避免 Redis 挂时全站 POST 挂)


def _try_cache_response(
    client: redis.Redis, key: str, status_code: int, body_bytes: bytes
) -> None:
    """请求处理完后 cache response(只 cache 2xx,4xx/5xx 不 cache 让客户端重试)。"""
    if not (200 <= status_code < 300):
        # 失败 response 不 cache(让客户端重试可能成功)
        # 但释放 processing 锁 — 直接删 key,下个请求能正常进入
        try:
            client.delete(key)
        except Exception:
            pass
        return

    # 2xx 才走完整 cache 路径
    try:
        body_str = body_bytes.decode("utf-8", errors="replace")
        # 验证是不是合法 JSON,否则 cache 反而报 500
        json.loads(body_str)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 非 JSON response(纯文本 / 二进制)— 不 cache
        try:
            client.delete(key)
        except Exception:
            pass
        return

    try:
        pipe = client.pipeline()
        pipe.hset(key, mapping={
            "status": "complete",
            "response_status": str(status_code),
            "response_body": body_str,
        })
        pipe.expire(key, _TTL_SECONDS)
        pipe.execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("idempotency: cache write failed (%s); best-effort", e)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Idempotency-Key 中间件(只对 POST 生效)。

    客户端带 ``Idempotency-Key`` header 时:
    1. 查 Redis 是否已有 cache
       - complete → 返缓存
       - processing (非 stale) → 409 in_progress
       - processing stale (>5s) → 放过,新请求重新占位
       - 没 → 放行 + SETNX 占位
    2. 放行后处理请求,capture response body
    3. 2xx 写 cache;4xx/5xx 删 cache(允许重试)

    客户端不带 header → 直接放行(向后兼容)。
    Redis 挂时 → fail-open(只 log warning,不让 Redis 挂拖垮 POST)。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 只对 POST 生效;其他方法直接放行
        if request.method != "POST":
            return await call_next(request)

        idem_key = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)

        # tenant_id 推断:从 auth header 拿不到(中间件在 auth 之前跑)
        # 暂用 IP(同 IP 同一用户行为)— Phase 1 改成 JWT sub claim
        tenant_id = self._extract_tenant_id(request)
        redis_key = _make_key(tenant_id, idem_key)

        client = get_default_client()
        cached = _try_get_cached(client, redis_key)

        # 路径 1:有 complete cache → 返缓存
        if cached and "status_code" in cached and "_in_progress" not in cached and "_stale_processing" not in cached:
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["body"],
            )

        # 路径 2:in_progress (非 stale) → 409
        if cached and cached.get("_in_progress"):
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["body"],
            )

        # 路径 3:SETNX 占位(失败说明别人刚刚占上,简单放过 — 罕见并发)
        _try_set_processing(client, redis_key)

        # 路径 4:放行请求
        response = await call_next(request)

        # BaseHTTPMiddleware 把 downstream 包成 _StreamingResponse,
        # response.body 不存在,要读 body_iterator 才能拿到 bytes。
        # 读完后 body_iterator 被消费,需用新 Response 包回去给客户端。
        body_bytes = b""
        try:
            chunks: list[bytes] = []
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                chunks.append(chunk)
            body_bytes = b"".join(chunks)
            # 重新组装一个非流式 Response,把 body 喂回去
            response = Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as e:  # noqa: BLE001
            # body_iterator 拿不到 → 跳过 cache,放过请求
            logger.warning(
                "idempotency: failed to read response body (%s); skip cache", e,
            )
            try:
                client.delete(redis_key)
            except Exception:
                pass
            return response

        # Cache response(只 2xx)
        _try_cache_response(client, redis_key, response.status_code, body_bytes)

        return response

    @staticmethod
    def _extract_tenant_id(request: Request) -> Optional[int]:
        """Phase 0 简化:暂用 None(全局 anon namespace)。

        Phase 1 改:从 Authorization Bearer JWT 解 sub → 查 DB 拿
        tenant_id;或者跑 auth 中间件 → request.state.tenant_id。
        """
        return None


__all__ = [
    "IdempotencyMiddleware",
    "get_default_client",
    "reset_default_client",
    "_make_key",
    "_try_get_cached",
    "_try_set_processing",
    "_try_cache_response",
]