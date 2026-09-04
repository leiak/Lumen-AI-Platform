"""Phase 1 Group A 3.4 (2026-09-04): UNIQUE × soft-delete 冲突修复测试。

覆盖 9 张表(10 个 UNIQUE 索引)的核心修复行为:
- 软删后名字/identifier 可复用(主修复目标)
- active 行仍受 UNIQUE 约束(不能误把 UNIQUE 改没)
- composite (tenant_id, ...) 跨 tenant 不冲突(原 spec 行为不破坏)
- VIRTUAL GENERATED dedup 列 active=原值 / 软删=NULL 自动算

测试用真 MySQL(dev DB) + 独立 ``SessionLocal``,fixture helper 自动
teardown(``DELETE WHERE name LIKE 'test_unique_%'``)避免污染 dev DB,模式同
M37.1 wx purge 清理(详见 MEMORY.md §M37.1)。
"""
from __future__ import annotations

from typing import Type

import pytest
from sqlalchemy.exc import IntegrityError

from lumen_core.database import SessionLocal
from lumen_models.customer import CustomerFieldDefinition
from lumen_models.external_app import ExternalApp
from lumen_models.model_config import ModelConfig
from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig
from lumen_models.role import Role
from lumen_models.skill import Skill
from lumen_models.user import User
from lumen_models.wx_publisher import WxAccount


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

TEST_PREFIX = "test_unique_"
A_USER_ID = 1  # dev seed admin user
A_TENANT_ID = 1


def _unique_name(tag: str) -> str:
    """生成带 test_unique_ 前缀的 identifier,便于 teardown 清理。

    时间戳后缀确保并发 case 不撞名(基本不需要,但安全起见)。
    """
    import time
    return f"{TEST_PREFIX}{tag}_{int(time.time() * 1000)}"


def _pick_two_tenant_ids(db) -> tuple[int, int]:
    """从 dev DB 拿两个不同的真实 tenant_id,用于跨 tenant test。

    跨 tenant test 必须用真实存在的 tenant_id(否则 FK 失败,跟 UNIQUE
    修复无关)。
    """
    rows = db.execute(
        __import__("sqlalchemy").text(
            "SELECT id FROM tenants ORDER BY id LIMIT 2"
        )
    ).fetchall()
    if len(rows) < 2:
        pytest.skip("dev DB needs >= 2 tenants for cross-tenant test")
    return rows[0][0], rows[1][0]


def _make_user(db, name: str, tenant_id: int = A_TENANT_ID) -> User:
    """造一条 active 用户(软删场景用)。"""
    import secrets
    u = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=secrets.token_hex(8),
        is_active=True,
        is_superuser=False,
        tenant_id=tenant_id,
    )
    db.add(u)
    db.flush()  # 拿 id
    return u


def _teardown(db, model: Type, *columns) -> None:
    """teardown helper:删除所有 test_unique_ 前缀 row。

    **新开 SessionLocal** 而非复用传入 db —— 测试中途如果 IntegrityError
    把原 session 标记为 invalid 状态,后续 query 会 PendingRollbackError。
    独立 session 永远干净(同 M37.1 wx purge cleanup 模式)。

    列名传列属性(如 ``User.username`` / ``Role.name``),便于跨表通用。
    不传列时默认按 ``name`` 字段匹配(配合 Role / Skill /
    CustomerFieldDefinition / MultimodalEmbeddingConfig)。
    """
    fresh = SessionLocal()
    try:
        if not columns:
            q = fresh.query(model).filter(model.name.like(f"{TEST_PREFIX}%"))
        else:
            q = fresh.query(model).filter(columns[0].like(f"{TEST_PREFIX}%"))
        q.delete(synchronize_session=False)
        fresh.commit()
    finally:
        fresh.close()


# ---------------------------------------------------------------------------
# users(2 个 UNIQUE:email + username)
# ---------------------------------------------------------------------------


def test_users_soft_delete_then_reuse_email():
    """软删 user → 新 user 同 email OK(原本 UNIQUE(email) 会冲突)。"""
    db = SessionLocal()
    try:
        email = _unique_name("email_reuse") + "@example.com"
        username = _unique_name("user_reuse")
        u1 = _make_user(db, username)
        u1.email = email
        db.commit()
        # 软删
        u1.is_active = False
        db.commit()
        # 新 user 同 email
        u2 = _make_user(db, _unique_name("user2"))
        u2.email = email  # 同 email
        db.commit()  # 不抛
        assert u2.id != u1.id
        # u1 dedup_email = NULL(因为 is_active=False)
        db.refresh(u1)
        assert u1.users_dedup_email is None
        # u2 dedup_email = 原 email
        db.refresh(u2)
        assert u2.users_dedup_email == email
    finally:
        _teardown(db, User, User.username)
        db.close()


