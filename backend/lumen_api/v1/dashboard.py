from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.common import SingleResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/stats", response_model=SingleResponse)
async def get_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from fastapi import HTTPException
    from lumen_models.agent import Agent
    from lumen_models.knowledge import KnowledgeBase
    from lumen_models.chat import Conversation
    from lumen_models.workflow import Workflow

    try:
        agent_count = db.query(Agent).filter(Agent.tenant_id == current_user.tenant_id).count()
        kb_count = db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == current_user.tenant_id).count()
        conversation_count = db.query(Conversation).filter(Conversation.tenant_id == current_user.tenant_id).count()
        workflow_count = db.query(Workflow).filter(Workflow.tenant_id == current_user.tenant_id).count()

        return SingleResponse(data={
            "agent_count": agent_count,
            "knowledge_count": kb_count,
            "conversation_count": conversation_count,
            "workflow_count": workflow_count,
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard stats: {str(e)}")