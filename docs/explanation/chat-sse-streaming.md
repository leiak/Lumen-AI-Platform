# SSE 流式输出

> Lumen AI Platform 的 chat / 工作流 Run / 媒体生成 / 通知 等都依赖 SSE 流式输出。
> 文档说明 Server-Sent Events 协议 + 后端怎么发 + 前端怎么收。

---

## 1. 什么是 SSE

**SSE (Server-Sent Events)** 是 HTTP 长连接,服务器可以持续推数据给客户端。

```
┌─────────┐                          ┌─────────┐
│ Browser │  GET /chat/stream        │ Server  │
│         │ ──────────────────────►  │         │
│         │  HTTP/1.1 200            │         │
│         │  Content-Type:           │         │
│         │    text/event-stream     │         │
│         │  ◄─────────────────────  │         │
│         │  data: chunk 1           │         │
│         │  ◄─────────────────────  │         │
│         │  data: chunk 2           │         │
│         │  ◄─────────────────────  │         │
│         │  data: [DONE]            │         │
└─────────┘                          └─────────┘
```

**vs WebSocket**:
- SSE: 单向(服务器 → 客户端),HTTP 协议
- WebSocket: 双向,独立协议
- SSE: 简单 / 自动重连 / 跨域友好
- WebSocket: 灵活 / 双向

Lumen 用 SSE 做 chat / 媒体(单向推送),用 WebSocket 做通知(双向 / 服务端主动)。

---

## 2. SSE 协议规范

### 2.1 Headers
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no   (防 Nginx 缓冲)
```

### 2.2 数据格式
每个 event 由若干行组成,空行分隔:
```
event: message
id: <id>
data: <data>

event: done
data: [DONE]

```

### 2.3 字段
- `event`:事件类型(默认 `message`)
- `id`:事件 ID(用于断点续传:`Last-Event-ID` header)
- `data`:数据内容(可多行)
- `retry`:客户端重连间隔(毫秒)

---

## 3. 后端实现

### 3.1 FastAPI 路由
```python
# backend/lumen_api/v1/chat.py
from fastapi.responses import StreamingResponse

@router.post("/stream")
async def stream_chat(
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    async def event_generator():
        async for chunk in chat_service.stream(payload, current_user):
            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
```

### 3.2 chat_service.stream
```python
# backend/lumen_services/chat_service.py
async def stream(payload, user):
    model = build_chat_model(agent.model_config)
    messages = build_messages(payload, agent, user)

    async for chunk in model.astream(messages):
        yield {
            "type": "content",
            "delta": chunk.content,
        }

    yield {
        "type": "done",
        "metadata": {...},
    }
```

### 3.3 CORS
- SSE 是跨域的,需要后端 CORS 允许
- Lumen 的 `DynamicCORSMiddleware` 自动处理
- 前端可用 `fetch` 或 `EventSource`

### 3.4 Nginx 反代
- 配置: `proxy_buffering off;`
- 否则 Nginx 缓冲,客户端收不到

---

## 4. 前端实现

### 4.1 用 fetch + ReadableStream
```ts
// frontend/lib/chat-sse-utils.ts
export async function* parseSSE(response: Response): AsyncGenerator<any> {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // 按空行切分 event
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''  // 剩余不完整

    for (const event of events) {
      const lines = event.split('\n')
      const dataLine = lines.find(l => l.startsWith('data: '))
      if (dataLine) {
        const data = dataLine.slice(6)
        if (data === '[DONE]') return
        yield JSON.parse(data)
      }
    }
  }
}
```

### 4.2 在 React 组件中
```tsx
async function handleSend(message: string) {
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
    },
    body: JSON.stringify({ message }),
  })

  let fullContent = ''
  for await (const chunk of parseSSE(res)) {
    if (chunk.type === 'content') {
      fullContent += chunk.delta
      setStreamingContent(fullContent)  // 实时更新 UI
    } else if (chunk.type === 'done') {
      // 完成
    }
  }
}
```

### 4.3 错误处理
```tsx
try {
  for await (const chunk of parseSSE(res)) {
    // ...
  }
} catch (e) {
  if (e.name === 'AbortError') {
    // 用户取消
  } else {
    // 网络错误 → 重连?
  }
}
```

### 4.4 取消
```tsx
const controller = new AbortController()
const res = await fetch(url, { signal: controller.signal })
// 用户点取消:
controller.abort()
```

---

## 5. 协议规范(Lumen 自定义)

### 5.1 chunk 类型
- `content`: LLM 输出增量
- `tool_call`: 工具调用决策
- `tool_result`: 工具执行结果
- `citation`: 引用 chunk(id + content)
- `done`: 完成 + metadata
- `error`: 错误

### 5.2 chunk schema
```ts
type StreamChunk =
  | { type: 'content', delta: string }
  | { type: 'tool_call', name: string, args: any, id: string }
  | { type: 'tool_result', id: string, result: string, error?: string }
  | { type: 'citation', id: number, content: string, metadata: any }
  | { type: 'done', metadata: { tokens: any, duration_ms: number } }
  | { type: 'error', message: string, code?: number }
