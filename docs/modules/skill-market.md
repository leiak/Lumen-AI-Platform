# 模块:技能市场

> Lumen AI Platform 的技能市场 + 技能类型化抽象。
> 文档讲透技能是什么、有哪些类型、怎么装、怎么用。

---

## 1. 产品定位

**技能(Skill)是什么?**
- 一种"可复用单元",Agent 或工作流能调用
- 比"工具"更结构化: 有类型 + 详情 + 适用场景
- 业务价值: 让运营 / 销售不用懂代码就能"装技能"

**和"工具"的区别?**
- 工具: 1 个函数,LLM 调
- 技能: 1 个产品化的能力,有 UI / 详情 / 配置

**和"插件"的区别?**
- 插件: 通用扩展机制
- 技能: 7 种类型化,每种有专属 UI

---

## 2. 7 种技能类型

| 类型 | 用途 | 配置 |
|------|------|------|
| **prompt** | 预写好的 prompt 模板 | name / template / variables |
| **script** | 跑 Python 脚本 | code / env / timeout |
| **http** | HTTP 请求 | url / method / headers / body |
| **tool** | 包装 Tool | tool_name / input_schema |
| **knowledge_retrieval** | KB 检索 | kb_ids / query / top_k |
| **workflow** | 整个工作流 | workflow_id / input_schema |
| **composite** | 组合多个技能 | sub_skills / orchestration |

---

## 3. 数据模型

### 3.1 skills
```python
class Skill(Base):
    id: int
    name: str
    description: str
    type: str                     # 7 种类型
    type_config: dict             # 类型相关配置
    is_platform: bool             # 平台级(tenant_id IS NULL)
    tenant_id: int                # 租户级(可空)
    content: str                  # 提示词内容
    version: str
    author: str
    tags: list
    install_count: int
    rating: float
```

### 3.2 skill_installations
```python
class SkillInstallation(Base):
    id: int
    skill_id: int
    tenant_id: int
    installed_at: datetime
    config: dict                  # 安装时配置
    enabled: bool
```

### 3.3 文件
- ORM: `backend/lumen_models/skill.py`
- Schema: `backend/lumen_schemas/skill.py`
- 服务: `backend/lumen_services/skill_market_service.py`
- 路由: `backend/lumen_api/v1/skill_market.py`

---

## 4. UI

### 4.1 技能市场
- 路径: `frontend/app/dashboard/skills/market/page.tsx`
- 浏览 / 搜索 / 详情 / 安装
- 列表卡片:名字 / 描述 / 类型标签 / 评分 / 安装数

### 4.2 已装技能
- 路径: `frontend/app/dashboard/skills/installed/page.tsx`
- 当前租户已装
- 操作:启停 / 卸载 / 配置

### 4.3 技能详情(按 type 渲染)
- 路径: `frontend/components/skills/detail/`
- PromptDetail / ScriptDetail / HttpDetail / KnowledgeRetrievalDetail / ToolDetail / WorkflowDetail / CompositeDetail
- 按 type 显示不同字段 + 测试按钮

### 4.4 技能管理(创建 / 编辑)
- 路径: `frontend/components/skills/admin/SkillUpsertForm.tsx`
- 选 type → 显示对应表单

---

## 5. 关键能力详解

### 5.1 平台级 vs 租户级
- **平台级** (`is_platform=True` + `tenant_id=NULL`): 预置,所有租户可装
- **租户级** (`is_platform=False` + `tenant_id=N`): 私有,本租户可装可发
- 平台级只能由超管创建/编辑

### 5.2 安装
- 平台级技能 → 一键装
- 租户级技能 → 需搜索 + 装
- 装时允许改 config

### 5.3 在 Agent 中用
- 编辑 Agent → "允许使用的工具" → 选技能
- LLM 调技能 = 调对应类型的 invoke 函数

### 5.4 在工作流中用
- Tool 节点 → `tool_name` = 技能名
- 或 Workflow 节点(workflow 类型技能)

