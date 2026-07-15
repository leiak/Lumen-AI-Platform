"""
Local MCP demo server startup script.

Usage:
    python backend/run_mcp_server.py

Environment variables:
    MCP_PORT (default 8765)  - port to listen on
    MCP_HOST (default 127.0.0.1) - host to bind
    MCP_DEFAULT_TENANT_ID (default 1) - tenant used by tools when
        tenant_id is not explicitly provided
"""
import os
import sys

# Make ``lumen_*`` packages importable when this script is run directly
# from any working directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8765"))
    host = os.getenv("MCP_HOST", "127.0.0.1")

    try:
        uvicorn.run(
            "lumen_mcp_servers.local_demo:app",
            host=host, port=port, log_level="info",
        )
    except OSError as e:
        # Windows raises WinError 10048 (address in use); POSIX raises
        # errno 98 with message "address already in use". Catch both.
        msg = str(e).lower()
        if "address already in use" in msg or e.errno in (98, 10048):
            print(
                f"❌ Port {port} is in use. Set MCP_PORT to a free port and retry.",
                file=sys.stderr,
            )
            sys.exit(1)
        raise
