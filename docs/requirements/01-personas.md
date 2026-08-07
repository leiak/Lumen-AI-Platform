# 用户画像(Personas)

> Lumen AI Platform 服务 5 类核心用户,每类有明确的使用场景、痛点和关键任务。
> 文档供产品 / 销售 / 客服 / 设计师参考,在做需求评审时对照"我们满足了谁"。

---

## Persona 总览

| # | 角色 | 占比 | 关键场景 | 痛点 |
|---|------|------|---------|------|
| 1 | **平台管理员** (IT/AI 团队负责人) | 15% | 部署、配置、监控 | 模型切换、权限分配、出问题定位 |
| 2 | **AI 应用开发者** (内部研发) | 20% | 搭 Agent / 工作流 / 知识库 | 调试难、链路长、错误难复现 |
| 3 | **业务运营** (内容/营销/客服) | 30% | 写文章、做图、配客服 | 不会写 prompt、想直接给 AI 喂文档 |
| 4 | **销售/客户经理** | 15% | 客户跟进、查资料 | 数据散、追客户效率低 |
| 5 | **终端客户/访客** | 20% | 通过 Widget 聊天、查订单 | 想要快速准确的回答 |

---

## Persona 1:平台管理员 - 李 IT(35 岁)

### 画像
- **职位**:某制造业公司 IT 总监
- **背景**:10 年企业 IT 经验,对 Linux / Docker / 网络有基本了解,对 LLM 是新手
- **KPI**:系统稳定运行 + 数据不出公司 + 故障快速恢复
- **决策权**:选择供应商 / 批准预算

### 典型一天
1. 早上 9:00 看 [日志审计](../modules/llm-call-logs.md) — 昨晚有没有异常 LLM 调用
2. 10:00 给业务团队开新租户(招了 5 个客服)
3. 14:00 业务部门反馈"AI 答得慢",查 [LLM 调用日志](../modules/llm-call-logs.md) → 定位是 embedding 维度不匹配
4. 16:00 给 [知识库 RAG](../modules/knowledge-base.md) 换了 embedding 模型
5. 18:00 收到 [通知中心](../modules/notification.md) 告警 — Ollama 容器挂了,重启

### 痛点
- "我不懂 AI,但公司让我管 AI 平台" — 需要清晰的运维文档和告警
- "出问题找不到根因" — 需要 LLM 调用级日志和 trace
- "老板要看效果" — 需要 [RAG 评测看板](../modules/rag-evaluation.md) 给老板看分数

### 关键需求
- 部署简单(Docker compose)
- 监控可视化(LLM 调用日志 + trace)
- 故障快速定位([uvicorn-zombie 排错](../troubleshooting/uvicorn-zombie.md) 这样的文档)
- 权限分明(谁改了什么有审计)

---

## Persona 2:AI 应用开发者 - 王工(28 岁)

### 画像
- **职位**:企业内部 AI 工程师
- **背景**:3 年 Python 经验,会 LangChain 但不熟;前端 React/Next.js 一般
- **KPI**:1 周交付 1 个 AI 应用
- **使用频率**:每天 8 小时

