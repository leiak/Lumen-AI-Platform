from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import logging
from lumen_core.database import get_db

logger = logging.getLogger(__name__)
from lumen_api.v1.auth import get_current_user, require_admin
from lumen_models.user import User
from lumen_models.agent import Agent
from lumen_models.model_config import ModelConfig
from lumen_schemas.agent import (
    AgentCreate, AgentUpdate, AgentResponse,
    AgentUpdateModel,
    ChatRequest, ChatMessage
)
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_agent_response(agent: Agent) -> dict:
    """M21: 手动序列化 Agent → response payload。

    Pydantic model_validate 没办法处理 orphan binding(对应 KB 被硬删的情况),
    这里显式把 AgentKnowledgeBase + KnowledgeBase 转成 KBRef dict。硬删的 KB
    fallback 成 ``(已删除 KB #N)`` + ``status="deleted"``,前端能识别并显示
    删除状态。
    """
    kb_refs = []
    for binding in agent.knowledge_bases:
        kb = binding.knowledge_base
        if kb is None:
            kb_refs.append({
                "id": binding.knowledge_base_id,
                "name": f"(已删除 KB #{binding.knowledge_base_id})",
                "status": "deleted",
            })
        else:
            kb_refs.append({
                "id": kb.id,
                "name": kb.name,
                "status": kb.status or "active",
            })
    return {
        "id": agent.id,
        "tenant_id": agent.tenant_id,
        "is_active": bool(agent.is_active),
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "name": agent.name,
        "description": agent.description,
        "prompt_template": agent.prompt_template,
        "model_name": agent.model_name,
        "temperature": agent.temperature,
        "memory_policy": agent.memory_policy or "sliding_window",
        "memory_window_size": agent.memory_window_size,
        "memory_max_tokens": agent.memory_max_tokens,
        "memory_compression": bool(agent.memory_compression),
        "tool_choice": agent.tool_choice or "auto",
        "tool_choice_required": bool(agent.tool_choice_required),
        "allowed_tools": agent.allowed_tools or [],
        "kb_retrieval_config": agent.kb_retrieval_config or {"top_k": 3, "rrf_k": 30},
        "knowledge_bases": kb_refs,
    }


@router.get("/", response_model=PaginatedResponse[AgentResponse])
async def list_agents(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    agents = service.list_agents(db, current_user.tenant_id)
    total = len(agents)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[_to_agent_response(a) for a in agents[start:end]],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/", response_model=SingleResponse[AgentResponse])
async def create_agent(
    data: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    agent = service.create_agent(db, current_user.tenant_id, data, current_user)
    return SingleResponse(data=_to_agent_response(agent))


@router.get("/{agent_id}", response_model=SingleResponse[AgentResponse])
async def get_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    agent = service.get_agent(db, agent_id, current_user.tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return SingleResponse(data=_to_agent_response(agent))


@router.put("/{agent_id}", response_model=SingleResponse[AgentResponse])
async def update_agent(
    agent_id: int,
    data: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    try:
        agent = service.update_agent(db, agent_id, current_user.tenant_id, data)
    except ValueError as e:
        # M21: 差量同步 / config 校验失败 → 422
        raise HTTPException(status_code=422, detail=str(e))
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return SingleResponse(data=_to_agent_response(agent))


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    success = service.delete_agent(db, agent_id, current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return SingleResponse(message="Deleted successfully")


@router.put(
    "/{agent_id}/model",
    response_model=SingleResponse[dict],
    summary="Admin-only:切换 Agent 引用 ModelConfig",
    description=(
        "Agent 调 chat API 时由 agent.model_name 反查 model_configs 表拿 "
        "(base_url / api_key / model_type)。当某 ModelConfig 的 API key "
        "死了(例如 MiniMax 401 → workflow 节点 60s 超时),admin 可以用这个 "
        "端点把 agent 切到另一个 active 的 ModelConfig 恢复流程。\n\n"
        "行为:\n"
        "- 传 model_config_id → 反查 model_configs 取 model_name 写回 agent\n"
        "- 传 model_name → 走 AgentService._get_model_config 验证 active + "
        "base_url + api_key 完备,任一缺失 422\n"
        "- 都不传或都传 → 422(AgentUpdateModel 互斥校验)\n"
        "- 不存在 agent / model_config → 404\n"
        "- 非 admin → 403(require_admin 守门)"
    ),
)
async def update_agent_model(
    agent_id: int,
    payload: AgentUpdateModel,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    # 1. 拿 agent,跨租户 admin 才能切(同 WxAccount purge 模式 — 见 lumen
    #    _api/v1/auth.py:59 require_admin + lumen_services/wx_publisher.py
    #    purge_account 不过 tenant_id 滤)。不传 tenant_id 走全局 query。
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    old_model_name = agent.model_name

    # 2. 决定 target model_name + 校验目标 ModelConfig 健康
    if payload.model_config_id is not None:
        target_mc = (
            db.query(ModelConfig)
            .filter(ModelConfig.id == payload.model_config_id)
            .first()
        )
        if not target_mc:
            raise HTTPException(
                status_code=404,
                detail=f"ModelConfig {payload.model_config_id} not found",
            )
        if not target_mc.is_active:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"ModelConfig {target_mc.id} ({target_mc.name}) "
                    f"is_active=False,无法切到禁用配置"
                ),
            )
        new_model_name = target_mc.model_name
    else:
        # payload.model_name 走 AgentService._get_model_config 反查,跟
        # AgentService.chat 路径完全一致,保证「能解析到 active + base_url
        # + api_key 完备」才允许切,避免切完立刻又 401。
        mc = AgentService()._get_model_config(db, payload.model_name, agent.tenant_id)
        if mc is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"model_name={payload.model_name!r} 在 model_configs 表中"
                    f"找不到 active row(agent executor 也会同样 404)"
                ),
            )
        if not mc.is_active:
            raise HTTPException(
                status_code=422,
                detail=f"model_name={payload.model_name!r} 对应 ModelConfig 已禁用",
            )
        if not mc.base_url or not mc.api_key:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"model_name={payload.model_name!r} 对应 ModelConfig 缺少 "
                    f"base_url 或 api_key,agent executor 也会报缺配置"
                ),
            )
        new_model_name = mc.model_name

    # 3. 写入 + commit,允许 reason 落到 audit_log(可选,本期不强制 audit 接入)
    if old_model_name != new_model_name:
        agent.model_name = new_model_name
        db.commit()
        db.refresh(agent)
        logger.info(
            "[admin=%s] agent.id=%s model_name: %s → %s (reason=%s)",
            admin_user.username, agent_id, old_model_name, new_model_name,
            payload.reason or "<none>",
        )

    # 4. 返完整 agent 详情 + 切换 delta,前端可以原地刷新列表,也能展示
    #    「这次切到了哪个 model / 是否变了」用于确认 toast。
    return SingleResponse(
        data={
            "agent": _to_agent_response(agent),
            "old_model_name": old_model_name,
            "new_model_name": agent.model_name,
            "changed": old_model_name != agent.model_name,
            "reason": payload.reason,
        }
    )


