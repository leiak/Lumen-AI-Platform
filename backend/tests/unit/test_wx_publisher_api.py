"""API endpoint tests for /api/v1/wx-publisher/* routers.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.1 / §8.1

6 + 4 tests (T14 阶段 6 个 + T18 阶段 4 个 AI/render endpoint), all via TestClient:
- POST /accounts/ → 201 + SingleResponse
- POST /accounts/ no token → 401
- Tenant A cannot see tenant B's account in list
- GET /accounts/{id} cross-tenant → 404 (防 IDOR)
- DELETE /templates/{id} on system template → 403
- PUT /drafts/{id} on publishing draft → 409

T18 新增 4 个(AI / render endpoint 鉴权 + 状态锁 + 跨租户):
- POST /ai/outline unauthenticated → 401
- POST /ai/rewrite cross-tenant → 404 (防 IDOR)
- POST /render on publishing draft → 409
- POST /ai/title no token → 401
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_account,
    make_draft,
    make_material,
    make_section,
    make_template,
    make_tenant,
    make_user,
)

# (保持原 import 顺序)


# ---- TestClient + dependency override ---------------------------------------

@pytest.fixture
def client():
    """Plain TestClient — app.main is the real FastAPI app (uses dev DB)."""
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def override_current_user():
    """Override get_current_user to return a fresh mock user per test.

    The override is removed in teardown so other tests in the same
    session aren't affected.
    """
    from lumen_api.v1.auth import get_current_user
    from lumen_main import app

    yield  # test runs here, fixture below sets/clears the override
    # placeholder; the actual override is set in tests that need it
    _ = get_current_user
    _ = app


# ---- Per-file row-tracking fixtures -----------------------------------------

@pytest.fixture
def db_session():
    db = fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def track_user_ids():
    return []


@pytest.fixture
def track_tenant_ids():
    return []


@pytest.fixture
def track_account_ids():
    return []


@pytest.fixture
def track_template_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def track_material_ids():
    return []


@pytest.fixture
def cleanup_rows(
    track_user_ids, track_tenant_ids, track_account_ids,
    track_template_ids, track_draft_ids, track_material_ids,
):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        account_ids=track_account_ids, template_ids=track_template_ids,
        draft_ids=track_draft_ids, material_ids=track_material_ids,
    )


# ---- helpers ----------------------------------------------------------------

def _override_with(user):
    """Install a get_current_user override on the live app and return
    a teardown function. The override returns the actual User row so
    downstream code can read .id / .tenant_id / .is_superuser.
    """
    from lumen_api.v1.auth import get_current_user
    from lumen_main import app

    app.dependency_overrides[get_current_user] = lambda: user

    def _teardown():
        app.dependency_overrides.pop(get_current_user, None)
    return _teardown


def _make_user_for_request(db, *, tenant_id, is_superuser=False):
    """Create + commit a user suitable for the API test (active=True)."""
    return make_user(db, tenant_id=tenant_id, is_superuser=is_superuser)


# ---- tests ------------------------------------------------------------------

def test_create_account_endpoint_201(
    client, db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /wx-publisher/accounts/ 返 201 + SingleResponse"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    teardown = _override_with(user)
    try:
        r = client.post(
            "/api/v1/wx-publisher/accounts/",
            json={
                "name": "primary",
                "app_id": "wx" + ("1" * 16),  # 18 chars
                "app_secret": "a" * 32,
                "account_type": "subscription",
                "is_mock": True,
            },
        )
    finally:
        teardown()

    assert r.status_code == 201
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["app_id"] == "wx" + ("1" * 16)
    # AppSecret is masked — never plaintext
    assert data["app_secret_masked"] == "aa****aa"  # first 2 + **** + last 2 of "a"*32
    assert "app_secret" not in data
    track_account_ids.append(data["id"])


def test_create_account_endpoint_401_unauthenticated(
    client, db_session, cleanup_rows, track_user_ids, track_tenant_ids,
):
    """无 token 返 401"""
    # No override installed — get_current_user requires a real JWT.
    # We don't even need a DB row; the dependency raises 401 first.
    r = client.post(
        "/api/v1/wx-publisher/accounts/",
        json={
            "name": "x",
            "app_id": "wx" + ("2" * 16),
            "app_secret": "b" * 32,
        },
    )
    assert r.status_code == 401


def test_list_accounts_endpoint_tenant_isolation(
    client, db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """tenant A 拿不到 tenant B 的 account"""
    # Tenant A
    t_a = make_tenant(db_session, suffix="a")
    track_tenant_ids.append(t_a.id)
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    track_user_ids.append(u_a.id)
    acc_a = make_account(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_account_ids.append(acc_a.id)

    # Tenant B (no accounts)
    t_b = make_tenant(db_session, suffix="b")
    track_tenant_ids.append(t_b.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.append(u_b.id)

    teardown = _override_with(u_b)
    try:
        r = client.get("/api/v1/wx-publisher/accounts/")
    finally:
        teardown()

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    # Tenant B sees 0 rows
    assert body["total"] == 0
    assert body["data"] == []


def test_get_account_endpoint_404_cross_tenant(
    client, db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """跨租户 GET account 返 404(防 IDOR)"""
    t_a = make_tenant(db_session, suffix="ga")
    t_b = make_tenant(db_session, suffix="gb")
    track_tenant_ids.extend([t_a.id, t_b.id])
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.extend([u_a.id, u_b.id])
    acc_a = make_account(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_account_ids.append(acc_a.id)

    teardown = _override_with(u_b)
    try:
        r = client.get(f"/api/v1/wx-publisher/accounts/{acc_a.id}")
    finally:
        teardown()

    # 404 (not 403) — 防 IDOR 信息泄露
    assert r.status_code == 404


def test_delete_template_endpoint_403_system_template(
    client, db_session, cleanup_rows, track_template_ids,
    track_user_ids, track_tenant_ids,
):
    """DELETE 系统模板返 403"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    super_user = _make_user_for_request(
        db_session, tenant_id=tenant.id, is_superuser=True,
    )
    track_user_ids.append(super_user.id)
    system_tpl = make_template(
        db_session, tenant_id=tenant.id, user_id=super_user.id, is_system=True,
    )
    track_template_ids.append(system_tpl.id)

    teardown = _override_with(super_user)
    try:
        r = client.delete(f"/api/v1/wx-publisher/templates/{system_tpl.id}")
    finally:
        teardown()

    assert r.status_code == 403


