# 技术栈

> Lumen AI Platform 的全部技术选型 + 选型理由。
> 文档供工程师在选型时参考,也供合作伙伴 / 投资人在做技术尽调时使用。

---

## 1. 后端技术栈

| 层 | 技术 | 版本 | 选型理由 |
|----|------|------|---------|
| **Web 框架** | FastAPI | 0.115+ | 异步原生支持 / 自动 OpenAPI / Pydantic 集成 |
| **ORM** | SQLAlchemy | 2.0+ | 成熟 / 异步支持 / 类型注解友好 |
| **数据校验** | Pydantic | 2.x | 与 FastAPI 一体 / 性能好 |
| **数据库** | MySQL | 8.0 | 事务稳定 / 字符集 utf8mb4 / 团队熟悉 |
| **数据库驱动** | PyMySQL | 1.1+ | 纯 Python,无 C 扩展 |
| **迁移** | 手动 SQL + ensure_* | - | 不引入 Alembic,业务简单可控 |
| **AI 框架** | LangChain | 1.0 | 行业标准 / 生态全 |
| **Agent 框架** | LangGraph | 1.0 | 工作流编排 / StateGraph 状态管理 |
| **向量库** | FAISS | - | 嵌入式 / 速度快 / 不需要外部服务 |
| **搜索引擎** | Elasticsearch | 8.x | BM25 全文检索 / 混合检索 |
| **LLM 服务** | Ollama | - | 本地私有化 / embedding + chat |
| **LLM 兼容** | OpenAI Python SDK | 1.x | 兼容其他 OpenAI 兼容服务 |
| **图像 OCR** | Docling | - | IBM 出品 / 文档解析精度高 |
| **TTS** | Edge TTS / Piper / OpenAI | - | 多 provider,免费可用 |
| **STT/SRT** | 纯 Python 算法 | - | 不依赖外部服务 |
| **视频合成** | ffmpeg | - | 工业级 |
| **图像生成** | OpenAI / Stability / Ollama / Stub | - | 多 provider |
| **图像处理** | Pillow | - | 缩略图 / 文字叠加 |
| **异步任务** | Celery | 5.x | 工业标准 |
| **消息队列** | Redis | 7.x | Celery broker + pubsub |
| **WebSocket** | FastAPI 内置 | - | 不引入额外依赖 |
| **认证** | OAuth2 + JWT | - | 标准 / 兼容第三方 |
| **密码哈希** | PassLib + bcrypt | - | 工业标准 |
| **MCP 客户端** | httpx + 自研 JSON-RPC | - | 轻量 |
| **MCP demo** | FastAPI 127.0.0.1:8765 | - | 自研 |
| **测试** | pytest + pytest-asyncio | - | 异步友好 |
| **类型检查** | mypy | - | 严格模式 |
| **API 文档** | Swagger + Redoc | - | FastAPI 自动生成 |

---

## 2. 前端技术栈

| 层 | 技术 | 版本 | 选型理由 |
|----|------|------|---------|
| **框架** | Next.js | 15.x | App Router / SSR / RSC |
| **UI 库** | React | 18.x | Next.js 标配 |
| **类型** | TypeScript | 5.x | 强类型 |
| **UI 组件** | Ant Design | 5.22+ | 中文友好 / 组件全 |
| **高级组件** | @ant-design/pro-components | 2.8+ | ProLayout / 高级表格 |
| **状态管理** | Zustand | 5.x | 轻量 / 比 Redux 简单 |
| **数据请求** | TanStack Query | 5.x | 缓存 / 重试 |
| **HTTP 客户端** | Axios | 1.7+ | 拦截器完善 |
| **表单** | react-hook-form + zod | - | 性能好 / 类型友好 |
| **工作流画布** | @xyflow/react | 12.x | React Flow 改名版 |
| **Markdown** | @uiw/react-md-editor | 4.x | 编辑器 |
| **Markdown 渲染** | react-markdown + remark-gfm + rehype-highlight | - | 统一 |
| **代码高亮** | highlight.js | 11.x | 多语言 |
| **docx 导出** | docx | 9.x | 纯 JS |
| **pptx 导出** | pptxgenjs | 4.x | 纯 JS |
| **图标** | @ant-design/icons | 5.x | 与 AntD 配套 |
| **日期** | dayjs | 1.11+ | 轻量 |
| **测试** | Vitest + Testing Library | - | 速度快 |
| **E2E** | Playwright | 1.61+ | 真实浏览器 |
| **API 代理** | Next.js rewrites | - | 绕开 CORS |
| **CSS 处理** | Next.js 内置 | - | CSS Modules |
| **SSR 样式** | @ant-design/nextjs-registry | 1.3+ | 防 FOUC |

---

## 3. Widget 技术栈

| 层 | 技术 | 版本 | 选型理由 |
|----|------|------|---------|
| **框架** | Lit | 3.1+ | Web Component 标准 / 不依赖框架 |
| **构建** | esbuild | 0.20+ | 速度极快 / bundle 小 |
| **Markdown** | markdown-it | 14.x | 轻量 / 插件多 |
| **代码高亮** | highlight.js | 11.x | 与前端统一 |
| **测试** | Vitest + @open-wc/testing | - | Web Component 测试 |

