# 模块:通知中心

> Lumen AI Platform 的站内通知系统。
> 文档讲透通知怎么产生、怎么推、离线了怎么补。

---

## 1. 产品定位

**通知中心是什么?**
- 长耗时任务完成后,主动告诉用户
- WebSocket 实时推送 + DB 持久化兜底
- 右上角铃铛 + 抽屉列表

**为什么需要?**
- 文档解析、视频合成、PPT 生成这些任务要几十秒到几分钟
- 用户不可能盯着页面等
- 没有通知 → 用户只能反复刷新列表页猜进度

**设计原则(一句话)**:
> **先落库,再广播。**广播失败不影响用户下次打开页面时看到这条通知。

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 事件持久化 | 先写 DB 再推送,不丢消息 |
| WebSocket 实时推送 | `/ws/web`,JWT 鉴权 |
| 未读计数 | 铃铛角标 |
| 游标分页 | `id DESC` + cursor,不用 OFFSET |
| 单条已读 / 全部已读 | — |
| 资源跳转 | 通知带 `resource_type` + `resource_id`,点击直达 |
| 心跳保活 | 25 秒 ping / 120 秒静默断开 |
| 严格用户隔离 | 查询永远带 `user_id`,不存在跨用户可见 |

---

## 3. 数据模型

### 3.1 notifications

```python
# backend/lumen_models/notification.py

class Notification(Base):
    """In-app notification row. Persisted before broadcast so that
    missed events (e.g. user was offline) can be backfilled on the
    next page load or by the fallback poller.
    """
    __tablename__ = "notifications"

    id: int
    user_id: int                  # → users.id,有索引
    type: str                     # 事件类型,见 §4
    title: str                    # 标题(≤200)
    body: str | None              # 详情正文
    resource_type: str | None     # document / generated_video / workflow_run / ...
    resource_id: int | None       # 对应资源 id,前端据此跳转
    metadata_json: dict | None    # 额外结构化数据
    read_at: datetime | None      # NULL = 未读
    created_at: datetime

    __table_args__ = (
        Index("ix_notifications_user_unread_created",
              "user_id", "read_at", "created_at"),
    )
```

**索引设计要点**:`(user_id, read_at, created_at)` 这个复合索引同时服务三个查询:
- 未读计数(`user_id` + `read_at IS NULL`)
- 未读列表(加 `created_at` 排序)
- 全部列表(只用 `user_id` 前缀)

一个索引顶三个。

### 3.2 文件清单

| 层 | 文件 |
|----|------|
| ORM | `backend/lumen_models/notification.py` |
| 服务 | `backend/lumen_services/notification_service.py` |
| REST 路由 | `backend/lumen_api/v1/notifications.py` |
| WebSocket | `backend/lumen_api/v1/electron_ws.py`(`/ws/web`) |
| 连接管理 | `backend/lumen_services/electron_service.py` |
| 前端铃铛 | `frontend/components/notifications/BellBadge.tsx` |
| 前端抽屉 | `frontend/components/notifications/NotificationDrawer.tsx` |

---

## 4. 事件类型清单

通知类型**没有集中枚举**,分散在各个生产者里。以下是全量清单:

| type | 触发者 | resource_type | 说明 |
|------|--------|---------------|------|
| `knowledge_parse_completed` | `document_tasks.py` | `document` | 文档解析成功 |
| `knowledge_parse_failed` | `document_tasks.py` | `document` | 文档解析失败 |
| `IMAGE_GENERATION_COMPLETED` | `image_generation_service.py` | `image_generation` | 图片生成成功 |
| `IMAGE_GENERATION_FAILED` | `image_generation_service.py` | `image_generation` | 图片生成失败 |
| `AUDIO_GENERATION_COMPLETED` | `tts_service.py` | `generated_audio` | TTS 成功 |
| `AUDIO_GENERATION_FAILED` | `tts_service.py` | `generated_audio` | TTS 失败 |
| `VIDEO_COMPOSE_COMPLETED` | `video_compose_service.py` | `generated_video` | 视频合成完成 |
| `VIDEO_COMPOSE_FAILED` | `video_compose_service.py` | `generated_video` | 视频合成失败 |
| `VIDEO_COMPOSE_CANCELLED` | `video_compose_service.py` | `generated_video` | 视频合成已取消 |
| `WORKFLOW_RUN_COMPLETED` | `workflow_service.py` | `workflow_run` | 工作流完成(body 带耗时) |
| `WORKFLOW_RUN_FAILED` | `workflow_service.py` | `workflow_run` | 工作流失败(body 带错误前 200 字) |
| `WORKFLOW_RUN_CANCELLED` | `workflow_service.py` | `workflow_run` | 工作流已取消 |
| `TEXT2SQL_COMPLETED` | `text2sql_service.py` | — | 智能问数完成 |
| `TEXT2SQL_FAILED` | `text2sql_service.py` | — | 智能问数失败 |
| `WX_PUBLISH_COMPLETED` | `wx_publisher/publish_service.py` | — | 公众号发布成功 |
| `WX_PUBLISH_FAILED` | `wx_publisher/publish_service.py` | — | 公众号发布失败(带 errcode 前 30 字) |
| `ppt_generation_completed` | `ppt_task.py` | `ppt_task` | PPT 已生成 |