def test_draft_update_endpoint_409_when_publishing(
    client, db_session, cleanup_rows, track_draft_ids, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """PUT /wx-publisher/drafts/{id} 在 publishing 状态返 409"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        account_id=account.id, status="publishing",
    )
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.put(
            f"/api/v1/wx-publisher/drafts/{draft.id}",
            json={"title": "new title", "content_markdown": "new body"},
        )
    finally:
        teardown()

    assert r.status_code == 409


# ====== 2026-06-29 — partial update 不擦未传字段 ======
# Bug: WxDraftUpdate Optional 字段 (account_id / template_id / kb_id /
# tags / summary / author) Pydantic v2 默认 None。update_draft 直接
# ``row.account_id = payload.account_id`` → 未传的字段被 None 覆盖,
# 真实事故链:前端 handleSave 发 {title, content_markdown} → 保存后
# account_id 和 template_id 被擦掉,刷新页面看到"没选"。修法:用
# ``model_dump(exclude_unset=True)`` 只取 caller 显式提供的字段。
# 显式传 null 仍可清空(因为 ``exclude_unset`` 只过滤 "未传",不过滤
# "传了 None")。

def test_draft_update_preserves_unsent_optional_fields(
    client, db_session, cleanup_rows, track_draft_ids, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """PUT 只发 title + content_markdown 时,account_id / template_id 应保留原值。

    回归 2026-06-29 的事故:前端点「保存草稿」只发 title+content,后端
    把 account_id / template_id 一起清掉 → 再进编辑页 Select 是空的。
    """
    from lumen_schemas.wx_publisher import WxDraftUpdate
    # 验证 schema 行为 — exclude_unset=True 时只返回 caller 提供的字段,
    # 这是修法的关键。如果这里失败说明 Pydantic 行为变了,需要重新审视。
    payload = WxDraftUpdate(title="x", content_markdown="y")
    dumped = payload.model_dump(exclude_unset=True)
    assert "title" in dumped
    assert "content_markdown" in dumped
    # account_id / template_id / kb_id / tags / summary / author 都不在
    assert "account_id" not in dumped
    assert "template_id" not in dumped
    assert "kb_id" not in dumped
    assert "tags" not in dumped
    assert "summary" not in dumped
    assert "author" not in dumped
    # 显式传 null 仍然出现在 dict(exclude_unset 不过滤 None)—
    # 这就是 partial update 的能力:caller 可以清字段。
    payload_null = WxDraftUpdate(title="x", content_markdown="y", account_id=None)
    dumped_null = payload_null.model_dump(exclude_unset=True)
    assert dumped_null.get("account_id") is None  # 在 dict 里,值为 None

    # 端到端:起一个 draft 带 account_id+template_id,PUT 不带这两个字段,
    # 验证 DB 里 account_id+template_id 还在
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    template = make_template(db_session, tenant_id=tenant.id, user_id=user.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        account_id=account.id, template_id=template.id,
    )
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.put(
            f"/api/v1/wx-publisher/drafts/{draft.id}",
            json={"title": "new title", "content_markdown": "new body"},
        )
    finally:
        teardown()

    assert r.status_code == 200
    body = r.json()
    assert body["data"]["title"] == "new title"
    # 关键断言:account_id 和 template_id 都保留
    assert body["data"]["account_id"] == account.id
    assert body["data"]["template_id"] == template.id


def test_draft_update_can_explicitly_clear_field_with_null(
    client, db_session, cleanup_rows, track_draft_ids, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """显式传 null 能清字段(caller 主动清 account_id)。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        account_id=account.id,
    )
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.put(
            f"/api/v1/wx-publisher/drafts/{draft.id}",
            json={
                "title": draft.title,
                "content_markdown": draft.content_markdown,
                "account_id": None,  # 显式清空
            },
        )
    finally:
        teardown()

    assert r.status_code == 200
    assert r.json()["data"]["account_id"] is None


