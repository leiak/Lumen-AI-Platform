"""平台级聚合统计 - 集中所有 SQL 聚合逻辑,便于后续统一维护"""
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session


_RANGE_TO_WINDOW = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class AggregateService:
    """跨租户聚合服务,所有 SQL 集中在此文件,端点只做参数/DTO 转换。"""

    def __init__(self, db: Optional[Session]):
        self.db = db

    @staticmethod
    def range_to_window(range_: str) -> timedelta:
        if range_ not in _RANGE_TO_WINDOW:
            raise ValueError(f"invalid range: {range_}, must be one of {list(_RANGE_TO_WINDOW)}")
        return _RANGE_TO_WINDOW[range_]

    def overview(self, window: timedelta) -> dict:
        from lumen_models.tenant import Tenant
        from lumen_models.user import User
        from lumen_models.agent import Agent
        from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk
        from lumen_models.workflow import Workflow
        from lumen_models.chat import Message
        from lumen_services.logging_service import AuditLog
        from datetime import datetime
        from sqlalchemy import distinct, func

        now = datetime.utcnow()
        since = now - window

        total_tenants = self.db.query(Tenant).count()
        total_users = self.db.query(User).count()
        total_agents = self.db.query(Agent).count()
        total_kbs = self.db.query(KnowledgeBase).count()
        total_workflows = self.db.query(Workflow).count()
        total_documents = self.db.query(Document).count()
        total_chunks = self.db.query(DocumentChunk).count()
        total_chat_messages = self.db.query(Message).count()

        # AI 调用:基于 audit_logs,resource_type 限定 llm_call / chat
        ai_filter = [
            AuditLog.created_at >= since,
            AuditLog.resource_type.in_(["llm_call", "chat"]),
        ]
        ai_calls = self.db.query(AuditLog).filter(*ai_filter).count()
        ai_errors = self.db.query(AuditLog).filter(
            *ai_filter, AuditLog.status == "failure"
        ).count()
        ai_error_rate = (ai_errors / ai_calls) if ai_calls > 0 else 0.0

        # 活跃 tenant/user:audit_logs 中出现过的去重
        active_tenants = self.db.query(distinct(AuditLog.tenant_id)).filter(
            AuditLog.created_at >= since
        ).filter(AuditLog.tenant_id.isnot(None)).count()
        active_users = self.db.query(distinct(AuditLog.user_id)).filter(
            AuditLog.created_at >= since
        ).filter(AuditLog.user_id.isnot(None)).count()

        # top_tenants: 按 AI 调用数倒排,前 5
        top_rows = (
            self.db.query(AuditLog.tenant_id, func.count(AuditLog.id).label("c"))
            .filter(*ai_filter)
            .filter(AuditLog.tenant_id.isnot(None))
            .group_by(AuditLog.tenant_id)
            .order_by(func.count(AuditLog.id).desc())
            .limit(5)
            .all()
        )
        top_tenants = [{"tenant_id": r[0], "ai_calls": int(r[1])} for r in top_rows]

        return {
            "total_tenants": total_tenants,
            "active_tenants": int(active_tenants),
            "total_users": total_users,
            "active_users": int(active_users),
            "total_agents": total_agents,
            "total_kbs": total_kbs,
            "total_workflows": total_workflows,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "total_chat_messages": total_chat_messages,
            "ai_calls": ai_calls,
            "ai_errors": ai_errors,
            "ai_error_rate": round(ai_error_rate, 4),
            "top_tenants": top_tenants,
            "data_source_note": "AI 调用统计基于 audit_logs 近似聚合",
        }

    def knowledge_summary(self, window: timedelta) -> dict:
        from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk
        from datetime import datetime
        from sqlalchemy import func

        now = datetime.utcnow()
        since = now - window

        total_kbs = self.db.query(KnowledgeBase).count()  # all-time (catalog total)
        total_documents = self.db.query(Document).count()  # all-time
        total_chunks = self.db.query(DocumentChunk).count()  # all-time
        parse_success = self.db.query(Document).filter(
            Document.created_at >= since, Document.status == "completed"
        ).count()
        parse_failed = self.db.query(Document).filter(
            Document.created_at >= since, Document.status == "failed"
        ).count()
        embedding_failed = self.db.query(DocumentChunk).filter(
            DocumentChunk.created_at >= since, DocumentChunk.embedding_status == "failed"
        ).count()

        by_status_rows = (
            self.db.query(Document.status, func.count(Document.id))
            .filter(Document.created_at >= since)
            .group_by(Document.status)
            .all()
        )
        by_status = [{"status": r[0] or "unknown", "count": int(r[1])} for r in by_status_rows]

        return {
            "total_kbs": total_kbs,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "parse_success": parse_success,
            "parse_failed": parse_failed,
            "embedding_failed": embedding_failed,
            "by_status": by_status,
        }

    def ai_calls_series(self, window: timedelta, granularity: str) -> dict:
        from lumen_services.logging_service import AuditLog
        from sqlalchemy import func, case
        from datetime import datetime

        now = datetime.utcnow()
        since = now - window

        # 时间桶: MySQL DATE_FORMAT 桶(粒度参数未识别时回退到 hour)
        bucket_dispatch = {
            "minute": func.date_format(AuditLog.created_at, "%Y-%m-%d %H:%i:00"),
            "hour": func.date_format(AuditLog.created_at, "%Y-%m-%d %H:00:00"),
            "day": func.date(AuditLog.created_at),
        }
        bucket_expr = bucket_dispatch.get(granularity, bucket_dispatch["hour"])

        rows = (
            self.db.query(
                bucket_expr.label("ts"),
                func.count(AuditLog.id).label("calls"),
                func.sum(case((AuditLog.status == "failure", 1), else_=0)).label("errors"),
                func.avg(AuditLog.duration_ms).label("avg_ms"),
            )
            .filter(AuditLog.created_at >= since)
            .filter(AuditLog.resource_type.in_(["llm_call", "chat"]))
            .group_by("ts")
            .order_by("ts")
            .all()
        )
        series = [
            {
                "ts": str(r[0]),
                "calls": int(r[1]),
                "errors": int(r[2] or 0),
                "avg_latency_ms": int(r[3] or 0),
                "p95_latency_ms": None,
            }
            for r in rows
        ]

        # by_model: 从 details JSON 提取(MySQL JSON_EXTRACT + JSON_UNQUOTE)
        model_expr = func.json_unquote(func.json_extract(AuditLog.details, "$.model"))
        by_model_rows = (
            self.db.query(
                model_expr.label("model"),
                func.count(AuditLog.id).label("calls"),
                func.sum(case((AuditLog.status == "failure", 1), else_=0)).label("errors"),
                func.avg(AuditLog.duration_ms).label("avg_ms"),
            )
            .filter(AuditLog.created_at >= since)
            .filter(AuditLog.resource_type.in_(["llm_call", "chat"]))
            .group_by("model")
            .order_by(func.count(AuditLog.id).desc())
            .limit(10)
            .all()
        )
        by_model = [
            {
                "model": r[0] or "unknown",
                "calls": int(r[1] or 0),
                "errors": int(r[2] or 0),
                "avg_latency_ms": int(r[3] or 0),
            }
            for r in by_model_rows
        ]

        return {"series": series, "by_model": by_model}

    def workflow_summary(self, window: timedelta) -> dict:
        from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun
        from datetime import datetime
        from sqlalchemy import func, case, text

        now = datetime.utcnow()
        since = now - window

        total_workflows = self.db.query(Workflow).count()
        total_runs = self.db.query(WorkflowRun).count()
        success = self.db.query(WorkflowRun).filter(WorkflowRun.status == "completed").count()
        failed = self.db.query(WorkflowRun).filter(WorkflowRun.status == "failed").count()
        cancelled = self.db.query(WorkflowRun).filter(WorkflowRun.status == "cancelled").count()

        # avg_duration_ms: WorkflowRun 没有 duration_ms 列,从 started_at/finished_at 计算
        # MySQL TIMESTAMPDIFF(SECOND, ...) * 1000 (MySQL 不支持 MILLISECOND 单位)
        # 仅统计 finished_at 非空的运行(进行中/中断的任务没有有效 duration)
        duration_expr = (
            func.timestampdiff(text("SECOND"), WorkflowRun.started_at, WorkflowRun.finished_at) * 1000
        )
        avg_ms_raw = (
            self.db.query(func.avg(duration_expr))
            .filter(WorkflowRun.finished_at.isnot(None))
            .scalar()
        )
        avg_ms = int(avg_ms_raw) if avg_ms_raw is not None else 0

        node_rows = (
            self.db.query(
                WorkflowNodeRun.node_type,
                func.count(WorkflowNodeRun.id).label("runs"),
                func.sum(case((WorkflowNodeRun.status == "failed", 1), else_=0)).label("errors"),
            )
            .filter(WorkflowNodeRun.created_at >= since)
            .group_by(WorkflowNodeRun.node_type)
            .all()
        )
        by_node_type = [
            {"node_type": r[0] or "unknown", "runs": int(r[1]), "errors": int(r[2] or 0)}
            for r in node_rows
        ]

        return {
            "total_workflows": total_workflows,
            "total_runs": total_runs,
            "success": success,
            "failed": failed,
            "cancelled": cancelled,
            "avg_duration_ms": avg_ms,
            "by_node_type": by_node_type,
        }

    def tenant_user_growth(self, window: timedelta) -> dict:
        from lumen_models.tenant import Tenant
        from lumen_models.user import User
        from lumen_services.logging_service import AuditLog
        from sqlalchemy import func
        from datetime import datetime

        now = datetime.utcnow()
        since = now - window

        # 累计计数(简化:每个时间窗口返回一个累计点;空库时不输出占位点)
        tenant_count = self.db.query(Tenant).count()
        user_count = self.db.query(User).count()
        tenant_growth = (
            [{"ts": since.isoformat() + "Z", "count": tenant_count}] if tenant_count > 0 else []
        )
        user_growth = (
            [{"ts": since.isoformat() + "Z", "count": user_count}] if user_count > 0 else []
        )

        # top_active_tenants: 按 audit_logs 数倒排
        top_rows = (
            self.db.query(AuditLog.tenant_id, func.count(AuditLog.id).label("c"))
            .filter(AuditLog.created_at >= since)
            .filter(AuditLog.tenant_id.isnot(None))
            .group_by(AuditLog.tenant_id)
            .order_by(func.count(AuditLog.id).desc())
            .limit(5)
            .all()
        )
        top_active_tenants = [
            # messages: None — chat message count not yet implemented, P1 uses audit_logs calls only
            {"tenant_id": r[0], "calls": int(r[1]), "messages": None} for r in top_rows
        ]

        return {
            "tenant_growth": tenant_growth,
            "user_growth": user_growth,
            "top_active_tenants": top_active_tenants,
        }
