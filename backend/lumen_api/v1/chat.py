import os
import uuid
import tempfile
import json
import asyncio
import logging
from dataclasses import asdict
from datetime import datetime

logger = logging.getLogger(__name__)
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_core.config import settings
from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    set_embedding_context,
    reset_embedding_context,
)
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.chat import (
    Message, ConversationCreate, ConversationResponse, ChatRequest,
    ConversationUpdate, UploadResult,
)
from lumen_services.chat_service import ChatService
from lumen_services.agent_service import AgentService
from lumen_services.memory_service import memory_service
from lumen_api.v1.memory import verify_conversation
from lumen_services.document_parser import DocumentParser
from lumen_services.chat_features import ChatFeatureService
from lumen_models.chat import Conversation, Message as MessageModel
from lumen_schemas.common import SingleResponse

router = APIRouter(prefix="/chat", tags=["chat"])


def _serialize_conversation(conv: Conversation, agent_name: Optional[str]) -> ConversationResponse:
    """Build a ConversationResponse for one row.

    ``agent_name`` is a *joined* column (LEFT JOIN agents) and does not
    exist on the Conversation ORM model, so Pydantic's
    ``from_attributes=True`` cannot see it — passing the ORM row
    directly would silently leave ``agent_name=None`` in the response.
    Endpoints MUST pass the joined name explicitly. Pass ``None`` when
    the conv has no agent or the agent row was deleted.
    """
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        agent_id=conv.agent_id,
        agent_name=agent_name,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _build_assistant_meta(ctx, request: ChatRequest) -> dict:
    """Build the JSON-serializable metadata dict for an assistant message.

    The frontend reads this off `message.metadata` to render citations
    and the web-search-failure notice. SearchResult is a dataclass and
    must be converted via `asdict` before json.dumps.
    """
    meta: dict = {}
    if request.enable_web_search:
        meta["search_status"] = ctx.search_status
    if ctx.sources:
        meta["sources"] = [asdict(s) for s in ctx.sources]
    if ctx.skill_names:
        meta["skills"] = ctx.skill_names
    return meta


def _build_done_event(assistant_meta: dict, conversation_id: int) -> dict:
    """The final SSE event of /chat/stream.

    Carries the assistant metadata so the frontend can patch its
    local message state with `search_status`, `sources`, and `skills`
    immediately after the stream ends, without needing a DB re-fetch.
    The MessageBubble component reads these off `message.metadata`.
    """
    payload: dict = {"content": "", "done": True, "conversation_id": conversation_id}
    if assistant_meta.get("search_status") is not None:
        payload["search_status"] = assistant_meta["search_status"]
    if assistant_meta.get("sources"):
        payload["sources"] = assistant_meta["sources"]
    if assistant_meta.get("skills"):
        payload["skills"] = assistant_meta["skills"]
    return payload


from lumen_schemas.chat import (
    RecommendSkillsRequest,
    RecommendSkillsResponse,
    SkillRecommendationItem,
)
from lumen_services.skill_recommender import SkillRecommender


