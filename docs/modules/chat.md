# 模块:聊天 / 对话

> Lumen AI Platform 的 Chat 界面,流式对话的核心交互。
> 文档从产品视角讲透对话能做什么、关键交互、与 Agent 的关系。

---

## 1. 产品定位

**Chat 是什么?**
- 1 个 Chat = 1 个 conversation(会话),含多条 messages
- 选 Agent(或多 Agent 团队)→ 发消息 → 流式收回复
- 多个会话并列,左侧列表

**和"通用 ChatGPT"比有什么不同?**
- 按对话绑定 Agent(M14 ship): 每个会话可挂不同 Agent
- 引用 KB 文档(Citations): 答案带"来源"标签
- 业务系统集成: 能查 CRM / 调工具 / 看工作流
- 多端访问: Web / 桌面 / 第三方 Widget

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 会话列表 | 左栏,按时间倒序 |
| 新建会话 | 选 Agent / 选团队 / 留空 |
| 消息流 | 用户消息 / AI 回复 / 工具调用 / 引用 |
| 流式输出 | SSE,逐字渲染 |
| 引用显示 | 点 Citations 看 KB 来源 |
| 会话改名 | 点标题编辑 |
| 删除会话 | 软删除(deleted_at) |
| 切 Agent | 顶部下拉 |
| 多轮上下文 | 记忆策略 |
| 实时通知 | 完成后 WS 推送(可选) |

---

## 3. 数据模型

### 3.1 conversations
```python
class Conversation(Base):
    id: int
    title: str                     # 默认取首条消息前 30 字
    user_id: int                   # 创建者
    tenant_id: int
    agent_id: int                  # 绑定的 Agent(可空,表示"默认")
    team_id: int                   # 绑定的团队(可空)
    external_app_id: int           # 外部应用(可空)
    external_visitor_id: int       # 外部访客(可空)
    deleted_at: datetime           # 软删除
```

### 3.2 messages
```python
class Message(Base):
    id: int
    conversation_id: int
    role: str                      # user / assistant / system / tool
    content: str                   # 文本
    msg_metadata: dict             # JSON: 引用 / tool_call / ...
    created_at: datetime
```

### 3.3 文件
- ORM: `backend/lumen_models/chat.py`
- Schema: `backend/lumen_schemas/chat.py`
- 服务: `backend/lumen_services/chat_service.py`
- 路由: `backend/lumen_api/v1/chat.py`

---

## 4. UI

### 4.1 列表(左栏)
- 路径: `frontend/app/dashboard/chat/page.tsx`
- 显示:会话标题 + 时间 + Agent 标签
- 操作:点击切换 / 新建 / 删除 / 改名

### 4.2 消息流(右栏)
- 路径: 同上
- 用户消息: 右对齐,蓝色
- AI 消息: 左对齐,白底
- 工具调用:折叠显示(点开看详情)
- 引用 Citations: 末尾 chip 列表
- 输入框: 底部,Enter 发送 / Shift+Enter 换行

### 4.3 顶部 Agent 切换器
- 当前会话的 Agent 显示
- 点下拉换 Agent(改了重新加载记忆)

### 4.4 关键组件
- `frontend/components/chat/MessageBubble.tsx`
- `frontend/components/chat/Markdown.tsx`
- `frontend/components/chat/Citations.tsx`
- `frontend/components/chat/AttachmentChip.tsx`

---

## 5. 关键能力详解

### 5.1 流式输出(SSE)
- 后端用 `StreamingResponse(media_type="text/event-stream")`
- 前端用 `parseSSE` 解析
- LLM 推 chunk → 前端逐字渲染
- 详见 [explanation/chat-sse-streaming.md](../explanation/chat-sse-streaming.md)

### 5.2 多轮上下文
- 消息流: [system, ...history, user]
- `history` 来自 messages 表
- 受 Agent.memory_policy 限制:
  - `sliding_window`: 留最近 N 条
  - `token_limit`: 留 N token 内
  - `semantic_compression`: 旧消息 LLM 摘要
  - `none`: 只看当前 user

### 5.3 引用(Citations)
- LLM 回答中引用的 KB chunk
- 数据: `msg_metadata.citations: [{id, content, score, document_id}]`
- 前端: `Citations.tsx` 渲染
- 点 chip → 跳到文档详情 + 高亮 chunk

