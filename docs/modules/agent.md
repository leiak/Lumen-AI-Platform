# 模块:AI Agent

> Lumen AI Platform 的核心模块 —— 单 AI Agent 的完整生命周期。
> 文档从产品视角讲透 Agent 能做什么、怎么用、关键参数。

---

## 1. 产品定位

**Agent 是什么?**
- 1 个 Agent = 1 个"AI 员工",有名字、性格、知识、工具、记忆
- 例:"销售助理" Agent 能查 CRM + 查产品手册 + 给客户发消息

**和"ChatGPT"比有什么不同?**
- ChatGPT 是通用对话;Agent 是"业务定制"
- Agent 有专属知识库(不是 ChatGPT 训练时的数据)
- Agent 有专属工具(不是 ChatGPT 插件)
- Agent 有记忆(不是 ChatGPT 隔次清空)
- Agent 可工作流编排(不是 ChatGPT 单轮)

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| Agent CRUD | 创建 / 编辑 / 删除 / 启停 |
| 系统提示词 | 人格 + 业务规则 |
| 模型选择 | LLM / 温度 / max_tokens |
| 工具选择 | 内置 + MCP + 技能 + 工作流 |
| 知识库关联 | 多 KB 检索 |
| 记忆策略 | 4 种(none / sliding_window / token_limit / semantic_compression) |
| 工具选择策略 | auto / required / none / specific |
| 工具最大迭代 | 默认 5 轮 |
| 流式对话 | SSE |
| 对话历史 | messages 表 |

---

## 3. Agent 模型

### 3.1 核心字段
```python
class Agent(Base):
    id: int
    name: str                        # 名字
    description: str                 # 描述
    prompt_template: str             # 系统提示词
    model_config_id: int             # 用哪个 LLM
    temperature: int                 # 0~100(存整数)
    max_tokens: int                  # LLM 输出上限
    is_active: bool                  # 启停
    config: dict                     # 额外配置(JSON)

    # 记忆
    memory_policy: str               # none / sliding_window / token_limit / semantic_compression
    memory_window_size: int          # 滑动窗口大小
    memory_max_tokens: int           # token 限制
    memory_compression: bool         # 是否语义压缩

    # 工具
    tool_choice: str                 # auto / required / none / specific
    tool_choice_required: bool       # 是否必须调
    allowed_tools: list              # 白名单(空 = 全部)

    # 知识库
    kb_retrieval_config: dict        # per-KB top_k / score

    # 多租户
    tenant_id: int
```

### 3.2 文件
- ORM: `backend/lumen_models/agent.py`
- Schema: `backend/lumen_schemas/agent.py`
- 服务: `backend/lumen_services/agent_service.py`
- 路由: `backend/lumen_api/v1/agent.py`

---

## 4. UI

### 4.1 列表
- 路径: `frontend/app/dashboard/agent/page.tsx`
- 表格:名字 / 描述 / 模型 / 状态 / 创建时间
- 操作:对话(打开 Chat) / 编辑 / 启停 / 删除

### 4.2 创建 / 编辑表单
- 文件: `frontend/components/agent/AgentFormModal.tsx`
- 字段:
  - 基本:名字 / 描述
  - 系统提示词(代码风格编辑器)
  - 模型:ChatModelSelect
  - 温度:0~100 滑块
  - 工具:多选(列表)
  - 知识库:MultiKBSelector + per-KB 配置
  - 记忆策略:下拉
  - 工具选择策略:下拉

### 4.3 详情 / 对话
- 路径: `frontend/app/dashboard/agent/page.tsx` 内嵌 Modal
- 直接在 Agent 列表点"对话" → 打开 Chat Modal

---

## 5. 关键能力详解

### 5.1 系统提示词(Prompt)
- 用户故事: "我想让 AI 表现得像资深销售,亲切、专业、能查订单"
- 模板示例:
  ```
  你是 Lumen 公司的资深销售助理,负责服务 B 端客户。
  你的特点:
  - 亲切但不谄媚
  - 主动了解客户需求
  - 严格按公司报价表报价
  - 客户问技术细节时,调知识库
  - 不确定就说不确定,不要编
  ```
- 支持 `{{variable}}` 变量引用(运行时替换)
- 支持 Markdown

### 5.2 模型选择
- 来源: `model_configs` 表
- 筛选: `is_chat=True` (M13 加)
- 选哪个? 业务 / 性能 / 成本三选一
  - 业务:支持 function call + 上下文长度
  - 性能:QPS / TTFT
  - 成本:每 1k token 价
- 推荐:默认 Ollama(qwen2.5:7b)用于内部 demo,生产用 OpenAI GPT-4o

### 5.3 温度(temperature)
- 0~100(存整数,前端显示 0.0~1.0)
- 0 = 精确(查 KB / 工具)
- 50 = 平衡(对话)
- 100 = 创造(文案生成)
- 默认:50

