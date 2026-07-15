"""WechatStubClient — mock WechatClient,内存字典存草稿 + 返伪 ID.

Spec §7.5 — 默认 dev 用。零网络依赖,所有方法返 ``mock_xxx_{uuid16}``
格式的伪 ID。**没有持久化** — uvicorn 重启后内存字典归零。

启动时打 ``WARNING`` log 提醒 dev 同学「这是 stub,真发布请改
``account.is_mock=False`` + 配置真实 AppID」,避免「mock 测试过
以为是真接口 OK 就上线」的踩坑。
"""
from __future__ import annotations

import logging
from uuid import uuid4

from lumen_models.wx_publisher import WxAccount
from lumen_services.wx_publisher.wechat_client.protocol import WechatClient

log = logging.getLogger(__name__)


class WechatStubClient:
    """mock 实现,内存字典存草稿,返伪 ID。默认 dev 用。

    满足 ``WechatClient`` Protocol 的 4 方法结构(PEP 544 鸭子类型)
    — publish_service 直接当 Protocol 用,不需要 isinstance 检查。
    """

    def __init__(self) -> None:
        self._drafts: dict[str, dict] = {}
        self._images: dict[str, str] = {}
        log.warning(
            "WechatStubClient in use, set wx_accounts.is_mock=false "
            "to use real WeChat API"
        )

    async def get_access_token(
        self, account: WxAccount, *, force_refresh: bool = False
    ) -> str:
        """返伪 access_token。

        ``force_refresh`` 参数忽略 — stub 不缓存,每次返新串。命名格式
        ``mock_access_token_{16 hex}`` 方便日志/调试肉眼识别「这是
        mock 行为」。
        """
        return f"mock_access_token_{uuid4().hex[:16]}"

    async def upload_image(self, account: WxAccount, image_url: str) -> str:
        """存 ``image_url`` → 伪 media_id。

        Stub 不实际下载图片,只把 URL 存字典。返 ``mock_image_media_id_xxx``
        让 publish_service 后续传给 ``add_draft`` 当 ``thumb_media_id``。
        """
        media_id = f"mock_image_media_id_{uuid4().hex[:16]}"
        self._images[media_id] = image_url
        return media_id

    async def add_draft(self, account: WxAccount, message: dict) -> str:
        """存 ``message`` → 伪 media_id。

        ``message`` 是 publish_service 拼好的微信图文消息 dict,Stub
        直接收字典返 ``mock_draft_media_id_xxx``。``account`` 不读 —
        stub 不区分多租户(同进程内 dict 全局共享,MVP 简化)。
        """
        media_id = f"mock_draft_media_id_{uuid4().hex[:16]}"
        self._drafts[media_id] = message
        return media_id

    async def mass_sendall(self, account: WxAccount, media_id: str) -> str:
        """返伪 msg_id。

        Stub 不验证 ``media_id`` 是否真在 ``_drafts`` 里(给测试更
        灵活 — 测试可以传伪造的 ``media_id`` 直接走完流程)。
        """
        return f"mock_msg_id_{uuid4().hex[:16]}"

    # ---- async context manager (跟 WechatRealClient 对齐) ----
    # publish_service 用 ``async with client:`` 套住整个发布流程,Real 客户端
    # 借这个 hook 关 httpx.AsyncClient。Stub 是纯内存没资源要关,但缺方法
    # 会让 Python 抛 ``'WechatStubClient' object does not support the
    # asynchronous context manager protocol``(2026-06-29 _run_publish 复现)。
    # 实现成 no-op 即可,跟 Real 客户端协议对齐。
    async def __aenter__(self) -> "WechatStubClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None