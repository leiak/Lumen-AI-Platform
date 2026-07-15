"""M32 公众号助手 - WechatClient Protocol + Stub / Real / factory.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §7.5

CP4 范围 (T20):
- WechatAPIError: 微信 API 错(带 errcode + errmsg)
- WechatClient (Protocol): 4 方法 (get_access_token / upload_image /
  add_draft / mass_sendall)
- WechatStubClient: mock 实现,内存字典存草稿,返伪 ID(默认 dev 用)
- WechatRealClient: httpx 调微信开放平台 /cgi-bin/*,需真实 AppID + IP 白名单
- get_wechat_client(account): factory 按 account.is_mock + settings 路由

不在本包范围(留给 publish_service):
- 业务编排(上传封面 + 渲染 + 调 add_draft + 群发)
- 后台任务 / WS 通知
"""
from lumen_services.wx_publisher.wechat_client.protocol import (
    WechatAPIError,
    WechatClient,
)
from lumen_services.wx_publisher.wechat_client.stub_client import WechatStubClient
from lumen_services.wx_publisher.wechat_client.real_client import WechatRealClient
from lumen_services.wx_publisher.wechat_client.factory import get_wechat_client

__all__ = [
    "WechatAPIError",
    "WechatClient",
    "WechatStubClient",
    "WechatRealClient",
    "get_wechat_client",
]