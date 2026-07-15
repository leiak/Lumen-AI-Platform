"""Tests for AIAdvisor service.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §7.1
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T16

Covers:
  - prompt 模板字段填充
  - JSON 解析的 3 种常见 LLM 输出形式(纯 JSON / markdown 包裹 / 杂文包裹)
  - LLMCallContext 集成验证(mock create_chat_model 验 context 设置)
"""
from __future__ import annotations

import itertools
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from lumen_core.database import SessionLocal, create_tables
from lumen_core.security import get_password_hash
from lumen_core.llm_call_context import get_call_context, reset_call_context, set_call_context
from lumen_models.customer import Customer, CustomerFollowUp
from lumen_models.model_config import ModelConfig
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.customer.ai_advisor import (
    AIAdvisor,
    CUSTOMER_CALL_TYPE_AI_SUGGEST,
)

create_tables()

_TEST_TENANT_CODE = "t-ai-advisor-test"
_TEST_USER_NAME = "u-ai-advisor-test"
_counter = itertools.count(1)


def _next_id() -> int:
    return next(_counter)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    s = SessionLocal()
    try:
        tenant_ids_q = s.query(Tenant.id).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%"))
        s.query(CustomerFollowUp).filter(CustomerFollowUp.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(Customer).filter(Customer.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(ModelConfig).filter(ModelConfig.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(User).filter(User.username.like(f"{_TEST_USER_NAME}%")).delete(synchronize_session=False)
        s.query(Tenant).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%")).delete(synchronize_session=False)
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _make_tenant_user_customer(db):
    t = Tenant(
        name="ai advisor test",
        code=f"{_TEST_TENANT_CODE}-{_next_id()}",
        status=True,
        max_users=10,
    )
    db.add(t)
    db.flush()
    n = _next_id()
    u = User(
        username=f"{_TEST_USER_NAME}-{n}",
        email=f"ai-advisor-{n}@test.local",
        hashed_password=get_password_hash("x"),
        full_name="AI Test",
        is_active=True,
        tenant_id=t.id,
    )
    db.add(u)
    db.flush()
    c = Customer(
        tenant_id=t.id,
        owner_user_id=u.id,
        created_by=u.id,
        name="测试客户",
        company_name="ACME 测试公司",
        company_position="CTO",
        level="vip",
        source="referral",
        tags=["决策人", "紧急"],
        custom_fields={"ltv": 50000},
        remark="通过老王介绍",
    )
    db.add(c)
    db.commit()
    db.refresh(t)
    db.refresh(u)
    db.refresh(c)
    return t, u, c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_prompt_format_includes_customer_profile(db):
    """Spec §7.1 — prompt 模板应包含客户档案所有关键字段。"""
    t, u, c = _make_tenant_user_customer(db)

    advisor = AIAdvisor(db, current_user=u)
    formatted = advisor._format_follow_up_history([])  # 空 timeline
    # 空历史返"(暂无跟进记录)"
    assert formatted == "(暂无跟进记录)"

    # 拉 customer 关键字段做 prompt 拼接(通过 suggest_next_step 间接验)
    # 用 mock create_chat_model 直接捕获 prompt
    fake_response = MagicMock()
    fake_response.content = json_response_text()

    captured = {}

    def fake_invoke(messages):
        # messages: [SystemMessage, HumanMessage]
        captured["user_msg"] = messages[1].content
        return fake_response

    fake_chat = MagicMock()
    fake_chat.invoke = fake_invoke

    with patch.object(AIAdvisor, "_resolve_chat_model", return_value=fake_chat):
        advisor.suggest_next_step(c)

    user_msg = captured["user_msg"]
    # 关键字段填充
    assert "测试客户" in user_msg
    assert "ACME 测试公司" in user_msg
    assert "CTO" in user_msg
    assert "vip" in user_msg
    assert "referral" in user_msg
    assert "决策人" in user_msg
    assert "50000" in user_msg
    assert "老王" in user_msg


def test_parse_response_handles_three_common_formats():
    """Spec §7.1 — JSON 解析处理 3 种常见 LLM 输出。"""
    # Case 1: 纯 JSON
    raw1 = json_response_text()
    parsed1 = AIAdvisor._parse_response(raw1)
    assert "suggested_message" in parsed1
    assert "reasoning" in parsed1

    # Case 2: Markdown 包裹
    raw2 = "Here is the answer:\n```json\n" + json_response_text() + "\n```\nHope it helps!"
    parsed2 = AIAdvisor._parse_response(raw2)
    assert "suggested_message" in parsed2

    # Case 3: 前后杂文 + JSON
    raw3 = "好的,根据客户档案,我建议:\n" + json_response_text() + "\n\n祝销售顺利!"
    parsed3 = AIAdvisor._parse_response(raw3)
    assert "suggested_message" in parsed3

    # Case 4: 损坏的 JSON → HTTPException(500)
    with pytest.raises(HTTPException) as exc:
        AIAdvisor._parse_response("not json at all")
    assert exc.value.status_code == 500


def test_suggest_next_step_uses_llm_call_context(db):
    """Spec §7.1 — LLMCallContext.call_type = customer.ai_suggest + tenant_id/user_id 正确填充。

    mock create_chat_model,捕获 invoke 调用,验证 set_call_context 在调用前后正确切换。
    """
    t, u, c = _make_tenant_user_customer(db)

    # 加一条跟进让 timeline 非空
    db.add(CustomerFollowUp(
        tenant_id=t.id, customer_id=c.id, user_id=u.id,
        follow_up_type="phone", content="初次沟通",
    ))
    db.commit()

    fake_response = MagicMock()
    fake_response.content = json_response_text()

    captured_contexts = []
    original_set = set_call_context

    def fake_set_call_context(ctx):
        captured_contexts.append(ctx)
        return original_set(ctx)

    fake_chat = MagicMock()

    def fake_invoke(messages):
        # invoke 调用期间应该有一个 context active
        ctx = get_call_context()
        if ctx:
            captured_contexts.append(ctx)
        return fake_response

    fake_chat.invoke = fake_invoke

    with patch.object(AIAdvisor, "_resolve_chat_model", return_value=fake_chat):
        with patch("lumen_services.customer.ai_advisor.set_call_context", side_effect=fake_set_call_context):
            advisor = AIAdvisor(db, current_user=u)
            result = advisor.suggest_next_step(c)

    # 至少 capture 到 1 个 LLMCallContext(call_type=customer.ai_suggest)
    ctx_objects = [x for x in captured_contexts if hasattr(x, "call_type")]
    assert len(ctx_objects) >= 1
    ctx = ctx_objects[0]
    assert ctx.call_type == CUSTOMER_CALL_TYPE_AI_SUGGEST
    assert ctx.tenant_id == t.id
    assert ctx.user_id == u.id
    assert ctx.extra["customer_id"] == c.id

    # response 字段正确填充
    assert isinstance(result["suggested_message"], str)
    assert len(result["suggested_message"]) > 50  # LLM 应该返 200-300 字话术
    assert isinstance(result["reasoning"], str)
    assert result["llm_call_id"] == ctx.call_id
    assert result["duration_ms"] >= 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def json_response_text() -> str:
    # 真实话术 200-300 字的中文 prompt 输出 mock;测试只验字段填充,不验长度
    # (因为 mock 的话术是 stub),所以下面 assertion 用 isinstance + non-empty,不强制长度。
    return (
        '{"suggested_message": "您好张总,上次沟通的产品 demo 我整理了一份 ROI 分析文档,从您公司的客户成功案例切入,展示了同类企业部署后 6 个月内的核心指标提升,希望对您有参考价值。如果方便,这周找个时间详细沟通一下?"'
        ', "suggested_next_follow_up_at": "2026-06-22T10:00:00"'
        ', "reasoning": "基于最近 3 次跟进,客户处于评估对比阶段,建议 2-3 天后跟进价格"}'
    )