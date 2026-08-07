# 里程碑时间线(M1 ~ M37)

> Lumen AI Platform 从 2025-12 立项到 2026-08 共完成 37 个里程碑。
> 文档记录每个里程碑的目标、ship 的能力、对应的 commit / spec,供团队回顾和未来规划参考。

---

## 总览

| 阶段 | 里程碑 | 时间 | 主题 |
|------|--------|------|------|
| **Phase 1:基础** | M1~M10 | 2025-12 ~ 2026-05 | 单 Agent + 工作流雏形 |
| **Phase 2:扩展** | M11~M20 | 2026-05 ~ 2026-06 | 多渠道 + 多 Agent + 知识库增强 |
| **Phase 3:加固** | M21~M30 | 2026-06 | 可观测性 + 修复 + 平台化 |
| **Phase 4:品牌升级** | 1.0 | 2026-06-23 | AI Platform → Lumen AI Platform |
| **Phase 5:专业化** | M31~M37 | 2026-07 ~ 2026-08 | 媒体流水线 + 智能问数 + 评测 |

---

## Phase 1:基础(2025-12 ~ 2026-05)

### M1 ~ M5:基础架构
- **M1**:项目脚手架(FastAPI + Next.js + MySQL)
- **M2**:认证 + 用户/角色 + JWT
- **M3**:Agent CRUD + 单轮对话
- **M4**:知识库基础(上传 + Docling 解析 + Embedding)
- **M5**:流式聊天 + LangChain 接入

### M6 ~ M10:工作流雏形
- **M6**:LangGraph 集成
- **M7**:基础工作流(LLM / 输入 / 输出 / 条件)
- **M8**:工具调用(5 轮 loop)
- **M9**:工作流 P2(9 新节点)+ error/retry/timeout
- **M10**:MCP 协议接入

---

## Phase 2:扩展(2026-05 ~ 2026-06)

### M11 ~ M15:多渠道 + 多 Agent
- **M11**:多 Agent 团队(LangGraph StateGraph)
- **M12**:全局记忆 + 跨会话
- **M13**:Embedding 模型配置化(per-KB + Ollama 导入)
- **M14**:Chat 按对话绑定 Agent(顶部切换器)
- **M15**:Widget `<lumen-chat>` Lit 3 嵌入

### M16 ~ M20:知识库 + 媒体
- **M16**:混合检索(FAISS + Elasticsearch + Rerank)
- **M17**:图片生成(OpenAI + Stability + Ollama + Stub)
- **M18**:TTS 语音合成(Edge + Piper + OpenAI)
- **M19**:Playbook 风格系统(YAML token)
- **M20**:Electron 桌面端(远程工具执行器)

---

## Phase 3:加固(2026-06)

### M21 ~ M25:可观测性
- **M21**:LLMCallLog + trace_id 串联
- **M22**:图片生成详情 + Bearer auth 模式
- **M23**:WebSocket 通知中心
- **M24**:日志审计 UI
- **M25**:节点级可观测性

### M26 ~ M30:清扫 + 平台化
- **M26**:KB search_weights 4 滑块
- **M27**:可观测性 4 项落地
- **M28**:聊天烟测 3 bug 修复
- **M29**:docx 三级 fallback + Celery 修复
- **M30**:工作流大版本(22 节点 + undo-redo + 真并行 + resume)

### **1.0 重命名(2026-06-23)**
- AI Platform → Lumen AI Platform
- 后端扁平化 `lumen_*/` 包
- `<lc-chat>` → `<lumen-chat>`
- Docker 容器 `lumen-platform-*`
- Celery `lumen_platform`
- **MySQL schema `ai_platform` 保留**(用户决定,避免 1.0 DB 迁移)

---

## Phase 5:专业化(2026-07 ~ 2026-08)

### M31 ~ M33:内容工厂
- **M31**:客户 CRM + OwnerUserSelect(M31.1)
- **M32**:公众号助手(草稿 + AI 创作 + 微信 API + 5 张新表 + 26 endpoint)
- **M32.1**:公众号助手体验升级(MDEditor + 11 维 CSS 排版)
- **M33**:Text2SQL 智能问数(两阶段 LLM + SQLGuard + 5 张表 + 9 endpoint)

### M34 ~ M36:媒体 + 视频
- **M34**:技能市场广度扩充(15 个新 seed + SystemConfig)
- **M35**:Playbook + TTS + 图片生成 体验整合
- **M36**:视频合成基础(`/api/v1/videos/` + ffmpeg)
- **M36.1**:视频合成前端(`/dashboard/videos`)
- **M36.2.1**:股票素材库(30 张预置图)
- **M36.2.1.x**:video_compose image URL 解析扩展
- **M36.2.2**:配乐生成 — BGM stock music 库(stock_musics 表 + 30 张预置音频)+ ComposeModal MusicPickerModal + 视频合成自动混音
- **M37.1 收尾**:wx-publisher 账号 admin purge 端点(`POST /wx-publisher/accounts/{id}/purge`,admin-only 真硬删 publish_records + SET NULL drafts.account_id + DELETE 主行)
- **M37.2 收尾**:draft-85 401 链修复(后端 409 detail 加 `published_at` 字段结构化 dict + 前端发布按钮 disable + Tooltip + 前端 5 个集合 POST 路径加尾斜杠防 FastAPI `redirect_slashes` 307 丢 Authorization)
- **M37.3 收尾**:eval dashboard parent/children menu(layout 加 SubMenu 容器)+ runs 列表页新建入口

