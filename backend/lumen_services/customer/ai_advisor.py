"""M33 客户管理(CRM) - AI 智能建议 service.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §7.1
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T14

基于最近 N 条跟进 + 客户档案,推荐下次跟进话术和时间。
同步响应(5-15s);走 ``create_chat_model`` + ``LLMCallContext`` 自动登记 llm_call_logs。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional

from fastapi import HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import (
    LLMCallContext,
    reset_call_context,
    set_call_context,
)
from lumen_models.customer import Customer, CustomerFollowUp
from lumen_models.model_config import ModelConfig
from lumen_models.user import User
from lumen_services.model_loader import create_chat_model

log = logging.getLogger(__name__)


# call_type 常量 — 写到 llm_call_logs.call_type,可在 /dashboard/logs/llm-calls 过滤
CUSTOMER_CALL_TYPE_AI_SUGGEST = "customer.ai_suggest"

# Prompt 模板(中文,200-300 字建议)
SYSTEM_PROMPT = """你是一位销售顾问,擅长基于客户画像和跟进历史,推荐下次跟进的沟通话术和时间。

你的回复必须严格遵循 JSON 格式,不要包含任何其他文字或 markdown 标记:
{
  "suggested_message": "话术正文,200-300 字,自然不套路,贴合客户行业和当前阶段",
  "suggested_next_follow_up_at": "ISO 8601 datetime,推荐的下次跟进时间",
  "reasoning": "推荐依据,50-100 字,说明为什么这个时间和话术"
}
"""

USER_PROMPT = """# 客户档案
姓名: {name}
公司: {company_name} - {company_position}
等级: {level}
来源: {source}
标签: {tags}
自定义字段: {custom_fields}
备注: {remark}

# 最近跟进历史(最多 {history_limit} 条,时间倒序)
{follow_up_history}

# 本次关注点(可选)
{focus_line}

