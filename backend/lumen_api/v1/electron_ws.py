from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Request, Header, HTTPException
from typing import List, Optional
from lumen_services.electron_service import electron_service, ElectronConnection
from lumen_core.config import settings

router = APIRouter(tags=["electron"])


@router.websocket("/ws/electron")
async def electron_websocket(
    websocket: WebSocket,
    connection_id: Optional[str] = Query(None)
):
    """
    Electron WebSocket 端点

    Provides bidirectional communication with Electron desktop clients.
    Supports file operations, command execution, and tool calls.
    """
    # Register connection
    conn = electron_service.register_connection(websocket, connection_id)

    try:
        # Accept the WebSocket connection (required by ASGI before any send)
        await websocket.accept()

        # Send connection acknowledgment
        await websocket.send_json({
            "type": "connection_established",
            "connection_id": conn.connection_id,
            "message": "Connected to AI Platform Electron Service"
        })

        # Main message loop
        while True:
            data = await websocket.receive_json()
            conn.update_activity()

            # Handle batch messages
            if data.get("type") == "batch":
                # Process batch of messages
                results = []
                for msg in data.get("messages", []):
                    result = await electron_service.handle_message(msg, conn.connection_id)
                    results.append(result)
                await websocket.send_json({
                    "type": "batch_response",
                    "results": results
                })
            else:
                # Process single message
                result = await electron_service.handle_message(data, conn.connection_id)
                await websocket.send_json(result)

    except WebSocketDisconnect:
        electron_service.unregister_connection(conn.connection_id)
    except Exception as e:
        electron_service.unregister_connection(conn.connection_id)
        # Try to send error before closing
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except:
            pass
        raise


@router.get("/electron/status")
async def get_electron_status():
    """
    获取 Electron 服务状态

    Returns information about the service and active connections.
    """
    status = await electron_service.handle_message({
        "action": "status"
    })
    return status.get("data", status)


@router.get("/electron/connections")
async def list_connections():
    """列出所有活动的 Electron 连接"""
    connections = electron_service.get_active_connections()
    return {
        "connections": [conn.to_dict() for conn in connections],
        "count": len(connections)
    }


@router.post("/electron/broadcast")
async def broadcast_message(
    request: Request,
    x_internal_broadcast: str = Header(default=""),
):
    """向所有活跃 WebSocket 客户端广播消息。

    Accepts the canonical envelope:
        {"type": "broadcast", "event": <event>, "payload": <payload>,
         "target_user_id": <int|None>}

    The optional ``target_user_id`` scopes the broadcast to one user (across
    all their browser tabs). It is ONLY honored when the caller presents
    a matching ``X-Internal-Broadcast: <BROADCAST_INTERNAL_SECRET>`` header.
    Without the secret (or with the wrong value), ``target_user_id`` is
    dropped and the broadcast fans out to every connected client — the
    existing Electron-compatible behavior. This prevents untrusted Electron
    clients from spoofing "send only to user X".

    For backward compatibility, if the caller posts a flat dict (no
    "payload" key), all non-`type` keys are promoted into the payload
    slot so legacy callers keep working.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="invalid json body")

    target_user_id = body.get("target_user_id")
    if target_user_id is not None and not isinstance(target_user_id, int):
        # Reject anything that isn't a JSON int (string "42", list, dict, bool, etc.)
        # silently — callers with the secret are internal but may mis-serialize.
        target_user_id = None
    if target_user_id is not None:
        secret = settings.BROADCAST_INTERNAL_SECRET
        if not secret or x_internal_broadcast != secret:
            # Untrusted caller tried to scope the broadcast; fall back to
            # fan-out-to-all so the existing Electron path keeps working.
            target_user_id = None

    event = body.get("event")
    if "payload" in body:
        payload = body.get("payload") or {}
    else:
        payload = {k: v for k, v in body.items() if k != "type"}

    sent = await electron_service.broadcast_event_async(
        event_type=event or "",  # M30: param is `event_type`, not `event`
        payload=payload,
        target_user_id=target_user_id,
    )
    return {"sent": sent, "total": len(electron_service.connections)}


@router.get("/electron/health")
async def electron_health():
    """Electron 服务健康检查"""
    try:
        health = await electron_service.handle_message({"action": "health"})
        return {
            "healthy": health.get("success", False),
            **health.get("data", {})
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e)
        }


@router.websocket("/ws/web")
async def web_websocket(
    websocket: WebSocket,
    token: str = Query(""),
):
    """Authenticated WebSocket for the web frontend.

    Auth: JWT in ``?token=...`` query string. Bad/expired token → 4401.
    On accept, registers the connection in ``ElectronService`` with the
    user's id and tenant. Heartbeat: client should send
    ``{"type":"ping"}`` every 25s; server replies with ``{"type":"pong"}``
    and closes on 120s of silence.
    """
    import asyncio
    from lumen_core.security import decode_access_token
    from lumen_core.database import SessionLocal
    from lumen_models.user import User

    if not token:
        await websocket.close(code=4401)
        return

    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=4401)
        return

    username = payload.get("sub")
    if not username:
        await websocket.close(code=4401)
        return

    db = SessionLocal()
    conn = None
    try:
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            await websocket.close(code=4401)
            return

        await websocket.accept()
        conn = electron_service.register_connection(
            websocket,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        await websocket.send_json({
            "type": "connection_acknowledged",
            "connection_id": conn.connection_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
        })

        # Heartbeat loop: client sends {"type":"ping"}; we reply pong.
        # If no frame (ping or otherwise) for 120s, close with 4408.
        while True:
            try:
                msg = await asyncio.wait_for(
                    websocket.receive_json(), timeout=120.0
                )
            except asyncio.TimeoutError:
                await websocket.close(code=4408)
                break
            except WebSocketDisconnect:
                break
            conn.update_activity()
            if isinstance(msg, dict) and msg.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        # Best-effort error surface; on failure we just close.
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        if conn is not None:
            try:
                electron_service.unregister_connection(conn.connection_id)
            except Exception:
                pass
        db.close()