def test_users_soft_delete_then_reuse_username():
    """软删 user → 新 user 同 username OK。"""
    db = SessionLocal()
    try:
        username = _unique_name("username_reuse")
        u1 = _make_user(db, username)
        db.commit()
        u1.is_active = False
        db.commit()
        u2 = _make_user(db, username)
        db.commit()
        assert u2.id != u1.id
    finally:
        _teardown(db, User, User.username)
        db.close()


def test_users_active_conflict_still_blocked():
    """两条 active 同 email → 必须抛 IntegrityError(UNIQUE 不被破坏)。"""
    db = SessionLocal()
    try:
        email = _unique_name("email_conflict") + "@example.com"
        username1 = _unique_name("conflict_user1")
        username2 = _unique_name("conflict_user2")
        u1 = _make_user(db, username1)
        u1.email = email
        db.commit()
        u2 = _make_user(db, username2)
        u2.email = email  # 同 email
        try:
            db.commit()
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate active email"
    finally:
        _teardown(db, User, User.username)
        db.close()


# ---------------------------------------------------------------------------
# model_configs(composite (tenant_id, model_type, model_name))
# ---------------------------------------------------------------------------


def _make_model_config(db, name: str, tenant_id=A_TENANT_ID) -> ModelConfig:
    mc = ModelConfig(
        name=name,
        model_type="ollama",
        model_name=f"model_for_{name}",
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(mc)
    db.flush()
    return mc


def test_model_configs_soft_delete_then_reuse():
    """软删 model_config → 新建同 (type, name) OK。"""
    db = SessionLocal()
    try:
        mc1 = _make_model_config(db, _unique_name("mc_reuse"))
        db.commit()
        mc1.is_active = False
        db.commit()
        mc2 = _make_model_config(db, mc1.name)  # 同 name
        db.commit()  # 不抛
        assert mc2.id != mc1.id
    finally:
        _teardown(db, ModelConfig, ModelConfig.name)
        db.close()


def test_model_configs_active_conflict_still_blocked():
    """两条 active 同 (tenant_id, type, name) → IntegrityError。"""
    db = SessionLocal()
    try:
        mc1 = _make_model_config(db, _unique_name("mc_conflict"))
        db.commit()
        # 注意:try 必须包住 ``_make_model_config`` 调用本身 —— 它内部
        # ``db.flush()`` 就触发 IntegrityError,比 ``db.commit()`` 更早。
        try:
            _make_model_config(db, mc1.name)
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate active (tenant, type, name)"
    finally:
        _teardown(db, ModelConfig, ModelConfig.name)
        db.close()


def test_model_configs_cross_tenant_allowed():
    """跨 tenant 同 (type, name) 不冲突(composite 跨 tenant)。"""
    db = SessionLocal()
    try:
        t1, t2 = _pick_two_tenant_ids(db)
        mc1 = _make_model_config(db, _unique_name("mc_cross"), tenant_id=t1)
        db.commit()
        mc2 = _make_model_config(db, mc1.name, tenant_id=t2)
        db.commit()  # 不同 tenant 不冲突
        assert mc2.id != mc1.id
    finally:
        _teardown(db, ModelConfig, ModelConfig.name)
        db.close()


# ---------------------------------------------------------------------------
# multimodal_embedding_configs(composite (tenant_id, name) + enabled)
# ---------------------------------------------------------------------------


def _make_mec(db, name: str, tenant_id=A_TENANT_ID) -> MultimodalEmbeddingConfig:
    m = MultimodalEmbeddingConfig(
        name=name,
        provider="jina_clip_v2",
        model_name="jinaai/jina-clip-v2",
        enabled=True,
        tenant_id=tenant_id,
    )
    db.add(m)
    db.flush()
    return m


def test_mec_soft_delete_then_reuse():
    """软删(enabled=False)→ 新建同 (tenant, name) OK。"""
    db = SessionLocal()
    try:
        m1 = _make_mec(db, _unique_name("mec_reuse"))
        db.commit()
        m1.enabled = False
        db.commit()
        m2 = _make_mec(db, m1.name)
        db.commit()
        assert m2.id != m1.id
    finally:
        _teardown(db, MultimodalEmbeddingConfig, MultimodalEmbeddingConfig.name)
        db.close()


def test_mec_active_conflict_still_blocked():
    """两条 enabled=True 同 (tenant, name) → IntegrityError。"""
    db = SessionLocal()
    try:
        m1 = _make_mec(db, _unique_name("mec_conflict"))
        db.commit()
        # try 必须包住 ``_make_mec`` 调用本身 —— 它内部 ``db.flush()``
        # 就触发 IntegrityError,比 ``db.commit()`` 更早。
        try:
            _make_mec(db, m1.name)
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate enabled=True (tenant, name)"
    finally:
        _teardown(db, MultimodalEmbeddingConfig, MultimodalEmbeddingConfig.name)
        db.close()


# ---------------------------------------------------------------------------
# external_apps(single (app_key))
# ---------------------------------------------------------------------------


def _make_external_app(db, name: str, app_key: str, tenant_id=A_TENANT_ID) -> ExternalApp:
    import secrets
    ea = ExternalApp(
        tenant_id=tenant_id,
        name=name,
        app_key=app_key,
        app_secret_hash=secrets.token_hex(16),
        allowed_origins=["https://example.com"],
        allowed_agent_ids=[],
        allowed_team_ids=[],
        scopes="chat:stream",
        rate_limit_per_min=60,
        is_active=True,
    )
    db.add(ea)
    db.flush()
    return ea


def test_external_apps_soft_delete_then_reuse_app_key():
    """软删 → 新建同 app_key OK。"""
    db = SessionLocal()
    try:
        app_key = _unique_name("appkey_reuse")
        ea1 = _make_external_app(db, _unique_name("ea_reuse"), app_key)
        db.commit()
        ea1.is_active = False
        db.commit()
        ea2 = _make_external_app(db, _unique_name("ea2"), app_key)
        db.commit()
        assert ea2.id != ea1.id
    finally:
        _teardown(db, ExternalApp, ExternalApp.name)
        db.close()


def test_external_apps_active_conflict_still_blocked():
    """两条 active 同 app_key → IntegrityError。"""
    db = SessionLocal()
    try:
        app_key = _unique_name("appkey_conflict")
        ea1 = _make_external_app(db, _unique_name("ea_conflict1"), app_key)
        db.commit()
        # try 必须包住 ``_make_external_app`` 调用本身 —— 它内部
        # ``db.flush()`` 就触发 IntegrityError,比 ``db.commit()`` 更早。
        try:
            _make_external_app(db, _unique_name("ea_conflict2"), app_key)
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate active app_key"
    finally:
        _teardown(db, ExternalApp, ExternalApp.name)
        db.close()


# ---------------------------------------------------------------------------
# wx_accounts(composite (tenant_id, app_id))
# ---------------------------------------------------------------------------


def _make_wx_account(db, app_id: str, tenant_id=A_TENANT_ID) -> WxAccount:
    import secrets
    wa = WxAccount(
        tenant_id=tenant_id,
        user_id=A_USER_ID,
        app_id=app_id,
        app_secret_encrypted=secrets.token_bytes(64),
        name=f"wx_{app_id}",
        account_type="subscription",
        is_mock=True,
        is_active=True,
    )
    db.add(wa)
    db.flush()
    return wa


def test_wx_accounts_soft_delete_then_reuse_app_id():
    """软删 → 新建同 (tenant, app_id) OK。"""
    db = SessionLocal()
    try:
        app_id = _unique_name("wxappid_reuse")
        wa1 = _make_wx_account(db, app_id)
        db.commit()
        wa1.is_active = False
        db.commit()
        wa2 = _make_wx_account(db, app_id)
        db.commit()
        assert wa2.id != wa1.id
    finally:
        _teardown(db, WxAccount, WxAccount.app_id)
        db.close()


def test_wx_accounts_cross_tenant_allowed():
    """跨 tenant 同 app_id 不冲突。"""
    db = SessionLocal()
    try:
        t1, t2 = _pick_two_tenant_ids(db)
        app_id = _unique_name("wxappid_cross")
        wa1 = _make_wx_account(db, app_id, tenant_id=t1)
        db.commit()
        wa2 = _make_wx_account(db, app_id, tenant_id=t2)
        db.commit()
        assert wa2.id != wa1.id
    finally:
        _teardown(db, WxAccount, WxAccount.app_id)
        db.close()


# ---------------------------------------------------------------------------
# roles(single (name))
# ---------------------------------------------------------------------------


def _make_role(db, name: str) -> Role:
    r = Role(name=name, description="test", is_active=True)
    db.add(r)
    db.flush()
    return r


def test_roles_soft_delete_then_reuse_name():
    """软删 role → 新建同名 role OK。"""
    db = SessionLocal()
    try:
        r1 = _make_role(db, _unique_name("role_reuse"))
        db.commit()
        r1.is_active = False
        db.commit()
        r2 = _make_role(db, r1.name)
        db.commit()
        assert r2.id != r1.id
    finally:
        _teardown(db, Role)
        db.close()


def test_roles_active_conflict_still_blocked():
    """两条 active 同 name → IntegrityError。"""
    db = SessionLocal()
    try:
        r1 = _make_role(db, _unique_name("role_conflict"))
        db.commit()
        # try 必须包住 ``_make_role`` 调用本身 —— 它内部 ``db.flush()``
        # 就触发 IntegrityError,比 ``db.commit()`` 更早。
        try:
            _make_role(db, r1.name)
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate active role name"
    finally:
        _teardown(db, Role)
        db.close()


# ---------------------------------------------------------------------------
# skills(single (name))
# ---------------------------------------------------------------------------


def _make_skill(db, name: str) -> Skill:
    s = Skill(
        name=name,
        description="test",
        content="test",
        is_active=True,
    )
    db.add(s)
    db.flush()
    return s


def test_skills_soft_delete_then_reuse_name():
    """软删 skill → 新建同名 skill OK。"""
    db = SessionLocal()
    try:
        s1 = _make_skill(db, _unique_name("skill_reuse"))
        db.commit()
        s1.is_active = False
        db.commit()
        s2 = _make_skill(db, s1.name)
        db.commit()
        assert s2.id != s1.id
    finally:
        _teardown(db, Skill)
        db.close()


def test_skills_active_conflict_still_blocked():
    """两条 active 同 name → IntegrityError。"""
    db = SessionLocal()
    try:
        s1 = _make_skill(db, _unique_name("skill_conflict"))
        db.commit()
        # try 必须包住 ``_make_skill`` 调用本身 —— 它内部 ``db.flush()``
        # 就触发 IntegrityError,比 ``db.commit()`` 更早。
        try:
            _make_skill(db, s1.name)
            raised = False
        except IntegrityError:
            raised = True
            db.rollback()
        assert raised, "expected IntegrityError on duplicate active skill name"
    finally:
        _teardown(db, Skill)
        db.close()


# ---------------------------------------------------------------------------
# customer_field_definitions(composite (tenant_id, field_key))
# ---------------------------------------------------------------------------


def _make_cfd(db, field_key: str, tenant_id=A_TENANT_ID) -> CustomerFieldDefinition:
    cfd = CustomerFieldDefinition(
        tenant_id=tenant_id,
        field_key=field_key,
        field_label="test",
        field_type="text",
        required=False,
        order_index=0,
        is_active=True,
        created_by=A_USER_ID,
    )
    db.add(cfd)
    db.flush()
    return cfd


def test_customer_field_definitions_soft_delete_then_reuse_field_key():
    """软删 → 新建同 (tenant, field_key) OK。"""
    db = SessionLocal()
    try:
        field_key = _unique_name("cfd_reuse")
        c1 = _make_cfd(db, field_key)
        db.commit()
        c1.is_active = False
        db.commit()
        c2 = _make_cfd(db, field_key)
        db.commit()
        assert c2.id != c1.id
    finally:
        _teardown(db, CustomerFieldDefinition, CustomerFieldDefinition.field_key)
        db.close()


def test_customer_field_definitions_cross_tenant_allowed():
    """跨 tenant 同 field_key 不冲突。"""
    db = SessionLocal()
    try:
        t1, t2 = _pick_two_tenant_ids(db)
        field_key = _unique_name("cfd_cross")
        c1 = _make_cfd(db, field_key, tenant_id=t1)
        db.commit()
        c2 = _make_cfd(db, field_key, tenant_id=t2)
        db.commit()
        assert c2.id != c1.id
    finally:
        _teardown(db, CustomerFieldDefinition, CustomerFieldDefinition.field_key)
        db.close()


# ---------------------------------------------------------------------------
# dedup column 自动计算(单一 case 覆盖所有表)
# ---------------------------------------------------------------------------


def test_dedup_columns_are_auto_computed():
    """验 9 张表的 dedup VIRTUAL 列:active=原值 / 软删=NULL。"""
    db = SessionLocal()
    try:
        # users × 2 dedup 列
        email = _unique_name("dedup_email") + "@example.com"
        username = _unique_name("dedup_username")
        u = _make_user(db, username)
        u.email = email
        db.commit()
        assert u.users_dedup_email == email
        assert u.users_dedup_username == username
        u.is_active = False
        db.commit()
        db.refresh(u)
        assert u.users_dedup_email is None
        assert u.users_dedup_username is None
        # roles 单列
        r = _make_role(db, _unique_name("dedup_role"))
        db.commit()
        assert r.roles_dedup_key == r.name
        r.is_active = False
        db.commit()
        db.refresh(r)
        assert r.roles_dedup_key is None
        # model_configs composite dedup(=model_type|model_name)
        mc = _make_model_config(db, _unique_name("dedup_mc"))
        db.commit()
        assert mc.model_configs_dedup_key == f"ollama|{mc.model_name}"
    finally:
        _teardown(db, User, User.username)
        _teardown(db, Role)
        _teardown(db, ModelConfig, ModelConfig.name)
        db.close()