# 输出要求(严格 JSON)
输出一个 JSON 对象,包含 suggested_message / suggested_next_follow_up_at / reasoning 三个字段。"""


class AIAdvisor:
    """AI 智能建议 — 基于历史跟进 + 客户画像推荐下次话术和时间。"""

    def __init__(self, db: Session, current_user: User):
        self.db = db
        self.current_user = current_user

    # ---- 公开 API --------------------------------------------------------

    def suggest_next_step(
        self,
        customer: Customer,
        *,
        model_config_id: Optional[int] = None,
        focus: Optional[str] = None,
        history_limit: int = 5,
    ) -> dict:
        """生成 AI 智能建议。同步返回 dict。

        Returns
        -------
        dict with keys: suggested_message, suggested_next_follow_up_at,
        reasoning, llm_call_id, duration_ms
        """
        chat = self._resolve_chat_model(model_config_id)
        follow_ups = self._recent_follow_ups(customer.id, limit=history_limit)

        # LLMCallContext
        trace_id = str(uuid.uuid4())
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=None,
            call_type=CUSTOMER_CALL_TYPE_AI_SUGGEST,
            call_index=0,
            tenant_id=self.current_user.tenant_id,
            user_id=self.current_user.id,
            username=self.current_user.username,
            extra={
                "customer_id": customer.id,
                "focus": focus or "",
                "history_count": len(follow_ups),
            },
        )

        # Prompt 组装
        prompt = USER_PROMPT.format(
            name=customer.name,
            company_name=customer.company_name or "未填",
            company_position=customer.company_position or "未填",
            level=customer.level,
            source=customer.source or "未填",
            tags=", ".join(customer.tags or []) or "无",
            custom_fields=json.dumps(customer.custom_fields or {}, ensure_ascii=False),
            remark=customer.remark or "无",
            history_limit=history_limit,
            follow_up_history=self._format_follow_up_history(follow_ups),
            focus_line=f"关注点: {focus}" if focus else "(无指定)",
        )

        # 调 LLM
        t0 = time.monotonic()
        token = set_call_context(ctx)
        try:
            response = chat.invoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            response_text = self._extract_text(response)
        except Exception:
            log.exception(
                "AIAdvisor.suggest_next_step failed (customer_id=%s)", customer.id
            )
            raise
        finally:
            reset_call_context(token)
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "AIAdvisor.suggest_next_step: customer_id=%s duration_ms=%d",
            customer.id, duration_ms,
        )

        # 解析 JSON
        parsed = self._parse_response(response_text)

        return {
            "suggested_message": parsed["suggested_message"],
            "suggested_next_follow_up_at": parsed["suggested_next_follow_up_at"],
            "reasoning": parsed["reasoning"],
            "llm_call_id": call_id,
            "duration_ms": duration_ms,
        }

    # ---- helpers ---------------------------------------------------------

    def _resolve_chat_model(self, model_config_id: Optional[int]):
        """Spec §7.1 — 解析 model_config_id → create_chat_model。

        - model_config_id 给定 → 查 model_configs(同 tenant)
        - None → 查 tenant 默认 chat 模型
        - 都没有 → HTTPException(400, "no available chat model")
        """
        mc: Optional[ModelConfig] = None
        if model_config_id is not None:
            mc = (
                self.db.query(ModelConfig)
                .filter(
                    ModelConfig.id == model_config_id,
                    ModelConfig.is_active.is_(True),
                )
                .first()
            )
        if mc is None:
            mc = (
                self.db.query(ModelConfig)
                .filter(
                    ModelConfig.tenant_id == self.current_user.tenant_id,
                    ModelConfig.is_active.is_(True),
                    ModelConfig.is_chat.is_(True),
                )
                .order_by(ModelConfig.is_default.desc(), ModelConfig.id.asc())
                .first()
            )
        if mc is not None:
            return create_chat_model(
                model_type=mc.model_type,  # type: ignore[arg-type]
                model_name=mc.model_name,  # type: ignore[arg-type]
                base_url=mc.base_url,  # type: ignore[arg-type]
                api_key=mc.api_key,  # type: ignore[arg-type]
                temperature=mc.temperature or 0.7,  # type: ignore[arg-type]
                timeout=mc.timeout or 30,  # AI 智能建议 timeout 收紧到 30s
            )
        raise HTTPException(400, "no available chat model configured for this tenant")

    def _recent_follow_ups(
        self,
        customer_id: int,
        limit: int,
    ) -> List[CustomerFollowUp]:
        """拉最近 N 条跟进(按 created_at 倒序)。"""
        return (
            self.db.query(CustomerFollowUp)
            .filter(CustomerFollowUp.customer_id == customer_id)
            .order_by(CustomerFollowUp.created_at.desc())
            .limit(limit)
            .all()
        )

    def _format_follow_up_history(self, follow_ups: List[CustomerFollowUp]) -> str:
        """格式化跟进历史为 prompt 友好的多行字符串。"""
        if not follow_ups:
            return "(暂无跟进记录)"
        lines = []
        for fu in follow_ups:
            ts = fu.created_at.strftime("%Y-%m-%d") if fu.created_at else "?"
            line = (
                f"- [{ts}] 类型:{fu.follow_up_type} "
                f"内容:{fu.content[:200]}"
            )
            if fu.next_step:
                line += f" 下一步:{fu.next_step[:100]}"
            if fu.next_follow_up_at:
                line += f" 原定下次:{fu.next_follow_up_at.strftime('%Y-%m-%d')}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 LangChain AIMessage 抽 content。"""
        if hasattr(response, "content"):
            content = response.content
        else:
            content = str(response)
        # 部分模型可能返 list of content blocks
        if isinstance(content, list):
            return "".join(
                blk.get("text", "") if isinstance(blk, dict) else str(blk)
                for blk in content
            )
        return content or ""

    @staticmethod
    def _parse_response(response_text: str) -> dict:
        """解析 LLM 返回的 JSON 文本。

        处理 3 类常见 LLM 输出:
        1. 纯 JSON:`{...}` 直接 json.loads
        2. Markdown 包裹:```json\n{...}\n```
        3. 前后有杂文:``Here is the answer: {...}``

        失败时 raise HTTPException(500, "AI response parse failed")。
        """
        text = (response_text or "").strip()
        if not text:
            raise HTTPException(500, "AI returned empty response")

        # 尝试 1: 纯 JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试 2: 提取 markdown ```json ... ``` 块
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试 3: 找第一个 { 到最后一个 } 的内容
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        raise HTTPException(500, "AI response is not valid JSON")

    @staticmethod
    def _coerce_datetime(value: Any) -> Optional[datetime]:
        """把 LLM 输出的时间字符串规范化为 datetime;失败返 None。

        接受格式:
        - ISO 8601 完整 datetime: "2026-06-22T10:00:00"
        - 仅日期: "2026-06-22"(假设 10:00 默认)
        """
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        # 仅日期(10 字符)
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            try:
                d = datetime.strptime(text, "%Y-%m-%d")
                return d.replace(hour=10)
            except ValueError:
                return None
        # ISO 8601
        try:
            # 替换 Z 为 +00:00 让 fromisoformat 接受
            cleaned = text.replace("Z", "+00:00")
            # 优先用 fromisoformat(Python 3.11+ 支持更广)
            return datetime.fromisoformat(cleaned).replace(tzinfo=None)
        except (ValueError, TypeError):
            return None