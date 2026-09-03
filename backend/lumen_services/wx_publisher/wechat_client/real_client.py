"""WechatRealClient — 真实 WechatClient 走 httpx 调微信开放平台 /cgi-bin/*。

Spec §7.5 + §7.6 — **不在 dev 跑**(需要真实 AppID + IP 白名单 +
HTTPS 出口),通过 factory 路由。MVP 简化:

- ``get_access_token`` 调 ``/cgi-bin/token`` + 缓存到 ``WxAccount``;
  提前 5min 主动刷,40001/42001/40014 被动刷新(spec §7.6)
- ``upload_image`` 先 httpx GET ``image_url`` 拉 bytes,再 POST
  ``/cgi-bin/material/add_material?type=image`` (multipart/form-data)
- ``add_draft`` POST ``/cgi-bin/draft/add``, body ``{"articles": [msg]}``
- ``mass_sendall`` POST ``/cgi-bin/message/mass/sendall``,
  body ``{"filter": {"is_to_all": True}, "mpnews": {"media_id": ...},
  "msgtype": "mpnews", "send_ignore_reprint": 0}``

AppSecret 通过 ``WxAccountService.decrypt_app_secret`` 解密(对称
Fernet 加密,settings.WX_PUBLISHER_FERNET_KEY)。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx

from lumen_models.wx_publisher import WxAccount
from lumen_services.wx_publisher.wechat_client.protocol import (
    WechatAPIError,
    WechatClient,
)

log = logging.getLogger(__name__)


# 微信开放平台 base URL
WECHAT_API_BASE = "https://api.weixin.qq.com"

# access_token 中控缓存策略 (spec §7.6)
ACCESS_TOKEN_TTL_SECONDS = 2 * 60 * 60  # 2 hours (微信官方 TTL)
ACCESS_TOKEN_REFRESH_LEAD_SECONDS = 5 * 60  # 提前 5 分钟主动刷新

# 触发被动刷新的 errcode
PASSIVE_REFRESH_ERRCODES = frozenset({40001, 40014, 42001})


def _decrypt_app_secret(account: WxAccount) -> str:
    """解密 AppSecret。运行时从 WxAccountService 拿 helper。

    延迟导入 WxAccountService 是为了避开 wx_publisher.account_service
    ↔ wechat_client.real_client 之间的潜在循环(a_s 也 import WechatClient
    吗?目前不,但留这个 lazy import 当保险)。
    """
    from lumen_services.wx_publisher.account_service import WxAccountService
    # BUG fix 2026-08-07:之前传整个 account ORM 对象进 decrypt_app_secret,
    # 签名要 bytes — Fernet 收到 SQLAlchemy 实例抛 TypeError,RealClient
    # 路径从 M32 ship 至今 1.5 个月在第一关 get_access_token 就跪,根本
    # 碰不到微信 API。修后传 app_secret_encrypted (bytes)。
    return WxAccountService().decrypt_app_secret(account.app_secret_encrypted)


def _is_token_expired(account: WxAccount, *, now: Optional[datetime] = None) -> bool:
    """判断 token 是否临近过期(< now + lead_seconds)。"""
    if not account.access_token or not account.access_token_expires_at:
        return True
    now = now or datetime.utcnow()
    return account.access_token_expires_at <= now + timedelta(
        seconds=ACCESS_TOKEN_REFRESH_LEAD_SECONDS
    )


class WechatRealClient:
    """真实 WechatClient 走 httpx 调微信开放平台 /cgi-bin/*。

    实例无状态(httpx.AsyncClient 通过 ``__aenter__``/``__aexit__``
    走 async context manager)。publish_service 用法::

        async with WechatRealClient() as client:
            token = await client.get_access_token(account)
            ...
    """

    def __init__(self, timeout: float = 60.0) -> None:
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "WechatRealClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "WechatRealClient must be used as async context manager: "
                "`async with WechatRealClient() as c: ...`"
            )
        return self._client

    # --- access_token 中控 ------------------------------------------------

    async def get_access_token(
        self, account: WxAccount, *, force_refresh: bool = False
    ) -> str:
        """主动刷新 access_token(spec §7.6)。

        1. 缓存未过期 + 不强制刷新 → 返 ``account.access_token``
        2. 过期或 ``force_refresh=True`` → 调 ``/cgi-bin/token`` 拉新,
           写回 ``WxAccount.access_token`` + ``access_token_expires_at``
        3. 微信返 ``errcode != 0`` → 抛 ``WechatAPIError``
        """
        if not force_refresh and not _is_token_expired(account) and account.access_token:
            return account.access_token  # type: ignore[return-value]

        app_id = account.app_id
        app_secret = _decrypt_app_secret(account)
        client = self._require_client()
        try:
            resp = await client.get(
                f"{WECHAT_API_BASE}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": app_id,
                    "secret": app_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            log.exception("WeChat /cgi-bin/token network error: %s", exc)
            raise WechatAPIError(
                errcode=-1, errmsg=f"network error: {exc}", http_status=503,
            ) from exc

        if payload.get("errcode"):
            raise WechatAPIError(
                errcode=int(payload["errcode"]),
                errmsg=payload.get("errmsg", "unknown error"),
            )

        # 写回缓存
        account.access_token = payload["access_token"]
        account.access_token_expires_at = datetime.utcnow() + timedelta(
            seconds=int(payload.get("expires_in", ACCESS_TOKEN_TTL_SECONDS))
        )
        return account.access_token  # type: ignore[return-value]

    # --- 上传素材 / 草稿 / 群发 --------------------------------------------

    async def _ensure_token(self, account: WxAccount) -> str:
        """确保 token 有效(供 4 个 public 方法调用)。

        失败抛 ``WechatAPIError``。
        """
        return await self.get_access_token(account, force_refresh=False)

    async def _passive_retry(
        self,
        account: WxAccount,
        coro_factory,
    ) -> Any:
        """执行 coro_factory(token),遇到 PASSIVE_REFRESH_ERRCODES 强制刷一次。

        coro_factory 接收一个 str token 参数,返回 coroutine(因为
        不能 await 然后再 await — 两次 await 须手动 retry)。

        Phase 1 Group A 2.5 (2026-09-03): 同时包 transient retry —— 网络层
        connect refused / read timeout 等异常走 tenacity 3 次 exponential
        backoff 0.5/1/2s 重试;token 过期 errcode 仍走单次 force_refresh。
        """
        token = await self._ensure_token(account)
        from lumen_services.retry import call_async_with_retry

        # 双层 try: 内层 tenacity 处理 transient 网络异常, 外层 WechatAPIError
        # 处理业务级 token 过期 (40001/40014/42001)。
        async def _call_with_transient_retry():
            try:
                return await coro_factory(token)
            except WechatAPIError as exc:
                # 业务级错误不走 tenacity (不属于 transient 网络异常)
                raise exc

        try:
            return await call_async_with_retry(
                _call_with_transient_retry,
                func_name="wechat._passive_retry",
            )
        except WechatAPIError as exc:
            if exc.errcode not in PASSIVE_REFRESH_ERRCODES:
                raise
            log.warning(
                "WeChat token passive refresh: errcode=%s, retry once", exc.errcode
            )
            token = await self.get_access_token(account, force_refresh=True)
            return await coro_factory(token)

    async def upload_image(self, account: WxAccount, image_url: str) -> str:
        """从 image_url 拉 bytes → POST /cgi-bin/material/add_material?type=image。

        微信只接受 ``image/jpeg`` / ``image/png`` / ``image/gif``,
        max 2MB(MVP 简化:不校验类型/大小,微信服务端会返 40006 等)。
        """
        client = self._require_client()
        # 1) 拉图片 bytes
        try:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            image_bytes = img_resp.content
        except httpx.HTTPError as exc:
            raise WechatAPIError(
                errcode=-1,
                errmsg=f"failed to fetch image_url: {exc}",
                http_status=503,
            ) from exc

        async def _upload(token: str) -> str:
            resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/material/add_material",
                params={"access_token": token, "type": "image"},
                files={"media": ("cover.jpg", image_bytes, "image/jpeg")},
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errcode"):
                raise WechatAPIError(
                    errcode=int(payload["errcode"]),
                    errmsg=payload.get("errmsg", "unknown error"),
                )
            return payload["media_id"]

        return await self._passive_retry(account, _upload)

    async def add_draft(self, account: WxAccount, message: dict) -> str:
        """POST /cgi-bin/draft/add body {"articles": [message]} → 返 media_id。

        微信「草稿箱」新接口(2020 后),单次 1 篇图文消息。
        """
        client = self._require_client()

        async def _post(token: str) -> str:
            resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/draft/add",
                params={"access_token": token},
                json={"articles": [message]},
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errcode"):
                raise WechatAPIError(
                    errcode=int(payload["errcode"]),
                    errmsg=payload.get("errmsg", "unknown error"),
                )
            return payload["media_id"]

        return await self._passive_retry(account, _post)

    async def mass_sendall(self, account: WxAccount, media_id: str) -> str:
        """POST /cgi-bin/message/mass/sendall → 返 msg_id。

        spec §7.5: body ``{"filter": {"is_to_all": True},
        "mpnews": {"media_id": ...}, "msgtype": "mpnews",
        "send_ignore_reprint": 0}``。
        """
        client = self._require_client()
        body = {
            "filter": {"is_to_all": True},
            "mpnews": {"media_id": media_id},
            "msgtype": "mpnews",
            "send_ignore_reprint": 0,
        }

        async def _post(token: str) -> str:
            resp = await client.post(
                f"{WECHAT_API_BASE}/cgi-bin/message/mass/sendall",
                params={"access_token": token},
                json=body,
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("errcode"):
                raise WechatAPIError(
                    errcode=int(payload["errcode"]),
                    errmsg=payload.get("errmsg", "unknown error"),
                )
            return payload["msg_id"]

        return await self._passive_retry(account, _post)