"""Pydantic schemas for /api/v1/wx-publisher/* (M32 公众号助手).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.3

This module ships the **account-management** subset for CP1 (T4). The
remaining schemas (template / draft / material / publish) will land
in later checkpoints — T7-T12. Keeping everything in one ``__init__``
matches the project's convention (see ``schemas/knowledge.py`` /
``schemas/agent.py``), which is why the spec calls for a single
``schemas/wx_publisher/__init__.py`` despite the broader spec using
sub-files in §12 for the longer-term layout.
"""
from datetime import datetime
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Account schemas (CP1, T4)
# ---------------------------------------------------------------------------

class WxAccountCreate(BaseModel):
    """Body schema for ``POST /wx-publisher/accounts``.

    Spec §4.3 — ``app_id`` is constrained to the WeChat AppID
    shape (``wx`` prefix + 16-32 lowercase alphanumerics) via a
    Pydantic ``pattern``; ``app_secret`` is plain-text at this layer
    and is encrypted by the service before persistence.
    """
    name: str = Field(min_length=1, max_length=100)
    # WeChat AppID format: starts with "wx" then 16-32 [a-z0-9].
    # Pydantic v2 ``pattern`` is anchored with re.search (no need to
    # add ^...$). We keep the anchors in the pattern to make the
    # regex self-documenting and to defend against partial matches
    # if the implementation ever switches validators.
    app_id: str = Field(
        min_length=10,
        max_length=50,
        pattern=r"^wx[a-z0-9]{16,32}$",
    )
    # 20-char minimum is WeChat's de-facto AppSecret floor; we cap at
    # 100 to defend against unbounded input.
    app_secret: str = Field(min_length=20, max_length=100)
    account_type: Literal["subscription", "service", "enterprise"] = "subscription"
    # Default True: new accounts start in mock mode so the operator
    # can dry-run the publish flow before turning on real posting.
    is_mock: bool = True
    # One IP per entry; service layer stores JSON-encoded text.
    ip_whitelist: Optional[List[str]] = None


class WxAccountUpdate(BaseModel):
    """Body schema for ``PUT /wx-publisher/accounts/{id}``.

    ``app_secret`` is intentionally absent: changing it is gated by a
    separate endpoint in V2 (so we can re-prompt for the old secret
    and re-verify the new one before swapping). For CP1, the secret
    is immutable post-create — same pattern as M14 widget
    ``updateExternalApp`` where the API key/secret live in their own
    rotate endpoint.
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    is_active: Optional[bool] = None
    ip_whitelist: Optional[List[str]] = None
    # is_mock toggling is allowed but the operator should run
    # ``POST /accounts/{id}/verify`` first; service layer does not
    # enforce that here — UI surfaces the recommendation.
    is_mock: Optional[bool] = None


class WxAccountResponse(BaseModel):
    """List-item shape. AppSecret is masked; never return plaintext."""
    # Pydantic v2: model_validate(orm_row) requires from_attributes=True.
    # 不加的话 ValidationError → 500(2026-06-29 publish endpoint 真实翻车)。
    # 项目里 agent.py / agent_team.py / chat.py / knowledge.py 都加了,
    # wx_publisher 漏了 — 这里统一补上,后续 _to_response() 重构也兼容。
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    app_id: str
    app_secret_masked: str  # "ab****90" (first 2 + "****" + last 2)
    account_type: str
    is_mock: bool
    is_active: bool
    last_verified_at: Optional[datetime] = None
    created_at: datetime


class WxAccountDetail(WxAccountResponse):
    """Detail shape — adds fields that are useful in the editor but
    too noisy for list rendering.
    """
    access_token_expires_at: Optional[datetime] = None
    # Parsed list (not the JSON-encoded TEXT). Service layer does
    # the json.loads — schemas stays declarative.
    ip_whitelist: Optional[List[str]] = None


class WxAccountVerifyRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/accounts/{id}/verify``.

    Currently a no-op placeholder — the verify endpoint takes
    ``account_id`` from the URL path and has no body params. The
    class exists for forward-compatibility: V2 will add ``force`` /
    ``ip_check`` options here without breaking the route signature.
    """
    pass


class WxAccountVerifyResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/accounts/{id}/verify``."""
    account_id: int
    valid: bool
    message: str
    verified_at: datetime


class WxAccountPurgeResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/accounts/{id}/purge`` (admin only).

    Lists row counts that the purge operation swept so the operator
    (and the audit log) sees what was destroyed. Note: the spec §3.6
    design choice is that accounts are soft-deleted (``is_active=False``)
    to preserve ``wx_publish_records`` audit history. This endpoint
    is the **explicit override** for operators who have decided to
    break that audit trail — it cascades through:

    - ``wx_publish_records`` (FK ON DELETE RESTRICT) — rows are
      **deleted** (not nulled), destroying the audit record
    - ``wx_drafts`` (FK ON DELETE SET NULL) — ``account_id`` is
      auto-nulled by MySQL on parent delete
    - ``wx_accounts`` — the account row is hard-deleted
    """
    account_id: int
    deleted_publish_records: int
    drafts_set_null: int
    deleted_account: bool


# ---------------------------------------------------------------------------
# Draft schemas (CP2, T9-T10)
# ---------------------------------------------------------------------------

class WxDraftCreate(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts``.

    spec §4.3 — minimal required fields (title + content_markdown).
    account_id / template_id / kb_id / tags are all optional at create
    time so the UI can land on the editor first and bind resources
    later via PATCH.

    We use ``Field(default=None)`` for optional IDs (rather than
    Pydantic's sentinel magic) so the Pydantic-generated JSON schema
    always emits ``"default": null`` and the OpenAPI client gets a
    clear "leave it out or set null" UX.
    """
    title: str = Field(min_length=1, max_length=200)
    # content_markdown 可空字符串(spec §4.3: ``min_length=0``)— 客户端
    # 可能先存标题后填内容。
    content_markdown: str = Field(default="", min_length=0)
    account_id: Optional[int] = None
    template_id: Optional[int] = None
    kb_id: Optional[int] = None
    tags: Optional[List[str]] = None


class WxDraftUpdate(BaseModel):
    """Body schema for ``PUT /wx-publisher/drafts/{id}``.

    Required fields for an editor save: ``title`` and
    ``content_markdown``. Optional fields default to ``None`` and
    the service applies them as-is — including setting them back to
    ``None`` to clear (e.g. detach a template). This matches the
    spec §4.3 spirit of "the UI explicitly sends nulls for fields
    the user cleared in the editor".
    """
    title: str = Field(min_length=1, max_length=200)
    content_markdown: str = Field(default="", min_length=0)
    account_id: Optional[int] = None
    template_id: Optional[int] = None
    kb_id: Optional[int] = None
    tags: Optional[List[str]] = None
    summary: Optional[str] = Field(default=None, max_length=500)
    author: Optional[str] = Field(default=None, max_length=50)


class WxDraftListItem(BaseModel):
    """List-item shape — fields the table needs, no body content.

    List pages do not show ``content_markdown`` (potentially MB-sized);
    the editor loads the detail endpoint for the full record.
    """
    # from_attributes=True: 与 WxAccountResponse 注释同 — model_validate(orm) 必须。
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    account_id: Optional[int] = None
    template_id: Optional[int] = None
    status: str
    scheduled_at: Optional[datetime] = None
    updated_at: datetime


class WxDraftResponse(WxDraftListItem):
    """Detail-list-friendly shape — adds the bookkeeping fields the
    detail page's sidebar needs (cover / kb / tags / publish state).

    Note: ``content_markdown`` and ``content_html`` are intentionally
    NOT here — the full ``WxDraftDetail`` adds those on top.
    """
    cover_image_id: Optional[int] = None
    kb_id: Optional[int] = None
    tags: Optional[List[str]] = None
    published_at: Optional[datetime] = None
    wechat_media_id: Optional[str] = None
    error_message: Optional[str] = None


class WxDraftDetail(WxDraftResponse):
    """Detail shape — the full row + sections list.

    Used by ``GET /drafts/{id}``. ``sections`` is sorted by
    ``order_index`` ASC at the service layer.
    """
    user_id: int
    summary: Optional[str] = None
    author: Optional[str] = None
    content_markdown: str
    content_html: Optional[str] = None
    cover_url: Optional[str] = None
    created_at: datetime
    sections: List["WxDraftSectionResponse"] = []


class WxDraftSectionCreate(BaseModel):
    """Body schema for ``POST /drafts/{id}/sections``.

    Caller supplies ``order_index`` explicitly so the UI can insert
    a section at a specific position; the service validates against
    the UNIQUE(draft_id, order_index) constraint and returns 409 on
    collision.
    """
    order_index: int = Field(ge=0)
    heading: Optional[str] = Field(default=None, max_length=200)
    content_markdown: str = Field(default="", min_length=0)


class WxDraftSectionUpdate(BaseModel):
    """Body schema for ``PUT /drafts/{id}/sections/{sid}``."""
    order_index: int = Field(ge=0)
    heading: Optional[str] = Field(default=None, max_length=200)
    content_markdown: str = Field(default="", min_length=0)


class WxDraftSectionResponse(BaseModel):
    """Return shape for a single section."""
    id: int
    order_index: int
    heading: Optional[str] = None
    content_markdown: str
    content_html: Optional[str] = None
    ai_prompt: Optional[str] = None
    ai_model_config_id: Optional[int] = None


class WxDraftSectionReorderRequest(BaseModel):
    """Body schema for ``POST /drafts/{id}/sections/reorder``.

    ``orders`` is a list of ``(section_id, new_order_index)`` pairs.
    Service validates no duplicate ``new_order_index`` values and
    that all section_ids belong to the draft.
    """
    orders: List[Tuple[int, int]]


# Forward ref resolution: WxDraftDetail references WxDraftSectionResponse
# (which is defined after it) — Pydantic v2 resolves this lazily but
# calling ``model_rebuild()`` makes it explicit and avoids surprises
# in the OpenAPI schema generation.
WxDraftDetail.model_rebuild()


# ---------------------------------------------------------------------------
# Template schemas (CP2, T7-T8)
# ---------------------------------------------------------------------------

# Spec §3.2: 5 categories of styling.
TEMPLATE_CATEGORIES = Literal["minimal", "tech", "magazine", "literary", "business"]


class WxTemplateCreate(BaseModel):
    """Body schema for ``POST /wx-publisher/templates``.

    Spec §4.3: ``name`` (1-100), ``category`` (one of 5 styles),
    ``html_body`` (>=10 chars; placeholder-rich HTML), ``css_variables``
    (dict — font / line-height / theme color / padding). The service
    layer silently coerces ``is_system=True`` to ``False`` for non-admin
    callers — the schema keeps the field for forward-compatibility with
    admin-only template seeding tools.
    """
    name: str = Field(min_length=1, max_length=100)
    category: TEMPLATE_CATEGORIES
    description: Optional[str] = Field(default=None, max_length=500)
    # Spec §3.2: HTML body is LONGTEXT (multi-MB expected for magazine
    # designs). We enforce a 10-char floor to filter out blank submits
    # but allow truly tiny templates (e.g. a minimal "title + content"
    # shell) without imposing a heavy minimum.
    html_body: str = Field(min_length=10)
    # ``Dict[str, Any]`` so callers can pass arbitrary CSS variable
    # shapes — the renderer doesn't need a typed contract for this in
    # CP2; spec §7.2 just does string substitution on the rendered HTML.
    css_variables: dict
    preview_html: Optional[str] = None
    # is_system is admin-only; the API layer silently forces False for
    # non-superuser callers (so client-supplied True is harmless).
    is_system: bool = False


class WxTemplateUpdate(BaseModel):
    """Body schema for ``PUT /wx-publisher/templates/{id}``.

    System templates cannot be updated (the service layer returns 403
    before this schema is even consulted). The schema mirrors
    ``WxTemplateCreate`` minus ``is_system`` — a tenant cannot promote
    a row to system status via update; that's an admin-only operation
    reserved for seeding scripts.
    """
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    category: Optional[TEMPLATE_CATEGORIES] = None
    description: Optional[str] = Field(default=None, max_length=500)
    html_body: Optional[str] = Field(default=None, min_length=10)
    css_variables: Optional[dict] = None
    preview_html: Optional[str] = None


class WxTemplateListItem(BaseModel):
    """List-item shape for the template gallery.

    ``has_thumbnail`` is a cheap boolean so the UI can render a
    placeholder for templates without a generated preview image
    (typical for user-uploaded templates — the seed copy of system
    templates ships with a thumbnail, see spec §3.2).
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: Optional[str] = None
    is_system: bool
    usage_count: int
    has_thumbnail: bool
    created_at: datetime


class WxTemplateDetail(WxTemplateListItem):
    """Detail shape — adds the full HTML/CSS payload + editor metadata."""
    html_body: str
    css_variables: dict
    preview_html: Optional[str] = None
    # ``thumbnail_size`` is the byte size of the JPEG blob, useful for
    # the UI to decide whether to show "preview ready" or a spinner.
    thumbnail_size: Optional[int] = None
    created_by: int
    updated_at: datetime


# ``WxTemplateResponse`` is intentionally identical to the list item —
# the create / update endpoints return the same shape. We keep them
# as separate types so future divergence (e.g. adding ``updated_at`` to
# the response) doesn't ripple into the list item.
WxTemplateResponse = WxTemplateListItem


# ---------------------------------------------------------------------------
# Material schemas (CP2, T11-T12) — spec §3.5 / §4.1
# ---------------------------------------------------------------------------
#
# 2 source types for now: ``manual`` (operator-typed) + ``kb`` (imported
# from a RetrievalPipeline search). ``url`` (browser clipper) is V2 —
# the field accepts it but the API/UI does not yet expose it.

class WxMaterialCreate(BaseModel):
    """Body schema for ``POST /wx-publisher/materials`` (manual entry).

    Spec §3.5 — ``source_type`` is forced to ``"manual"`` in the API
    layer regardless of what the caller sends, so a hand-rolled curl
    can't sneak in a row that pretends to come from a KB without a
    real ``kb_chunk_id`` link.
    """
    title: str = Field(min_length=1, max_length=200)
    # LONGTEXT in DB — no length cap at the schema layer; the column
    # itself is ~4 GB so we'd hit other limits first.
    content: str = Field(min_length=1)
    tags: Optional[List[str]] = None
    # ``kb_chunk_id`` is optional here too: a manual entry that the
    # operator typed but later wants to *also* link to a KB chunk can
    # pass it; the service layer does not validate it exists in DB
    # (FK constraint on insert will surface a 409 if it doesn't).
    kb_chunk_id: Optional[int] = None


class WxMaterialListItem(BaseModel):
    """List-item shape — content is truncated to 200 chars so the
    list endpoint stays cheap. The full content lives in
    ``WxMaterialResponse`` (used by the detail view).
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    # 200-char preview; the service layer slices ``content`` and
    # appends ``"…"`` when truncation happened. Frontend reads this
    # as a plain string.
    content_preview: str
    source_type: str
    kb_chunk_id: Optional[int]
    tags: Optional[List[str]]
    is_used: bool
    created_at: datetime


class WxMaterialResponse(BaseModel):
    """Detail shape — full content + everything the list item has.

    Note: we deliberately do NOT include a separate
    ``content_preview`` field here. The full content is in ``content``
    and the frontend can compute a preview client-side.
    """
    id: int
    title: str
    content: str
    source_type: str
    kb_chunk_id: Optional[int]
    tags: Optional[List[str]]
    is_used: bool
    created_at: datetime
    updated_at: datetime


class WxMaterialImportFromKBRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/materials/from-kb``.

    Spec §4.3 — the 3 fields are exactly the ones
    ``RetrievalPipeline.search`` needs; the service layer maps them
    1:1 onto ``pipeline.search(query=..., k=top_k, filter_expr=...)``.
    """
    kb_id: int = Field(ge=1)
    query: str = Field(min_length=1, max_length=200)
    # Hard cap at 50 — same as the spec; ``top_k`` is the number of
    # chunks to import, not the k in the hybrid retriever's RRF.
    top_k: int = Field(default=20, ge=1, le=50)


class WxMaterialImportResult(BaseModel):
    """Return shape for ``POST /wx-publisher/materials/from-kb``.

    Spec §4.2:
    - ``imported``: rows actually inserted
    - ``skipped``: candidates we already had (same ``kb_chunk_id``
      in this tenant) — MVP currently always 0 (no dedup, see
      ``MaterialService.import_from_kb`` docstring).
    - ``materials``: full ``WxMaterialResponse`` for each inserted
      row, in the order the search returned them.
    """
    imported: int
    skipped: int
    materials: List[WxMaterialResponse]


# ---------------------------------------------------------------------------
# AI schemas (CP3, T17)
# ---------------------------------------------------------------------------
# 4 个 AI 创作 + 1 个 render 端点。spec §4.1 + §4.2:
# - /ai/outline /ai/rewrite /ai/expand /ai/title — 都同步响应,带
#   sections 列表 / 改写文本 / 标题候选。Response 都带 llm_call_id +
#   duration_ms 便于前端跳到 LLMCallLog 详情。
# - /render — 应用模板渲染 Markdown → HTML,返 content_html + preview_url。

AI_STYLES = Literal["总-分-总", "观点递进", "故事+感悟", "FAQ 形式"]


class WxAIOutlineRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/ai/outline``.

    Spec §4.2:
    - ``topic``: 文章主题(必填,2-200 字)
    - ``section_count``: 期望章节数(3-10,默认 5)
    - ``model_config_id``: 可选,None → tenant 默认 chat 模型
    - ``style``: 4 种之一,默认 "总-分-总"
    """
    topic: str = Field(min_length=2, max_length=200)
    section_count: int = Field(default=5, ge=3, le=10)
    model_config_id: Optional[int] = None
    style: AI_STYLES = "总-分-总"


class WxAIOutlineResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/drafts/{id}/ai/outline``.

    spec §4.2 — sections 是新建的 ``WxDraftSectionResponse`` 列表
    (已 commit,已替换 draft 现有 sections)。
    ``llm_call_id`` 是 ``llm_call_logs.call_id``(uuid 字符串),点跳
    ``/dashboard/logs/llm-calls/{id}``。
    """
    sections: List[WxDraftSectionResponse]
    llm_call_id: str
    duration_ms: int


class WxAIRewriteRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/ai/rewrite``."""
    section_id: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=500)
    model_config_id: Optional[int] = None


class WxAIRewriteResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/drafts/{id}/ai/rewrite``。

    改写后 markdown 文本**不**自动写库,让 UI 弹 Diff Modal 让用户点「应用」。
    """
    section_id: int
    new_content_markdown: str
    llm_call_id: str
    duration_ms: int


class WxAIExpandRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/ai/expand``."""
    section_id: int = Field(ge=1)
    expansion_ratio: float = Field(default=1.5, ge=1.2, le=3.0)
    model_config_id: Optional[int] = None


class WxAIExpandResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/drafts/{id}/ai/expand``。

    扩写后 markdown 文本**不**自动写库,让 UI 弹 Diff Modal 让用户点「应用」。
    """
    section_id: int
    new_content_markdown: str
    llm_call_id: str
    duration_ms: int


class WxAITitleRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/ai/title``."""
    count: int = Field(default=5, ge=3, le=8)
    model_config_id: Optional[int] = None


class WxAITitleResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/drafts/{id}/ai/title``。

    候选标题列表 — 不自动写 ``draft.title``,让 UI 弹候选列表让用户挑。
    """
    titles: List[str]
    llm_call_id: str
    duration_ms: int


class WxRenderRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/render``."""
    template_id: int = Field(ge=1)


class WxRenderResponse(BaseModel):
    """Return shape for ``POST /wx-publisher/drafts/{id}/render``。

    spec §4.2:
    - ``draft_id``: 回显
    - ``content_html``: 应用模板渲染后的完整 HTML
    - ``preview_url``: 跳编辑页 + 预览参数(``?preview=1``),前端用
      iframe 打开看实时效果
    """
    draft_id: int
    content_html: str
    preview_url: str


class WxDraftPasteHtmlRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/drafts/{id}/paste-html`` (M32.1)。

    粘贴的 HTML 来自飞书/网页 clipboard(``text/html`` MIME)。
    后端用 ``HtmlToMarkdownConverter`` 转 MD 后 append 到
    ``draft.content_markdown``(末尾 + 2 换行)。

    ``html`` 长度上限 500_000 chars — 飞书一篇长文档典型 50-100KB,
    留 5x 余量;前端粘贴前先检查(``>200KB`` 提示用户)。
    """
    html: str = Field(min_length=1, max_length=500_000)


# ---------------------------------------------------------------------------
# Publish schemas (CP4, T22) — spec §4.1 / §4.2
# ---------------------------------------------------------------------------
#
# POST /publish — 异步发布(BackgroundTasks + WS 通知)。
# GET  /publish/{id} — 查发布记录详情。
# MVP 简化:HTML → 微信图文消息只取 cover + title + 截前 2000 字
# content_html 作为 content(微信图文消息 content 字段是 HTML)。

class WxPublishRequest(BaseModel):
    """Body schema for ``POST /wx-publisher/publish/``。

    spec §4.2:
    - ``draft_id``: 要发布的草稿
    - ``account_id``: 目标公众号账号
    - ``scheduled_at``: 可选;None / 未来时间 → None 立即发 / 未来时间
      入 APScheduler('date' trigger)。

    service 层会校验 ``draft.status`` 可发 + ``account.is_active=True``
    + ``draft.tenant_id == account.tenant_id``,失败返 404 / 422 / 409。
    """
    draft_id: int = Field(ge=1)
    account_id: int = Field(ge=1)
    scheduled_at: Optional[datetime] = None


class WxPublishRecordListItem(BaseModel):
    """List-item shape — 列表页用,不暴露错误堆栈全文。

    spec §4.1: ``status`` 是 6 状态之一(queued / uploading / uploaded /
    mass_sending / success / failed)。
    """
    # from_attributes=True:publish endpoint 调 model_validate(record) 把
    # SQLAlchemy ORM 转 schema。Pydantic v2 默认 model_config 不开
    # from_attributes,传 ORM 对象会被当成 dict-like,raise ValidationError
    # → FastAPI 默认 exception handler 兜底 500(2026-06-29 复现)。
    model_config = ConfigDict(from_attributes=True)

    id: int
    draft_id: int
    account_id: int
    user_id: int
    status: str
    wechat_media_id: Optional[str] = None
    wechat_msg_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class WxPublishRecordResponse(WxPublishRecordListItem):
    """Detail shape — 详情页用,加上错误码 + 错误消息。

    ``error_code`` 是微信 API errcode(字符串,避免前端 int overflow
    处理);``error_message`` 截前 1000 字(spec §7.4)。
    """
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


# Internal — service 层 create_publish_record / run_publish 之间用的
# 内部 record 不暴露 schema(直接 ORM 行),不需要单独 Pydantic。
WxPublishRecordCreate = WxPublishRequest  # 内部复用 Request shape,不起新名
