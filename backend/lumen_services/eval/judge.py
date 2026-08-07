"""M37.2 — LLM-as-judge 客户端。

封装 judge LLM 调用,沿用项目 create_chat_model + LLMCallContext 模式:

- ``call_type="eval_judge"`` —— LLMCallLog 行的 call_type 字段填这个
  值,便于 M37.3 dashboard 按 call_type 过滤评测 trace。
- ``extra={"eval_run_id": X, "eval_metric": "faithfulness"}`` —— 把
  eval_run_id 塞进 LLMCallLog 的 JSON extra 列,**零 ALTER TABLE** 就
  能从 trace 跳回 eval_run。
- 严格 schema 输出(``extra="forbid"``)+ judge prompt 强制 JSON —— 守
  D8:LLM judge 自身不确定时,Pydantic strict schema 兜底。
- 解析失败 / LLM 失败 → 返 ``score=0, reasoning="judge parse failed"``,
  不 raise —— 让 runner 继续跑完所有 item,不因单条 judge 失败而中断。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2 答案指标
Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T11 + D8
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, Generic, Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field
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


# ---------------------------------------------------------------------------
# Judge 输出 strict schemas(plan D8:extra="forbid" 兜底 judge 不确定)
# ---------------------------------------------------------------------------


class _JudgeScoreBase(BaseModel):
    """judge 输出的公共字段。

    ``model_config = ConfigDict(extra="forbid")`` 拒绝任何额外字段,
    防止 LLM 在 JSON 里夹带解释文字 / 重复字段,被 Pydantic 静默忽略
    导致 audit 漏字段。``reasoning`` 限 500 字防 LLM 写小说。
    """

    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=2, description="0/1/2 三档,见对应 judge prompt 评分标准")
    reasoning: str = Field(max_length=500, description="简短解释,中文")


class FaithfulnessScore(_JudgeScoreBase):
    """faithfulness judge 输出 —— 答案是否被上下文支撑(0/1/2)。"""

    # 类型化字段让 mypy 能区分 FaithfulnessScore / AnswerRelevancyScore
    pass


class AnswerRelevancyScore(_JudgeScoreBase):
    """answer_relevancy judge 输出 —— 答案是否回答了 query(0/1/2)。"""

    pass


# ---------------------------------------------------------------------------
# judge 响应解析 —— 纯函数,易测
# ---------------------------------------------------------------------------


def _extract_json_object(text: str) -> Optional[str]:
    """在 text 中 brace-balance 找第一个 ``{...}`` JSON object。

    LLM 偶尔在自然语言里夹 JSON(没 ```` ```json ```` fence 也没
    ``<think>`` 块),例如「我的评估如下。{...}」。从第一个 ``{``
    开始 brace 计数,字符串内 ``"`` 跳过(支持 ``\"`` 转义),找到
    匹配的 ``}`` 时返回该 JSON 子串。找不到返回 ``None``,让上层
    抛 ValueError 兜底。

    比 ``json.JSONDecoder.raw_decode`` 优势:即使 JSON 前面贴着自然
    语言(开头不是 ``{``)也能从第一个 ``{`` 起扫;raw_decode 要
    求起点必须是合法 JSON 头,贴 prose 时直接抛。
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            # \" 转义:吃掉这个字符,下个字符按字面意义处理
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_judge_response(
    content: str, response_format: Type[_TModel]
) -> _TModel:
    """把 LLM 原始输出解析成 strict schema 实例。

    兼容 4 种常见 LLM 输出形态:

    1. 纯 JSON(直接 ``model_validate_json``)
    2. ```` ```json ... ``` ```` 完整包(头尾都有 fence)
    3. 「客套话 + JSON + 客套话」混合 —— LLM 经常先说「我的评估如下」
       再贴 JSON。regex 抓 ```` ``` ```` 代码块内容。
    4. 推理模型(deepseek-r1 / MiniMax-M3)先吐 ``<think>...</think>``
       推理块,再贴 JSON —— 剥 think 块后用 brace-balance 兜底抓 JSON。

    解析失败抛 ``ValueError``(由 JudgeClient 兜底,转为 score=0)。
    """
    text = content.strip()
    # 路径 1:regex 兜底 ```` ```json ... ``` ```` 完整包(原行为,优先)。
    # re.DOTALL 让 . 匹配换行;非贪婪 .*? 防止跨多个代码块错抓。
    md_match = re.search(
        r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL
    )
    if md_match:
        text = md_match.group(1).strip()
    else:
        # 路径 2:推理模型(deepseek-r1 / MiniMax-M3)会先吐
        # ``<think>...</think>`` 推理块再贴 JSON。think 块内可能有
        # 反引号 / 嵌套 brace,不能直接 brace-balance —— 先剥 think
        # 块再继续。re.DOTALL 让 .*? 跨换行,非贪婪匹配最近 ``</think>``。
        think_match = re.search(r"<think>.*?</think>", text, re.DOTALL)
        if think_match:
            text = (text[: think_match.start()] + text[think_match.end() :]).strip()

    # 路径 3:LLM 在自然语言里夹 JSON 时,brace-balance 找 ``{...}``。
    # ``text.startswith("{")`` 直接走 json.loads;否则扫 brace 边界。
    if not text.startswith("{"):
        obj = _extract_json_object(text)
        if obj is None:
            raise ValueError(f"judge output not a JSON object: {text[:200]!r}")
        text = obj

    # 严格 JSON 解析 + Pydantic 严格 schema 校验
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"judge output not a JSON object: {type(data).__name__}")
    return response_format.model_validate(data)


def make_parse_failed_response(
    response_format: Type[_TModel], reason: str = "judge parse failed"
) -> _TModel:
    """构造「解析失败」的安全 fallback —— score=0 + 错误 reason。

    用 ``response_format.model_validate`` 走 strict schema 校验,确保
    fallback 也能过 extra="forbid" 校验,不会偷偷破坏 schema 契约。
    """
    return response_format.model_validate({"score": 0, "reasoning": reason})


# ---------------------------------------------------------------------------
# JudgeClient
# ---------------------------------------------------------------------------

_TModel = TypeVar("_TModel", bound=_JudgeScoreBase)


class JudgeClient(Generic[_TModel]):
    """LLM-as-judge 客户端,封装 context 设置 + LLM 调用 + 解析兜底。

    Usage:
        client = JudgeClient(
            db, model_config_id=2, eval_run_id=42, metric="faithfulness",
        )
        score = await client.call(prompt, FaithfulnessScore)
        # score.score == 0 表示 judge 解析失败,见 reasoning 字段
    """

    def __init__(
        self,
        db: Session,
        *,
        model_config_id: int,
        eval_run_id: int,
        metric: str,
        tenant_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> None:
        self.db = db
        self.model_config_id = model_config_id
        self.eval_run_id = eval_run_id
        self.metric = metric
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def call(
        self, prompt: str, response_format: Type[_TModel]
    ) -> _TModel:
        """调 judge LLM + 解析响应,失败兜底返 score=0。

        Args:
            prompt: 完整 prompt 字符串(由 metrics.py 的 faithfulness_prompt /
                answer_relevancy_prompt 构造)。
            response_format: strict schema,FaithfulnessScore 或
                AnswerRelevancyScore。

        Returns:
            response_format 实例。**绝不 raise** —— judge 失败/解析失败
            统一返 ``score=0, reasoning="judge parse failed: <原因>"``,
            让 runner 继续跑完所有 item(plan D5 per-item commit 配合)。
        """
        ctx = self._build_context()
        token = set_call_context(ctx)
        try:
            chat = self._build_chat_model()
            response = await chat.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            content = getattr(response, "content", str(response))
            try:
                return parse_judge_response(content, response_format)
            except (ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "judge parse failed (eval_run_id=%s metric=%s): %s",
                    self.eval_run_id,
                    self.metric,
                    exc,
                )
                return make_parse_failed_response(
                    response_format, reason=f"judge parse failed: {exc}"
                )
        except Exception as exc:  # noqa: BLE001
            # LLM 调用层任何异常(网络 / 配置错 / rate limit)同样兜底,
            # 不让单条 item 把整个 run 拖崩。
            logger.warning(
                "judge LLM call failed (eval_run_id=%s metric=%s): %s",
                self.eval_run_id,
                self.metric,
                exc,
            )
            return make_parse_failed_response(
                response_format, reason=f"judge parse failed: {exc}"
            )
        finally:
            reset_call_context(token)

    def _build_context(self) -> LLMCallContext:
        """构造 LLMCallContext,call_type=eval_judge,extra 带 eval_run_id。

        沿用 chat / widget / workflow.llm 同一模式 —— LLMCallContext
        是 NamedTuple,所有字段都有默认;我们只需 set 跟评测相关的
        几个。``trace_id`` 默认空字符串 —— runner 在外层创建 trace 时
        通常已经 set 了一个,继承外层即可(``get_call_context`` 取)。
        """
        parent = get_call_context()
        call_id = str(uuid.uuid4())
        # 继承外层 trace_id(让同一 run 的所有 judge call 共享一条 trace,
        # dashboard 按 trace_id GROUP BY 能看到完整 judge 时间线)
        trace_id = parent.trace_id if parent else str(uuid.uuid4())
        return LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=parent.call_id if parent else None,
            call_type="eval_judge",
            call_index=0,
            tenant_id=self.tenant_id or (parent.tenant_id if parent else None),
            user_id=self.user_id or (parent.user_id if parent else None),
            extra={
                "eval_run_id": self.eval_run_id,
                "eval_metric": self.metric,
            },
        )

    def _build_chat_model(self):
        """按 model_config_id 查 DB → 构造 LoggingChatModel(同 wx_publisher/ai_creator._resolve_chat_model 模式)。

        ModelConfig 找不到对应行(被删 / inactive)→ ValueError —— 让
        JudgeClient.call() 的 except 兜底返 score=0,不 raise 给 runner。
        """
        mc: Optional[ModelConfig] = (
            self.db.query(ModelConfig)
            .filter(
                ModelConfig.id == self.model_config_id,
                ModelConfig.is_active.is_(True),
            )
            .first()
        )
        if mc is None:
            raise ValueError(
                f"ModelConfig #{self.model_config_id} not found or inactive"
            )
        return create_chat_model(
            model_type=mc.model_type,  # type: ignore[arg-type]
            model_name=mc.model_name,  # type: ignore[arg-type]
            base_url=mc.base_url,  # type: ignore[arg-type]
            api_key=mc.api_key,  # type: ignore[arg-type]
            temperature=mc.temperature or 0.0,  # type: ignore[arg-type]
            timeout=mc.timeout or 120,  # type: ignore[arg-type]
        )