```

### 5.3 例子
```
data: {"type": "content", "delta": "今天"}
data: {"type": "content", "delta": "北京"}
data: {"type": "content", "delta": "天气"}
data: {"type": "tool_call", "name": "get_weather", "args": {"city": "北京"}, "id": "1"}
data: {"type": "tool_result", "id": "1", "result": "晴,25°C"}
data: {"type": "content", "delta": "晴,25°C"}
data: {"type": "done", "metadata": {"tokens": {"prompt": 50, "completion": 20}, "duration_ms": 1200}}
data: [DONE]
```

---

## 6. 5 个 SSE 端点

| 端点 | 用途 | 数据 |
|------|------|------|
| `POST /api/v1/chat/stream` | Chat 流式 | LLM content + tool |
| `POST /api/v1/agents/{id}/chat/stream` | Agent chat | 同上 |
| `POST /api/v1/workflow-runs/{id}/stream` | 工作流 Run 状态 | 节点进度 |
| `POST /api/v1/external/chat/stream` | Widget 外部 chat | 同 chat |
| `POST /api/v1/videos/{id}/stream` | 视频合成进度 | 状态更新 |

---

## 7. 与 WebSocket 的分工

### 7.1 用 SSE 的场景
- 单向推送
- 短连接(< 5 分钟)
- 简单协议
- 走 HTTP 代理友好

### 7.2 用 WebSocket 的场景
- 双向
- 长连接(数小时)
- 频繁双向通信
- 消息类型多

### 7.3 Lumen 实践
- **SSE**: chat / workflow stream / 视频进度
- **WebSocket**: 通知中心 / 桌面端实时 / 多端同步

---

## 8. 性能

### 8.1 首 token 延迟(TTFT)
- LLM: 0.5~2 秒
- 端到端: 1~3 秒

### 8.2 吞吐
- 字符 / 秒
- GPT-3.5: 30~50 字/秒
- GPT-4: 15~25 字/秒
- Ollama(qwen2.5:7b): 20~40 字/秒

### 8.3 监控
- LLMCallLog `duration_ms` 字段
- 前端可见 chunk 数 + 总耗时

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 收不到任何 chunk | Nginx 缓冲 | 配 `proxy_buffering off` |
| chunk 不完整 | 多行 data 没合并 | 检查 parser |
| 连接很快断 | 反代超时 | 调 `proxy_read_timeout` |
| CORS 错 | Origin 不在白名单 | 加白名单 |
| 重复收到 | `parseSSE` 边界错 | 用 buffer 累积 |
| 客户端收不到 done | parser 提前 return | 检查 [DONE] 处理 |

---

## 10. 升级

### 10.1 二进制流
- 当前:text
- 计划:支持图片 / 视频流(多模态)

### 10.2 双向流
- 当前:SSE 单向
- 计划:用 WebTransport(Web 双向流)

### 10.3 断点续传
- 当前:不支持
- 计划:`Last-Event-ID` header

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
