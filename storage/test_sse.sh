#!/bin/bash
# Simulate a full MCP SSE client flow to diagnose Trae issue.
# Step 1: GET /sse, capture session_id from event: endpoint
echo "=== Step 1: GET /sse ==="
RESP=$(curl -sS -N --max-time 3 http://localhost:8765/sse 2>&1)
echo "$RESP"
SESSION_URL=$(echo "$RESP" | grep -oE '/messages/\?session_id=[a-f0-9]+' | head -1)
echo ""
echo "=== Captured SESSION_URL: $SESSION_URL ==="
echo ""

if [ -z "$SESSION_URL" ]; then
  echo "FAIL: server didn't return event: endpoint"
  exit 1
fi

# Step 2: POST initialize
echo "=== Step 2: POST initialize ==="
curl -sS -i -X POST "http://localhost:8765${SESSION_URL}" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test-curl", "version": "1.0"}
    }
  }' | head -10
echo ""
sleep 1

# Step 3: POST notifications/initialized
echo "=== Step 3: POST notifications/initialized ==="
curl -sS -i -X POST "http://localhost:8765${SESSION_URL}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' | head -5
echo ""
sleep 1

# Step 4: POST tools/list
echo "=== Step 4: POST tools/list ==="
curl -sS -i -X POST "http://localhost:8765${SESSION_URL}" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | head -10
echo ""
sleep 1

echo "=== Done ==="