### 5.4 工具
- 5 大来源:
  1. **内置工具**: `knowledge_retrieval` / `http_request` / `code_execution`
  2. **MCP 工具**: `<server>__<tool>`
  3. **技能 Tool**: 租户注册的
  4. **工作流**: 整个工作流作为工具
  5. **Agent 自身**: 多 Agent 团队中其他 Agent
- `allowed_tools` 白名单(空 = 全部可用)
- 详见 [explanation/tool-calling.md](../explanation/tool-calling.md)

### 5.5 知识库关联
- 多对多:`agent_knowledge_bases` 中间表
- `kb_retrieval_config` JSON per-KB:
  ```json
  {
    "kb_<id>_top_k": 5,
    "kb_<id>_score_threshold": 0.5,
    "kb_<id>_vector_weight": 0.7,
    "kb_<id>_keyword_weight": 0.3
  }
  ```
- UI: `components/agent/MultiKBSelector.tsx` + `components/agent/KbRetrievalConfigFields.tsx`

### 5.6 记忆策略
- `none` — 不记忆(每轮独立)
- `sliding_window` — 保留最近 N 条(默认 10)
- `token_limit` — 限制总 token(默认 4000)
- `semantic_compression` — 旧消息 LLM 摘要压缩
- 详见 [memory 模块](memory.md)

### 5.7 工具选择策略
- `auto` — LLM 决定(默认)
- `required` — 必须调至少一个
- `none` — 禁止调工具
- `specific` — 必须调指定工具(配合 `allowed_tools`)

---

## 6. Agent 对话

### 6.1 入口
- 路径 A: `dashboard/chat`(选 Agent 聊天)
- 路径 B: Agent 列表点"对话"按钮(临时对话)
- 路径 C: 第三方 Widget 嵌入(`external_apps.agent_id` 绑定)

### 6.2 流程
```
用户输入
   │
   ▼
1. 加载 Agent 配置(模型 / 工具 / KBs)
2. 加载对话历史(messages)
3. 加载 memory(按 memory_policy)
4. 构造 messages: [system, ...history, user]
5. 5 轮 tool loop:
   a. 调 LLM(LoggingChatModel 包装)
   b. LLM 决定:返回 content 或 tool_calls
   c. 调 tool / 查 KB
   d. 拼回 messages
6. 流式返回 SSE
7. 写 messages 表
```

### 6.3 关键代码
- 服务: `backend/lumen_services/agent_service.py::chat`
- 流式: `agent_service.stream`
- 前端 Chat: `frontend/app/dashboard/chat/page.tsx`

详见 [chat 模块](chat.md) 和 [explanation/tool-calling.md](../explanation/tool-calling.md)。

---

## 7. 边界与不做

### 7.1 当前
- ✅ 单 Agent 完整 CRUD
- ✅ 5 轮 tool loop
- ✅ 多 KB
- ✅ 4 记忆策略
- ✅ 与 Chat 集成
- ✅ 与工作流集成(Agent 节点)
- ✅ 多 Agent 团队([agent-team](agent-team.md))

### 7.2 不做
- ❌ Agent 版本管理(暂未实现,改完就生效)
- ❌ Agent 模板市场(暂未发布)
- ❌ Agent 训练 / 微调(走 [model-training](model-training.md) 模块)

---

## 8. 升级路径

### 短期
- 📋 Agent 版本管理
- 📋 A/B 测试(多版本对比)
- 📋 Agent 评分(自动)

### 中期
- 📋 Agent 模板市场
- 📋 Agent 自描述(AI 写 prompt)

### 长期
- 📋 Agent 自动训练(RLHF)
- 📋 Agent 联邦(跨租户协作)

---

## 9. 常见误区

### 9.1 模型选最大 = 最好
- ❌ 错。qwen2.5:7b 本地免费,GPT-4 慢且贵
- ✅ 业务匹配 + 性能 + 成本

### 9.2 工具给越多越好
- ❌ 错。工具多了 LLM 不会选
- ✅ 给 3~5 个常用工具即可

### 9.3 prompt 越详细越好
- ❌ 错。太长 LLM 抓不住重点
- ✅ 关键规则 5~10 条

### 9.4 KB 越多越好
- ❌ 错。KB 多了检索噪声大
- ✅ 业务相关 1~3 个

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| Agent 答非所问 | prompt 不清 | 改 prompt |
| LLM 不调工具 | tool_choice / description | 改 tool_choice=auto + 写好 desc |
| KB 检索 0 结果 | KB 没数据 | 上传文档 |
| 5 轮跑完没结果 | 工具链错 | 看 trace |
| 速度慢 | 模型慢 / KB 大 | 换模型 / 减小 KB |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06
