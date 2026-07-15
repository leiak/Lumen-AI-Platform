"""M32 公众号助手 - 账号管理 service.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.1 / §4.2

Responsibilities (CP1 scope):
- AppSecret 对称加密 (Fernet) + 列表项脱敏
- 账号 CRUD with multi-tenant 隔离 (row.tenant_id == current_user.tenant_id)
- ``access_token`` 中控缓存 — 2h TTL, 提前 5min 主动刷
- ``verify`` 端点的占位实现(真实 WeChatRealClient 在 T20 写)

注意 (T5 阶段):
- ``WechatClient`` Protocol 还没建 (T20 任务),所以 ``_fetch_access_token_from_wechat``
  抛 ``NotImplementedError``。 调用方 ``get_access_token`` 在 ``is_mock=False`` 时
  走这个分支也会冒泡 NotImplementedError — T20 之前这个分支仅是函数签名占位。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy.orm import Session

from lumen_core.config import settings
from lumen_models.user import User
from lumen_models.wx_publisher import WxAccount
from lumen_schemas.wx_publisher import WxAccountCreate, WxAccountUpdate

log = logging.getLogger(__name__)


# access_token 中控缓存策略 (spec §7.6)
ACCESS_TOKEN_TTL_SECONDS = 2 * 60 * 60  # 2 hours (微信官方 TTL)
ACCESS_TOKEN_REFRESH_LEAD_SECONDS = 5 * 60  # 提前 5 分钟主动刷新


def mask_app_secret(plain: str) -> str:
    """First 2 + "****" + last 2. Falls back gracefully for short
    strings so a 4-char input still renders as ``"ab****cd"``
    rather than indexing into a negative.
    """
    if len(plain) <= 4:
        # degenerate case: show first 2, mask, last 2 — for
        # brevity the whole short string still goes through
        head = plain[:2]
        tail = plain[-2:] if len(plain) >= 2 else ""
        return f"{head}****{tail}"
    return f"{plain[:2]}****{plain[-2:]}"


class WxAccountService:
    """账号管理业务逻辑。Multi-tenant 通过 ``current_user.tenant_id`` 隔离。"""

    # --- Fernet 加密 / 解密 ------------------------------------------------

    def _fernet(self) -> Fernet:
        """Build a Fernet from the configured key.

        ``settings.WX_PUBLISHER_FERNET_KEY`` is expected to be a
        32-byte url-safe base64 string in production. For dev
        convenience we also accept a raw passphrase and derive a
        deterministic Fernet key from it via SHA-256 — this lets
        the dev sentinel (``"dev-only-fernet-key-do-not-use-in-prod-32b"``)
        work out of the box without forcing ops to generate a real
        key just to start uvicorn.

        Production must override the env var with a real key (we
        detect that by checking if the value parses as Fernet input
        directly; if so, no derivation is applied).
        """
        import base64
        import hashlib

        raw = settings.WX_PUBLISHER_FERNET_KEY
        try:
            return Fernet(raw.encode())
        except ValueError:
            # Not a valid Fernet key — derive one deterministically
            # from the raw passphrase. SHA-256 → 32 bytes →
            # url-safe base64 → Fernet.
            #
            # SECURITY: this path runs whenever the env var is unset
            # or set to a non-Fernet string. In production the
            # operator MUST override WX_PUBLISHER_FERNET_KEY with a
            # real 32-byte url-safe base64 Fernet key (e.g. via
            # ``python -c "from cryptography.fernet import Fernet;
            # print(Fernet.generate_key())"``). Otherwise the
            # derived key is only as strong as the dev sentinel —
            # the WARNING below is a loud, idempotent reminder.
            log.warning(
                "WX_PUBLISHER_FERNET_KEY is not a valid Fernet key; "
                "deriving a deterministic key from the raw value via "
                "SHA-256 (dev-only). Set a real Fernet key in production "
                "(see app.core.config.WX_PUBLISHER_FERNET_KEY)."
            )
            digest = hashlib.sha256(raw.encode("utf-8")).digest()
            derived = base64.urlsafe_b64encode(digest)
            return Fernet(derived)

    def encrypt_app_secret(self, plain: str) -> bytes:
        """Encrypt the AppSecret for storage. Idempotency: same input
        produces different ciphertext each time (Fernet uses a random
        IV), so we never try to compare encrypted blobs directly.
        """
        return self._fernet().encrypt(plain.encode("utf-8"))

    def decrypt_app_secret(self, encrypted: bytes) -> str:
        """Decrypt for outbound calls. Raises ``InvalidToken`` on
        tampering or wrong key — callers should treat that as a 500
        (it means either the DB row was corrupted, the key was
        rotated, or someone hand-edited a row).
        """
        try:
            return self._fernet().decrypt(encrypted).decode("utf-8")
        except InvalidToken as e:
            log.error("AppSecret decrypt failed (key rotated? row tampered?): %s", e)
            raise

    @staticmethod
    def mask_app_secret(plain: str) -> str:
        """Thin class-level wrapper that delegates to the module-level
        function ``mask_app_secret`` — kept so callers using the
        service instance (``WxAccountService().mask_app_secret(...)``)
        continue to work, while module-level imports for tests /
        other services also work.
        """
        return mask_app_secret(plain)

    # --- CRUD --------------------------------------------------------------

    def create_account(
        self, db: Session, *, current_user: User, payload: WxAccountCreate
    ) -> WxAccount:
        """Create a new WxAccount, encrypt the AppSecret, write the row.

        Uniqueness on (tenant_id, app_id) is enforced by the DB
        UNIQUE index (``uk_wx_accounts_tenant_appid``). On
        IntegrityError we surface a 409 to the operator.
        """
        encrypted = self.encrypt_app_secret(payload.app_secret)
        ip_text = json.dumps(payload.ip_whitelist) if payload.ip_whitelist else None
        row = WxAccount(
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            app_id=payload.app_id,
            app_secret_encrypted=encrypted,
            name=payload.name,
            account_type=payload.account_type,
            is_mock=payload.is_mock,
            ip_whitelist=ip_text,
            is_active=True,
        )
        db.add(row)
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            log.warning("create_account: commit failed (likely dup app_id): %s", e)
            raise HTTPException(409, "AppID already exists in this tenant")
        db.refresh(row)
        return row

    def get_account(
        self, db: Session, *, current_user: User, account_id: int
    ) -> WxAccount:
        """Load a WxAccount scoped to ``current_user.tenant_id``.

        Returns 404 (NOT 403) for cross-tenant access — leaking the
        existence of another tenant's resource would be an IDOR
        information leak. This is the same pattern as
        ``external_apps.py`` and M21 ``agent_rag``.
        """
        row = db.query(WxAccount).filter(
            WxAccount.id == account_id,
            WxAccount.tenant_id == current_user.tenant_id,
        ).first()
        if not row:
            raise HTTPException(404, "Account not found")
        return row

    def list_accounts(
        self, db: Session, *, current_user: User,
        page: int = 1, page_size: int = 20,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[WxAccount], int]:
        """Paginated list. ``is_active`` filter is optional and lets
        the operator hide deactivated accounts in the list view.
        """
        q = db.query(WxAccount).filter(WxAccount.tenant_id == current_user.tenant_id)
        if is_active is not None:
            q = q.filter(WxAccount.is_active == is_active)
        total = q.count()
        q = q.order_by(WxAccount.created_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def update_account(
        self, db: Session, *, current_user: User, account_id: int,
        payload: WxAccountUpdate,
    ) -> WxAccount:
        """Local update of the operator-editable fields.

        ``app_id`` / ``app_secret_encrypted`` are intentionally NOT
        editable here — secret rotation goes through a dedicated
        endpoint in V2 (see spec §4.2 + WxAccountUpdate comment).
        ``is_mock`` toggling is allowed but the operator is
        encouraged (by the UI) to verify first.
        """
        row = self.get_account(db, current_user=current_user, account_id=account_id)
        if payload.name is not None:
            row.name = payload.name
        if payload.is_active is not None:
            row.is_active = payload.is_active
        if payload.ip_whitelist is not None:
            row.ip_whitelist = json.dumps(payload.ip_whitelist)
        if payload.is_mock is not None:
            row.is_mock = payload.is_mock
        db.commit()
        db.refresh(row)
        return row

    def delete_account(
        self, db: Session, *, current_user: User, account_id: int
    ) -> None:
        """Soft-delete: flip ``is_active`` to False.

        We do NOT hard-delete because:
        1. ``wx_publish_records.account_id`` is ON DELETE RESTRICT —
           the audit trail must stay intact.
        2. ``wx_drafts.account_id`` is ON DELETE SET NULL — drafts
           would orphan if we hard-deleted, which loses the
           user-visible "bound to which account" history.
        Soft-delete (is_active=False) is the right MVP behavior;
        V2 may add a hard-delete that first nils out the FKs.
        """
        row = self.get_account(db, current_user=current_user, account_id=account_id)
        row.is_active = False
        db.commit()

    # --- access_token 中控缓存 (spec §7.6) ----------------------------------

    def get_access_token(
        self, db: Session, *, current_user: User, account_id: int,
        force_refresh: bool = False,
    ) -> str:
        """Return a valid access_token for the account, refreshing
        proactively when within 5min of expiry, or when ``force_refresh``
        is set.

        Mock accounts short-circuit to a stable sentinel string.
        Real accounts (T20) will call WechatRealClient.get_access_token;
        for CP1 we raise NotImplementedError to make the missing
        dependency explicit.
        """
        account = self.get_account(db, current_user=current_user, account_id=account_id)
        now = datetime.utcnow()

        if account.is_mock:
            # Stable per-account mock token — same value every time
            # so dev can correlate across log lines.
            return f"mock_access_token_{account.id}"

        if not force_refresh and account.access_token and account.access_token_expires_at:
            refresh_at = account.access_token_expires_at - timedelta(
                seconds=ACCESS_TOKEN_REFRESH_LEAD_SECONDS
            )
            if now < refresh_at:
                return account.access_token

        # Cold path — need to call Wechat API. T20 wires this up.
        token, expires_at = self._fetch_access_token_from_wechat(account)
        account.access_token = token
        account.access_token_expires_at = expires_at
        account.last_verified_at = now
        db.commit()
        db.refresh(account)
        return token

    def _fetch_access_token_from_wechat(
        self, account: WxAccount,
    ) -> Tuple[str, datetime]:
        """T20 placeholder: the real client (WechatRealClient) will
        GET ``https://api.weixin.qq.com/cgi-bin/token`` and return
        ``(token, expires_at)``.

        For CP1 we raise NotImplementedError so callers fail loudly
        rather than silently returning a stale cached token.
        """
        raise NotImplementedError(
            "WechatRealClient not yet implemented (T20); "
            "set account.is_mock=True or use a real AppID via the UI once T20 ships."
        )

    # --- verify (POST /accounts/{id}/verify) -------------------------------

    def verify_account(
        self, db: Session, *, current_user: User, account_id: int,
    ) -> dict:
        """Validate the AppID/AppSecret by asking WeChat for a fresh
        access_token.

        For mock accounts we skip the network call and mark the
        account as "verified now". For real accounts this delegates
        to ``get_access_token`` (which in turn raises
        NotImplementedError until T20 ships).
        """
        account = self.get_account(db, current_user=current_user, account_id=account_id)
        now = datetime.utcnow()
        if account.is_mock:
            account.last_verified_at = now
            db.commit()
            return {
                "account_id": account.id,
                "valid": True,
                "message": "Mock account — verification skipped",
                "verified_at": now,
            }
        # Real path — this will raise NotImplementedError until T20
        # lands. The endpoint will surface that as a 500 to the UI.
        try:
            self.get_access_token(db, current_user=current_user, account_id=account_id, force_refresh=True)
            return {
                "account_id": account.id,
                "valid": True,
                "message": "Verified",
                "verified_at": now,
            }
        except NotImplementedError as e:
            log.warning("verify_account: %s", e)
            raise HTTPException(501, "WechatRealClient not implemented (T20 pending)")
