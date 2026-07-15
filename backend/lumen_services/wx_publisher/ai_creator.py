"""M32 公众号助手 - AI 创作 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.2 / §7.1

CP3 范围 (T15):
- 4 个 prompt 模板 (OUTLINE / REWRITE / EXPAND / TITLE),作为类常量内嵌字符串。
  把模板集中放这里便于测试时检查完整性(无需读 prompt 文件)。
- 4 个公开方法: ``generate_outline`` / ``rewrite_section`` /
  ``expand_section`` / ``generate_titles``。
- 走 ``create_chat_model`` factory + ``LLMCallContext``(M26 ship)。
  LoggingChatModel 包装器自动写 1 行 ``llm_call_logs``(spec §1.3)。
- 4 个 call_type 常量供 notification_service / 测试 import 复用:
  ``WX_PUBLISHER_CALL_TYPE_OUTLINE`` / ``_REWRITE`` / ``_EXPAND`` / ``_TITLE``。

LLMCallContext 字段(参考 spec §4.2 / agent_rag / workflow LLMNode 模式):
- call_id = uuid4
- trace_id = uuid4
- call_type = 4 个 wx_publisher.* 之一
- tenant_id / user_id / draft_id
- 不用 Conversation/message/agent/team/workflow 关联(本模块不相关)

不在本 service 范围:
- 实际写 wx_drafts / wx_draft_sections(由 api 端调 draft_service 完成,
  本 service 只负责「给 api 一个 sections 列表 + 改写后文本 + 标题候选」)
- 模板渲染 (T16 renderer.py)
- 封面图 (M22 ImageGenerationService 复用,V2 阶段)
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from lumen_core.llm_call_context import (
    LLMCallContext,
    set_call_context,
    reset_call_context,
)
from lumen_models.model_config import ModelConfig
from lumen_models.user import User
from lumen_models.wx_publisher import WxDraft, WxDraftSection
from lumen_services.model_loader import create_chat_model

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 4 个 call_type 常量(供 notification_service / 测试 import)
# ---------------------------------------------------------------------------

WX_PUBLISHER_CALL_TYPE_OUTLINE = "wx_publisher.outline"
WX_PUBLISHER_CALL_TYPE_REWRITE = "wx_publisher.rewrite"
WX_PUBLISHER_CALL_TYPE_EXPAND = "wx_publisher.expand"
WX_PUBLISHER_CALL_TYPE_TITLE = "wx_publisher.title"


# ---------------------------------------------------------------------------
# 4 个 prompt 模板 — 集中内嵌字符串便于测试检查完整性
# ---------------------------------------------------------------------------

class WxAIPromptTemplates:
    """4 个 prompt 模板,内嵌常量字符串。

    模板输出要求"严格 JSON"以便 ``parse_*_response`` 用 ``json.loads`` 解析。
    若 LLM 偶发输出了 JSON 之外的字符(前后 ```json 包裹、解释文字),
    解析层会先尝试 ``json.loads``,失败时用 ``_extract_json_block`` 抢救
    出 ``{...}`` / ``[...]`` 块。
    """

    OUTLINE = """你是一位公众号写作助手,擅长 {style} 结构的爆款文章。
请根据以下主题,生成 {section_count} 个章节大纲,每个章节 1 句标题 + 1 段概要。

主题: {topic}

要求:
1. 章节标题用"一、二、三..."或"1. 2. 3."格式
2. 概要 30-80 字
3. 输出严格 JSON: {{ "sections": [{{ "heading": "...", "summary": "..." }}] }}
"""

    REWRITE = """你是一位公众号写作助手,请根据用户的改写指令重写下面这一段内容。

原始内容:
{original}

改写指令: {instruction}

要求:
1. 保留核心观点,但语气/结构按指令调整
2. 输出 markdown 格式
3. 只输出改写后的正文,不要任何解释或前后缀
"""

    EXPAND = """你是一位公众号写作助手,请将下面这一段内容扩写到大约 {target_chars} 字(原长度约 {original_chars} 字,目标扩展比 {expansion_ratio:.1f}x)。

原始内容:
{original}

要求:
1. 围绕原观点增加细节、案例或数据
2. 保持原有语气和结构
3. 输出 markdown 格式
4. 只输出扩写后的正文,不要任何解释或前后缀
"""

    TITLE = """你是一位公众号运营专家,擅长起高点击率的爆款标题。
请根据下面的文章主题 + 摘要,生成 {count} 个候选标题。

主题: {topic}

摘要: {summary}

要求:
1. 15-25 字,中文
2. 可适当用数字/疑问/对比等修辞
3. 输出严格 JSON: {{ "titles": ["标题1", "标题2", ...] }}
"""


# ---------------------------------------------------------------------------
# 解析辅助
# ---------------------------------------------------------------------------

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json_block(text: str) -> Optional[str]:
    """从 LLM 输出里抢救 JSON 块(允许 ```json 包裹、解释前后缀)。"""
    if not text:
        return None
    # 1. 直接尝试
    try:
        json.loads(text)
        return text
    except (ValueError, TypeError):
        pass
    # 2. 找 ```json ... ``` 围栏
    m = _JSON_FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    # 3. 找最外层 { ... } 或 [ ... ]
    for opener, closer in (("{", "}"), ("[", "]")):
        i = text.find(opener)
        if i == -1:
            continue
        j = text.rfind(closer)
        if j == -1 or j < i:
            continue
        return text[i : j + 1]
    return None


# ---------------------------------------------------------------------------
# 解析结果数据类
# ---------------------------------------------------------------------------

@dataclass
class OutlineSection:
    """``generate_outline`` 解析出的一个 section(head + summary)。"""

    heading: str
    summary: str
    order_index: int

    def to_markdown(self) -> str:
        """把 section 渲染成 markdown 文本(写到 ``WxDraftSection.content_markdown``)。"""
        heading = self.heading.strip() if self.heading else ""
        summary = self.summary.strip() if self.summary else ""
        if heading:
            return f"## {heading}\n\n{summary}" if summary else f"## {heading}"
        return summary or ""


# ---------------------------------------------------------------------------
# WxAICreator — 4 个公开方法
# ---------------------------------------------------------------------------

class WxAICreator:
    """AI 创作业务逻辑。Multi-tenant 通过 ``current_user.tenant_id`` 隔离。

    调用方(``api/v1/wx_publisher/drafts.py`` 的 T17 endpoint)传入 ``draft``
    + ``current_user``,方法内部:
    1. 解析 ``model_config_id``(None → 用该 tenant 的默认 chat 模型)
    2. 用 ``LLMCallContext`` 注入 trace_id + call_type + draft_id
    3. ``create_chat_model(...)`` 拿 LoggingChatModel proxy(M26 ship)
    4. ``chat.invoke(prompt)`` 调 LLM,LoggingChatModel 自动写 1 行 llm_call_logs
    5. 解析响应,返 (sections / new_text / titles)
    """

    def __init__(self, db: Session, current_user: User):
        self.db = db
        self.current_user = current_user

    # ---- public: outline ----

    def generate_outline(
        self,
        draft: WxDraft,
        *,
        topic: str,
        section_count: int = 5,
        model_config_id: Optional[int] = None,
        style: str = "总-分-总",
    ) -> List[WxDraftSection]:
        """AI 大纲生成:写 N 个 section 到 draft(spec §7.1)。

        Args:
            draft: 目标 draft(只读 — 不直接写,返 sections 让调用方写)
            topic: 文章主题
            section_count: 章节数 (3-10)
            model_config_id: 用的模型;None → tenant 默认 chat 模型
            style: 风格: 总-分-总 / 观点递进 / 故事+感悟 / FAQ 形式

        Returns:
            写入 ``wx_draft_sections`` 的 ``WxDraftSection`` 列表(已 commit)。
            sections 按 ``order_index`` ASC 排。**替换**现有 sections —
            ``wx_draft_sections`` UNIQUE(draft_id, order_index) 约束
            通过「先删后写」处理。
        """
        # 1. 解析模型
        chat = self._resolve_chat_model(model_config_id)
        # 2. LLMCallContext
        trace_id = str(uuid.uuid4())
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=None,
            call_type=WX_PUBLISHER_CALL_TYPE_OUTLINE,
            call_index=0,
            tenant_id=self.current_user.tenant_id,
            user_id=self.current_user.id,
            username=self.current_user.username,
            extra={
                "draft_id": draft.id,
                "section_count": section_count,
                "style": style,
            },
        )
        # 3. 调 LLM
        prompt = WxAIPromptTemplates.OUTLINE.format(
            style=style, section_count=section_count, topic=topic,
        )
        t0 = time.monotonic()
        token = set_call_context(ctx)
        try:
            response = chat.invoke(prompt)
            response_text = self._extract_text(response)
        except Exception:
            log.exception("generate_outline: LLM call failed (draft_id=%s)", draft.id)
            raise
        finally:
            reset_call_context(token)
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "generate_outline: draft_id=%s duration_ms=%d", draft.id, duration_ms,
        )
        # 4. 解析 JSON → sections
        outline_sections = self._parse_outline_response(response_text, expected=section_count)
        # 5. 写库:先删现有 sections(避免 UNIQUE 冲突)
        self._replace_sections(draft=draft, outline_sections=outline_sections)
        # 6. 返新建 sections list
        return self._list_sections_ordered(draft=draft)

    # ---- public: rewrite ----

    def rewrite_section(
        self,
        section: WxDraftSection,
        *,
        instruction: str,
        model_config_id: Optional[int] = None,
    ) -> str:
        """AI 改写指定 section(不自动写,让 UI 弹 Diff Modal 让用户点「应用」)。

        Args:
            section: 目标 section(只读,本方法不写库)
            instruction: 改写指令(例: "改得更口语化,加 1 个案例")
            model_config_id: 用的模型;None → tenant 默认 chat 模型

        Returns:
            改写后的 markdown 文本。
        """
        chat = self._resolve_chat_model(model_config_id)
        trace_id = str(uuid.uuid4())
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=None,
            call_type=WX_PUBLISHER_CALL_TYPE_REWRITE,
            call_index=0,
            tenant_id=self.current_user.tenant_id,
            user_id=self.current_user.id,
            username=self.current_user.username,
            extra={
                "draft_id": section.draft_id,
                "section_id": section.id,
                "instruction": instruction[:200],
            },
        )
        prompt = WxAIPromptTemplates.REWRITE.format(
            original=section.content_markdown, instruction=instruction,
        )
        token = set_call_context(ctx)
        try:
            response = chat.invoke(prompt)
            response_text = self._extract_text(response)
        except Exception:
            log.exception(
                "rewrite_section: LLM call failed (section_id=%s)", section.id,
            )
            raise
        finally:
            reset_call_context(token)
        return (response_text or "").strip()

    # ---- public: expand ----

    def expand_section(
        self,
        section: WxDraftSection,
        *,
        expansion_ratio: float = 1.5,
        model_config_id: Optional[int] = None,
    ) -> str:
        """AI 扩写:在原内容基础上扩 ``expansion_ratio`` 倍(spec §4.2)。

        Args:
            section: 目标 section(只读)
            expansion_ratio: 扩写比 (1.2 - 3.0,1.5 默认)
            model_config_id: 用的模型;None → tenant 默认 chat 模型

        Returns:
            扩写后的 markdown 文本。
        """
        chat = self._resolve_chat_model(model_config_id)
        original_chars = len(section.content_markdown or "")
        target_chars = max(int(original_chars * expansion_ratio), original_chars + 50)
        trace_id = str(uuid.uuid4())
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=None,
            call_type=WX_PUBLISHER_CALL_TYPE_EXPAND,
            call_index=0,
            tenant_id=self.current_user.tenant_id,
            user_id=self.current_user.id,
            username=self.current_user.username,
            extra={
                "draft_id": section.draft_id,
                "section_id": section.id,
                "expansion_ratio": expansion_ratio,
                "original_chars": original_chars,
                "target_chars": target_chars,
            },
        )
        prompt = WxAIPromptTemplates.EXPAND.format(
            original=section.content_markdown,
            target_chars=target_chars,
            original_chars=original_chars,
            expansion_ratio=expansion_ratio,
        )
        token = set_call_context(ctx)
        try:
            response = chat.invoke(prompt)
            response_text = self._extract_text(response)
        except Exception:
            log.exception(
                "expand_section: LLM call failed (section_id=%s)", section.id,
            )
            raise
        finally:
            reset_call_context(token)
        return (response_text or "").strip()

    # ---- public: title ----

    def generate_titles(
        self,
        draft: WxDraft,
        *,
        count: int = 5,
        model_config_id: Optional[int] = None,
    ) -> List[str]:
        """AI 标题候选(不自动写 draft.title,让 UI 弹候选列表让用户挑)。

        Args:
            draft: 目标 draft(只读,本方法不写 draft.title)
            count: 候选标题数 (3 - 8)
            model_config_id: 用的模型;None → tenant 默认 chat 模型

        Returns:
            标题候选 list[str]。去空 + 去重 + 保序。
        """
        chat = self._resolve_chat_model(model_config_id)
        topic = draft.title or ""
        summary = draft.summary or draft.content_markdown[:200] if draft.content_markdown else ""
        trace_id = str(uuid.uuid4())
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=None,
            call_type=WX_PUBLISHER_CALL_TYPE_TITLE,
            call_index=0,
            tenant_id=self.current_user.tenant_id,
            user_id=self.current_user.id,
            username=self.current_user.username,
            extra={"draft_id": draft.id, "count": count},
        )
        prompt = WxAIPromptTemplates.TITLE.format(
            topic=topic, summary=summary, count=count,
        )
        token = set_call_context(ctx)
        try:
            response = chat.invoke(prompt)
            response_text = self._extract_text(response)
        except Exception:
            log.exception("generate_titles: LLM call failed (draft_id=%s)", draft.id)
            raise
        finally:
            reset_call_context(token)
        titles = self._parse_titles_response(response_text)
        # 去空 + 去重(保序)
        seen: set = set()
        out: List[str] = []
        for t in titles:
            t = (t or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out[:count]

    # ---- helpers ----

    def _resolve_chat_model(self, model_config_id: Optional[int]):
        """解析 model_config_id → create_chat_model(...)。

        - ``model_config_id`` 给定 → 查 model_configs 表(MVP 限制同 tenant)
        - None → 查该 tenant 的默认 chat 模型
        - 都没有 → fallback Ollama qwen2.5:7b(项目惯例,见 chat_service.py:24-32)
        """
        mc: Optional[ModelConfig] = None
        if model_config_id is not None:
            mc = self.db.query(ModelConfig).filter(
                ModelConfig.id == model_config_id,
                ModelConfig.is_active.is_(True),
            ).first()
        if mc is None:
            mc = self.db.query(ModelConfig).filter(
                ModelConfig.tenant_id == self.current_user.tenant_id,
                ModelConfig.is_active.is_(True),
                ModelConfig.is_chat.is_(True),
            ).order_by(ModelConfig.is_default.desc(), ModelConfig.id.asc()).first()
        if mc is not None:
            return create_chat_model(
                model_type=mc.model_type,  # type: ignore[arg-type]
                model_name=mc.model_name,  # type: ignore[arg-type]
                base_url=mc.base_url,  # type: ignore[arg-type]
                api_key=mc.api_key,  # type: ignore[arg-type]
                temperature=mc.temperature or 0.7,  # type: ignore[arg-type]
                timeout=mc.timeout or 120,  # type: ignore[arg-type]
                model_config_id=mc.id,  # type: ignore[arg-type]
            )
        # Fallback: ollama 默认
        return create_chat_model(
            model_type="ollama",
            model_name="qwen2.5:7b",
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 LangChain AIMessage 取文本。"""
        if response is None:
            return ""
        content = getattr(response, "content", None)
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        # list-of-parts(Anthropic 等) → 拼文本
        if isinstance(content, list):
            parts: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    t = part.get("text")
                    if t:
                        parts.append(str(t))
                elif isinstance(part, str):
                    parts.append(part)
            return "\n".join(parts)
        return str(content)

    def _parse_outline_response(
        self, text: str, expected: int,
    ) -> List[OutlineSection]:
        """解析 ``{ "sections": [{heading, summary}] }`` JSON 响应。"""
        body = _extract_json_block(text) or ""
        if not body:
            raise ValueError("AI outline response is empty / not JSON")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"AI outline response is not valid JSON: {e}")
        sections_raw = data.get("sections") if isinstance(data, dict) else None
        if not isinstance(sections_raw, list):
            raise ValueError("AI outline response missing 'sections' list")
        out: List[OutlineSection] = []
        for idx, item in enumerate(sections_raw[:expected]):
            if not isinstance(item, dict):
                continue
            heading = (item.get("heading") or "").strip() or f"第{idx + 1}节"
            summary = (item.get("summary") or "").strip()
            out.append(OutlineSection(heading=heading, summary=summary, order_index=idx))
        if not out:
            raise ValueError("AI outline response had no usable sections")
        # 补齐到 expected(LLM 偶尔漏返 1-2 个,补空 summary 短段)
        while len(out) < expected:
            i = len(out)
            out.append(OutlineSection(heading=f"第{i + 1}节", summary="", order_index=i))
        return out

    def _parse_titles_response(self, text: str) -> List[str]:
        """解析 ``{ "titles": ["标题1", ...] }`` JSON 响应。"""
        body = _extract_json_block(text) or ""
        if not body:
            return []
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return []
        titles_raw = data.get("titles") if isinstance(data, dict) else None
        if not isinstance(titles_raw, list):
            return []
        out: List[str] = []
        for item in titles_raw:
            if isinstance(item, str):
                out.append(item.strip())
        return [t for t in out if t]

    def _replace_sections(
        self, *, draft: WxDraft, outline_sections: List[OutlineSection],
    ) -> None:
        """删除 draft 现有 sections,写入新 sections(spec §4.2 "替换现有 sections")。

        走 ``wx_draft_sections`` 的 ``draft_id`` FK + CASCADE 删除的语义:
        直接 ``db.query(WxDraftSection).filter(draft_id=...).delete()``。
        """
        # 1. 删现有
        self.db.query(WxDraftSection).filter(
            WxDraftSection.draft_id == draft.id,
        ).delete(synchronize_session=False)
        self.db.commit()
        # 2. 写新
        for s in outline_sections:
            row = WxDraftSection(
                tenant_id=draft.tenant_id,
                draft_id=draft.id,
                order_index=s.order_index,
                heading=s.heading,
                content_markdown=s.to_markdown(),
                content_html=None,
                ai_prompt=(
                    f"style=总-分-总,section_count={len(outline_sections)}"
                ),
            )
            self.db.add(row)
        self.db.commit()

    def _list_sections_ordered(self, *, draft: WxDraft) -> List[WxDraftSection]:
        """返 draft 的 sections,按 order_index ASC 排。"""
        return self.db.query(WxDraftSection).filter(
            WxDraftSection.draft_id == draft.id,
        ).order_by(WxDraftSection.order_index.asc()).all()
