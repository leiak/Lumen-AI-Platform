"""PPT Schema 生成服务（LLM 调用）。

Spec: docs-internal/superpowers/specs/m35-ppt-generation.md §9
"""
import json
import logging
import re
import uuid
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_models.model_config import ModelConfig
from lumen_models.chat import Conversation
from lumen_models.chat import Message as MessageModel
from lumen_services.model_loader import create_chat_model

logger = logging.getLogger(__name__)

PPT_SYSTEM_PROMPT = """你是专业的 PPT 大纲生成助手。根据对话内容生成结构化 JSON 大纲。

输出硬约束：
- 生成 7~10 个 slide 对象（封面 + 5~8 内容页 + 结束页），第 1 页 layout=title_only，最后 1 页 layout=blank（content 固定 ["谢谢观看"]）。
- layout 仅限 title_only / title_content / two_column / chart / blank。
- content / leftContent / rightContent 必须是字符串数组，每个元素不超过 30 字，**禁止任何占位符（必须填入真实内容）**。
- title 必须是该页内容的真实总结（如 "本周工程进展"、"核心 KPI 概览"），**严禁 "第N页标题"/"左栏要点" 这种占位**。
- chart.type 只能是：bar、line、pie；chart 页可选，最多 1 页。
- leftContent / rightContent 禁止嵌套数组；如果原文含表格或列表，提取其中关键信息（任务名、描述、状态等）作为要点，不要保留 markdown 表格格式。

风格调性（由 style 参数决定，内容必须体现该调性）：
- simple（简约）：内容要简洁克制，每页 3 条要点以内，无套话，直接呈现事实；适合内部周报。
- business（商务）：内容要专业正式，鼓励出现 KPI 数据 / 百分比 / 对比，两栏布局常用 "已完成 vs 进行中"；适合汇报。
- academic（学术）：内容要严谨学术化，允许出现 "研究背景 / 方法 / 数据 / 结论" 结构，鼓励带年份/百分比引用；适合论文报告。

输出格式（严格 JSON，共 7~10 个 slide 对象）：
{
  "title": "PPT标题",
  "subtitle": "副标题（可选）",
  "author": "Lumen AI",
  "slides": [
    {"layout": "title_only", "title": "封面标题", "subtitle": "副标题（可选）"},
    {"layout": "title_content", "title": "本周工作概览", "content": ["AI脚本生成功能上线，支持文案续写和角色设定", "多语言字幕生成已发布，支持10+语言", "素材检索召回率提升至93%"]},
    {"layout": "two_column", "title": "本周完成与下周计划", "leftContent": ["AI脚本生成功能开发完成", "多语言字幕功能已上线", "素材检索优化完成"], "rightContent": ["视频风格迁移开发中", "虚拟数字人形象定制启动", "数据分析看板开发中"]},
    {"layout": "chart", "title": "核心 KPI 概览", "chart": {"type": "bar", "title": "本周数据", "labels": ["周一", "周二", "周三", "周四", "周五"], "datasets": [{"name": "调用量", "values": [120, 145, 168, 132, 190]}]}},
    {"layout": "blank", "content": ["谢谢观看"]}
  ]
}

注意：chart 对象**必须**包含 type、title、labels、datasets 四个字段（标准 ECharts 格式），不要使用 data: [{name, value}] 这种简化格式。

只输出严格合法 JSON，不要任何解释、注释、Markdown 围栏。"""

PPT_TITLE_PROMPT = """根据以下对话内容，生成一个简洁的 PPT 标题（不超过 30 个字符）。

对话内容：
{conversation_text}

只返回一个 JSON 对象：{{"title": "标题", "subtitle": "副标题（可选）"}}"""


def _get_default_model_config(db: Session, tenant_id: int):
    """获取 tenant 默认的聊天模型配置。

    兼容性说明：历史 model_configs 数据 tenant_id=NULL（全租户共享），新数据 tenant_id=具体值。
    同一查询必须同时覆盖 NULL 和具体值，否则 SQL 里 ``NULL = N`` 永远 false。
    """
    # 1. tenant 专属默认 chat 模型
    cfg = db.query(ModelConfig).filter(
        ModelConfig.tenant_id == tenant_id,
        ModelConfig.is_default == True,  # noqa: E712
        ModelConfig.is_chat == True,
    ).first()
    # 2. 全局共享默认 chat 模型（tenant_id=NULL）
    if not cfg:
        cfg = db.query(ModelConfig).filter(
            ModelConfig.tenant_id.is_(None),
            ModelConfig.is_default == True,  # noqa: E712
            ModelConfig.is_chat == True,
        ).first()
    # 3. tenant 任意 chat 模型（不限 ollama）
    if not cfg:
        cfg = db.query(ModelConfig).filter(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.is_chat == True,
            ModelConfig.is_active == True,
        ).first()
    # 4. 全局任意 chat 模型
    if not cfg:
        cfg = db.query(ModelConfig).filter(
            ModelConfig.tenant_id.is_(None),
            ModelConfig.is_chat == True,
            ModelConfig.is_active == True,
        ).first()
    return cfg