### M37:RAG 评测体系(2026-08-06 ship)
- **M37.1**:评测集管理(EvalDataset + items)
- **M37.2**:Eval Run + Runner + Celery
- **M37.3**:Eval Dashboard(看板 + 趋势 + Run 详情)
- **CP7**:全量测试修复(1469 passed)

---

## 最近 12 个月详细时间线

| 日期 | 里程碑 | 主要能力 |
|------|--------|---------|
| 2025-12-15 | M1 | 项目脚手架 |
| 2026-01-10 | M2 | 认证 + 多租户 |
| 2026-01-25 | M3 | Agent 单轮对话 |
| 2026-02-08 | M4 | 知识库基础 |
| 2026-02-22 | M5 | 流式聊天 |
| 2026-03-08 | M6 | LangGraph 集成 |
| 2026-03-22 | M7 | 工作流基础 4 节点 |
| 2026-04-05 | M8 | 工具调用 5 轮 loop |
| 2026-04-19 | M9 | 工作流 P2(9 新节点) |
| 2026-05-03 | M10 | MCP 协议 |
| 2026-05-10 | M11 | 多 Agent 团队 |
| 2026-05-17 | M12 | 全局记忆 |
| 2026-05-24 | M13 | Embedding 模型配置化 |
| 2026-05-31 | M14 | Chat 按对话绑定 Agent |
| 2026-06-04 | M15 | Widget 嵌入 |
| 2026-06-05 | M16 | 混合检索 |
| 2026-06-08 | M17 | 图片生成 |
| 2026-06-10 | M18 | TTS 语音合成 |
| 2026-06-12 | M19 | Playbook 风格系统 |
| 2026-06-15 | M20 | Electron 桌面端 |
| 2026-06-15 | M21 | LLMCallLog + trace_id |
| 2026-06-16 | M22 | 图片详情 Bearer auth 模式 |
| 2026-06-16 | M23 | WebSocket 通知中心 |
| 2026-06-17 | M24 | 日志审计 UI |
| 2026-06-18 | M25 | 节点级可观测性 |
| 2026-06-19 | M26 | KB search_weights |
| 2026-06-20 | M27 | 可观测性 4 项 |
| 2026-06-21 | M28 | 聊天烟测 3 bug 修复 |
| 2026-06-22 | M29 | docx fallback + Celery |
| 2026-06-23 | **1.0** | 品牌升级 |
| 2026-06-25 | M30 | 工作流大版本(22 节点) |
| 2026-06-25 | M31 | 客户 CRM + OwnerUserSelect |
| 2026-06-27 | M31.1 | OwnerUserSelect 前端集成 |
| 2026-06-18 | M32 | 公众号助手 |
| 2026-06-20 | M32.1 | 公众号体验升级 |
| 2026-06-20 | M33 | Text2SQL 智能问数 |
| 2026-06-30 | M34 | 技能市场扩充 |
| 2026-07-09 | dev DB NULL timestamp 回填 | - |
| 2026-07-15 | M35 | Playbook + TTS 整合 |
| 2026-07-15 | M36 | 视频合成后端 |
| 2026-07-15 | M36.1 | 视频合成前端 |
| 2026-07-16 | M36.2.1 | 股票素材库 |
| 2026-07-16 | M36.2.1.x | video URL 解析 |
| 2026-08-06 | M37 | RAG 评测体系 |
| 2026-08-06 | CP7 | 全量测试修复 |
| 2026-08-07 | M36.2.2 | 配乐生成(BGM stock music) |
| 2026-08-07 | M37 收尾 | wx-publisher admin purge / draft-85 401 链 / eval parent-children menu |

---

## 未来规划(2026 Q4+)

### 短期(1~2 个月)
- 📋 **邀请码接受流程**(M38)
- 📋 **多租户资源配额**(CPU/GPU/存储)
- 📋 **审批流**(敏感操作需审批)
- 📋 **Lumen Studio**(节点开发 IDE)

### 中期(3~6 个月)
- 📋 **多模态工作流**(节点支持图片/视频)
- 📋 **RAG 自适应**(自动选 KB)
- 📋 **AI 评分员**(自动评估 AI 答案)
- 📋 **移动端**(iOS/Android app)

### 长期(6~12 个月)
- 📋 **Agent Marketplace**(对外发布 Agent)
- 📋 **企业版 SSO**(SAML / OIDC)
- 📋 **联邦学习**(多租户联合训练)
- 📋 **AI 治理**(数据脱敏 + 合规审计)

---

## 数字基线(2026-08-07)

| 维度 | 数字 |
|------|------|
| **里程碑数** | 37 + 3 收尾 |
| **后端测试** | 1502 passed / 8 skipped / 1 xfailed / 0 failed(含 M37 3 个 wx_account purge 测试) |
| **前端测试** | 492 passed / 1 failed(整套件 baseline;1 个 pre-existing fail 见 CLAUDE.md §8) |
| **数据库表** | 80+ 张 |
| **API 端点** | 250+ 个 |
| **工作流节点** | 22 个 |
| **技能** | 15+ 个内置 |
| **代码行数** | 约 12 万行(后端 6 万 + 前端 4 万 + Widget/Electron 2 万) |

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-07(M37 收尾 + M36.2.2 配乐 ship)
