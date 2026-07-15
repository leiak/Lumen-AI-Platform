"""LLMNode — workflow node that calls a chat model with a (templated) prompt.

Spec-bug fix (2026-06-04, Task 9): the plan's verbatim code called
``create_chat_model(type=...)``. The actual signature in
``app/services/model_loader.py`` is::

    def create_chat_model(
        model_type: str,        # <-- first positional
        model_name: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        ...
    )

so we pass ``model_type=`` (or positionally) and ``model_name=`` explicitly.

# Spec note: plan referenced "NodeExecError" but no such class exists in
# app/core/workflow/entities.py. Legacy executor uses ValueError, so we
# match that convention. Phase D may introduce a NodeExecError class.

# M16 (2026-06-10, Task 9): migrated from module-level
# ``get_active_skills`` shim to ``SkillRunner.get_active_skills`` which
# returns ``(prompts, tools)``. The chat pipeline added tool calling in
# T8 (see ``app/services/chat_service.py::stream_chat_messages``) and
# this node mirrors that behavior: when the runner returns a non-empty
# tools list, we ``bind_tools(...)`` and run the same max-5-rounds tool
# call loop on the LLM. The loop is intentionally duplicated rather
# than abstracted (per plan: "M16 范围:简单复制,等 V2 再 refactor").
"""

import asyncio
import logging
import uuid

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import ConfigDict, Field

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_services.llm_call_logging import extract_usage, extract_finish_reason
from lumen_services.model_loader import create_chat_model
from lumen_services.skill_runner import SkillRunner

logger = logging.getLogger(__name__)


class LLMNodeData(BaseNodeData):
    model_config = ConfigDict(protected_namespaces=())
    model_config_id: int | None = None
    model_name: str = ""
    prompt: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int | None = None
    skill_ids: list[int] = Field(default_factory=list)


class LLMNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return LLMNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="response", type=SegmentType.STRING, description="LLM 输出"),
            OutputVar(name="model", type=SegmentType.STRING, description="使用模型"),
            OutputVar(name="finish_reason", type=SegmentType.STRING, description="结束原因"),
            OutputVar(name="usage", type=SegmentType.OBJECT, description="token 用量"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, LLMNodeData)
        d = self._data
        resolved_prompt = VariableTemplateParser(d.prompt).format(self.pool)

        if d.model_config_id is not None and self.db is not None:
            from lumen_models.model_config import ModelConfig
            mc = (
                self.db.query(ModelConfig)
                .filter(
                    ModelConfig.id == d.model_config_id,
                    ModelConfig.is_active.is_(True),
                )
                .first()
            )
            if not mc:
                raise ValueError("模型配置已失效")
            chat = create_chat_model(
                model_type=mc.model_type,  # type: ignore[arg-type]
                model_name=mc.model_name,  # type: ignore[arg-type]
                base_url=mc.base_url,  # type: ignore[arg-type]
                api_key=mc.api_key,  # type: ignore[arg-type]
            )
            model_display = mc.model_name  # type: ignore[assignment]
        elif d.model_name:
            chat = create_chat_model(model_type="ollama", model_name=d.model_name)  # type: ignore[arg-type]
            model_display = d.model_name  # type: ignore[assignment]
        else:
            raise ValueError("未指定模型")

        # Build the prompt prefix. Order: skills (persona) → system_prompt → user.
        # SkillRunner enforces per-tenant ownership + active status. The block is
        # folded into the prompt string because chat.invoke() here takes a single
        # string argument (see LLMNode code; the messages-list form is used in the
        # /chat/stream pipeline).
        # M16 (2026-06-10, Task 9): SkillRunner returns (prompts, tools).
        # `prompts` still fold into the system-prompt prefix as before;
        # `tools` enable the bind_tools + tool_call loop below.
        rendered_skills: list = []
        bound_tools: list = []
        if d.skill_ids:
            if self.db is None:
                logger.warning("LLMNode %s: skill_ids set but no db session, skipping", self.node_id)
            else:
                tenant_id = self.config.get("tenant_id")
                if tenant_id is None:
                    logger.warning("LLMNode %s: no tenant_id in config, skipping skills", self.node_id)
                else:
                    rendered_skills, bound_tools = SkillRunner.get_active_skills(
                        self.db, tenant_id, d.skill_ids
                    )

        skill_block = "\n\n---\n\n".join(
            f"【技能:{s.name}】\n{s.content}" for s in rendered_skills
        )
        system_prompt = d.system_prompt or ""
        prefix_parts = [b for b in [skill_block, system_prompt] if b]
        prefix = "\n\n---\n\n".join(prefix_parts)
        final_prompt = (
            f"{prefix}\n\n---\n\n{resolved_prompt}" if prefix else resolved_prompt
        )

        # M16 (2026-06-10, Task 9): tool calling — mirror chat_service.py.
        # If the runner produced tools, bind them and run the max-5-rounds
        # loop. Otherwise fall back to the original single-invoke path.
        # M26: stamp an LLMCallContext so the LoggingChatModel wrapper
        # writes one row per LLM invocation. The trace_id was injected
        # by WorkflowExecutor._instantiate.
        trace_id = self.config.get("trace_id") or str(uuid.uuid4())
        workflow_id = self.config.get("workflow_id")
        workflow_run_id = self.config.get("workflow_run_id")
        ctx_token = set_call_context(LLMCallContext(
            call_id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_call_id=None,
            call_type="workflow.llm",
            call_index=0,
            tenant_id=self.config.get("tenant_id"),
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            workflow_node_id=self.node_id,
            extra={"skill_ids": list(d.skill_ids or [])},
        ))
        try:
            if bound_tools:
                response_text = await self._invoke_with_tools(
                    chat=chat,
                    tools=bound_tools,
                    final_prompt=final_prompt,
                    system_prompt=prefix if prefix else "",
                )
                # _invoke_with_tools doesn't expose the underlying
                # response object (it returns just the text). For MVP
                # we keep the existing 0-token / "stop" finish_reason
                # placeholders for tool-loop calls — the wrapper still
                # records tool_calls JSON when bind_tools is invoked
                # via .invoke (see LoggingChatModel.invoke).
                finish_reason_value = "stop"
                usage_value = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            else:
                response = await asyncio.to_thread(chat.invoke, final_prompt)
                # Use response.content rather than str(response) — LangChain's
                # AIMessage.__str__ dumps the full repr (content + metadata)
                # which we don't want leaking into the workflow output.
                response_text = response.content if isinstance(response.content, str) else str(response.content)
                # M26: read real finish_reason + usage from the response
                # object instead of the historical hard-coded "stop" /
                # 0-token placeholders. None when Ollama / provider
                # doesn't report — UI shows "N/A".
                finish_reason_value = extract_finish_reason(response) or "stop"
                usage_value = extract_usage(response) or {
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                }
        finally:
            reset_call_context(ctx_token)

        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "response": response_text,
                "model": model_display,
                "finish_reason": finish_reason_value,
                "usage": usage_value,
            },
        )

    @staticmethod
    async def _invoke_with_tools(
        chat,
        tools: list,
        final_prompt: str,
        system_prompt: str,
    ) -> str:
        """Run the tool-call loop on the LLM, mirroring chat_service.py.

        Loop contract:
          * Bind tools to the chat model.
          * Build a messages list (system + user) and invoke.
          * If the response carries ``tool_calls``, execute each tool via
            ``tool.run(...)``, append a ``ToolMessage`` (matched by
            tool_call_id) to the messages, and re-invoke.
          * Cap at 5 rounds of tool calls; if we hit the cap, return the
            content of the last assistant message (or "" if none).
          * If a tool raises, the error string is fed back to the LLM as
            a ``ToolMessage`` (so it can recover / apologize) — same
            behavior as chat_service.py.
        """
        chat_model = chat.bind_tools(tools)
        max_tool_rounds = 5
        messages: list = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=final_prompt))

        last_response = None
        for _round in range(max_tool_rounds + 1):
            last_response = await asyncio.to_thread(chat_model.invoke, messages)

            tool_calls = getattr(last_response, "tool_calls", None) or []
            if not tool_calls:
                return getattr(last_response, "content", "") or str(last_response)

            # Append the assistant turn that emitted the tool_calls so the
            # next model invocation has the full conversation context.
            messages.append(last_response)

            for tool_call in tool_calls:
                tool_name = (
                    tool_call.get("name")
                    if isinstance(tool_call, dict)
                    else getattr(tool_call, "name", None)
                )
                tool_args = (
                    tool_call.get("args")
                    if isinstance(tool_call, dict)
                    else getattr(tool_call, "args", {}) or {}
                )
                tool_id = (
                    tool_call.get("id")
                    if isinstance(tool_call, dict)
                    else getattr(tool_call, "id", None)
                )
                tool = next((t for t in tools if t.name == tool_name), None)
                if tool is None:
                    tool_result = f"Tool {tool_name} not found"
                else:
                    try:
                        tool_result = tool.run(tool_args)
                    except Exception as e:  # noqa: BLE001
                        tool_result = f"Tool error: {e}"
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id or "",
                ))

        # Max rounds exceeded — return whatever the last response had.
        if last_response is not None:
            content = getattr(last_response, "content", "") or ""
            if content:
                return content
        return ""
