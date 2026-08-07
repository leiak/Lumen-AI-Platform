# 关键用户旅程(User Journeys)

> 5 类用户的 6 条核心旅程,每条旅程都对应一套产品功能。
> 文档供产品 / 销售 / 客服在客户演示和需求评审时使用。

---

## 旅程 1:运营人员用 Lumen 做公众号(M32 公众号助手)

> 典型人物:赵姐(教育公司内容运营),不会写代码。

### 目标
**每天花 2 小时,完成公众号周更 3 篇 + 视频号周更 2 条。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 登录平台 | OAuth2 验证,跳到 dashboard | [auth-and-rbac](../modules/auth-and-rbac.md) |
| 2 | 进入"公众号助手 → 草稿" | 列出已有草稿(11 篇) | [wx-publisher](../modules/wx-publisher.md) |
| 3 | 点击"新建草稿" | MDEditor + 双屏预览 | [wx-publisher](../modules/wx-publisher.md#编辑器) |
| 4 | 从 Word 复制文章粘贴到编辑器 | HtmlPasteHandler 自动转 MD | [wx-publisher](../modules/wx-publisher.md#粘贴转-md) |
| 5 | 选"学术风"模板 | 11 维 CSS 排版自动套用 | [wx-publisher](../modules/wx-publisher.md#模板市场) |
| 6 | 点"AI 改写" | AIRewriteModal 弹出,选"温暖叙事"风格 | [wx-publisher](../modules/wx-publisher.md#ai-改写) + [playbook](../modules/playbook.md) |
| 7 | 等待 30 秒,AI 输出改写后版本 | LLM 流式输出,日志留痕 | [llm-call-logs](../modules/llm-call-logs.md) |
| 8 | 点"AI 配图",输入"夏日儿童插画" | [图片生成](../modules/image-generation.md) 出 4 张选 1 | [image-generation](../modules/image-generation.md) + [playbook](../modules/playbook.md#视觉) |
| 9 | 点"保存草稿" | [通知中心](../modules/notification.md) 提示"已保存" | [notification](../modules/notification.md) |
| 10 | 点"发布到公众号" | 微信 API 调用,公众号后台草稿箱出现 | [wx-publisher](../modules/wx-publisher.md#发布) |
| 11 | 下班前 5 分钟,做视频号 | [视频合成](../modules/video-composition.md) 选素材 + ffmpeg 拼装 | [video-composition](../modules/video-composition.md) |

### 关键体验点
- ✅ **不会写 prompt**:Playbook 风格 + AI 改写 modal 把 prompt 隐藏
- ✅ **不会设计**:11 维 CSS 模板 + 缩略图 + 视觉风格
- ✅ **不离开平台**:从写稿到发布都在一个站
- ✅ **可追溯**:每次 LLM 调用都有 trace

### 失败兜底
- AI 改写超时(> 60 秒)→ 自动 fallback 到原文
- 图片生成失败 → 显示重试按钮,不丢失草稿
- 微信 API 报错 → 草稿留在平台,稍后手动重试

---

## 旅程 2:开发者用工作流做"客户问题自动分类"(工作流 P0)

> 典型人物:王工(企业内部 AI 工程师)。

### 目标
**3 小时内搭好"客户提问 → 分类 → 转人工"工作流。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 进入"工作流 → 设计器" | 打开 [React Flow 画布](../modules/workflow.md#设计器) | [workflow](../modules/workflow.md) |
| 2 | 拖入"输入"节点 | 节点面板列出 22 节点 | [workflow-nodes](../modules/workflow-nodes.md) |
| 3 | 拖入"Question Classifier"节点 | 节点属性面板出现 | [workflow-nodes](../modules/workflow-nodes.md#question-classifier) |
| 4 | 配置分类标签:账单/技术/投诉/其他 | 4 个 case 可填,每个 case 关联关键词 | [workflow-nodes](../modules/workflow-nodes.md#case-配置) |
| 5 | 拖入 4 个"LLM"节点(每个 case 一个) | 每个 LLM 节点挂不同知识库 | [workflow-nodes](../modules/workflow-nodes.md#llm) |
| 6 | 在"知识库"下拉选 KB | 22 节点的 KB 选择器出现 [EmbeddingModelSelect](../modules/model-management.md) | [knowledge-base](../modules/knowledge-base.md) |
| 7 | 拖入 4 个"输出"节点 | 每个 case 配不同回复 | [workflow-nodes](../modules/workflow-nodes.md#output) |
| 8 | 连线 + 测运行 | 工作流保存,点"运行" | [workflow](../modules/workflow.md#测试) |
| 9 | 节点逐个变绿/红 | [Run 详情](../modules/workflow.md#监控) BFS 日志 | [workflow-execution](../explanation/workflow-execution.md) |
| 10 | LLM 节点走错分支?改 prompt | undo/redo 走 5 步 | [workflow](../modules/workflow.md#undo-redo) |
| 11 | 改完再跑,正确 | 满意 | - |
| 12 | 点"发布到模板市场" | 模板上架,内部其他团队可装 | [workflow](../modules/workflow.md#模板市场) |

### 关键体验点
- ✅ **可视化**:不写一行代码
- ✅ **可调试**:节点级日志,知道哪步走错
- ✅ **可复用**:发布到模板市场

### 失败兜底
- 节点报错 → [ErrorStrategyPicker](../explanation/error-retry-timeout.md) 选"重试 3 次"或"转人工"
- 整个工作流失败 → 自动重跑 + 通知

---

## 旅程 3:销售用 Chat 调出客户档案 + 知识库(M14 Chat + M21 Knowledge)

> 典型人物:周销售(某 SaaS 公司大客户销售)。

### 目标
**见客户前 5 分钟,快速了解上次沟通内容 + 报价方案。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 登录 [Chat](../modules/chat.md) | 左侧对话列表 | [chat](../modules/chat.md) |
| 2 | 新建对话 → 选"销售助理"Agent | 顶部 Agent 切换器 | [agent](../modules/agent.md) |
| 3 | 输入"李总最近一次沟通" | Agent 调 [客户 CRM](../modules/customer-crm.md) 返回 | [agent](../modules/agent.md) + [customer-crm](../modules/customer-crm.md) |
| 4 | 输入"产品 A 报价方案" | Agent 调 [知识库 RAG](../modules/knowledge-base.md) 检索 | [knowledge-base](../modules/knowledge-base.md) |
| 5 | 看到引用来源(2 个文档) | [Citations 组件](../modules/chat.md#citations) | [chat](../modules/chat.md) |
| 6 | 客户问"能不能再降 5%" | Agent 调 [工具](../explanation/tool-calling.md) 查优惠策略 | [tool-calling](../explanation/tool-calling.md) |
| 7 | 关 Chat,走 [跟进记录](../modules/customer-crm.md#跟进) | 客户档案追加本次沟通 | [customer-crm](../modules/customer-crm.md) |
| 8 | 晚上 10 点收到 [通知](../modules/notification.md) | "李总在公众号留了言" | [notification](../modules/notification.md) |

### 关键体验点
- ✅ **多 Agent**:不同场景不同 Agent(销售/客服/技术)
- ✅ **业务集成**:Chat 直接调 CRM + 知识库
- ✅ **流式输出**:边看边想,不卡

### 失败兜底
- Agent 答非所问 → 切到"通用" Agent 兜底
- 知识库没结果 → 显示"无引用,建议人工"

---

## 旅程 4:客户在第三方网站用 Widget 聊天(M21 Widget)

> 典型人物:张访客(某公司采购经理,在客户公司)。

### 目标
**打开供应商网站,3 秒内看到 AI 客服,1 分钟内问到答案。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 打开供应商网站 | `<lumen-chat>` 浮窗在右下角 | [external-app-auth](../modules/external-app-auth.md#widget) |
| 2 | 点击浮窗 | 弹开 chat 界面(bundle < 250KB) | [widget](../architecture/02-module-topology.md#widget) |
| 3 | 输入"我的订单 #12345 什么时候发货" | widget 调后端 `/external/...` | [external-app-auth](../modules/external-app-auth.md) |
| 4 | 后端验 `app_key` 签 JWT | 通过后查 ERP | [external-app-auth](../modules/external-app-auth.md#公私钥) |
| 5 | AI 调用 MCP 工具 → ERP | 返回"已发货,运单号 SF12345" | [mcp](../modules/mcp.md) |
| 6 | 用户追问"能换货吗" | 同一会话继续 | - |
| 7 | 用户关掉网页 | 留下 [访客痕迹](../modules/external-app-auth.md#访客) | [external-app-auth](../modules/external-app-auth.md) |

### 关键体验点
- ✅ **秒开**:bundle < 250KB,无依赖
- ✅ **跨设备**:换手机登录,会话保持
- ✅ **集成业务**:直接调 ERP,无需人工

### 失败兜底
- AI 答错 → "转人工"按钮
- 后端超时 → 显示"重试"

---

## 旅程 5:IT 管理员部署 + 监控(P0 部署 + 监控)

> 典型人物:李 IT(制造业 IT 总监)。

### 目标
**30 分钟内本地启动,1 个月内正式上线给业务部门。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 克隆代码 → 看 [README](../../README.md) | 完整启动命令 | - |
| 2 | `docker compose up -d` | 5 个 lumen-platform-* 容器启动 | [deploy](../how-to/deploy.md) |
| 3 | `ollama pull nomic-embed-text` 等 | Ollama 模型下载 | - |
| 4 | `python scripts/init_dev_db.py` | 18 个 ensure_* 自动建表 + 种子数据 | [getting-started](../tutorials/getting-started.md) |
| 5 | 启动后端 `uvicorn lumen_main:app --port 11335` | FastAPI 启动,日志无 error | [dev-env](../how-to/dev-env.md) |
| 6 | 启动前端 `npm run dev` | Next.js 启动,11334 端口 | - |
| 7 | 打开 [Swagger](http://localhost:11335/docs) | API 文档 | [api](../reference/api.md) |
| 8 | 登录 `admin/admin123` | 跳到 dashboard | [auth-and-rbac](../modules/auth-and-rbac.md) |
| 9 | 业务团队申请新租户 | 创建租户 + 限用户数 | [multi-tenant](../architecture/04-multi-tenant.md) |
| 10 | 业务团队开始用,李 IT 看 [LLM 调用日志](../modules/llm-call-logs.md) | 每条 LLM call 留痕 | [llm-call-logs](../modules/llm-call-logs.md) |
| 11 | 业务反馈"AI 答得慢" | 李 IT 看 [trace](../modules/llm-call-logs.md#trace) → 定位是 embedding 维度不匹配 | [observability](../explanation/observability.md) |
| 12 | 切换 embedding 模型 → [RAG 评测](../modules/rag-evaluation.md) 重新跑 | 评测集趋势图提升 | [rag-evaluation](../modules/rag-evaluation.md) |

### 关键体验点
- ✅ **30 分钟启动**:一条命令 + init 脚本
- ✅ **可观测**:出问题 5 分钟内定位
- ✅ **可解释**:给老板看评测趋势图

### 失败兜底
- Docker 启动失败 → [deploy](../how-to/deploy.md) 排错
- uvicorn 静默挂掉 → [uvicorn-zombie](../troubleshooting/uvicorn-zombie.md) 排错
- 数据全没了 → [data-recovery](../troubleshooting/data-recovery.md) 从备份恢复

---

## 旅程 6:运营用智能问数查销售数据(M33 Text2SQL)

> 典型人物:周销售(销售经理,不会写 SQL)。

### 目标
**不写 SQL,5 秒内查到"上季度华东区新签客户数"。**

### 步骤

| 步骤 | 用户动作 | 系统响应 | 涉及模块 |
|------|---------|---------|---------|
| 1 | 进入"智能问数" | [Text2SQL](../modules/text2sql.md) 界面 | [text2sql](../modules/text2sql.md) |
| 2 | 输入"上季度华东区新签客户数" | AI 自动生成 SQL | [text2sql](../modules/text2sql.md#两阶段引擎) |
| 3 | 看到生成的 SQL | [SQLGuard](../modules/text2sql.md#sqlguard) 静态校验 | [text2sql](../modules/text2sql.md) |
| 4 | 点"试执行" | 返回数字 27 | [text2sql](../modules/text2sql.md#试执行) |
| 5 | 看到结果 | 数字 + 简单表格 | - |
| 6 | 追问"分行业拆分" | AI 改写 SQL 加上 group by | [text2sql](../modules/text2sql.md#追问) |
| 7 | 保存查询 | 下次可直接打开 | - |

### 关键体验点
- ✅ **不写 SQL**:自然语言问
- ✅ **安全**:SQLGuard 拦截 DROP/DELETE 等危险语句
- ✅ **追问**:支持多轮对话

### 失败兜底
- AI 写错 SQL → 试执行报错 → AI 自动重写
- 表不存在 → 提示"请用对话表 / 客户表,不要直接用 users"
- 越权查询 → 拒绝执行(白名单表)

---

## 跨旅程的"产品主张"

| 主张 | 实现 | 旅程 |
|------|------|------|
| **不写代码也能用** | 拖拽 + Playbook + 模板 | 1, 2, 6 |
| **业务接得上** | MCP / HTTP 节点 / 工具 | 2, 3, 4 |
| **能交付给客户** | Widget + 桌面端 | 4 |
| **可观测** | LLM 日志 + trace | 5 |
| **可解释** | 评测 + 看板 | 5 |
| **不绑定** | 多 provider + 多渠道 | 1, 3, 4 |

---

**维护者**:产品经理
**最近更新**:2026-08-06
