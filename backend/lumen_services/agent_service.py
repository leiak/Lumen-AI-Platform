from typing import List, Optional, Dict, Any
import logging
from sqlalchemy.orm import Session, joinedload
from lumen_models.agent import Agent, AgentTool, AgentKnowledgeBase
from lumen_models.user import User
from lumen_models.model_config import ModelConfig

logger = logging.getLogger(__name__)
from lumen_models.knowledge import KnowledgeBase
from lumen_schemas.agent import AgentCreate, AgentUpdate
from lumen_core.tenant import TenantContext
from langchain_core.messages import HumanMessage, SystemMessage
from lumen_tools.vector_store_factory import VectorStoreFactory
from lumen_services.model_loader import create_chat_model

# NOTE: the memory / tool_choice helpers live in app.services.agents.*.
# Importing them at module load time would create a circular import
# (agents/__init__.py -> team.py -> app.services.agent_service -> agents.*).
# We import them lazily inside the methods that need them.


class AgentService:
    def __init__(self):
        # No longer cache a single shared vector_store. Each KB has its
        # own embedding model now; chat() picks the right store per KB.
        pass

    def list_agents(self, db: Session, tenant_id: int) -> List[Agent]:
        # M21: joinedload 让 router 序列化时不需要 lazy-load KB refs
        return (
            db.query(Agent)
            .options(
                joinedload(Agent.knowledge_bases).joinedload(AgentKnowledgeBase.knowledge_base)
            )
            .filter(Agent.tenant_id == tenant_id)
            .all()
        )

    def create_agent(
        self, db: Session, tenant_id: int, data: AgentCreate, user: User
    ) -> Agent:
        agent = Agent(
            name=data.name,
            description=data.description,
            prompt_template=data.prompt_template,
            model_name=data.model_name,
            temperature=data.temperature,
            tenant_id=tenant_id,
            # --- Memory policy (Task 8) ---
            memory_policy=data.memory_policy or "sliding_window",
            memory_window_size=data.memory_window_size if data.memory_window_size is not None else 20,
            memory_max_tokens=data.memory_max_tokens if data.memory_max_tokens is not None else 4000,
            memory_compression=bool(data.memory_compression),
            # --- Tool choice (Task 8) ---
            tool_choice=data.tool_choice or "auto",
            tool_choice_required=bool(data.tool_choice_required),
            allowed_tools=list(data.allowed_tools or []),
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)

        # Add tools
        if data.tool_names:
            for tool_name in data.tool_names:
                tool = AgentTool(agent_id=agent.id, tool_name=tool_name)
                db.add(tool)

        # Add knowledge bases
        if data.knowledge_base_ids:
            for kb_id in data.knowledge_base_ids:
                akb = AgentKnowledgeBase(agent_id=agent.id, knowledge_base_id=kb_id)
                db.add(akb)

        db.commit()
        db.refresh(agent)
        return agent

    def get_agent(self, db: Session, agent_id: int, tenant_id: int) -> Optional[Agent]:
        # M21: joinedload 让 router 序列化时不需要 lazy-load KB refs
        return (
            db.query(Agent)
            .options(
                joinedload(Agent.knowledge_bases).joinedload(AgentKnowledgeBase.knowledge_base)
            )
            .filter(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
            )
            .first()
        )

    def update_agent(
        self, db: Session, agent_id: int, tenant_id: int, data: AgentUpdate
    ) -> Optional[Agent]:
        agent = self.get_agent(db, agent_id, tenant_id)
        if not agent:
            return None

        # 现有 scalar 字段更新(只更新 AgentUpdate 里显式传入的字段)
        for field in [
            "name", "description", "prompt_template", "model_name",
            "temperature", "is_active", "memory_policy", "memory_window_size",
            "memory_max_tokens", "memory_compression", "tool_choice",
            "tool_choice_required",
        ]:
            value = getattr(data, field, None)
            if value is not None:
                setattr(agent, field, value)
        # allowed_tools 特殊处理:None 表示不动,[] 表示显式清空
        if data.allowed_tools is not None:
            agent.allowed_tools = data.allowed_tools  # type: ignore[assignment]

        # M21: 同步 knowledge_base_ids(差量 — 删旧的增新的,中间层保留)
        if data.knowledge_base_ids is not None:
            existing_ids = {b.knowledge_base_id for b in agent.knowledge_bases}
            new_ids = set(data.knowledge_base_ids)
            # 删:不 list() snapshot 会让 in-place db.delete 跳过尾段
            for binding in list(agent.knowledge_bases):
                if binding.knowledge_base_id not in new_ids:
                    db.delete(binding)
            # 增:校验 KB 存在 + tenant 匹配(防 cross-tenant 注入)
            for kb_id in new_ids - existing_ids:
                kb = db.get(KnowledgeBase, kb_id)
                if kb is None or kb.tenant_id != tenant_id:
                    raise ValueError(f"KB {kb_id} not found or not in tenant")
                agent.knowledge_bases.append(
                    AgentKnowledgeBase(knowledge_base_id=kb_id)
                )

        # M21: 同步 kb_retrieval_config(范围校验)
        if data.kb_retrieval_config is not None:
            cfg = data.kb_retrieval_config
            top_k = cfg.get("top_k", 3)
            rrf_k = cfg.get("rrf_k", 30)
            if not (1 <= int(top_k) <= 10):
                raise ValueError("top_k must be in [1, 10]")
            if not (10 <= int(rrf_k) <= 100):
                raise ValueError("rrf_k must be in [10, 100]")
            agent.kb_retrieval_config = cfg  # type: ignore[assignment]

        db.commit()
        # 显式刷新 knowledge_bases 关系 — 普通 db.refresh 不重载 relationship,
        # 会让 router 序列化时拿到 diff sync 前的旧集合。
        db.refresh(agent, attribute_names=["knowledge_bases"])
        return agent

    def delete_agent(self, db: Session, agent_id: int, tenant_id: int) -> bool:
        agent = self.get_agent(db, agent_id, tenant_id)
        if not agent:
            return False
        db.delete(agent)
        db.commit()
        return True

    def _get_model_config(self, db: Session, model_name: str, tenant_id: int) -> Optional[ModelConfig]:
        """Look up model config by model_name or model_type pattern."""
        # Try exact match on model_name first
        config = db.query(ModelConfig).filter(
            ModelConfig.model_name == model_name,
            ModelConfig.is_active == True,
            (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
        ).first()

        if config:
            return config

        # Try matching by model_type pattern (e.g., "minimax" in model_name)
        model_lower = model_name.lower()
        if "minimax" in model_lower:
            config = db.query(ModelConfig).filter(
                ModelConfig.model_type == "minimax",
                ModelConfig.is_active == True,
                (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).first()
        elif "gpt" in model_lower or "openai" in model_lower:
            config = db.query(ModelConfig).filter(
                ModelConfig.model_type == "openai",
                ModelConfig.is_active == True,
                (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).first()
        elif "claude" in model_lower or "anthropic" in model_lower:
            config = db.query(ModelConfig).filter(
                ModelConfig.model_type == "anthropic",
                ModelConfig.is_active == True,
                (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).first()
        elif "glm" in model_lower or "zhipu" in model_lower:
            config = db.query(ModelConfig).filter(
                ModelConfig.model_type == "zhipu",
                ModelConfig.is_active == True,
                (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).first()
        elif "ollama" in model_lower:
            config = db.query(ModelConfig).filter(
                ModelConfig.model_type == "ollama",
                ModelConfig.is_active == True,
                (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None))
            ).first()

        return config

    def chat(
        self,
        db: Session,
        agent_id: int,
        tenant_id: int,
        message: str,
        history: List[Dict[str, str]] = None,
        user: Optional[User] = None,
    ) -> str:
        logger.info("[AgentService.chat] agent_id=%s, tenant_id=%s", agent_id, tenant_id)
        agent = self.get_agent(db, agent_id, tenant_id)
        if not agent:
            raise ValueError("Agent not found")
        logger.info("[AgentService.chat] agent found: %s, model=%s", agent.name, agent.model_name)

        # Get knowledge base context
        knowledge_context = ""
        kb_links = db.query(AgentKnowledgeBase).filter(
            AgentKnowledgeBase.agent_id == agent_id
        ).all()
        logger.info("[AgentService.chat] kb_links count: %s", len(kb_links))

        if kb_links:
            kb_ids = [link.knowledge_base_id for link in kb_links]
            # Look up each KB's embedding config and search each store.
            # An agent may be linked to KBs with different embedding
            # models; mixing them in one store would be meaningless.
            try:
                all_results = []
                per_kb_k = max(1, 3 // len(kb_ids))
                # M38.2.x v2: per-KB ``kb.read`` 过滤。``user is None`` 走
                # graceful open(widget visitor / cron / fixture)。
                from lumen_services.permission_service import PermissionService
                _perm_svc = PermissionService() if user is not None else None
                for link in kb_links:
                    kb = db.query(KnowledgeBase).filter(
                        KnowledgeBase.id == link.knowledge_base_id,
                        KnowledgeBase.tenant_id == tenant_id,
                    ).first()
                    if kb is None or kb.embedding_model_config_id is None:
                        continue
                    if _perm_svc is not None and not _perm_svc.check(
                        db, user, "kb.read", kb.workspace_id,
                    ):
                        logger.info(
                            "[AgentService.chat] skip KB %s: user %s no kb.read",
                            kb.id, getattr(user, "id", None),
                        )
                        continue
                    vector_store = VectorStoreFactory.get_store(
                        kb_id=kb.id,
                        model_config_id=kb.embedding_model_config_id,
                        db=db,
                    )
                    per_filter = (
                        f"tenant_id == {tenant_id} and kb_id == {kb.id}"
                    )
                    per_results = vector_store.similarity_search(
                        message, k=per_kb_k, filter_expr=per_filter,
                    )
                    all_results.extend(per_results)
                # Trim back to top k=3.
                results = all_results[:3]
                if results:
                    knowledge_context = "\n\n".join(
                        [r["text"] for r in results]
                    )
            except Exception as e:
                logger.warning("[AgentService.chat] Vector store error (non-fatal): %s", e)

        # ------------------------------------------------------------------
        # Task 8: apply the agent's memory policy to the chat history.
        # The policy is stored on the Agent row (memory_policy, window size,
        # max tokens, compression flag). When SEMANTIC_COMPRESSION is on
        # we also try an LLM-backed summarizer; otherwise we just keep
        # the last N turns.
        # ------------------------------------------------------------------
        from lumen_services.agents.memory import (
            apply_memory_policy,
            summarize_for_compression,
        )

        summarizer = None
        if (
            (agent.memory_policy or "sliding_window") == "semantic_compression"
            and getattr(agent, "memory_compression", False)
        ):
            def _s(messages):
                return summarize_for_compression(db, agent, messages)
            summarizer = _s

        filtered_history = apply_memory_policy(
            history,
            agent.memory_policy or "sliding_window",
            window_size=agent.memory_window_size,
            max_tokens=agent.memory_max_tokens,
            compression=getattr(agent, "memory_compression", False),
            summarizer=summarizer,
        )
        logger.info(
            "[AgentService.chat] memory_policy=%s, history_in=%s, history_out=%s",
            agent.memory_policy, len(history or []), len(filtered_history),
        )

        # ------------------------------------------------------------------
        # Task 8: apply the agent's tool-choice strategy to its configured
        # tools. This currently only logs the resolved subset; the actual
        # LLM binding happens via the existing path because the project's
        # chat models don't yet expose a native tool-calling surface.
        # ------------------------------------------------------------------
        try:
            from lumen_services.agents.tool_choice import (
                select_tools,
                tool_choice_hint,
            )
            available_tool_rows = list(agent.tools or [])
            resolved = select_tools(
                available_tool_rows,
                agent.tool_choice or "auto",
                allowed=agent.allowed_tools or [],
                required_hint=bool(getattr(agent, "tool_choice_required", False)),
            )
            tool_names = [t.get("name") for t in resolved]
            logger.info(
                "[AgentService.chat] tool_choice=%s, tool_count=%s, names=%s",
                agent.tool_choice, len(tool_names), tool_names,
            )
            hint = tool_choice_hint(
                agent.tool_choice or "auto",
                required=getattr(agent, "tool_choice_required", False),
            )
            if hint:
                logger.info("[AgentService.chat] tool_choice hint -> %s", hint)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[AgentService.chat] tool-choice resolution failed (non-fatal): %s",
                exc,
            )

        # Build messages
        # MiniMax doesn't support system role in messages, so we prepend system prompt to first user message
        system_prompt = f"[System]\n{agent.prompt_template}\n\nKnowledge:\n{knowledge_context}".strip()

        messages = []

        # Add filtered history messages (MiniMax expects user/assistant roles only)
        for msg in filtered_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                # MiniMax doesn't support assistant role directly, include as user message
                messages.append(HumanMessage(content=f"[Previous Assistant]\n{msg['content']}"))
            elif msg["role"] == "system":
                # Memory-summary messages produced by semantic_compression
                messages.append(HumanMessage(content=f"[Memory]\n{msg['content']}"))

        # Prepend system prompt to the first message
        if messages:
            first_content = messages[0].content
            messages[0] = HumanMessage(content=f"{system_prompt}\n\n{first_content}")
        else:
            # No history, prepend system prompt to current message
            message = f"{system_prompt}\n\n[User]\n{message}"

        # Add current user message
        messages.append(HumanMessage(content=message))

        # Get model config and create appropriate LLM
        logger.info("[AgentService.chat] Getting model config for: %s", agent.model_name)
        model_config = self._get_model_config(db, agent.model_name, tenant_id)
        logger.info("[AgentService.chat] model_name=%s, model_config=%s", agent.model_name, model_config)

        if model_config:
            if not model_config.base_url or not model_config.api_key:
                raise ValueError(f"Model {agent.model_name} is missing base_url or api_key in model config")
            logger.info("[AgentService.chat] Using model_type=%s, base_url=%s", model_config.model_type, model_config.base_url)
            llm = create_chat_model(
                model_type=model_config.model_type,
                model_name=agent.model_name,
                base_url=model_config.base_url.strip() if model_config.base_url else None,
                api_key=model_config.api_key,
                temperature=agent.temperature or model_config.temperature,
                timeout=model_config.timeout,
            )
        else:
            # Fallback: try ollama as default - but warn since this likely won't work
            logger.warning("No model config found for model %s, falling back to ollama", agent.model_name)
            raise ValueError(f"No model configuration found for model '{agent.model_name}'. Please add a model configuration in 系统管理 -> 模型管理")

        logger.info("[AgentService.chat] Invoking LLM with model=%s...", agent.model_name)
        try:
            response = llm.invoke(messages)
            logger.info("[AgentService.chat] Response received: %s...", response.content[:100])
            return response.content
        except Exception as e:
            logger.error("[AgentService.chat] LLM invoke failed: %s: %s", type(e).__name__, e)
            raise

    async def run(
        self,
        agent_id: int,
        message: str,
        tenant_id: int,
    ) -> str:
        """
        Async entry point used by the workflow executor.

        Opens its own DB session (the executor is invoked from request
        handlers and scheduler jobs that don't have a session handy) and
        delegates to the synchronous ``chat()`` via ``asyncio.to_thread`` so
        the event loop is never blocked on a sync DB / LLM call.
        """
        import asyncio

        from lumen_core.database import SessionLocal

        def _sync() -> str:
            db = SessionLocal()
            try:
                return self.chat(
                    db=db,
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                    message=message,
                    history=None,
                )
            finally:
                db.close()

        return await asyncio.to_thread(_sync)
