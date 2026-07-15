"""WechatClient Protocol — 抽象「上传素材/草稿/群发」.

Spec §7.5 — Protocol (structural typing) 让 Stub / Real 实现可被
publish_service 在不知道具体类型的情况下调用。**4 方法语义**:

- ``get_access_token``: 拉 / 刷新 access_token,WechatStubClient 返伪串,
  WechatRealClient 走 ``/cgi-bin/token`` 并缓存到 ``wx_accounts.access_token``
- ``upload_image``: 上传封面图到微信素材库,返 ``media_id``
- ``add_draft``: 把「微信图文消息 dict」加到微信草稿箱,返 ``media_id``
- ``mass_sendall``: 群发草稿(对所有用户),返 ``msg_id``

``WechatAPIError`` 携带 ``errcode + errmsg + http_status``,publish_service
会捕获并落库到 ``wx_publish_records.error_code / error_message``。
"""
from __future__ import annotations

from typing import Protocol

from lumen_models.wx_publisher import WxAccount


class WechatAPIError(Exception):
    """微信 API 错(带 errcode + errmsg)。

    Spec §4.4: 微信 API 错返 ``http_status=502``(微信 4xx/5xx 都映射到
    这个,跟 nginx ``502 Bad Gateway`` 语义一致 — 上游网关错误)。

    ``errcode`` 是微信官方错误码(``40001`` invalid credential /
    ``40014`` invalid access_token / ``45009`` call frequency 超限 等),
    ``errmsg`` 是微信返回的中文/英文描述。
    """

    def __init__(self, errcode: int, errmsg: str, http_status: int = 502):
        self.errcode = errcode
        self.errmsg = errmsg
        self.http_status = http_status
        super().__init__(f"WeChat API error {errcode}: {errmsg}")


class WechatClient(Protocol):
    """4 方法: get_access_token / upload_image / add_draft / mass_sendall.

    Protocol 是 PEP 544 结构化子类型 — Stub / Real 不用显式继承即可
    通过 isinstance(..., WechatClient) 检查。``account`` 参数是
    ``WxAccount`` ORM 行,client 只读 ``app_id`` + ``is_mock`` +
    ``access_token`` + ``app_secret_encrypted``(WechatRealClient 用
    WxAccountService 解密)。
    """

    async def get_access_token(
        self, account: WxAccount, *, force_refresh: bool = False
    ) -> str:
        """拉 access_token(Stub 返伪串;Real 走 /cgi-bin/token + 缓存)。

        ``force_refresh=True`` 跳过缓存强制重拉(WechatRealClient 用
        在收到 40001/42001/40014 时被动刷新)。Stub 实现忽略此参数。
        """
        ...

    async def upload_image(self, account: WxAccount, image_url: str) -> str:
        """上传封面到微信素材库,返 media_id。

        Stub 把 ``image_url`` 存内存 dict 返伪 ``media_id``;Real
        从 URL 拉 bytes + POST ``/cgi-bin/material/add_material?type=image``。
        """
        ...

    async def add_draft(self, account: WxAccount, message: dict) -> str:
        """加微信图文消息到草稿箱,返 media_id。

        ``message`` 是微信开放平台规范的图文消息 dict(``title`` /
        ``content`` / ``thumb_media_id`` / ``author`` / ``digest`` /
        ``content_source_url`` / ``need_open_comment`` 等)。

        Stub 把 ``message`` 存内存 dict;Real 走 ``/cgi-bin/draft/add``
        body ``{"articles": [message]}``。
        """
        ...

    async def mass_sendall(self, account: WxAccount, media_id: str) -> str:
        """对所有用户群发草稿,返 msg_id。

        Stub 返伪 ``msg_id``;Real 走 ``/cgi-bin/message/mass/sendall``
        body ``{"filter": {"is_to_all": True}, "mpnews": {"media_id": ...},
        "msgtype": "mpnews", "send_ignore_reprint": 0}``。
        """
        ...