def _messages_to_text(messages) -> str:
    """把 Message 列表转成可读文本。"""
    lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "AI"
        content = m.content if hasattr(m, "content") else str(m)
        lines.append(f"{role}：{content}")
    return "\n".join(lines)


def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出中鲁棒提取顶层 JSON 对象。

    依次尝试：1. 整段直接解析；2. 剥离 ```json``` 围栏；3. 平衡括号提取第一个顶层 {}。
    """
    if not text:
        return None
    try:
        result = json.loads(text)  # 1. 直接解析
        return result if isinstance(result, dict) else None
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        try:
            result = json.loads(m.group(1))  # 2. 剥离围栏
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    start = text.find("{")
    if start >= 0:
        depth, end = 0, start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if depth == 0:
            try:
                result = json.loads(text[start:end])  # 3. 平衡括号
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
    return None


class PptService:
    def build_schema(
        self,
        db: Session,
        tenant_id: int,
        user_id: int,
        conversation_id: int,
        title: Optional[str] = None,
        content_range: int = 10,
        include_charts: bool = False,
        style: str = "simple",
    ) -> "PptSchema":
        """调用 LLM 生成 PPT JSON Schema。"""
        from lumen_schemas.ppt import PptSchema

        # 1. 读取对话消息
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found")

        query = db.query(MessageModel).filter(
            MessageModel.conversation_id == conversation_id,
            MessageModel.role == "assistant",
        ).order_by(MessageModel.created_at.desc())

        if content_range > 0:
            query = query.limit(content_range)

        messages = query.all()
        if not messages:
            raise ValueError("对话没有任何消息")

        conv_text = _messages_to_text(messages)

        # 2. 获取模型
        cfg = _get_default_model_config(db, tenant_id)
        if not cfg:
            raise ValueError(f"No model config found for tenant {tenant_id}")

        chat = create_chat_model(
            model_type=cfg.model_type,
            model_name=cfg.model_name,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            temperature=0.3,
            timeout=300,
            model_config_id=cfg.id,
            max_tokens=4096,
        )

        trace_id = str(uuid.uuid4())

        def _new_ctx(call_index: int) -> LLMCallContext:
            """每次 LLM 调用都生成独立 call_id；trace_id 共享以串联同次 PPT 任务。"""
            return LLMCallContext(
                call_id=str(uuid.uuid4()),
                trace_id=trace_id,
                parent_call_id=None,
                call_type="ppt_generation",
                call_index=call_index,
                tenant_id=tenant_id,
                user_id=user_id,
                username="system",
                extra={"conversation_id": conversation_id},
            )

        # 3. 生成标题（如果未指定）
        if not title:
            title_prompt = PPT_TITLE_PROMPT.format(conversation_text=conv_text[:2000])
            try:
                token = set_call_context(_new_ctx(call_index=0))
                title_response = chat.invoke([HumanMessage(content=title_prompt)])
                title_content = title_response.content if hasattr(title_response, "content") else str(title_response)
                # 提取 JSON
                title_data = _extract_json(title_content)
                if title_data:
                    title = title_data.get("title", "PPT 演示文稿")
                    subtitle = title_data.get("subtitle")
                else:
                    title = "PPT 演示文稿"
                    subtitle = None
            except Exception as e:
                logger.warning("PPT title generation failed: %s", e)
                title = "PPT 演示文稿"
                subtitle = None
            finally:
                reset_call_context(token)
        else:
            subtitle = None

        # 4. 生成 PPT Schema
        content_prompt = f"""对话内容（最近 {content_range} 条）：
{conv_text}

请按 7~10 页（封面 + 5~8 内容页 + 结束页）生成结构化 PPT 大纲。

风格：{style}
包含图表：{"是" if include_charts else "否"}"""

        try:
            token = set_call_context(_new_ctx(call_index=1))
            response = chat.invoke([
                SystemMessage(content=PPT_SYSTEM_PROMPT),
                HumanMessage(content=content_prompt),
            ])
            content_str = response.content if hasattr(response, "content") else str(response)

            # 提取 JSON（直接解析 → 剥围栏 → 平衡括号）
            data = _extract_json(content_str)
            if data is None:
                # 修复重试：让 LLM 把上次输出重写成合法 JSON
                logger.warning("PPT JSON parse failed, attempting repair-retry")
                repair_token = set_call_context(_new_ctx(call_index=2))
                try:
                    repair_resp = chat.invoke([
                        SystemMessage(content="你是 JSON 格式化助手。上次输出不是合法 JSON，请把以下内容仅重写为严格合法 JSON，无任何解释："),
                        HumanMessage(content=content_str[:4000]),
                    ])
                finally:
                    reset_call_context(repair_token)
                repaired = repair_resp.content if hasattr(repair_resp, "content") else str(repair_resp)
                data = _extract_json(repaired)
            if data is None:
                raise ValueError("LLM 返回内容不是有效的 JSON（修复重试后仍失败）")

            schema = PptSchema(**data)
            # 覆盖标题
            schema.title = title
            if subtitle:
                schema.subtitle = subtitle

            return schema

        except Exception as e:
            logger.error("PPT schema generation failed: %s", e)
            raise ValueError(f"PPT 生成失败: {e}")
        finally:
            reset_call_context(token)
