# widget/demo — 本地嵌入验证页

服务起在 `11337`(必须,因为后端 dev seed 的 `allowed_origins` 只放了 11334/11337/127.0.0.1:11337)。

````bash
cd widget
npm run build                       # 产物写到 dist/
cd demo
npx http-server -p 11337            # 浏览器开 http://localhost:11337
````

预期:

- widget 容器出现,header 写 "Demo AI"
- 第一条静态消息 "👋 Hi! ..." 立即显示
- 输入消息回车 → SSE 流式回复出现在 chat 区域
- 浏览器 DevTools 看 `/external/auth/token` 200,`/external/chat/stream` 200(text/event-stream)

调试:

- DevTools Network → `static/widget/lumen-chat.js` 应 200
- Application → Local Storage → `lc-widget-visitor-id` 应有 UUID

## CORS 跨域手动验证 checklist

按下面顺序逐项验证(全部 ✓ 才算 widget 跨域工作正常):

- [ ] 后端 `allowed_origins` 加 `http://localhost:11337`(管理后台「外部应用授权 → 编辑」加,保存后 60s 内 `get_cors_cache().invalidate()` 强制失效;或在 demo 期间手动 `python -c "from app.core.dynamic_cors import get_cors_cache; get_cors_cache().invalidate()"`)。
- [ ] `npx http-server widget/demo -p 11337` 起 demo。
- [ ] 浏览器 DevTools Network 找到 `/external/auth/token` 的 `OPTIONS` preflight → 状态 200,`Access-Control-Allow-Origin: http://localhost:11337`。
- [ ] 紧跟着的 `POST /external/auth/token` 200,`access-control-allow-origin` 也是 `http://localhost:11337`(不是 `*`)。
- [ ] `POST /external/chat/stream` 200,响应类型 `text/event-stream`,收到 `data: {content}` 流。
- [ ] 把 `app.allowed_origins` 改成 `["https://other.com"]` + invalidate cache → widget 收到 403 + UI 显示 "origin not allowed"。
- [ ] 改回 `http://localhost:11337` → widget 重新正常工作(说明 cache 失效正常)。
- [ ] DevTools Application → Local Storage → `lc-widget-visitor-id` 有 UUID。
- [ ] 关浏览器再开,visitor_id 不变,「启用会话」时历史会话能拉回。

如果任何一步卡住:
- 4003 CORS 头缺失 → 看 backend 日志 `dynamic_cors` cache 是否被清
- 401 → token 已过期或被 kill,重新 `fetchToken`
- 403 origin → 检查 `app.allowed_origins` + cache TTL
- 425 / 429 → 触发 rate-limit,等 60s

## 截图(待人工补)

本任务完成后,**人工**打开浏览器跑 demo,截 2-3 张图保存到 `widget/demo/screenshots/`:
1. 首次加载状态(显示 welcome message)
2. SSE 流式回复(typing 状态)
3. 多 agent 下拉展开

(这是给 README 文档用的,不在本 MVP 的自动化范围。)
