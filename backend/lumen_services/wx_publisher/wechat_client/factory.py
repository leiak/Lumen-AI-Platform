"""WechatClient factory — 按 account.is_mock + settings 路由 Stub / Real.

Spec §7.5:
- ``account.is_mock=True`` → 永远走 ``WechatStubClient``
- ``settings.WX_PUBLISHER_REAL_CLIENT_ENABLED=False`` → 走 Stub(默认 dev 安全)
- 两者都 False / True 才走 ``WechatRealClient``

``publish_service.publish_sync`` 在调 client 前先 ``get_wechat_client(account)``
拿到一个 client 实例。Stub 不需要 ``async with``(无 httpx 客户端),
Real 必须 ``async with WechatRealClient() as c`` —— publish_service
统一用 ``async with`` 包裹,Stub 走 no-op 上下文(``__aenter__/__aexit__``
是 identity)。
"""
from __future__ import annotations

import logging

from lumen_core.config import settings
from lumen_models.wx_publisher import WxAccount
from lumen_services.wx_publisher.wechat_client.protocol import WechatClient
from lumen_services.wx_publisher.wechat_client.real_client import WechatRealClient
from lumen_services.wx_publisher.wechat_client.stub_client import WechatStubClient

log = logging.getLogger(__name__)


def get_wechat_client(account: WxAccount) -> WechatClient:
    """Factory — 按 account.is_mock + settings 路由。

    路由优先级(spec §7.5):
    1. ``account.is_mock=True`` → 永远 Stub(运营在账号配置页手动开关)
    2. ``settings.WX_PUBLISHER_REAL_CLIENT_ENABLED=False`` → Stub
       (默认 dev 安全 — 全局开关,环境变量级)
    3. 否则 → Real(需要真实 AppID + IP 白名单 + HTTPS 出口)
    """
    if account.is_mock or not settings.WX_PUBLISHER_REAL_CLIENT_ENABLED:
        log.info(
            "Using WechatStubClient (account.is_mock=%s, real_enabled=%s)",
            account.is_mock, settings.WX_PUBLISHER_REAL_CLIENT_ENABLED,
        )
        return WechatStubClient()
    log.info("Using WechatRealClient for account %s", account.id)
    return WechatRealClient()