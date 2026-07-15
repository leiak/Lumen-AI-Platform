# `<lumen-chat>` — Lumen AI Platform 嵌入式 Chat Widget

一个独立的 Lit Web Component,通过一行 `<script>` 标签嵌入任何第三方网站。
对话能力来自 AI Platform 后端的 `/api/v1/external/*` 端点。

## 是什么

`@lumen-platform/chat-widget` 是 lumen-platform monorepo 内的嵌入式 chat widget 包:

- **Package**: `@lumen-platform/chat-widget`(见 `package.json` · name 字段)
- **技术栈**: Lit 3 + Web Components + 原生 ESM,零运行时依赖(运行时只 3 个 dep:lit / markdown-it / highlight.js)
- **后端怎么 serve**: `backend/lumen_main.py:196-198` mount `widget/dist/` 到 `/static/widget/lumen-chat.js`(`/static/widget/lumen-chat.esm.js` 也挂)
- **不发布 npm**:外部网站直接 `<script src="https://your-server/static/widget/lumen-chat.js">` 引即可,见 §8 YAGNI 「npm publish」一行
- **数据流**:widget 内 `fetchToken` → `/api/v1/external/auth/token` 拿 JWT → `streamChat` → `/api/v1/external/chat/stream` 收 SSE,所有调用都带 `Origin` 头做 CORS 校验
- **跟 dashboard 内部 API 的区别**:`/api/v1/external/*` 是 public bearer-token 路由(任何持 key/secret 的第三方网站都能调),`/api/v1/*` 是登录 session 路由(只有 dashboard 用户能调),详见 `backend/lumen_api/v1/external/`

## 快速开始(30 秒)

1. 确认后端在 `11335` 跑着:`curl -s -o /dev/null -w "%{http_code}\n" http://localhost:11335/docs` 返 200
2. `cd widget && npm install`(首次)
3. `cd widget && npm run build` → 写 `dist/lumen-chat.js` (IIFE) + `dist/lumen-chat.esm.js`
4. `cd widget/demo && npx http-server -p 11337 -c-1 --silent &`(端口 11337 在 dev seed 的 CORS allowlist 里)
5. 浏览器开 `http://localhost:11337` 看到精准停车 widget 调试页
6. 嵌第三方网站,3 行 HTML:

   ```html
   <script src="https://your-server.com/static/widget/lumen-chat.js"></script>
   <lumen-chat
       server="https://your-server.com"
       app-key="lc_pub_...">
   </lumen-chat>
   ```

7. 跑测试 + 体积门禁:

   ```bash
   cd widget && npm test            # vitest 32 tests
   npm run check:size               # 体积预算 ≤ 240KB
   npm run ci                       # build + size + test 一把过
   ```

## 1. 嵌入(embed)

```html
<script src="https://your-server.com/static/widget/lumen-chat.js"></script>
<lumen-chat
    server="https://your-server.com"
    app-key="lc_pub_..."
    agent-id="3"
    theme="auto"
    title="AI 助手"
    welcome-message="👋 Hi! 我能帮你什么?">
</lumen-chat>
```

## 2. 三种用法

### A. 一行嵌入(默认;`floating=false`)

```html
<script src="..."></script>
<lumen-chat server="..." app-key="..."></lumen-chat>
```

### B. 浮动按钮模式(右下角圆形,点击展开)

```html
<lumen-chat server="..." app-key="..." floating></lumen-chat>
```

(MVP 仅隐藏关闭按钮;完整浮动按钮 + 展开动画是 P2 扩展。)

### C. 程序化控制

```ts
const chat = document.querySelector("lumen-chat");
chat.send("Hello");           // 立即发一条
chat.switchAgent(7, "team");  // 切到 team_id=7
chat.startNewConversation();  // 开新对话
chat.cancel();                // abort 当前 SSE
```

## 3. 全属性

| 属性 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `server` | string | (必填) | 后端根 URL |
| `app-key` | string | (必填) | 应用公钥 |
| `agent-id` | number | — | 默认 agent |
| `team-id` | number | — | 默认 team(与 agent-id 互斥) |
| `theme` | `'light'\|'dark'\|'auto'` | `'auto'` | auto 跟随系统 |
| `title` | string | `'AI 助手'` | header 文字 |
| `placeholder` | string | `'输入消息...'` | 输入框 |
| `welcome-message` | string | — | 首条静态消息(无网络) |
| `height` | string | `'600px'` | 容器高 |
| `width` | string | `'400px'` | 容器宽 |
| `floating` | boolean | `false` | 浮动模式(隐藏关闭按钮) |
| `enable-agent-switch` | boolean | `false` | 显示多 agent 下拉 |
| `enable-conversations` | boolean | `false` | 显示会话侧栏 |
| `conversation-id` | number | — | 初始恢复某会话 |

## 4. 事件

```ts
chat.addEventListener("lc-ready", (e) => { /* {allowed_agents, allowed_teams} */ });
chat.addEventListener("lc-message", (e) => { /* {role, content, conversation_id} */ });
chat.addEventListener("lc-error", (e) => { /* {code, message} */ });
chat.addEventListener("lc-agent-change", (e) => { /* {id, type} */ });
chat.addEventListener("lc-close", () => { /* floating=false 关闭按钮 */ });
```

## 5. CSS 变量(外部覆盖)

```css
lumen-chat {
  --lc-primary: #10b981;     /* 主题色 */
  --lc-bg-page: #f5f5f5;     /* 容器背景 */
  --lc-radius-md: 10px;      /* 圆角 */
  --lc-font-size-base: 14px; /* 字号 */
}
```

## 6. 构建与发布

```bash
npm install
npm run build      # 写 dist/lumen-chat.js (IIFE) + dist/lumen-chat.esm.js
npm test           # vitest, 27+ tests
npm run check:size # 体积预算 ≤ 200KB
npm run ci         # build + size + test 一把过
```

## 7. 本地 demo

```bash
cd demo
npx http-server -p 11337
# 浏览器开 http://localhost:11337
```

## 8. 不做什么(YAGNI)

- ❌ 思维链折叠 / 引用 chip / Feature toggle
- ❌ 悬浮按钮模式完整动画 / 拖拽
- ❌ 嵌入访客"我"概念(头像/注册)
- ❌ i18n / 多模态 vision
- ❌ Server-to-server token / Redis rate-limit
- ❌ WebSocket / 长连接
- ❌ npm publish(后端 StaticFiles 挂出即可)