@router.post("/recommend-skills", response_model=SingleResponse[List[SkillRecommendationItem]])
async def recommend_skills(
    body: RecommendSkillsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """推荐适合当前消息的已安装技能（关键词匹配 + LLM 语义判断）。

    返回最多 5 个推荐技能，按置信度从高到低排序。
    前端在用户点击发送后调用此接口，有推荐则弹确认框。
    """
    recommender = SkillRecommender(db=db, user=current_user)
    results = recommender.recommend(body.message, top_k=5)
    return SingleResponse(data=[
        SkillRecommendationItem(
            skill_id=r.skill_id,
            marketplace_skill_id=r.marketplace_skill_id,
            name=r.name,
            description=r.description,
            reason=r.reason,
            confidence=r.confidence,
            match_type=r.match_type,
        )
        for r in results
    ])


@router.get("/conversations", response_model=SingleResponse[List[ConversationResponse]])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # SQL outer join pulls agents.name in one round-trip; avoids N+1 from
    # Python-side joins and doesn't require adding a `relationship` to the
    # Conversation model (keeps blast radius minimal).
    from lumen_models.agent import Agent
    rows = (
        db.query(Conversation, Agent.name)
        .outerjoin(Agent, Conversation.agent_id == Agent.id)
        .filter(
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.user_id == current_user.id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    out = [
        _serialize_conversation(c, agent_name)  # agent_name is None on LEFT JOIN miss
        for (c, agent_name) in rows
    ]
    return SingleResponse(data=out)

@router.post("/conversations", response_model=SingleResponse[ConversationResponse])
async def create_conversation(
    data: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    conv = Conversation(
        title=data.title or "新对话",
        agent_id=data.agent_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Fetch the joined agent_name explicitly. The Conversation ORM has
    # no `agent_name` column, so Pydantic's from_attributes would
    # silently leave it None on the response (silent data loss — see
    # MEMORY.md "Pydantic 静默丢弃未知字段"). A scalar() lookup is
    # cheaper than an outerjoin for a single row.
    agent_name: Optional[str] = None
    if conv.agent_id is not None:
        from lumen_models.agent import Agent
        agent_name = (
            db.query(Agent.name)
            .filter(Agent.id == conv.agent_id)
            .scalar()
        )

    return SingleResponse(data=_serialize_conversation(conv, agent_name))

@router.get("/conversations/{conv_id}/messages", response_model=SingleResponse[List[Message]])
async def get_messages(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check conversation belongs to user
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == current_user.id,
        Conversation.tenant_id == current_user.tenant_id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs = db.query(MessageModel).filter(
        MessageModel.conversation_id == conv_id
    ).order_by(MessageModel.created_at.asc()).all()
    return SingleResponse(data=msgs)

@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    fastapi_request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # M26 trace_id is established INSIDE the generator below — the
    # generator runs after this function returns (StreamingResponse
    # iterates the generator in a later step), so any context set at
    # the function level would be cleared by the outer try/finally
    # before the LLM call happens. We capture the trace_id here so
    # the generator can re-attach the same context.
    trace_id = str(uuid.uuid4())
    request_ip = (fastapi_request.client.host if fastapi_request.client else None)
    user_agent = fastapi_request.headers.get("user-agent")

    async def generate():
        # M26: re-establish the per-request LLMCallContext inside the
        # generator so the LoggingChatModel wrapper in model_loader
        # writes one row per LLM call. The context is reset at the end
        # of the generator (try/finally) so the token doesn't leak.
        ctx_token = set_call_context(LLMCallContext(
            call_id=trace_id,  # root call_id == trace_id for the dashboard chat path
            trace_id=trace_id,
            parent_call_id=None,
            call_type="chat",
            call_index=0,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            username=current_user.username,
            client_app="dashboard",
            request_ip=request_ip,
            user_agent=user_agent,
        ))
        # M27: parallel embedding context so KB retrieval calls inside
        # ``feats.prepare()`` (step 4 = KB RAG) write embedding rows that
        # share this trace_id with the LLM rows for trace timeline UI.
        # Generate a separate call_id so the embedding row is distinct
        # from the LLM row.
        emb_ctx_token = set_embedding_context(EmbeddingCallContext(
            call_id=str(uuid.uuid4()),
            trace_id=trace_id,  # SAME trace as LLM
            parent_call_id=trace_id,  # nested under the chat trace root
            call_type="kb_retrieval",
            call_index=0,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            username=current_user.username,
            client_app="dashboard",
            request_ip=request_ip,
            user_agent=user_agent,
        ))
        # Phase 1 Group B 4.4 Day 3 (2026-09-05): chat.endpoint root span。
        # 在 generator 内(非 endpoint 层)起 — Phase 0 已 ship 注释解释了
        # 为什么不在 endpoint 层(StreamingResponse 后 outer try/finally 会在
        # LLM 调用前清掉 context)。span 作为 chat.stream / llm.chat 的 parent。
        from opentelemetry import trace as _otel_trace

        _endpoint_span = _otel_trace.get_tracer("lumen.manual").start_span(
            "chat.endpoint",
            attributes={
                "chat.endpoint": "/chat/stream",
                "chat.user_id": current_user.id,
                "chat.tenant_id": current_user.tenant_id,
                "chat.conversation_id": (
                    int(request.conversation_id) if request.conversation_id else -1
                ),
                "chat.agent_id": (
                    int(request.agent_id) if request.agent_id else -1
                ),
                "chat.status": "running",
            },
        )
        # 把 OTel trace_id 同步到 contextvar,让老 LLMCallLog.trace_id
        # 跟 OTel span trace_id 对齐(back-compat)
        try:
            from lumen_core.tracing_decorator import _set_contextvar_from_span
            _set_contextvar_from_span(_endpoint_span)
        except Exception:  # noqa: BLE001
            pass
        # 把 endpoint 自己的 trace_id(32-hex)写到 contextvar,这样后续
        # 嵌套的 chat.stream / llm.chat / retrieval.search / embedding.generate
        # span 都用同一个 trace_id,contextvar 优先保证 LLMCallLog.trace_id 一致
        from lumen_core.tracing import set_trace_id as _set_tid
        try:
            sc = _endpoint_span.get_span_context()
            if sc.is_valid:
                _set_tid(format(sc.trace_id, "032x"))
        except Exception:  # noqa: BLE001
            pass

        import time as _time
        _endpoint_t0 = _time.monotonic()
        _endpoint_status = "completed"

        try:
            service = ChatService()
            agent_service = AgentService()

            # 鲁棒性补丁:request.agent_id 为空时,从 conversation_id 自动加载
            # conv.agent_id。前端漏发也能正确工作。Pydantic BaseModel 默认 mutable,
            # 改 request.agent_id 之后 line 130 的 if request.agent_id 分支自然走对。
            if not request.agent_id and request.conversation_id:
                existing_conv = (
                    db.query(Conversation)
                    .filter(
                        Conversation.id == request.conversation_id,
                        Conversation.tenant_id == current_user.tenant_id,
                    )
                    .first()
                )
                if existing_conv and existing_conv.agent_id:
                    logger.info(
                        "[chat/stream] auto-resolved agent_id=%s from conv %s",
                        existing_conv.agent_id, request.conversation_id,
                    )
                    request.agent_id = existing_conv.agent_id

            # Load agent model config if agent_id is provided
            model_type = "ollama"
            model_name = "qwen2.5:7b"
            base_url = None
            api_key = None
            temperature = 0.7

            if request.agent_id:
                from lumen_models.agent import Agent
                agent = db.query(Agent).filter(
                    Agent.id == request.agent_id,
                    Agent.tenant_id == current_user.tenant_id
                ).first()
                if not agent:
                    logger.warning(
                        "Agent %s not found for tenant %s, falling back to defaults",
                        request.agent_id, current_user.tenant_id,
                    )
                else:
                    model_name = agent.model_name or "qwen2.5:7b"
                    # Agent.temperature is Integer, ensure proper type handling for float
                    temperature = float(agent.temperature) if agent.temperature is not None else 0.7

                    # Get model config from database instead of hardcoded values
                    model_config = agent_service._get_model_config(db, model_name, current_user.tenant_id)
                    if model_config:
                        model_type = model_config.model_type or model_type
                        base_url = model_config.base_url
                        api_key = model_config.api_key
                        # Use model_config temperature as fallback if agent temperature not set
                        if agent.temperature is None and model_config.temperature is not None:
                            temperature = float(model_config.temperature)

                    # Set the model on service
                    service.set_model(
                        model_type=model_type,
                        model_name=model_name,
                        base_url=base_url,
                        api_key=api_key,
                        temperature=temperature,
                    )
            else:
                # No agent selected: fall back to the tenant's default model config
                # (the one with is_default=1 in model_configs). Without this we'd
                # use the hardcoded ChatOllama default and fail to connect to a
                # possibly-missing local Ollama.
                from lumen_models.model_config import ModelConfig
                default_cfg = db.query(ModelConfig).filter(
                    ModelConfig.tenant_id == current_user.tenant_id,
                    ModelConfig.is_default == True,  # noqa: E712
                    ModelConfig.is_active == True,   # noqa: E712
                ).first()
                if default_cfg:
                    service.set_model(
                        model_type=default_cfg.model_type,
                        model_name=default_cfg.model_name,
                        base_url=default_cfg.base_url,
                        api_key=default_cfg.api_key,
                        temperature=default_cfg.temperature or 0.7,
                    )

            try:
                # Get or create conversation
                conv_id = request.conversation_id
                if not conv_id:
                    conv = Conversation(
                        title=request.message[:50],
                        user_id=current_user.id,
                        tenant_id=current_user.tenant_id,
                        agent_id=request.agent_id
                    )
                    db.add(conv)
                    db.commit()
                    db.refresh(conv)
                    conv_id = conv.id
                else:
                    # Reuse existing conv. If it still has the placeholder title
                    # (set by POST /chat/conversations when the user clicked
                    # "新建对话"), upgrade it to the first message so the sidebar
                    # shows something meaningful instead of "新对话" forever.
                    existing = db.query(Conversation).filter(
                        Conversation.id == conv_id,
                        Conversation.tenant_id == current_user.tenant_id,
                    ).first()
                    if existing and (not existing.title or existing.title == "新对话"):
                        existing.title = request.message[:50]
                        db.commit()

                # Save user message
                user_msg = MessageModel(
                    conversation_id=conv_id,
                    role="user",
                    content=request.message
                )
                db.add(user_msg)
                db.commit()

                # Add to memory
                memory_service.add_message(conv_id, "user", request.message, current_user.tenant_id, db=db)

                # Get history
                history_msgs = db.query(MessageModel).filter(
                    MessageModel.conversation_id == conv_id
                ).order_by(MessageModel.created_at.asc()).all()
                history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]
            except Exception as e:
                _endpoint_status = "error"
                yield f"data: {json.dumps({'content': f'Database error: {str(e)}', 'done': True})}\n\n"
                return

            # —— Feature preprocessing pipeline ——
            try:
                # M38.2.x v2: 透传 user 让 KB RAG 做 per-KB ``kb.read`` 过滤
                feats = ChatFeatureService(db, current_user.tenant_id, user=current_user)
                # M21: pass agent_id so step 4 (KB RAG context) runs.
                # ``request.agent_id`` was auto-resolved from the conversation
                # at the top of this function (see M14 logic) — passing it
                # through here is the single switch for /chat/stream KB
                # injection. None is also fine (no agent bound -> no KB).
                ctx = feats.prepare(history, request, agent_id=request.agent_id)

                # Persist attachment metadata (name/size/mime only — NOT content_text)
                if request.attachments:
                    user_msg_meta = {
                        "attachments": [
                            {"name": a.name, "size": a.size, "mime_type": a.mime_type}
                            for a in request.attachments
                        ]
                    }
                    user_msg.msg_metadata = json.dumps(user_msg_meta, ensure_ascii=False)
                    db.commit()
            except Exception as e:
                _endpoint_status = "error"
                yield f"data: {json.dumps({'content': f'Feature prep error: {str(e)}', 'done': True})}\n\n"
                return

            # Stream response
            full_response = ""
            try:
                # M16: pass tools from PreparedContext to chat_service for
                # function calling (script / http skills).
                async for chunk in service.stream_chat_messages(
                    ctx.messages, tools=ctx.tools,
                ):
                    full_response += chunk
                    yield f"data: {json.dumps({'content': chunk, 'done': False})}\n\n"
            except Exception as e:
                _endpoint_status = "error"
                yield f"data: {json.dumps({'content': f'LLM error: {str(e)}', 'done': True})}\n\n"
                return

            # Phase 1 Group B 4.4 Day 3 (2026-09-05): chat.endpoint span 上写
            # completion_chars + model。content 不写(PII 安全)。
            try:
                _endpoint_span.set_attribute("chat.completion_chars", len(full_response or ""))
                _endpoint_span.set_attribute(
                    "chat.model",
                    getattr(getattr(service, "chat_model", None), "model", None)
                    or getattr(getattr(service, "chat_model", None), "model_name", None)
                    or "unknown",
                )
            except Exception:  # noqa: BLE001
                pass

            # Save assistant message
            try:
                assistant_meta = _build_assistant_meta(ctx, request)
                assistant_msg = MessageModel(
                    conversation_id=conv_id,
                    role="assistant",
                    content=full_response,
                    msg_metadata=json.dumps(assistant_meta, ensure_ascii=False) if assistant_meta else None,
                )
                db.add(assistant_msg)
                db.commit()

                # Add to memory
                memory_service.add_message(conv_id, "assistant", full_response, current_user.tenant_id, db=db)

                # Broadcast chat message completion to Electron clients
                conv_title = db.query(Conversation).filter(Conversation.id == conv_id).first()
                conv_title_str = conv_title.title if conv_title else "对话"
                try:
                    from lumen_services.electron_service import electron_service
                    await electron_service.broadcast_event_async(
                        "chat_message_received",
                        {
                            "conversation_id": conv_id,
                            "conversation_title": conv_title_str,
                            "preview": full_response[:100] if full_response else "(空回复)",
                            "tenant_id": current_user.tenant_id,
                        },
                    )
                except Exception as broadcast_err:
                    import logging
                    logging.getLogger(__name__).warning(
                        f"Failed to broadcast chat_message_received: {broadcast_err}"
                    )
            except Exception as e:
                logger.error("Failed to save assistant message: %s", e)

            # Final event carries search_status + sources so the frontend
            # can patch the live assistant message without a DB re-fetch.
            done_event = _build_done_event(assistant_meta, conv_id)
            yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"
        finally:
            reset_call_context(ctx_token)
            reset_embedding_context(emb_ctx_token)
            # Phase 1 Group B 4.4 Day 3 (2026-09-05): chat.endpoint root span 收尾
            try:
                _endpoint_span.set_attribute("chat.status", _endpoint_status)
                _endpoint_span.set_attribute(
                    "chat.duration_ms",
                    int((_time.monotonic() - _endpoint_t0) * 1000),
                )
                if _endpoint_status == "error":
                    from opentelemetry.trace import Status as _St, StatusCode as _Sc
                    _endpoint_span.set_status(_St(_Sc.ERROR, "chat endpoint error"))
            except Exception:  # noqa: BLE001
                logger.debug("chat.endpoint span attr write failed; ignored", exc_info=True)
            finally:
                try:
                    _endpoint_span.end()
                except Exception:  # noqa: BLE001
                    pass

    return StreamingResponse(generate(), media_type="text/event-stream")


ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".pptx", ".xlsx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CONTENT_TEXT_BYTES = 5 * 1024 * 1024  # 5 MB of extracted text


@router.post("/upload", response_model=SingleResponse[UploadResult])
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Parse an uploaded file to plain text and return it for the frontend
    to keep in component state. Content is NOT persisted server-side in V1.
    """
    filename = file.filename or "upload"
    ext = ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件格式:{ext}。支持:{sorted(ALLOWED_EXTENSIONS)}",
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大({len(raw)} bytes),上限 {MAX_UPLOAD_BYTES} bytes",
        )

    # Reuse existing document parser via temp file (it expects a path)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        parser = DocumentParser()
        result = await asyncio.to_thread(parser.parse, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    content_text = ""
    if isinstance(result, dict):
        content_text = result.get("content") or result.get("text") or ""
        if not content_text and "chunks" in result:
            content_text = "\n\n".join(
                c.get("content", "") for c in result["chunks"] if c.get("content")
            )
    elif isinstance(result, str):
        content_text = result

    if not content_text:
        raise HTTPException(status_code=422, detail="文件解析失败:未提取到文本")

    # Cap in-memory payload at 5MB of text
    if len(content_text.encode("utf-8")) > MAX_CONTENT_TEXT_BYTES:
        raise HTTPException(status_code=413, detail="解析后文本过大(>5MB)")

    return SingleResponse(data=UploadResult(
        file_id=str(uuid.uuid4()),
        name=filename,
        size=len(raw),
        mime_type=file.content_type or "application/octet-stream",
        content_text=content_text,
    ))


@router.patch("/conversations/{conv_id}", response_model=SingleResponse[ConversationResponse])
async def update_conversation(
    conv_id: int,
    data: ConversationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the bound agent of a conversation. Pass agent_id=null to
    unbind (revert to tenant default model config)."""
    conv = verify_conversation(conv_id, current_user, db)

    # M30 P1-5 (per spec §6 risk #3): conversations are bound to EITHER
    # an agent OR a team, never both. PATCH /conversations/{id} only
    # mutates agent_id — if the conv is already team-bound, refuse
    # rather than silently creating a mixed-mode row that nothing
    # else in the system knows how to render. Operators who need to
    # unbind the team should hit the team endpoints, not this one.
    if data.agent_id is not None and conv.team_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Conversation is bound to an agent team; unbind the team "
                "via the team endpoints before setting agent_id."
            ),
        )

    target_name: Optional[str] = None
    if data.agent_id is not None:
        from lumen_models.agent import Agent
        target = (
            db.query(Agent)
            .filter(
                Agent.id == data.agent_id,
                Agent.tenant_id == current_user.tenant_id,
                Agent.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not target:
            raise HTTPException(
                status_code=404, detail="Agent not found or inactive",
            )
        target_name = target.name

    conv.agent_id = data.agent_id
    db.commit()
    db.refresh(conv)

    # `target_name` is already None when `data.agent_id` is None (the
    # branch above only sets it on a successful agent lookup), so it
    # can be passed directly to the serializer.
    return SingleResponse(
        data=_serialize_conversation(conv, target_name)
    )


@router.delete("/conversations/{conv_id}", response_model=SingleResponse[None])
async def delete_conversation(
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a conversation. Sets deleted_at; row preserved for future restore.

    TODO(future): add scheduled job to hard-delete rows where deleted_at < utcnow() - 30d
    TODO(future): consider clearing MemoryService entries for this conv (out of scope here)
    """
    conv = verify_conversation(conv_id, current_user, db)
    conv.deleted_at = datetime.utcnow()
    db.commit()
    return SingleResponse(message="Deleted successfully")