**为什么不用 React**?
- Bundle 太大(React 50KB+ vs Lit 5KB)
- 第三方网站可能已有 React,版本冲突
- Web Component 原生支持,与宿主技术无关

---

## 4. Electron 桌面端

| 层 | 技术 | 版本 | 选型理由 |
|----|------|------|---------|
| **框架** | Electron | 33.x | 跨平台桌面 |
| **WS 客户端** | ws | 8.x | 标准 |
| **Token 加密** | safeStorage | (Electron 内置) | OS 加密 |
| **打包** | electron-builder | 25.x | 跨平台安装包 |

---

## 5. 基础设施

| 组件 | 容器 | 端口 | 镜像 |
|------|------|------|------|
| MySQL | lumen-platform-mysql | 3307 | mysql:8.0 |
| Redis | lumen-platform-redis | 6379 | redis:7-alpine |
| Elasticsearch | lumen-platform-elasticsearch | 9200 | elasticsearch:8.x |
| Ollama | lumen-platform-ollama | 11434 | ollama/ollama |
| Celery worker | (Python 进程) | - | - |

---

## 6. 关键选型决策

### 6.1 为什么 FastAPI 而不是 Django?
- **异步原生**:LangChain 异步友好
- **Pydantic 集成**:自动校验
- **OpenAPI 自动**:Swagger / Redoc 免维护
- **轻量**:不捆绑 ORM / Admin(我们用 AntD)

### 6.2 为什么 MySQL 而不是 PostgreSQL?
- 团队熟悉度
- utf8mb4 完整支持(emoji + 中文)
- 运维生态成熟
- 后期可平迁 PG(MyBatis 风格 ORM 友好)

### 6.3 为什么 LangChain 1.0 而不是自研?
- 行业标准,招聘容易
- 工具调用 / ReAct / RAG 全套
- LangGraph 1.0 配套工作流

### 6.4 为什么 FAISS 而不是 ChromaDB / Milvus?
- 嵌入式,无外部依赖
- 性能好
- 数据规模可控(< 1M 向量)
- 后期可平迁 Milvus

### 6.5 为什么 Ollama 而不是直接 OpenAI?
- 私有化部署
- 数据不出本地
- 零 API 成本
- 兼容 OpenAI API

### 6.6 为什么 Next.js 而不是 Vite + React?
- 内置 SSR / RSC
- 内置路由系统(App Router)
- rewrites 简化 API 代理
- Vercel 部署友好(虽然我们自托管)

### 6.7 为什么 AntD 而不是 MUI / Tailwind?
- 中文文档好
- 组件全(尤其 ProTable / ProForm)
- 国内生态成熟
- B 端首选

### 6.8 为什么 Zustand 而不是 Redux?
- 状态量少(只有通知)
- API 简单,无需 action / reducer
- TypeScript 友好

### 6.9 为什么 Lit 而不是 React(Vue) for Widget?
- 5KB 体积
- Web Component 标准
- 第三方网站零冲突
- 不依赖打包器

### 6.10 为什么 Electron 而不是 Tauri?
- 团队熟悉度
- 生态成熟
- 打包工具齐全
- 后期可平迁 Tauri

---

## 7. 不选的(明确排除)

| 候选 | 不选理由 |
|------|---------|
| Django | 太重 / ORM 迁移复杂 |
| PostgreSQL | 团队 MySQL 熟悉 |
| MongoDB | 关系数据为主 |
| React Native | 暂不投入移动端 |
| Tauri | 学习成本 |
| Webpack | Vite / esbuild 已足够 |
| 阿里云百炼 / 智谱 | 数据出域风险 |
| HuggingFace | 私有化部署复杂 |
| LangSmith | 额外成本 |
| Vector DBaaS | 增加外部依赖 |

---

## 8. 版本升级策略

- **核心框架**(FastAPI / Next.js / React):每 6 个月评估,大版本滞后 1 个
- **UI 库**(AntD):小版本紧跟,大版本滞后 1 个
- **数据库**:MySQL 8.0 锁定
- **Python**:3.11 锁定(3.12 评估中)
- **Node**:20 LTS 锁定
- **LLM 框架**:LangChain 1.0 锁定,LangGraph 1.0 锁定

---

## 9. 监控与可观测

| 工具 | 用途 |
|------|------|
| 应用日志 | `logging` + stdout |
| LLM 日志 | 自建 `llm_call_logs` 表 |
| Trace | 自建 `trace_id` |
| 错误追踪 | Sentry(可选) |
| 指标 | Prometheus + Grafana(生产推荐) |
| 链路追踪 | OpenTelemetry(评估中) |

---

## 10. 总结

**Lumen AI Platform 的技术栈是"主流 + 保守 + 私有化优先"**:
- 主流:行业标准库,招人 / 学习成本低
- 保守:不追新,不赌小众
- 私有化:无 SaaS 依赖,数据全在客户内网

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