@router.get("/count")
async def count_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.agent import Agent
    count = db.query(Agent).filter(Agent.tenant_id == current_user.tenant_id).count()
    return {"count": count}


@router.post("/{agent_id}/chat")
async def chat_with_agent(
    agent_id: int,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = AgentService()
    try:
        # 1. Resolve or auto-create a Conversation tied to this agent.
        #    This makes the agent chat appear in the Memory Management
        #    page (which lists conversations via /chat/conversations).
        from lumen_models.chat import Conversation, Message
        from lumen_services.memory_service import MemoryService

        conv_id = data.conversation_id
        if conv_id is None:
            title_src = (data.message or "").strip().replace("\n", " ")
            title = (title_src[:50] + "…") if len(title_src) > 50 else (title_src or f"Agent {agent_id} 会话")
            conv = Conversation(
                title=title,
                user_id=current_user.id,
                tenant_id=current_user.tenant_id,
                agent_id=agent_id,
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
            conv_id = conv.id

        # 2. Call the LLM (existing behavior, untouched).
        history = [h.model_dump() for h in data.history] if data.history else None
        # M38.2.x v2: 透传 user 让 KB RAG 做 per-KB ``kb.read`` 过滤
        response = service.chat(
            db=db,
            agent_id=agent_id,
            tenant_id=current_user.tenant_id,
            message=data.message,
            history=history,
            user=current_user,
        )

        # 3. Best-effort persistence to Message / ConversationMemory /
        #    GlobalMemory. Any failure here is logged but does not fail
        #    the chat — the user already got their answer.
        try:
            db.add(Message(conversation_id=conv_id, role="user", content=data.message))
            db.add(Message(conversation_id=conv_id, role="assistant", content=response))
            db.commit()

            mem = MemoryService(db)
            for role, content in (("user", data.message), ("assistant", response)):
                mem.add_conversation_memory(db, conv_id, current_user.tenant_id, role, content)
                # M15: thread conversation_id so the global context panel
                # can tell "this row is from the conv the user is
                # currently looking at" apart from rows that came from
                # other conversations.
                mem.add_global_memory(
                    db, current_user.tenant_id, role, content,
                    conversation_id=conv_id,
                )
            # Cap global memory so a chatty tenant doesn't blow up the table.
            mem.cap_global_memory(db, current_user.tenant_id, max_entries=1000)
        except Exception as persist_err:
            import traceback
            logger.warning("[agent chat] persistence error (non-fatal): %s", persist_err)
            logger.debug("[agent chat] traceback: %s", traceback.format_exc())

        return SingleResponse(data={
            "response": response,
            "conversation_id": conv_id,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}"
        # For API connection errors, provide more helpful message
        if "APIConnectionError" in error_msg or "Connection error" in error_msg:
            error_msg = "API连接失败：可能是网络问题、API Key无效或API地址错误。请检查模型配置。"
        elif "AuthenticationError" in error_msg or "401" in error_msg:
            error_msg = "API认证失败：API Key无效或已过期。请检查模型配置中的API Key。"
        elif "NotFoundError" in error_msg or "404" in error_msg:
            error_msg = "API地址错误：无法找到对应的API端点。请检查模型配置中的Base URL。"
        logger.error("Agent chat error: %s", error_msg)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_msg)