# ---------------------------------------------------------------------------
# T18 — AI / render endpoint 鉴权 + 状态锁 + 跨租户
# ---------------------------------------------------------------------------

def test_ai_outline_endpoint_401_unauthenticated(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /ai/outline 无 token 返 401(不走 DB,鉴权在前面 fail)。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    # 不装 override → 鉴权 401
    r = client.post(
        f"/api/v1/wx-publisher/drafts/{draft.id}/ai/outline",
        json={"topic": "AI Agent 应用", "section_count": 3},
    )
    assert r.status_code == 401


def test_ai_rewrite_endpoint_404_cross_tenant(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /ai/rewrite 跨租户 section 返 404(防 IDOR 信息泄露)。

    tenant A 建 draft + section,tenant B 调 AI 改写 tenant A 的 section。
    service 层 get_draft 先 404(跨租户),不会进入 ai_creator。
    """
    # Tenant A — owner of draft + section
    t_a = make_tenant(db_session, suffix="ra")
    track_tenant_ids.append(t_a.id)
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    track_user_ids.append(u_a.id)
    draft_a = make_draft(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_draft_ids.append(draft_a.id)
    section_a = make_section(
        db_session, tenant_id=t_a.id, draft_id=draft_a.id,
        order_index=0, heading="h", content_markdown="body",
    )

    # Tenant B — caller
    t_b = make_tenant(db_session, suffix="rb")
    track_tenant_ids.append(t_b.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.append(u_b.id)

    teardown = _override_with(u_b)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft_a.id}/ai/rewrite",
            json={"section_id": section_a.id, "instruction": "更口语化"},
        )
    finally:
        teardown()

    # 跨租户 — 404(不是 403,防 IDOR)
    assert r.status_code == 404


def test_render_endpoint_409_when_publishing(
    client, db_session, cleanup_rows, track_draft_ids, track_account_ids,
    track_template_ids, track_user_ids, track_tenant_ids,
):
    """POST /render 在 publishing 状态返 409(spec §4.4)。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    template = make_template(
        db_session, tenant_id=tenant.id, user_id=user.id,
    )
    track_template_ids.append(template.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        account_id=account.id, status="publishing",
    )
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft.id}/render",
            json={"template_id": template.id},
        )
    finally:
        teardown()

    assert r.status_code == 409


def test_ai_title_endpoint_401_unauthenticated(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /ai/title 无 token 返 401。"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    r = client.post(
        f"/api/v1/wx-publisher/drafts/{draft.id}/ai/title",
        json={"count": 5},
    )
    assert r.status_code == 401


