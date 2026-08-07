# 模块:Agent 团队

> Lumen AI Platform 的多智能体协同能力。
> 文档说明怎么把多个 Agent 组成团队,让它们协作完成复杂任务。

---

## 1. 产品定位

**为什么需要 Agent 团队?**
- 单 Agent 难处理"跨领域"问题
- 例:"先查订单 → 再看产品手册 → 再写邮件"需要 3 个 Agent
- 多 Agent 团队 = 1 个 manager + N 个 worker,manager 路由到合适 worker

**和单 Agent 比有什么不同?**
- 单 Agent:1 个人做所有事
- 多 Agent:manager 调度,worker 各管一摊
- 团队成员可加工具、加 KB,彼此独立

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 团队 CRUD | 创建 / 编辑 / 删除 / 启停 |
| 团队成员 | 多 Agent + 角色 + 优先级 |
| 路由策略 | 3 种(manager_decides / round_robin / first_match) |
| 聚合器 | 多 Agent 输出聚合(可选) |
| 对话入口 | Chat 选团队 |

---

## 3. 数据模型

### 3.1 agent_teams(团队)
```python
class AgentTeam(Base):
    id: int
    name: str
    description: str
    manager_agent_id: int         # manager Agent(必填,自己也是 Agent)
    route_policy: str             # manager_decides / round_robin / first_match
    aggregator_prompt: str        # 聚合器提示词(可选)
    config: dict                  # 团队级配置
    is_active: bool
    tenant_id: int
```

### 3.2 agent_team_members(成员)
```python
class AgentTeamMember(Base):
    id: int
    team_id: int
    agent_id: int                 # worker Agent
    role: str                     # 如 "researcher" / "writer"
    priority: int                 # 数字越小优先级越高
    is_active: bool
    config: dict
```

### 3.3 agent_team_routes(首匹配路由)
```python
class AgentTeamRoute(Base):
    id: int
    team_id: int
    agent_id: int
    keywords: list                # 关键词列表
    priority: int
```

### 3.4 文件
- ORM: `backend/lumen_models/agent_team.py`
- Schema: `backend/lumen_schemas/agent_team.py`
- 服务: `backend/lumen_services/agent_team_service.py`
- 路由: `backend/lumen_api/v1/agent_team.py`

---

## 4. 路由策略

### 4.1 `manager_decides`(默认)
- manager Agent 看用户问题 + 团队成员描述
- manager 决定"调哪个 worker"或"自己答"
- 适合:团队成员能力差异大
- 实现:LangGraph `add_conditional_edges(manager_fn, path_map)`

### 4.2 `round_robin`
- 轮流分配到每个 worker
- 不看用户问题
- 适合:任务均匀,无需判断
- 简单但笨

### 4.3 `first_match`
- 按 `agent_team_routes` 配置的关键词匹配
- 第一个匹配的 worker 处理
- 适合:显式规则
- 例:"订单" → 订单 worker;"价格" → 报价 worker

---

## 5. 聚合器(可选)

### 5.1 什么时候用
- 多 worker 都回答了 → 需要合并
- 例:"研究员查资料 + 写手写文案" → "生成最终报告"

### 5.2 配置
- `aggregator_prompt` 模板
- manager 自动收集所有 worker 输出 + 调 LLM 合并

### 5.3 不聚合
- manager 自己挑一个 worker 的输出

---

## 6. UI

### 6.1 列表
- 路径: `frontend/app/dashboard/agent/team/page.tsx`
- 表格:名字 / manager / 成员数 / 状态 / 操作

### 6.2 创建 / 编辑
- 基本:名字 / 描述 / manager / 路由策略
- 成员:多选 Agent + 角色 + 优先级
- 路由表(first_match 策略):关键词 → Agent
- 聚合器:文本框(可选)

---

## 7. 团队对话

### 7.1 入口
- 路径: `frontend/app/dashboard/chat`(选团队)

### 7.2 流程
```
用户输入"查订单 + 写邮件"
   │
   ▼
1. 加载团队 + manager + 成员列表
2. 调 manager Agent
3. manager 看问题,决定:
   - 自己答 / 调 worker_1 / 调 worker_2 / 多个 worker
4. 调 worker(可能并发)
5. 收集 worker 输出
6. (可选)调聚合器
7. 流式返回最终答案
```

### 7.3 5 轮 vs 团队递归
- 单 Agent 5 轮 loop
- 团队中,每个 worker 也可 5 轮
- manager 也可 5 轮
- 整体可能很多轮 → 加超时

---

## 8. 关键代码

### 8.1 LangGraph 团队编排
```python
# backend/lumen_services/agent_team_service.py
from langgraph.graph import StateGraph

def build_team_graph(team: AgentTeam, members: list[AgentTeamMember]) -> StateGraph:
    graph = StateGraph(TeamState)

    # manager 节点
    graph.add_node("manager", build_manager_node(team.manager_agent_id))

    # worker 节点
    for m in members:
        graph.add_node(f"worker_{m.id}", build_worker_node(m.agent_id))

    # 路由
    if team.route_policy == "manager_decides":
        graph.add_conditional_edges(
            "manager",
            manager_route_fn,
            {f"worker_{m.id}": f"worker_{m.id}" for m in members} | {"__end__": "__end__"}
        )
    elif team.route_policy == "first_match":
        for route in team.routes:
            graph.add_conditional_edges(
                "manager",
                lambda s: route.agent_id if any(kw in s["input"] for kw in route.keywords) else None,
                ...
            )

    # 聚合
    if team.aggregator_prompt:
        graph.add_node("aggregator", build_aggregator_node(team))
        # 所有 worker 接到 aggregator
        ...

    return graph.compile()
```

---

## 9. 与工作流的关系

### 9.1 协同
- 工作流可调 Agent(用 Agent 节点)
- Agent 内部可调工作流(用 workflow tool)
- 多层嵌套

### 9.2 怎么选
- **业务流程固定** → 工作流
- **业务流程灵活** → Agent 团队
- **混合**:工作流 + Agent 节点

详见 [workflow 模块](workflow.md) 和 [tool-calling](../explanation/tool-calling.md)。

---

## 10. 边界与不做

### 10.1 当前
- ✅ 3 路由策略
- ✅ 聚合器
- ✅ Chat 集成
- ❌ Agent 团队不能跨租户协作
- ❌ 没有"团队 A/B 测试"

### 10.2 计划
- 📋 团队版本管理
- 📋 团队评分
- 📋 团队模板市场

---

## 11. 常见误区

### 11.1 成员越多越好
- ❌ 错。5+ 成员 manager 难选
- ✅ 3~5 个成员最合适

### 11.2 团队能解决一切
- ❌ 错。简单任务用单 Agent,团队有 overhead
- ✅ 单 Agent 优先,复杂才用团队

### 11.3 聚合器总用
- ❌ 错。聚合器有 LLM 成本
- ✅ 必要时才用(多 worker 输出需合并)

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| manager 选错 worker | manager prompt 不清 | 改 manager prompt |
| 成员都不触发 | 路由策略错 | 检查 first_match 关键词 / round_robin |
| 团队很慢 | 成员多 + 都触发 | 减少成员 |
| 聚合器输出空 | aggregator_prompt 错 | 改 prompt |
| 团队不能对话 | 团队没启 / 成员失效 | 启团队 + 检查成员 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
