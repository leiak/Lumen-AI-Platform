"""WechatStubClient 单元测试 (M32 T23 / CP4).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §7.5

3 tests,验证 WechatStubClient 4 方法的内存字典行为:
- test_get_access_token_returns_mock_string_format
  ``mock_access_token_{16hex}`` 格式 + 每次返新串
- test_upload_image_stores_url_in_dict
  media_id 返 ``mock_image_media_id_xxx`` 格式 + 内部 dict 存了 URL
- test_add_draft_stores_message_in_dict
  media_id 返 ``mock_draft_media_id_xxx`` 格式 + 内部 dict 存了 message
  且可通过同 media_id 重新取出

不在范围:
- 异步实际 await 行为(纯 sync 测试,draft dict 行为是核心合约)
- WechatRealClient httpx 调用(需要 dev 网络,留给 T22+ 集成测试)
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models import (  # noqa: F401
    agent as _agent,
    image_generation as _image_generation,
    knowledge as _knowledge,
    model_config as _model_config,
    user as _user_model,
)
from lumen_services.wx_publisher.wechat_client.stub_client import WechatStubClient


def _run(coro):
    """Sync helper to await a coroutine in a test.

    Use a fresh event loop each time so the test doesn't depend on
    (or leak into) a shared loop from pytest-asyncio or other async
    tests in the suite. asyncio.get_event_loop() returns the running
    loop in some pytest contexts and raises "no current event loop"
    in others, both of which are flaky in a mixed sync/async suite.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_mock_account_stub():
    """Return a minimal duck-typed object with the WxAccount attributes
    the stub reads. Stub actually doesn't read any of them — but keeps
    the signature honest for future-proofing.
    """
    # Use SimpleNamespace for a duck-typed stand-in
    from types import SimpleNamespace
    return SimpleNamespace(
        id=1, app_id="wx" + "a" * 16, is_mock=True,
    )


# ---- tests ------------------------------------------------------------------


def test_get_access_token_returns_mock_string_format():
    """get_access_token 返 ``mock_access_token_{16 hex}`` 格式且每次不同。"""
    stub = WechatStubClient()
    account = _make_mock_account_stub()

    token1 = _run(stub.get_access_token(account))
    token2 = _run(stub.get_access_token(account))

    # 两次都满足 mock 前缀 + 16 hex 后缀
    assert token1.startswith("mock_access_token_")
    assert len(token1) == len("mock_access_token_") + 16
    # 每次返新串(无缓存)
    assert token1 != token2


def test_upload_image_stores_url_in_dict():
    """upload_image 返 ``mock_image_media_id_{16 hex}`` 格式 + dict 存了 URL。"""
    stub = WechatStubClient()
    account = _make_mock_account_stub()

    url = f"https://example.test/{uuid.uuid4().hex[:8]}.jpg"
    media_id = _run(stub.upload_image(account, url))

    assert media_id.startswith("mock_image_media_id_")
    assert len(media_id) == len("mock_image_media_id_") + 16
    # 字典里能取回 URL
    assert media_id in stub._images
    assert stub._images[media_id] == url


def test_add_draft_stores_message_in_dict_and_gettable():
    """add_draft 返 ``mock_draft_media_id_{16 hex}`` + 字典存 message,
    且同 media_id 可取回完整 message(dict 等值)。
    """
    stub = WechatStubClient()
    account = _make_mock_account_stub()

    message = {
        "title": "测试图文",
        "content": "<p>正文内容</p>",
        "thumb_media_id": "mock_thumb_123",
        "author": "tester",
        "digest": "摘要",
    }
    media_id = _run(stub.add_draft(account, message))

    assert media_id.startswith("mock_draft_media_id_")
    assert len(media_id) == len("mock_draft_media_id_") + 16
    # dict 里能取回完整 message
    assert media_id in stub._drafts
    assert stub._drafts[media_id] == message


def test_mass_sendall_returns_msg_id():
    """bonus: mass_sendall 返 ``mock_msg_id_{16 hex}``,不报错即可。"""
    stub = WechatStubClient()
    account = _make_mock_account_stub()

    msg_id = _run(stub.mass_sendall(account, "mock_draft_media_id_anything"))

    assert msg_id.startswith("mock_msg_id_")
    assert len(msg_id) == len("mock_msg_id_") + 16