> **命名不一致是历史遗留**:早期(文档解析、PPT)用 `snake_case`,后来统一成 `UPPER_SNAKE`。
> 前端按 type 做 icon / 颜色映射时**两种都要处理**。

### 4.1 有意不发通知的场景

公众号助手的 4 个 AI 调用(生成大纲、扩写等)**故意不发通知**:

> 同步响应,前端 loading 即可。

**判断标准**:同步返回的操作不发通知,只有**异步/后台任务**才发。否则铃铛会被刷屏。

封面生成复用 `IMAGE_GENERATION_COMPLETED`,不单独建类型。

---

## 5. 核心流程

### 5.1 发布事件

```python
# backend/lumen_services/notification_service.py

class NotificationService:
    @staticmethod
    def publish_event(
        db, *, user_id, type, title, body,
        resource_type, resource_id, metadata,
    ) -> Notification:
        n = Notification(
            user_id=user_id, type=type, title=title, body=body,
            resource_type=resource_type, resource_id=resource_id,
            metadata_json=metadata,
        )
        db.add(n)
        db.commit()          # ← 先落库并提交
        db.refresh(n)

        payload = {
            "id": n.id, "type": n.type, "title": n.title, "body": n.body,
            "resource_type": n.resource_type, "resource_id": n.resource_id,
            "metadata": n.metadata_json,
            "created_at": n.created_at.isoformat(),
        }
        broadcast_event_sync(          # ← 再广播
            event="notification_created",
            payload=payload,
            target_user_id=user_id,
        )
        return n
```

**顺序不能颠倒。**

先广播后落库的话:广播成功但 commit 失败 → 用户看到了通知,刷新后消失。
先落库后广播:广播失败但库里有 → 用户下次打开页面能看到。**只会晚,不会丢。**

### 5.2 端到端链路

```
Celery 任务完成
    ↓
NotificationService.publish_event()
    ├─ 1. INSERT notifications + COMMIT      ← 持久化,不可失败
    └─ 2. broadcast_event_sync()             ← best-effort,失败不抛
           ↓
       ElectronService 按 target_user_id 找连接
           ↓
       WebSocket 推 {"event": "notification_created", "payload": {...}}
           ↓
       前端 BellBadge 收到 → 未读数 +1 → 抽屉插入新行
```

**用户离线时**:广播找不到连接,静默跳过。用户下次打开页面 → `GET /notifications` 拉到。

---

## 6. WebSocket `/ws/web`

### 6.1 鉴权

```
ws://localhost:11335/ws/web?token=<JWT>
```

**JWT 走 query string,不是 header。**

