# 模块:公众号助手(Wx Publisher)

> 公众号从写稿到发布全流程。
> 文档讲透怎么绑定公众号账号、怎么用 AI 写文、怎么排版、怎么发到微信。

---

## 1. 产品定位

**公众号助手是什么?**

- 公众号文章**从创作到发布**全流程工具
- 5 步:绑定账号 → 选模板 → AI 写稿 → 排版 → 发布
- 复用平台现有 LLM + 图片生成能力,串成端到端流水线

**为什么需要?**

- 公众号编辑是个苦力活:写稿 + 排版 + 上图 + 同步到微信后台
- 写稿阶段:AI 出大纲、扩写、改风格
- 排版阶段:11 维 CSS 风格(字号、行距、配图位置……)
- 发布阶段:调用微信 API **草稿箱**或**发布**

**业务场景?**

- 企业新媒体团队:每天 5-10 篇,效率工具
- 内容工作室:批量产出,排版统一
- 客服:FAQ 整理成系列文章

**一句话**:把"编辑的工具"做成"AI 助手的工作流",从"想话题"到"发出去"一站式。

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 公众号账号管理 | 绑定 / 解绑 / 启用,凭证加密 |
| 模板管理 | 11 维 CSS 排版模板,主题缩略图 |
| 草稿管理 | 增 / 删 / 改 / 树形章节 |
| AI 写稿 | 生成大纲、扩写、改风格、生成摘要 |
| 素材库 | 图片/音频上传到草稿,CDN 缓存 |
| 一键排版 | 模板 → 草稿内容渲染 |
| 发布 | 推到微信草稿箱 / 直接发布 |
| 双屏预览 | MDEditor + 微信风格渲染并行 |
| 缩略图 | 模板封面图(15 张默认 + 自定义) |

---

## 3. 数据模型

### 3.1 五张表

```python
# backend/lumen_models/wx_publisher.py

class WxAccount(BaseModel):
    """公众号账号。app_id / app_secret 加密存(app_secret 用 Fernet 对称加密)。"""
    __tablename__ = "wx_accounts"
    tenant_id: int
    name: str                              # 公众号名
    app_id: str                            # 微信开放平台 app_id
    app_secret_encrypted: str              # Fernet 加密
    is_active: bool
    last_used_at: datetime | None


class WxTemplate(BaseModel):
    """排版模板(11 维 CSS)。"""
    __tablename__ = "wx_templates"
    tenant_id: int
    name: str
    description: str
    css_config: dict                       # 11 维 CSS 配置(JSON)
    thumbnail_path: str | None             # 缩略图路径
    is_active: bool
    is_builtin: bool                       # 平台内置(15 张)


class WxDraft(BaseModel):
    """草稿标题 + 树形章节。"""
    __tablename__ = "wx_drafts"
    tenant_id: int
    account_id: int                        # → wx_accounts.id
    template_id: int | None                # → wx_templates.id
    title: str
    summary: str | None                    # 摘要
    author: str | None
    cover_image: str | None                # 封面 URL
    status: str                            # draft / published / failed
    source_type: str                       # human / ai_generated / hybrid


class WxDraftSection(BaseModel):
    """草稿的章节(树形)。"""
    __tablename__ = "wx_draft_sections"
    draft_id: int
    parent_id: int | None                  # 自引用,树形
    order_index: int
    title: str | None
    content_md: str                        # Markdown 正文
    content_html: str | None               # 渲染后 HTML(用于微信)


class WxMaterial(BaseModel):
    """草稿用素材(图 / 音频)。"""
    __tablename__ = "wx_materials"
    tenant_id: int
    draft_id: int | None
    filename: str
    file_path: str                         # 磁盘绝对路径
    media_type: str                        # image / audio / video
    wx_media_id: str | None                # 上传微信后返回
    wx_url: str | None                     # 微信 CDN URL


class WxPublishRecord(BaseModel):
    """一次发布动作的记录。"""
    __tablename__ = "wx_publish_records"
    tenant_id: int
    draft_id: int
    account_id: int
    status: str                            # pending / success / failed
    wx_msg_id: str | None                  # 微信返回的 msg_id
    error_code: str | None
    error_message: str | None
    duration_ms: int | None
```

### 3.2 文件清单

