# 模块:记忆系统

> Lumen AI Platform 的记忆(Memory)系统。
> 文档讲透对话级记忆 + 全局记忆、4 种策略、怎么用。

---

## 1. 产品定位

**记忆是什么?**
- Agent 跨对话的"长期记忆"
- 避免每轮重头说
- 包含:用户偏好 / 历史 / 上下文

**和"messages"表的区别?**
- messages: 单次会话的对话流(短期)
- memory: 跨会话的偏好 / 事实(长期)

**业务场景?**
- 用户说"我不喜欢辣" → 全局记住
- 用户昨天问过"订单 #12345" → 跨会话能回忆
- 用户偏好某种回答风格 → 永久生效

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 对话级记忆 | messages 流(短期) |
| Agent 全局记忆 | 跨会话的偏好 / 事实(长期) |
| 4 种策略 | none / sliding_window / token_limit / semantic_compression |
| 手动管理 | 浏览 / 增 / 删 / 改 |
| 自动提取 | LLM 自动从对话提取 |
| UI 管理 | 记忆页面 |

---

## 3. 数据模型

### 3.1 memories
```python
class Memory(Base):
    id: int
    agent_id: int
    user_id: int                  # 哪个用户的记忆(可空:租户级)
    tenant_id: int
    content: str                  # 记忆内容
    category: str                 # preference / fact / context
    importance: float             # 0~1,用于筛选
    source_conversation_id: int   # 来源会话(可空)
    is_active: bool
    created_at, updated_at
```

### 3.2 文件
- ORM: `backend/lumen_models/memory.py`
- Schema: `backend/lumen_schemas/memory.py`
- 服务: `backend/lumen_services/memory_service.py`
- 路由: `backend/lumen_api/v1/memory.py`

---

## 4. 4 种记忆策略(Agent 级)

### 4.1 `none`
- 不记忆,每轮独立
- 适合: 简单问答 / 工具调用

### 4.2 `sliding_window`
- 保留最近 N 条消息(默认 10)
- 超出截断最早的
- 适合: 客服对话

### 4.3 `token_limit`
- 限制总 token 数(默认 4000)
- 超出截断最早的
- 适合: 长对话

### 4.4 `semantic_compression`
- 旧消息 LLM 摘要压缩
- 保留关键信息,省 token
- 适合: 长期对话

### 4.5 配置
- 在 Agent 详情里设
- 字段: `memory_policy` / `memory_window_size` / `memory_max_tokens` / `memory_compression`

---

## 5. 对话级 vs 全局

### 5.1 对话级(messages)
- 表: `messages`
- 范围: 单次会话
- 用途: 当前会话的上下文

### 5.2 全局级(memories)
- 表: `memories`
- 范围: 跨会话(同 Agent)
- 用途: 长期偏好 / 事实

### 5.3 怎么选
- "当前聊的内容" → messages
- "用户长期偏好" → memories

---

## 6. UI

### 6.1 记忆管理
- 路径: `frontend/app/dashboard/memory/page.tsx`
- 列表: 内容 / 类别 / 重要性 / 来源会话
- 操作:增 / 改 / 删 / 启停

### 6.2 自动提取
- 开关:每个 Agent 可设 "自动提取"
- 触发:每 N 轮对话后,调 LLM 提取
- 提取:
  - 用户偏好(例: "我不喜欢辣")
  - 重要事实(例: "我的生日是 5 月 1 日")
  - 上下文(例: "我正在做 X 项目")
- 写到 memories 表

---

## 7. 关键能力详解

### 7.1 记忆提取 LLM
```python
EXTRACTION_PROMPT = """
分析下面的对话,提取用户的关键信息:
- 偏好(preference): 用户喜欢 / 不喜欢
- 事实(fact): 关于用户的事实(生日 / 职业 / ...)
- 上下文(context): 用户的当前状态

对话:
{conversation}

输出 JSON:
{
  "memories": [
    {"content": "...", "category": "preference", "importance": 0.9}
  ]
}
"""
```

### 7.2 注入到 LLM prompt
- 把 memories 作为"system"消息的一部分
- 格式:
  ```
  【用户记忆】
  - 不喜欢辣
  - 生日 5 月 1 日

  你是 ...
  ```

### 7.3 重要度排序
- 按 `importance` 降序
- 取 top K
- 自动衰减(90 天前降权重)

### 7.4 用户控制
- 用户可看 / 改 / 删自己的记忆
- 用户可关"自动提取"
- 合规: 用户有"被遗忘"的权利

---

## 8. 关键代码

### 8.1 提取
```python
# backend/lumen_services/memory_service.py
async def extract_memories(conversation: Conversation) -> list[Memory]:
    messages = get_recent_messages(conversation.id, limit=20)
    prompt = EXTRACTION_PROMPT.format(conversation=format_messages(messages))
    response = await llm.ainvoke([SystemMessage(prompt)])
    data = json.loads(response.content)

    return [
        Memory(
            agent_id=conversation.agent_id,
            user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
            content=m["content"],
            category=m["category"],
            importance=m["importance"],
            source_conversation_id=conversation.id,
        )
        for m in data["memories"]
    ]
```

### 8.2 注入
```python
async def build_messages_with_memory(agent: Agent, user_id: int, base_messages: list) -> list:
    memories = get_active_memories(agent.id, user_id, top_k=10)
    if memories:
        memory_text = "\n".join(f"- {m.content}" for m in memories)
        memory_message = SystemMessage(f"【用户记忆】\n{memory_text}")
        return [memory_message, *base_messages]
    return base_messages
```

---

## 9. 与其他模块的关系

### 9.1 与 Chat
- Chat 走 messages(对话级)
- Memory 是跨对话补充

### 9.2 与 Agent
- Agent.memory_policy 决定 messages 怎么用
- Memory 与 Agent 关联(每个 Agent 独立)

### 9.3 与 RAG 评测
- 评测可针对"有记忆 vs 无记忆"做对比

---

## 10. 边界与不做

### 10.1 当前
- ✅ 4 策略
- ✅ 全局记忆表
- ✅ 手动管理
- ✅ 自动提取
- ✅ 重要性排序

### 10.2 不做
- ❌ 长期向量记忆(暂用全文)
- ❌ 自动遗忘(用户主动)
- ❌ 记忆分享(跨 Agent)

---

## 11. 升级路径

### 短期
- 📋 向量记忆
- 📋 记忆标签

### 中期
- 📋 自动遗忘
- 📋 记忆解释(为啥记住这个)

### 长期
- 📋 跨 Agent 记忆联邦
- 📋 记忆可视化

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| Agent 不记得 | memory_policy=none | 改 sliding |
| 上下文太长 | token_limit 太大 | 调小 |
| 记忆错 | 提取 LLM 错 | 改 prompt |
| 记忆重复 | 没去重 | 加 hash 校验 |
| 注入失败 | DB 错 | 看日志 |

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06
