from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
import logging
from lumen_core.database import get_db

logger = logging.getLogger(__name__)
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.agent import Agent
from lumen_schemas.agent import (
    AgentCreate, AgentUpdate, AgentResponse,
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