| 层 | 路径 |
|----|------|
| ORM | `backend/lumen_models/wx_publisher.py` |
| 服务 | `backend/lumen_services/wx_publisher/` |
| 路由 | `backend/lumen_api/v1/wx_publisher/{accounts,drafts,materials,publish,templates}.py` |
| 前端 | `frontend/app/dashboard/wx-publisher/` |
| 缩略图 | 15 张 Pillow 直绘默认 |

---

## 4. 核心流程

### 4.1 端到端流水线

```
[绑定公众号]
   POST /wx-publisher/accounts/  {app_id, app_secret}
   → 加密存库(每次用都解一次)
        ↓
[选模板]
   GET /wx-publisher/templates/  → 11 维 CSS
        ↓
[创建草稿]
   POST /wx-publisher/drafts/  {account_id, title, template_id}
        ↓
[AI 写稿 — 4 个同步端点]
   POST /wx-publisher/drafts/{id}/ai-outline   → 章节大纲
   POST /wx-publisher/drafts/{id}/ai-expand    → 扩写
   POST /wx-publisher/drafts/{id}/ai-polish    → 改风格
   POST /wx-publisher/drafts/{id}/ai-summary   → 摘要
        ↓
[素材插入]
   POST /wx-publisher/drafts/{id}/materials   (multipart)
   或引用已生成的 image / audio
        ↓
[一键排版]
   POST /wx-publisher/drafts/{id}/render
   → ContentMd → 应用 template.css_config → ContentHtml
        ↓
[发布]
   POST /wx-publisher/publish/  {draft_id, account_id}
   → 调微信 API → 记录到 wx_publish_records
```

### 4.2 AI 写稿的 4 个能力

| 端点 | 输入 | 输出 | LLM |
|------|------|------|-----|
| `ai-outline` | 标题 + 关键词 | 章节大纲(树形) | chat |
| `ai-expand` | 章节标题 + 上下文 | 该章节正文 | chat |
| `ai-polish` | 全文 | 改风格后全文 | chat |
| `ai-summary` | 全文 | 120 字内摘要 | chat |

**为什么 4 个而非 1 个全能端点**:
- 各自 prompt 独立,质量更稳
- 各自 LLMCallLog 入库,便于后续优化**具体哪个能力**
- 失败可单点重试,不会把整篇稿子弄丢

### 4.3 11 维 CSS 模板

```json
{
  "font_family": "PingFang SC",
  "font_size": "16px",
  "line_height": "1.75",
  "color_text": "#333333",
  "color_link": "#1aad19",
  "color_quote": "#888888",
  "background": "#ffffff",
  "h1_style": { "size": "22px", "weight": "bold" },
  "h2_style": { "size": "18px", "weight": "bold" },
  "image_align": "center",
  "image_max_width": "100%"
}
```

**渲染流程**:
```
Markdown 原文
  ↓ python-markdown
HTML (无样式)
  ↓ beautifulsoup4 注入 css_config
HTML (微信风格)
  ↓ 序列化为 wx_renderer 期望的格式
最终 content_html
```

### 4.4 发布到微信

```python
# backend/lumen_services/wx_publisher/publish_service.py

def publish_draft(db, draft_id: int, account_id: int) -> WxPublishRecord:
    # 1. 加载草稿 + 账号 + 模板
    draft = db.get(WxDraft, draft_id)
    account = db.get(WxAccount, account_id)

    # 2. 解密 app_secret(单独走 settings.WX_FERNET_KEY)
    app_secret = decrypt(account.app_secret_encrypted)

    # 3. 拉 access_token(先用缓存)
    access_token = wx_token_cache.get_or_refresh(account.app_id, app_secret)

    # 4. 上传素材到微信(图片永久素材 / 文章配图)
    media_ids = upload_materials(access_token, draft.materials)

    # 5. 调 /cgi-bin/draft/add 创建微信草稿
    wx_response = wx_api.draft_add(access_token, article={
        "title": draft.title,
        "content": draft.content_html,
        "thumb_media_id": primary_cover_media_id,
        "digest": draft.summary,
        "content_source_url": "",
        "need_open_comment": 1,
    })

    # 6. 写 wx_publish_records
    record = WxPublishRecord(
        status="success" if wx_response else "failed",
        wx_msg_id=wx_response.get("media_id"),
        duration_ms=elapsed_ms,
        ...
    )
```