# ---- T23 (CP4) publish endpoint tests ---------------------------------------


def test_publish_endpoint_202_unauthenticated(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids, track_account_ids,
):
    """POST /wx-publisher/publish/ 无 token 返 401(无 draft/account 也行,
    鉴权在依赖注入层先抛)。
    """
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    # No override — get_current_user raises 401 before any DB lookup
    r = client.post(
        "/api/v1/wx-publisher/publish/",
        json={"draft_id": draft.id, "account_id": account.id},
    )
    assert r.status_code == 401


def test_publish_endpoint_404_cross_tenant(
    client, db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids, track_draft_ids,
):
    """跨租户 GET publish/{id} 返 404(防 IDOR)。

    注:POST /publish/ 在跨租户 draft 时也由 service.create_publish_record
    内部抛 404。这里用 GET 测试跨租户更简洁(GET 路径在 endpoint 层
    直接做 tenant_id 过滤,不调 service,行为更可预测)。
    """
    from lumen_models.wx_publisher import WxPublishRecord

    t_a = make_tenant(db_session, suffix="pa")
    t_b = make_tenant(db_session, suffix="pb")
    track_tenant_ids.extend([t_a.id, t_b.id])
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.extend([u_a.id, u_b.id])
    acc_a = make_account(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_account_ids.append(acc_a.id)
    draft_a = make_draft(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_draft_ids.append(draft_a.id)

    # Tenant A 自己写一条 record(走 publish_sync,不走 endpoint 防止
    # BackgroundTasks 实际跑)
    from lumen_schemas.wx_publisher import WxPublishRequest
    from lumen_services.wx_publisher.publish_service import WxPublishService
    svc = WxPublishService(db_session, u_a)
    rec_a = svc.publish_sync(
        WxPublishRequest(draft_id=draft_a.id, account_id=acc_a.id)
    )

    teardown = _override_with(u_b)
    try:
        r = client.get(f"/api/v1/wx-publisher/publish/{rec_a.id}")
    finally:
        teardown()

    # 404 — 防 IDOR 信息泄露
    assert r.status_code == 404

    # 显式清理 record(tests cleanup_rows 已知 track_record_ids;这里手动清)
    db_session.query(WxPublishRecord).filter(
        WxPublishRecord.id == rec_a.id
    ).delete(synchronize_session=False)
    db_session.commit()


# ---------------------------------------------------------------------------
# M32.1 — paste-html endpoint tests (HTML → MD 转换 + 跨租户 + 状态锁)
# ---------------------------------------------------------------------------

def test_paste_html_appends_to_content_markdown(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /paste-html 把 HTML 转 MD 并 append 到 draft.content_markdown.

    行为:
    - 不覆盖, append 到末尾
    - 返回 200 + 更新后的 draft
    """
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        content_markdown="# 现有内容",
    )
    track_draft_ids.append(draft.id)

    html_payload = (
        "<h2>粘贴的标题</h2>"
        "<p>这是 <strong>粘贴</strong> 的内容.</p>"
        "<ul><li>项目 1</li><li>项目 2</li></ul>"
    )

    teardown = _override_with(user)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft.id}/paste-html",
            json={"html": html_payload},
        )
    finally:
        teardown()

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["id"] == draft.id

    # 重新读 DB 验证 append 行为。用 fresh_session() 开全新 session —
    # 因为 db_session fixture 跟 endpoint 内部 session 共享 connection
    # pool,即便 expire_all 也可能读到 stale row(REPEATABLE READ 隔离
    # 级别,M24 dev DB 测试踩过同款问题 — 同 connection 上多次 query
    # 命中一致性快照)。
    from lumen_models.wx_publisher import WxDraft
    new_db = fresh_session()
    try:
        fresh = new_db.query(WxDraft).filter(WxDraft.id == draft.id).first()
        assert fresh is not None
        # 应包含原有 + 新粘贴内容
        assert "# 现有内容" in fresh.content_markdown
        assert "## 粘贴的标题" in fresh.content_markdown
        assert "**粘贴**" in fresh.content_markdown
        assert "- 项目 1" in fresh.content_markdown
        assert "- 项目 2" in fresh.content_markdown
    finally:
        new_db.close()


def test_paste_html_404_for_other_tenant_draft(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /paste-html 跨租户返 404(防 IDOR 信息泄露).

    tenant A 建 draft, tenant B 调 endpoint 应拿不到 draft (404)。
    """
    # Tenant A — owner
    t_a = make_tenant(db_session, suffix="pha")
    track_tenant_ids.append(t_a.id)
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    track_user_ids.append(u_a.id)
    draft_a = make_draft(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_draft_ids.append(draft_a.id)

    # Tenant B — caller
    t_b = make_tenant(db_session, suffix="phb")
    track_tenant_ids.append(t_b.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.append(u_b.id)

    teardown = _override_with(u_b)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft_a.id}/paste-html",
            json={"html": "<p>hostile paste</p>"},
        )
    finally:
        teardown()

    # 404 (not 403) — 防 IDOR
    assert r.status_code == 404


def test_paste_html_409_when_draft_publishing(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /paste-html 在 status in {publishing, published} 时返 409."""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        status="publishing",
    )
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft.id}/paste-html",
            json={"html": "<p>should be rejected</p>"},
        )
    finally:
        teardown()

    assert r.status_code == 409


def test_paste_html_400_when_html_empty(
    client, db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """POST /paste-html 空 html 返 422 (Pydantic Field min_length=1).

    注意:这里测的是 schema validation,所以 status code 是 422
    (Pydantic RequestValidationError) 而不是 4xx 自定义。
    """
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    teardown = _override_with(user)
    try:
        r = client.post(
            f"/api/v1/wx-publisher/drafts/{draft.id}/paste-html",
            json={"html": ""},
        )
    finally:
        teardown()

    # FastAPI RequestValidationError → 422
    assert r.status_code == 422


# ====== 2026-06-29 — GET /materials/{id} (草稿编辑器「插入素材」依赖) ======
# 前端 materialApi.get(id) 调这个 endpoint 拿全 content (list 只返 200 字
# content_preview)。CP2 spec 只列了 list/create/from-kb/delete 4 个,get
# 是后续草稿编辑器 UX 落地时加的 — 加上 404 防 IDOR 守门。

def test_get_material_endpoint_200(
    client, db_session, cleanup_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """GET /materials/{id} 返全 content"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    mat = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id,
        source_type="manual", tags=["ai", "draft"],
    )
    track_material_ids.append(mat.id)

    teardown = _override_with(user)
    try:
        r = client.get(f"/api/v1/wx-publisher/materials/{mat.id}")
    finally:
        teardown()

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    # 返 SingleResponse 包裹,data 是 WxMaterialResponse(全 content)
    assert body["data"]["id"] == mat.id
    assert body["data"]["title"] == mat.title
    # 全 content 必须在(insert 流程依赖) — make_material 写入
    # "material content for <suffix>",验证它出现
    assert "material content for" in body["data"]["content"]


def test_get_material_endpoint_404_cross_tenant(
    client, db_session, cleanup_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """跨租户 GET material 返 404(防 IDOR — 跟 account/draft 同模式)"""
    t_a = make_tenant(db_session, suffix="mgma")
    t_b = make_tenant(db_session, suffix="mgmb")
    track_tenant_ids.extend([t_a.id, t_b.id])
    u_a = _make_user_for_request(db_session, tenant_id=t_a.id)
    u_b = _make_user_for_request(db_session, tenant_id=t_b.id)
    track_user_ids.extend([u_a.id, u_b.id])
    mat_a = make_material(db_session, tenant_id=t_a.id, user_id=u_a.id)
    track_material_ids.append(mat_a.id)

    teardown = _override_with(u_b)
    try:
        r = client.get(f"/api/v1/wx-publisher/materials/{mat_a.id}")
    finally:
        teardown()

    # 404 not 403 — 防 IDOR 信息泄露
    assert r.status_code == 404


def test_get_material_endpoint_404_not_found(
    client, db_session, cleanup_rows, track_user_ids, track_tenant_ids,
):
    """GET 不存在的 material 返 404(同 cross-tenant 行为)"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = _make_user_for_request(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    teardown = _override_with(user)
    try:
        r = client.get("/api/v1/wx-publisher/materials/99999999")
    finally:
        teardown()

    assert r.status_code == 404


def test_get_material_endpoint_401_unauthenticated(client):
    """GET material 无 token 返 401"""
    r = client.get("/api/v1/wx-publisher/materials/1")
    assert r.status_code == 401
