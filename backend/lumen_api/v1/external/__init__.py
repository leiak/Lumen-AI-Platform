"""Public-facing /api/v1/external/* routes.

These endpoints are reachable from third-party websites (the widget
loads in a browser, calls these from the visitor's machine). They use
the External JWT — NOT the user JWT — and are NOT protected by the
``require_admin`` check.

Mounted by ``app.api.v1`` at prefix ``/external``.

Sub-routers (populated in later tasks):
  - ``auth``         (Task 7) — POST /external/auth/token
  - ``chat``         (Task 10) — POST /external/chat/stream
  - ``conversations`` (Task 12) — /external/conversations/*
  - ``agents``       (Task 13) — GET /external/agents
  - ``upload``       (Task 11) — POST /external/chat/upload
"""
from fastapi import APIRouter
from . import auth, chat, conversations, agents, upload

router = APIRouter(prefix="/external", tags=["external"])
router.include_router(auth.router)
router.include_router(chat.router)
router.include_router(conversations.router)
router.include_router(agents.router)
router.include_router(upload.router)