### 典型一周
- 周一:[工作流设计器](../modules/workflow.md) 搭一个"客户问题自动分类 + 转人工"流程
- 周二:[工作流节点](../modules/workflow-nodes.md) 加一个自定义 HTTP 节点调公司 ERP
- 周三:调试——"为什么这个 LLM 节点走错分支" → [工作流 Run 详情](../modules/workflow.md#监控) + trace
- 周四:[知识库](../modules/knowledge-base.md) 上传 100 份产品手册 → 看 [RAG 评测](../modules/rag-evaluation.md) → 调整 chunk size
- 周五:写 [自定义 MCP 工具](../modules/mcp.md) 给销售用

### 痛点
- "我搭了 5 个节点,跑 20 秒才出结果,不知道哪步慢" → 需要 [节点级时间统计](../modules/workflow.md#监控)
- "我改了一个 prompt,效果变差但不知道和哪个版本对比" → 需要 [评测集版本管理](../modules/rag-evaluation.md)
- "工作流报错信息太技术,业务方看不懂" → 需要 [业务友好的错误提示](../explanation/error-retry-timeout.md)

### 关键需求
- 可视化工作流设计器 + undo/redo
- 节点级日志 + trace_id 串联
- 自定义节点 / 工具能快速接入
- 完整的 [API 文档](../reference/api.md) 和 [数据库 schema](../reference/database-schema.md)

---

## Persona 3:业务运营 - 赵姐(32 岁)

### 画像
- **职位**:某教育公司内容运营经理
- **背景**:Marketing 专业出身,**不会写代码**,prompt 写得一般
- **KPI**:公众号周更 3 篇 + 视频号周更 2 条
- **使用频率**:每天 2~3 小时

### 典型一天
1. 上午 9:00 看 [公众号草稿箱](../modules/wx-publisher.md) — 上周 5 篇待发布
2. 10:00 让 AI 改写一篇客户案例 → [AI 改写 modal](../modules/wx-publisher.md#ai-改写) → 选"温暖叙事"风格
3. 11:00 在 [图片生成](../modules/image-generation.md) 输入"夏日儿童插画",出 4 张图选 1 张
4. 14:00 给 [公众号草稿](../modules/wx-publisher.md) 排版 — 选"学术风"模板,一键套用 11 维 CSS
5. 15:00 录 1 分钟口播 → [TTS 语音](../modules/tts.md) → 选"女声温柔"
6. 16:00 上传视频素材 → [视频合成](../modules/video-composition.md) → 自动配字幕
7. 17:00 一键发布到公众号

### 痛点
- "我不会写 prompt,AI 听不懂" → 需要 [Playbook 风格系统](../modules/playbook.md) 帮我预设
- "图生得不专业" → 需要 [Playbook 视觉风格](../modules/playbook.md#视觉风格) 锁住色调
- "我不懂代码,排版要搞半天" → 需要 [公众号模板市场](../modules/wx-publisher.md#模板市场) 一键套用
- "我想看哪些文章阅读量高" → 需要 [RAG 评测趋势图](../modules/rag-evaluation.md#趋势看板)

### 关键需求
- 不会写 prompt,也能出专业结果
- 一键套用模板,不需设计能力
- 中文 UI + 中文文档
- 风格统一(公司 VI 调性)

---

## Persona 4:销售/客户经理 - 周销售(30 岁)

### 画像
- **职位**:某 SaaS 公司大客户销售
- **背景**:销售出身,**手机用得多**,**PC 用得少**
- **KPI**:月成单 5 个
- **使用频率**:每天 1~2 小时

### 典型一天
1. 上午见客户前,在 [客户档案](../modules/customer-crm.md) 看该客户上次跟进记录
2. 客户问"你们产品怎么报价",用 [Chat](../modules/chat.md) 调出"产品报价知识库" AI 回答
3. 记录今天跟进内容 → [CRM 跟进记录](../modules/customer-crm.md#跟进)
4. 下午用 [智能问数](../modules/text2sql.md) 查"上季度华东区新签客户数" → AI 自动写 SQL → 跑出结果
5. 晚上,看 [通知中心](../modules/notification.md) — 客户"李总"留言询问

### 痛点
- "客户资料散在邮件、微信、Excel" → 需要 [客户 CRM](../modules/customer-crm.md) 一站式
- "报价每次都要翻合同" → 需要 [知识库 + Chat 联动](../modules/knowledge-base.md#场景化)
- "我不懂 SQL,想查销售数据" → 需要 [Text2SQL](../modules/text2sql.md)
- "在客户现场没带电脑" → 需要 [桌面端/移动端](..) 访问

### 关键需求
- CRM 与 Chat 集成(聊客户时自动调档案)
- 移动端/桌面端支持
- Text2SQL 不会写也能查数
- 跟进提醒

---

## Persona 5:终端客户/访客 - 张访客(28 岁)

### 画像
- **职位**:某公司采购经理(在客户公司)
- **使用方式**:通过第三方网站嵌入的 [Widget 聊天](../modules/external-app-auth.md) 接入
- **典型任务**:查订单 / 问产品参数 / 提工单

### 典型场景
1. 打开供应商网站,看到右下角浮窗 → 点击
2. 问"我的订单 #12345 什么时候发货"
3. AI 调 ERP 查订单 → 5 秒回答"已发货,运单号 SF12345"
4. 不满意 → 切换人工 / 留邮箱
5. 关闭 → 留下 [访客痕迹](../modules/external-app-auth.md#外部访客追踪)

### 痛点
- "我打开网站就要等" → Widget 要秒开
- "我换了手机就找不到上次对话" → 访客身份识别
- "AI 答非所问" → RAG 检索质量

### 关键需求
- 浮窗秒开,bundle < 250KB
- 跨设备会话保持
- 准确率

---

## 跨 Persona 的"产品承诺"

| 承诺 | 满足的人 | 实现方式 |
|------|---------|---------|
| **30 分钟启动** | Persona 1, 2 | Docker compose + init_dev_db.py |
| **不会代码也能用** | Persona 3 | 拖拽 + Playbook + 模板 |
| **能查能改** | Persona 2, 4 | API + UI 双入口 |
| **能交付给客户** | Persona 5 | Widget + 桌面端 + 多租户隔离 |
| **出问题能定位** | Persona 1, 2 | LLM 日志 + trace + 通知 |

---

## 商业侧参考

| 维度 | 决策点 |
|------|--------|
| **谁付钱** | Persona 1(IT 部门)/ 公司高层 |
| **谁用** | Persona 2(研发)/ 3(运营)/ 4(销售) |
| **谁评价** | Persona 1(看系统稳定 + 合规)/ Persona 5(看体验) |
| **谁拉新** | Persona 2(技术口碑)/ Persona 4(销售提效) |

---

**维护者**:产品经理
**最近更新**:2026-08-06