**异步**: `POST /publish/` 返 202,实际推到 Celery。

---

## 5. 微信 API 集成

### 5.1 凭证管理

| 凭证 | 存储 | 用法 |
|------|------|------|
| `app_id` | 明文 | 调 API 时直接带 |
| `app_secret` | Fernet 对称加密 | 每次用都解密 |
| `access_token` | **进程内缓存** | 2 小时 TTL,自动 refresh |

**access_token 缓存**:
```python
# 进程内 dict,key=app_id
_wx_token_cache: dict[str, tuple[str, float]] = {}  # (token, expires_at)

def get_or_refresh(app_id: str, secret: str) -> str:
    token, exp = _wx_token_cache.get(app_id, (None, 0))
    if time.time() < exp - 60:        # 提前 60s 续
        return token
    new = _fetch_access_token(app_id, secret)
    _wx_token_cache[app_id] = (new, time.time() + 7200)
    return new
```

**已知局限**:多实例下每实例独立缓存,refresh 次数会成 N 倍(对微信 API 友好性是 OK 的,但有点浪费)。

### 5.2 草稿 / 发布

| 微信端点 | 用途 |
|---------|------|
| `/cgi-bin/token` | 拿 access_token |
| `/cgi-bin/material/add_material` | 永久素材上传 |
| `/cgi-bin/draft/add` | 草稿 |
| `/cgi-bin/draft/update` | 更新草稿 |
| `/cgi-bin/draft/get` | 拉草稿 |
| `/cgi-bin/draft/delete` | 删草稿 |
| `/cgi-bin/freepublish/submit` | 发布 |
| `/cgi-bin/freepublish/get` | 查发布状态 |

**docstring 写在发起请求处** —— 微信 API 经常改,版本对齐由 spec 维护。

---

## 6. 安全设计

### 6.1 app_secret 加密

```python
# backend/lumen_core/security.py
from cryptography.fernet import Fernet

def encrypt_wx_secret(plain: str) -> str:
    return Fernet(settings.WX_FERNET_KEY).encrypt(plain.encode()).decode()

def decrypt_wx_secret(encrypted: str) -> str:
    return Fernet(settings.WX_FERNET_KEY).decrypt(encrypted.encode()).decode()
```

**`WX_FERNET_KEY`**:生产环境必须设置,缺失时启动会 fail。

### 6.2 IP 白名单

**微信 API 要求**:调用方 IP 必须配置在公众号后台"IP 白名单"里。

**应对**:部署文档强调配白名单;**当前没做** IP 校验(我们信微信侧)。

### 6.3 跨租户 404

`/?tenant_id != current.tenant_id` 一律 404,不返 403。

### 6.4 草稿分享

**当前**:草稿不放外链,只内部用户可访问。
**不做**:外部预览链接(微信公众号有自己的"预览"机制)。

---

## 7. 与其他模块的关系

```
[Image Generation] ─┐
[TTS]               ─┼─→ WxDraft (插入素材)
[Audio]             ─┘
        ↓
[LLM Call Logs] ← (ai-* 端点全部记录)
        ↓
[WxDraft] → publish → [WxPublishRecord]
        ↓
[Notification] (WX_PUBLISH_COMPLETED / FAILED)
```

**大模型调用复用**: `ai-outline` / `ai-expand` 走平台 chat 模型,自动写 `llm_call_logs`。

**图片生成复用**:封面图可调 `image_generation_service` 生成,走 `IMAGE_GENERATION_COMPLETED` 通知。

---

## 8. 关键设计决策

### 8.1 4 个 AI 端点而非 1 个

见 §4.2。

### 8.2 模板自带缩略图

```python
# frontend: TemplateCard.tsx
# 15 张缩略图用 Pillow 直绘(200x200 + 主题色 + 文字)
# 不依赖外部图片,容器重启 / 跨环境不丢失
```

### 8.3 双屏预览(前端)

```tsx
// dashboard/wx-publisher/drafts/[id]/page.tsx
<Row gutter={16}>
  <Col span={12}>
    <MDEditor value={draft.content_md} onChange={...} />
  </Col>
  <Col span={12}>
    <WxRenderer css={template.css_config} markdown={draft.content_md} />
  </Col>
</Row>
```

