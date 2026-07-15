from typing import Dict, Any, List, Optional
from fastapi import WebSocket
import asyncio
from pathlib import Path
import logging
import uuid
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    DISCONNECTED = "disconnected"


class ElectronConnection:
    """Represents a single Electron client connection"""

    def __init__(self, websocket: WebSocket, connection_id: str = None):
        self.websocket = websocket
        self.connection_id = connection_id or str(uuid.uuid4())
        self.state = ConnectionState.CONNECTED
        self.tenant_id: Optional[int] = None
        self.user_id: Optional[int] = None
        self.metadata: Dict[str, Any] = {}
        self.created_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()

    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "state": self.state.value,
            "tenant_id": self.tenant_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat()
        }


class ElectronService:
    """
    Electron Desktop 远程工具服务

    Provides secure file system operations, command execution,
    and tool integration for Electron desktop clients.
    """

    def __init__(self):
        self.connections: Dict[str, ElectronConnection] = {}
        # Path jail configuration - restrict operations to allowed directories
        self.allowed_dirs: List[Path] = []
        self._initialized = False

    def initialize(self, allowed_dirs: List[str] = None):
        """Initialize service with allowed directories for path jail"""
        if allowed_dirs:
            self.allowed_dirs = [Path(d).expanduser().resolve() for d in allowed_dirs]
        else:
            # Default to user home directory
            self.allowed_dirs = [Path.home().resolve()]
        self._initialized = True
        logger.info(f"ElectronService initialized with allowed dirs: {self.allowed_dirs}")

    def register_connection(
        self,
        websocket: WebSocket,
        connection_id: str = None,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
    ) -> ElectronConnection:
        """Register a new connection.

        ``user_id`` is None for Electron desktop clients (no per-user
        identity on the socket itself). The web-frontend ``/ws/web``
        route sets both ``user_id`` and ``tenant_id`` from the
        JWT-authenticated user so broadcasts can be filtered.
        """
        conn = ElectronConnection(websocket, connection_id)
        conn.user_id = user_id
        if tenant_id is not None:
            conn.tenant_id = tenant_id
        self.connections[conn.connection_id] = conn
        logger.info(f"New Electron connection: {conn.connection_id}")
        return conn

    def unregister_connection(self, connection_id: str):
        """Unregister an Electron connection"""
        if connection_id in self.connections:
            del self.connections[connection_id]
            logger.info(f"Electron connection closed: {connection_id}")

    def get_connection(self, connection_id: str) -> Optional[ElectronConnection]:
        """Get connection by ID"""
        return self.connections.get(connection_id)

    def get_active_connections(self) -> List[ElectronConnection]:
        """Get all active connections"""
        return list(self.connections.values())

    async def broadcast_event_async(
        self,
        event_type: str,
        payload: dict,
        target_user_id: Optional[int] = None,
    ) -> int:
        """向所有活跃 Electron 连接广播事件。

        若 ``target_user_id`` 不为 None,只投递给该 user_id 的连接
        (Electron 客户端 user_id=None,不会收到;浏览器多 tab 同
        user_id 都收)。``target_user_id=None`` 保持现状全员广播。

        Returns:
            成功发送的连接数。
        """
        sent = 0
        for conn_id, conn in list(self.connections.items()):
            if target_user_id is not None and conn.user_id != target_user_id:
                continue
            try:
                await conn.websocket.send_json({
                    "type": "broadcast",
                    "event": event_type,
                    "payload": payload,
                })
                sent += 1
            except Exception as e:
                logger.warning(f"Failed to broadcast to {conn_id}: {e}")
                self.connections.pop(conn_id, None)
        return sent

    async def handle_message(self, data: dict, connection_id: str = None) -> dict:
        """
        处理来自 Electron 的消息

        Expected message format:
        {
            "id": "uuid",  // Message correlation ID
            "action": "execute|read_file|write_file|list_dir|tool_call|health",
            "params": {...}
        }

        Response format:
        {
            "id": "uuid",  // Correlates with request
            "success": true|false,
            "data": {...} or "error": "..."
        }
        """
        if not self._initialized:
            self.initialize()

        message_id = data.get("id", str(uuid.uuid4()))
        action = data.get("action")
        params = data.get("params", {})

        # Update connection activity if connection_id provided
        if connection_id:
            conn = self.get_connection(connection_id)
            if conn:
                conn.update_activity()

        try:
            result = await self._dispatch_action(action, params)
            return {
                "id": message_id,
                "success": True,
                "data": result
            }
        except Exception as e:
            logger.error(f"Error handling message {message_id}: {e}")
            return {
                "id": message_id,
                "success": False,
                "error": str(e)
            }

    async def _dispatch_action(self, action: str, params: dict) -> dict:
        """Dispatch action to appropriate handler"""
        handlers = {
            "execute": self.execute_command,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "list_dir": self.list_dir,
            "tool_call": self.tool_call,
            "health": self.health_check,
            "authenticate": self.authenticate,
            "status": self.get_status,
        }

        handler = handlers.get(action)
        if not handler:
            raise ValueError(f"Unknown action: {action}")

        return await handler(params)

    def _validate_path(self, file_path: str, require_in_allowed: bool = True) -> Path:
        """Validate and sanitize file path with path jail"""
        p = Path(file_path).expanduser().resolve()

        if require_in_allowed:
            # Check if path is within allowed directories
            is_allowed = any(
                p.is_relative_to(allowed_dir) or p == allowed_dir
                for allowed_dir in self.allowed_dirs
            )
            if not is_allowed:
                raise PermissionError(f"Path '{file_path}' is outside allowed directories")

        return p

    async def authenticate(self, params: dict) -> dict:
        """Authenticate the Electron connection with tenant info"""
        token = params.get("token")
        tenant_id = params.get("tenant_id")

        # In production, validate JWT token here
        # For now, just store the info
        return {
            "authenticated": True,
            "tenant_id": tenant_id,
            "message": "Authentication successful"
        }

    async def execute_command(self, params: dict) -> dict:
        """执行 Shell 命令"""
        command = params.get("command", "")
        cwd = params.get("cwd")
        timeout = params.get("timeout", 30)  # Default 30 second timeout

        if not command:
            raise ValueError("Command is required")

        try:
            # Validate cwd if provided
            if cwd:
                self._validate_path(cwd)

            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise TimeoutError(f"Command timed out after {timeout} seconds")

            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode
            }

        except FileNotFoundError as e:
            raise FileNotFoundError(f"Command not found: {str(e)}")
        except PermissionError as e:
            raise PermissionError(f"Permission denied: {str(e)}")
        except TimeoutError as e:
            raise TimeoutError(str(e))
        except Exception as e:
            raise RuntimeError(f"Command execution failed: {str(e)}")

    async def read_file(self, params: dict) -> dict:
        """读取文件"""
        file_path = params.get("path", "")
        encoding = params.get("encoding", "utf-8")
        max_size = params.get("max_size", 1024 * 1024)  # Default 1MB max

        if not file_path:
            raise ValueError("Path is required")

        p = self._validate_path(file_path)

        if not p.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not p.is_file():
            raise IsADirectoryError(f"Path is a directory, not a file: {file_path}")

        # Check file size
        file_size = p.stat().st_size
        if file_size > max_size:
            raise ValueError(f"File too large: {file_size} bytes (max: {max_size})")

        try:
            content = p.read_text(encoding, errors="replace")
            return {
                "success": True,
                "content": content,
                "size": file_size,
                "path": str(p)
            }
        except (PermissionError, OSError) as e:
            raise PermissionError(f"Cannot read file: {str(e)}")

    async def write_file(self, params: dict) -> dict:
        """写入文件"""
        file_path = params.get("path", "")
        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")
        create_parents = params.get("create_parents", True)

        if not file_path:
            raise ValueError("Path is required")

        p = self._validate_path(file_path)

        try:
            if create_parents:
                p.parent.mkdir(parents=True, exist_ok=True)

            p.write_text(content, encoding)
            return {
                "success": True,
                "path": str(p),
                "size": len(content)
            }
        except (PermissionError, OSError) as e:
            raise PermissionError(f"Cannot write file: {str(e)}")

    async def list_dir(self, params: dict) -> dict:
        """列出目录"""
        dir_path = params.get("path", ".")
        max_items = params.get("max_items", 1000)

        p = self._validate_path(dir_path)

        if not p.exists():
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        if not p.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {dir_path}")

        try:
            items = []
            for item in p.iterdir():
                if len(items) >= max_items:
                    break
                try:
                    stat = item.stat()
                    items.append({
                        "name": item.name,
                        "is_dir": item.is_dir(),
                        "is_file": item.is_file(),
                        "size": stat.st_size if item.is_file() else 0,
                        "modified": stat.st_mtime
                    })
                except (PermissionError, OSError):
                    # Skip items we can't access
                    continue

            return {
                "success": True,
                "path": str(p),
                "items": items,
                "count": len(items)
            }
        except (PermissionError, OSError) as e:
            raise PermissionError(f"Cannot list directory: {str(e)}")

    async def tool_call(self, params: dict) -> dict:
        """Execute a tool via MCP integration"""
        tool_name = params.get("tool_name")
        tool_params = params.get("params", {})
        connection_id = params.get("connection_id")

        if not tool_name:
            raise ValueError("Tool name is required")

        # In production, this would call the MCP service
        # For now, return a placeholder response
        return {
            "success": True,
            "tool": tool_name,
            "result": {"message": "Tool execution via MCP"},
            "connection_id": connection_id
        }

    async def health_check(self, params: dict) -> dict:
        """Health check endpoint"""
        return {
            "status": "ok",
            "service": "electron",
            "timestamp": datetime.utcnow().isoformat(),
            "active_connections": len(self.connections)
        }

    async def get_status(self, params: dict) -> dict:
        """Get service status and connection info"""
        connections = [
            {
                "id": conn.connection_id,
                "state": conn.state.value,
                "last_activity": conn.last_activity.isoformat()
            }
            for conn in self.connections.values()
        ]

        return {
            "service": "electron",
            "status": "running",
            "initialized": self._initialized,
            "allowed_directories": [str(d) for d in self.allowed_dirs],
            "active_connections": len(connections),
            "connections": connections
        }