> **为什么**:浏览器的 `WebSocket` 构造函数**不支持自定义 header**。这和 `<img src>` 不能带 Authorization 是同一类限制。
> 详见 [常见错误 §2.1](../troubleshooting/common-errors.md#21-img-src-加载受保护资源必-401)。

鉴权失败一律 **close code 4401**:
- token 为空
- token 解不开 / 过期
- `sub` 缺失
- 用户不存在或 `is_active=False`

### 6.2 连接确认

accept 后立刻下发:

```json
{
  "type": "connection_acknowledged",
  "connection_id": "...",
  "user_id": 12,
  "tenant_id": 1
}
```

前端拿到这个才算连接就绪。

### 6.3 心跳

| 方向 | 消息 | 频率 |
|------|------|------|
| 客户端 → 服务端 | `{"type":"ping"}` | 每 25 秒 |
| 服务端 → 客户端 | `{"type":"pong"}` | 收到 ping 就回 |

**120 秒收不到任何帧** → 服务端 close code **4408**。

```python
while True:
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=120.0)
    except asyncio.TimeoutError:
        await websocket.close(code=4408)
        break
    except WebSocketDisconnect:
        break
    conn.update_activity()
    if isinstance(msg, dict) and msg.get("type") == "ping":
        await websocket.send_json({"type": "pong"})
```

> 25 秒 ping 配 120 秒超时 = 允许连丢 4 个 ping 才断,容忍网络抖动。

### 6.4 close code 对照

| Code | 含义 | 前端处理 |
|------|------|----------|
| 4401 | 鉴权失败 | **不要重连**,跳登录页 |
| 4408 | 心跳超时 | 可以重连 |
| 1000 / 1001 | 正常关闭 | 按需重连 |
| 1006 | 异常断开 | 指数退避重连 |

**4401 不重连很重要** —— token 过期还狂重连会打爆后端。

---

## 7. REST API

### 7.1 列表(游标分页)

```
GET /api/v1/notifications?unread_only=false&limit=20&cursor=<last_id>
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `unread_only` | `false` | 只看未读 |
| `limit` | 20 | 1~100 |
| `cursor` | — | 上一页最后一条的 `id`,取 `id < cursor` |

**响应**:

```json
{
  "code": 200,
  "data": {
    "items": [ ... ],
    "next_cursor": 1234,
    "unread_count": 7
  }
}
```

`next_cursor` 为 `null` 表示没有更多了。

**为什么用游标而不是 OFFSET**:
- 通知是不断新增的。用 OFFSET 时,翻页途中来了新通知 → 数据错位、重复。
- 游标锚定 id,新数据只会出现在第一页,不影响已翻的页。
- 深分页不退化(OFFSET 10000 要扫 1 万行)。

**实现技巧**:多取一条判断有没有下一页。

```python
rows = q.order_by(Notification.id.desc()).limit(limit + 1).all()
has_more = len(rows) > limit
items = rows[:limit]
next_cursor = items[-1].id if has_more and items else None
```

### 7.2 未读计数

```
GET /api/v1/notifications/unread-count
→ {"code": 200, "data": {"count": 7}}
```

单独一个轻量端点,给铃铛角标轮询用(WS 断线时的兜底)。

### 7.3 标记已读

```
POST /api/v1/notifications/{nid}/read
→ {"code": 200, "data": {"id": 42, "read_at": "2026-08-06T12:00:00"}}
```

**幂等**:已读的再调一次不改 `read_at`,直接返回。

```python
if n.read_at is None:
    n.read_at = datetime.utcnow()
    db.commit()
```

### 7.4 全部已读

```
POST /api/v1/notifications/read-all
→ {"code": 200, "data": {"affected": 7}}
```

用批量 UPDATE,不是逐条:

```python
affected = db.query(Notification).filter(
    Notification.user_id == current_user.id,
    Notification.read_at.is_(None),
).update({"read_at": now}, synchronize_session=False)
```

`synchronize_session=False` 跳过 session 内对象同步 —— 这里不需要,能省一次查询。

---

## 8. 安全

### 8.1 用户隔离是硬约束

**所有查询都带 `user_id == current_user.id`,没有例外。**

```python
n = db.query(Notification).filter(
    Notification.id == nid,
    Notification.user_id == current_user.id,   # ← 不能省
).first()
if not n:
    raise HTTPException(404, "notification not found")
```

**注意这里返回 404 而不是 403** —— 别人的通知对当前用户来说"不存在",不泄露"这条 id 存在但你没权限"这个信息。

### 8.2 WS 连接绑定用户

`register_connection(websocket, user_id=..., tenant_id=...)` 把连接和用户绑死。
广播时按 `target_user_id` 精确投递,不做房间/频道广播 —— 从机制上杜绝串号。

---

## 9. UI

### 9.1 铃铛(BellBadge)

- 文件: `frontend/components/notifications/BellBadge.tsx`
- 位置:dashboard 顶栏右上角
- 显示未读数角标
- 数据来源:
  - 初次加载 → `GET /notifications/unread-count`
  - WS 推送 → 本地 +1
  - WS 断线 → 降级为轮询 `unread-count`

### 9.2 通知抽屉(NotificationDrawer)

- 文件: `frontend/components/notifications/NotificationDrawer.tsx`
- 点铃铛打开
- 列表:图标(按 type)/ 标题 / 正文 / 相对时间
- 未读高亮
- 滚到底自动加载下一页(游标)
- 顶部「全部已读」按钮
- 点某条 → 标记已读 + 按 `resource_type` + `resource_id` 跳转

### 9.3 跳转映射

| resource_type | 跳转 |
|---------------|------|
| `document` | `/dashboard/document?highlight={id}` |
| `image_generation` | `/dashboard/image-generation` + 打开详情 |
| `generated_audio` | `/dashboard/tts` |
| `generated_video` | `/dashboard/videos` + 打开详情 |
| `workflow_run` | `/dashboard/workflow/runs/{id}` |
| `ppt_task` | PPT 列表 |

---

## 10. 与其他模块的关系

通知中心是**被动的横切服务** —— 它不主动做任何事,只被各模块调用。

```
document_tasks ──┐
image_generation ─┤
tts_service ──────┤
video_compose ────┼──→ NotificationService.publish_event ──→ WS + DB
workflow_service ─┤
text2sql ─────────┤
wx_publisher ─────┤
ppt_task ─────────┘
```

**新模块接入方式**:直接调 `publish_event`,不需要注册什么。

```python
from lumen_services.notification_service import NotificationService

NotificationService.publish_event(
    db,
    user_id=row.user_id,
    type="MY_TASK_COMPLETED",
    title="任务完成",
    body=f"耗时 {duration_ms}ms",
    resource_type="my_resource",
    resource_id=row.id,
    metadata={},
)
```

同时要在前端补 type → 图标/跳转的映射。

---

## 11. 边界与不做

### 11.1 当前
- ✅ 先落库再广播
- ✅ WS 实时推送 + JWT 鉴权
- ✅ 心跳保活
- ✅ 游标分页
- ✅ 未读计数 / 已读 / 全部已读
- ✅ 资源跳转
- ✅ 严格用户隔离

### 11.2 不做
- ❌ 邮件 / 短信 / 企微 / 钉钉推送
- ❌ 浏览器 Web Push(关页面后收不到)
- ❌ 通知偏好设置(哪些要哪些不要)
- ❌ 通知分组 / 折叠(10 个文档解析完 = 10 条)
- ❌ 通知删除(只能已读,不能删)
- ❌ 自动过期清理
- ❌ 富文本 / 按钮操作(通知里直接点「重试」)
- ❌ 租户级 / 角色级广播(只能发给具体用户)

### 11.3 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| 无分组折叠 | 批量任务刷屏 | 生产者侧自己合并后再发 |
| 无过期清理 | 表会一直涨 | 定期手工清理(见 §12) |
| 无删除 | 只能已读 | — |
| 多实例部署时 WS 不共享 | 用户连 A 实例,任务在 B 实例完成 → 推不到 | 加 Redis pub/sub 广播层 |
| type 命名不统一 | 前端映射要处理两种风格 | 新增一律 `UPPER_SNAKE` |

> **多实例那条是真正的坑**。当前 `ElectronService` 的连接表是**进程内内存**。单实例没问题,横向扩容必须先解决这个。
> 不过 DB 兜底还在 —— 用户刷新页面还是能看到,只是失去实时性。

---

## 12. 运维

### 12.1 清理老通知

```sql
-- 删 90 天前的已读通知(分批,避免锁表)
DELETE FROM notifications
WHERE read_at IS NOT NULL
  AND created_at < NOW() - INTERVAL 90 DAY
LIMIT 10000;
```

未读的建议保留更久(用户还没看到)。

### 12.2 监控指标

```sql
-- 各类型通知量
SELECT type, COUNT(*), SUM(read_at IS NULL) AS unread
FROM notifications
WHERE created_at > NOW() - INTERVAL 7 DAY
GROUP BY type ORDER BY COUNT(*) DESC;

-- 未读堆积严重的用户(可能是刷屏)
SELECT user_id, COUNT(*) AS unread
FROM notifications WHERE read_at IS NULL
GROUP BY user_id HAVING unread > 100 ORDER BY unread DESC;
```

---

## 13. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 收不到实时通知,刷新后有 | WS 没连上 | F12 Network → WS 看连接状态 |
| WS 连接被拒(4401) | token 过期 / 没传 | 重新登录;确认是 `?token=` 不是 header |
| WS 频繁断开(4408) | 前端没发心跳 | 确认 25 秒 ping |
| 通知一条都没有 | 任务根本没跑完 | 看 Celery 日志,别只看通知 |
| 通知有但点击不跳转 | 前端缺 `resource_type` 映射 | 补映射表 |
| 未读数不准 | WS 本地 +1 和服务端不同步 | 定期用 `unread-count` 校正 |
| 通知刷屏 | 批量任务逐条发 | 生产者侧合并 |
| 多实例下收不到 | WS 连接表是进程内的 | 加 Redis pub/sub |
| 404 notification not found | 想读别人的通知 | 设计如此,不是 bug |

---

**相关文档**
- [知识库](knowledge-base.md) — 文档解析通知的主要来源
- [工作流](workflow.md)
- [视频合成](video-composition.md)
- [鉴权与 RBAC](../architecture/05-auth-rbac.md)
- [常见错误速查](../troubleshooting/common-errors.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