**MDEditor → 周》杂志**:**粘贴转 MD** — 用户从 Word / 公众号复制粘贴过来自动识别成 Markdown(2026-06-20 follow-up)。

### 8.4 异步发布

```python
# POST /publish/ 返 202 + record_id
@celery_app.task
def publish_to_wechat_task(record_id: int):
    record = db.get(WxPublishRecord, record_id)
    try:
        result = _do_publish(record)
        record.status = "success"
        record.wx_msg_id = result["media_id"]
    except Exception as e:
        record.status = "failed"
        record.error_message = str(e)[:200]
    record.duration_ms = elapsed
    db.commit()

    NotificationService.publish_event(
        type="WX_PUBLISH_COMPLETED" if success else "WX_PUBLISH_FAILED",
        title=...,
        body=f"errcode 前 30 字: {err[:30]}" if failed else None,
    )
```

**为什么异步**:微信 API 网络往返有时 5-10s,同步发布会卡 request。

### 8.5 故意不发通知的 4 个 AI 端点

```python
# lumen_services/wx_publisher/ai_writer.py
# 4 个同步 LLM 调(ai-outline / expand / polish / summary)不调
# NotificationService — 同步操作,前端 loading 即可
# 详: 通知中心 § 4.1
```

---

## 9. 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| 微信公众号编辑器和我们的 css 渲染不完全一致 | 排版有偏差 | 双屏预览兜底 |
| access_token 进程内缓存 | 多实例重复 request | 单实例部署 |
| 单次发布只推 1 篇 | 批量发布需前端循环 | 不做后台批量 |
| 不能撤回已发布 | 微信 API 限制 | 通过 /cgi-bin/freepublish/delete |
| 草稿没版本控制 | 改回不去 | 手动复制 |
| 没有定时发布 | 微信 API 限制 | 客户端用定时任务调 /publish/ |
| 缩略图 15 张内置 | 第一次默认 | 管理员可自定义上传 |

---

## 10. 边界与不做

### 10.1 当前
- ✅ 公众号绑定 + 单篇草稿
- ✅ 5 步流水线(绑 → 模板 → 写 → 排版 → 发布)
- ✅ AI 写稿 4 能力
- ✅ 11 维 CSS 模板
- ✅ 异步发布 + 失败通知
- ✅ 缩略图生成
- ✅ 双屏预览

### 10.2 不做
- ❌ 视频号(视频号 API 另一套)
- ❌ 小程序
- ❌ 留言 / 评论管理
- ❌ 粉丝管理
- ❌ 数据分析(阅读量 / 转发)
- ❌ 自动排版(A/B 测试)
- ❌ 多公众号矩阵
- ❌ 定时发布
- ❌ 草稿批量操作

### 10.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | 缩略图上传自定义 |
| 短期 | 草稿历史版本 |
| 中期 | 微信视频号接入 |
| 长期 | 矩阵化(多账号管理) |
| 长期 | 留言管理 |
| 长期 | 数据回流(阅读量 → 知识库) |

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 绑账号失败(app_secret 错) | 公众号后台填错 | 重新填 |
| 拿到 access_token 但调 API 401 | IP 不在白名单 | 公众号后台加白 |
| 图片显示不出来 | 微信 CDN 跨域(已知) | /dashboard/wx-publisher 兜底 |
| 渲染后没样式 | 模板 css_config 字段缺失 | 改默认值 |
| 发布返 45001 | 微信 access_token 失效 | 清缓存强制 refresh |
| 发布返 45009 | 调用频率超限 | 降速 |
| 草稿不见了 | 列表过滤(is_active) | 看 status="draft" |
| 缩略图 404 | 路径错 | 检查 `storage/wx_publisher/thumbnails/` |
| 异步发布卡住 | Celery 没起 | 看 worker 日志 |

---

**相关文档**
- [通知中心](notification.md) — 异步发布完成 / 失败的推送
- [图片生成](image-generation.md) — 封面图复用
- [TTS](tts.md) — 音频素材
- [LLM 调用日志](llm-call-logs.md) — 4 个 AI 端点的调用记录

**维护者**:全栈架构师
**最近更新**:2026-08-06