# Singleton instance
electron_service = ElectronService()


def broadcast_event_sync(
    event: str,
    payload: dict,
    target_user_id: Optional[int] = None,
    timeout: float = 5.0,
) -> int:
    """Best-effort fire-and-forget broadcast for callers in another process (e.g. Celery worker).

    Posts a wrapped envelope to the existing FastAPI HTTP endpoint
    ``POST /api/v1/electron/broadcast`` so the in-process
    ``ElectronService`` instance can fan the message out to active
    WebSocket connections. The endpoint is expected to broadcast the
    SAME ``{"type": "broadcast", "event": event, "payload": payload}``
    envelope that ``broadcast_event_async`` produces — see
    ``backend/app/api/v1/electron_ws.py``.

    If ``target_user_id`` is given, also forwards it in the body and
    sets the ``X-Internal-Broadcast`` header from the
    ``BROADCAST_INTERNAL_SECRET`` env var. The receiving ``/broadcast``
    route uses this to decide whether to apply the user_id filter —
    without the matching secret the field is dropped, so Electron
    clients (which don't set target_user_id) are unaffected. See
    ``backend/app/api/v1/electron_ws.py`` for the auth model.

    Returns:
        成功送达的客户端数(0 表示失败/无客户端)。

    Note:
        Sync-only. If the calling context becomes async, use
        ``broadcast_event_async`` instead.
    """
    import os
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed; skipping electron broadcast")
        return 0
    try:
        backend_base = os.environ.get("BACKEND_PUBLIC_URL", "http://localhost:11335")
        body = {
            "type": "broadcast",
            "event": event,
            "payload": payload,
            "target_user_id": target_user_id,
        }
        headers = {"Content-Type": "application/json"}
        secret = os.environ.get("BROADCAST_INTERNAL_SECRET", "")
        if secret and target_user_id is not None:
            headers["X-Internal-Broadcast"] = secret
        resp = httpx.post(
            f"{backend_base}/api/v1/electron/broadcast",
            json=body,
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code >= 400:
            logger.warning(f"electron broadcast HTTP {resp.status_code}: {resp.text[:200]}")
            return 0
        try:
            return int(resp.json().get("sent", 0))
        except Exception:
            return 0
    except Exception as e:
        logger.warning(f"Failed to broadcast {event}: {e}")
        return 0
