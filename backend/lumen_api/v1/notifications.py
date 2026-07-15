"""Notifications REST API.

All endpoints require the current user; queries are scoped to
current_user.id (no cross-user visibility, ever). The list endpoint
uses cursor pagination by id DESC; the response is wrapped in the
project's standard envelope.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import SessionLocal
from lumen_models.notification import Notification
from lumen_models.user import User
from lumen_schemas.common import SingleResponse, PaginatedResponse


router = APIRouter()


def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[int] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(_get_db),
):
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    if cursor is not None:
        q = q.filter(Notification.id < cursor)
    rows = q.order_by(Notification.id.desc()).limit(limit + 1).all()
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = items[-1].id if has_more and items else None

    unread_count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read_at.is_(None),
    ).count()

    return SingleResponse(data={
        "items": [_serialize(n) for n in items],
        "next_cursor": next_cursor,
        "unread_count": unread_count,
    })


@router.get("/notifications/unread-count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(_get_db),
):
    count = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read_at.is_(None),
    ).count()
    return SingleResponse(data={"count": count})


@router.post("/notifications/{nid}/read")
def mark_read(
    nid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(_get_db),
):
    n = db.query(Notification).filter(
        Notification.id == nid,
        Notification.user_id == current_user.id,
    ).first()
    if not n:
        raise HTTPException(status_code=404, detail="notification not found")
    if n.read_at is None:
        n.read_at = datetime.utcnow()
        db.commit()
    return SingleResponse(data={"id": n.id, "read_at": n.read_at.isoformat()})


@router.post("/notifications/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(_get_db),
):
    now = datetime.utcnow()
    affected = db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.read_at.is_(None),
    ).update({"read_at": now}, synchronize_session=False)
    db.commit()
    return SingleResponse(data={"affected": affected})


def _serialize(n: Notification) -> dict:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "type": n.type,
        "title": n.title,
        "body": n.body,
        "resource_type": n.resource_type,
        "resource_id": n.resource_id,
        "metadata": n.metadata_json,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "created_at": n.created_at.isoformat(),
    }