---

## 6. 各类型详解

### 6.1 prompt 类型
- 内容: prompt 模板
- 例: "把下面文本改成小红书风格"
- 配置: `{template: "...", variables: ["text"]}`
- 调用: 渲染模板 → 喂 LLM

### 6.2 script 类型
- 内容: Python 代码
- 用途: 数据处理
- 配置: `{code: "...", inputs: {x: "int"}, env: ["PYTHONPATH=..."]}`
- 调用: subprocess 跑

### 6.3 http 类型
- 内容: HTTP 调用
- 用途: 接业务 API
- 配置: `{url, method, headers, body}`
- 调用: httpx

### 6.4 tool 类型
- 内容: 包装 1 个 Tool
- 用途: 把内置 Tool 暴露为技能
- 配置: `{tool_name: "...", input_schema: {...}}`

### 6.5 knowledge_retrieval 类型
- 内容: KB 检索
- 用途: 给 Agent 加 KB 能力
- 配置: `{kb_ids: [...], query_template: "..."}`

### 6.6 workflow 类型
- 内容: 引用 1 个工作流
- 用途: 把工作流暴露为技能
- 配置: `{workflow_id: 1, input_schema: {...}}`

### 6.7 composite 类型
- 内容: 组合多个技能
- 用途: 复杂工作
- 配置: `{sub_skills: [...], orchestration: "sequential"}`

---

## 7. 种子技能(M34 ship 15 个)

| 名字 | 类型 | 用途 |
|------|------|------|
| 客户跟进提醒 | prompt | 提醒写跟进 |
| 文本分类(NLP) | script | 用训练好的模型分类 |
| HTTP 天气查询 | http | 调 weatherapi |
| 知识库检索通用 | knowledge_retrieval | 通用 KB 检索 |
| ... | ... | ... |

详见 `backend/lumen_scripts/seed_skills.py`。

---

## 8. 关键代码

### 8.1 注册中心
```python
# backend/lumen_services/skill_registry.py
class SkillRegistry:
    _invokers = {
        "prompt": invoke_prompt,
        "script": invoke_script,
        "http": invoke_http,
        "tool": invoke_tool,
        "knowledge_retrieval": invoke_kb,
        "workflow": invoke_workflow,
        "composite": invoke_composite,
    }

    async def invoke(self, skill: Skill, inputs: dict) -> str:
        fn = self._invokers[skill.type]
        return await fn(skill, inputs)
```

### 8.2 装技能到 Agent
```python
# 后端:在 Agent 详情中查 allowed_tools
allowed_tool_names = agent.allowed_tools or []
agent_tools = []
for name in allowed_tool_names:
    if name.startswith("skill:"):
        skill_id = int(name.split(":")[1])
        skill = load_skill(skill_id, tenant_id)
        agent_tools.append(skill_to_tool(skill))
    else:
        agent_tools.append(builtin_tool(name))
```

---

## 9. 边界与不做

### 9.1 当前
- ✅ 7 种类型
- ✅ 平台 / 租户二级
- ✅ 15 个种子
- ✅ 安装 / 卸载 / 启停
- ✅ Agent 集成
- ✅ 工作流集成

### 9.2 不做
- ❌ 技能评分(暂用整数评分)
- ❌ 技能评论
- ❌ 跨租户分享

---

## 10. 升级路径

### 短期
- 📋 技能版本管理
- 📋 技能评分 / 评论

### 中期
- 📋 技能 A/B 测试
- 📋 跨租户市场

### 长期
- 📋 技能自动推荐
- 📋 技能自动生成(AI 写技能)

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 技能找不到 | 没装 | 先装 |
| 装上 Agent 不调 | tool_choice=none | 改 auto |
| http 技能 401 | 凭证错 | 改 headers |
| script 技能 timeout | 代码慢 | 调 timeout |
| 知识库技能 0 结果 | KB 没数据 | 上传文档 |
| workflow 技能失败 | 子工作流错 | 看子工作流日志 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