### 5.4 工具调用展示
- AI 决定调工具时,UI 显示"正在查订单..."
- 工具返回后,继续流式输出
- 详见 [tool-calling](../explanation/tool-calling.md)

### 5.5 按对话绑定 Agent(M14)
- 创建会话时选 Agent
- 会话列表显示 Agent 标签
- 切换 Agent → 重置 memory(从该 Agent 配置)
- 业务价值: 同一用户能跟"销售 Agent"和"技术 Agent"分别对话

### 5.6 删除会话(软删除)
- 实际打 `deleted_at`
- 前端不显示,但不真正 DELETE
- 30 天后清理(Celery beat)

### 5.7 会话标题自动生成
- 默认:首条 user 消息前 30 字
- 可手动改
- 计划:AI 自动起名

---

## 6. 外部访客对话

### 6.1 场景
- 第三方网站嵌入 Widget
- 访客没注册,但有 `external_visitor_id`
- conversation 带 `external_app_id` + `external_visitor_id`

### 6.2 数据隔离
- 内部用户对话: `user_id != null`, `external_app_id == null`
- 外部访客对话: `user_id == null`, `external_app_id != null`
- 列表:不同 query

详见 [external-app-auth](external-app-auth.md)。

---

## 7. 关键代码

### 7.1 后端 Chat 流程
```python
# backend/lumen_services/chat_service.py
async def stream(payload: ChatRequest, current_user: User):
    # 1. 解析 conversation
    conv = get_or_create_conversation(payload.conversation_id, current_user)

    # 2. 加载 Agent(按 conv.agent_id)
    agent = get_agent(conv.agent_id, current_user.tenant_id)

    # 3. 加载历史
    history = get_messages(conv.id, limit=memory_window_size)

    # 4. 拼 messages
    messages = [
        SystemMessage(agent.prompt_template),
        *history,
        HumanMessage(payload.message),
    ]

    # 5. 5 轮 tool loop + 流式
    async for chunk in agent_service.chat_stream(agent, messages, current_user):
        yield chunk
```

### 7.2 前端 SSE 处理
```tsx
// frontend/app/dashboard/chat/page.tsx
const handleSend = async (text: string) => {
  setStreaming(true)
  const res = await fetch(`${API_URL}/chat/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ conversation_id: convId, message: text }),
  })

  let fullContent = ''
  for await (const chunk of parseSSE(res)) {
    if (chunk.type === 'content') {
      fullContent += chunk.delta
      setStreamingContent(fullContent)
    } else if (chunk.type === 'citation') {
      setCitations([...citations, chunk])
    } else if (chunk.type === 'done') {
      // 完成
    }
  }
  setStreaming(false)
}
```

详见 [explanation/chat-sse-streaming.md](../explanation/chat-sse-streaming.md)。

---

## 8. 边界与不做

### 8.1 当前
- ✅ 多轮对话
- ✅ 流式输出
- ✅ 4 记忆策略
- ✅ 引用 KB
- ✅ 工具调用展示
- ✅ 切 Agent
- ✅ 软删除
- ✅ 外部访客

### 8.2 不做
- ❌ 语音输入(Web Speech API 计划中)
- ❌ 图片理解(多模态计划中)
- ❌ 会话导出
- ❌ 会话分享链接

---

## 9. 升级路径

### 短期
- 📋 语音输入
- 📋 会话搜索
- 📋 会话标签

### 中期
- 📋 多模态(图 / 音输入)
- 📋 会话分支(在同一会话中"分叉")
- 📋 AI 自动起名

### 长期
- 📋 跨会话知识沉淀
- 📋 会议纪要自动生成

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 流式断流 | Nginx 缓冲 | 配 `proxy_buffering off` |
| 引用不显示 | KB 检索 0 结果 | 上传更多文档 |
| 上下文丢失 | memory_policy=sliding + window_size 小 | 调大 |
| 切 Agent 不生效 | conv.agent_id 没改 | 调 PATCH /conversations/{id} |
| 消息重复 | SSE parser 边界错 | 检查 parseSSE |
| LLM 慢 | 模型慢 | 换模型 |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06
