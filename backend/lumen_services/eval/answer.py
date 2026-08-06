"""M37.2 — RAG answer generation for evaluation runs.

评测循环里「生成答案」的那一步:把检索到的 contexts + query 拼成 prompt,
调 chat 模型产出答案,再交给 judge 打 faithfulness / answer_relevancy。

设计跟 ``judge.py`` 对齐:

- ``call_type="eval_answer"`` —— LLMCallLog 按 call_type 区分「被评测的
  生成调用」和「judge 调用」(eval_judge),dashboard 能分开统计成本。
- ``extra={"eval_run_id": X, "eval_item_id": Y}`` —— 零 ALTER TABLE 就能
  从 trace 跳回具体 item。
- **绝不 raise**:生成失败返回 ``None``,runner 落库 answer=None,
  answer_metrics 只留规则指标。单条生成挂掉不拖垮整个 run。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2 答案指标
"""
from __future__ import annotations

import logging
import os
import uuid
from functools import lru_cache
from typing import List, Optional

from sqlalchemy.orm import Session

from lumen_core.llm_call_context import (
    LLMCallContext,
    get_call_context,
    reset_call_context,
    set_call_context,
)
from lumen_models.model_config import ModelConfig
from lumen_services.model_loader import create_chat_model

logger = logging.getLogger(__name__)

_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


@lru_cache(maxsize=1)
def _load_template() -> str:
    """加载答案生成 prompt 模板(prompts/answer_generation.txt)。"""
    path = os.path.join(_PROMPTS_DIR, "answer_generation.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def answer_generation_prompt(query: str, contexts: List[str]) -> str:
    """拼答案生成 prompt。contexts 标号,跟 faithfulness prompt 保持同一形态。

    contexts 为空时显式写「(无检索上下文)」,让模型走拒答分支 —— 这正是
    out_of_scope 类 item 期望的行为。
    """
    if contexts:
        numbered = "\n\n---\n\n".join(
            f"[context #{i + 1}]\n{c}" for i, c in enumerate(contexts)
        )
    else:
        numbered = "(无检索上下文)"
    return _load_template().format(contexts=numbered, query=query)


async def generate_answer(
    db: Session,
    *,
    query: str,
    contexts: List[str],
    model_config_id: int,
    eval_run_id: int,
    item_id: int,
    tenant_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> Optional[str]:
    """用 contexts 生成 RAG 答案;失败返回 None(不 raise)。"""
    parent = get_call_context()
    ctx = LLMCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=parent.trace_id if parent else str(uuid.uuid4()),
        parent_call_id=parent.call_id if parent else None,
        call_type="eval_answer",
        call_index=0,
        tenant_id=tenant_id or (parent.tenant_id if parent else None),
        user_id=user_id or (parent.user_id if parent else None),
        extra={"eval_run_id": eval_run_id, "eval_item_id": item_id},
    )
    token = set_call_context(ctx)
    try:
        mc: Optional[ModelConfig] = (
            db.query(ModelConfig)
            .filter(
                ModelConfig.id == model_config_id,
                ModelConfig.is_active.is_(True),
            )
            .first()
        )
        if mc is None:
            raise ValueError(
                f"ModelConfig #{model_config_id} not found or inactive"
            )
        chat = create_chat_model(
            model_type=mc.model_type,  # type: ignore[arg-type]
            model_name=mc.model_name,  # type: ignore[arg-type]
            base_url=mc.base_url,  # type: ignore[arg-type]
            api_key=mc.api_key,  # type: ignore[arg-type]
            temperature=mc.temperature or 0.0,  # type: ignore[arg-type]
            timeout=mc.timeout or 120,  # type: ignore[arg-type]
        )
        response = await chat.ainvoke(
            [{"role": "user", "content": answer_generation_prompt(query, contexts)}]
        )
        content = getattr(response, "content", str(response))
        text = str(content).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "eval answer generation failed (run=%s item=%s): %s",
            eval_run_id, item_id, exc,
        )
        return None
    finally:
        reset_call_context(token)
