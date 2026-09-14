"""Tests for ``lumen_services.auth_service.AuthService.authenticate_user``.

2026-09-14 dev 故障复盘:dev DB 有两条 username='admin' 的用户行
(id=1 hashed_password='x' 占位 + id=12 真实 admin),``authenticate_user``
用 ``.filter(...).first()`` 没有 ORDER BY,query plan 在不同 session
下随机命中其中一条 → 命中 id=1 时 passlib.exc.UnknownHashError → login
接口 500(本应 401)。

这条测试守住 ``ORDER BY id ASC`` 的稳定排序契约:多账号时永远
挑最小 id,而不是依赖 MySQL 任意一行扫描顺序。
"""
from unittest.mock import MagicMock, patch

from lumen_services.auth_service import AuthService


def _make_user(user_id: int, username: str, hashed: str | None,
               is_active: bool = True) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.username = username
    u.hashed_password = hashed
    u.is_active = is_active
    return u


def test_authenticate_picks_lowest_id_when_multiple_users_match():
    """同 username 撞车时,必须稳定选最小 id —— 否则小 id 那行如果
    hash 是占位或损坏,login 直接 500 而非预期的 401。
    """
    db = MagicMock()
    # query chain: db.query(User).filter(...).order_by(User.id.asc()).first()
    q = MagicMock()
    db.query.return_value = q
    q.filter.return_value = q
    q.order_by.return_value = q
    q.first.return_value = _make_user(1, "admin", "x")  # 占位 hash,坏

    # patch verify_password —— 用占位 'x' 调真 passlib 会抛
    # UnknownHashError 把整个测试搞崩。我们只关心 query chain 的
    # 调用顺序和 .order_by 是否被调用。
    with patch("lumen_services.auth_service.verify_password", return_value=False):
        result = AuthService.authenticate_user(db, "admin", "admin123")

    # result 应该是 None(verify 失败)—— 这就是"401 而非 500"的契约
    assert result is None
    # .order_by 必须被调用 —— 这是契约的核心,守住这条防止未来有人
    # 觉得"反正 .first() 也工作"把 ORDER BY 删了。
    assert q.order_by.called, (
        "authenticate_user 必须显式 ORDER BY id ASC,否则多账号时"
        "可能命中坏 hash 行(2026-09-14 dev 故障)。"
    )
    assert q.filter.called
    assert q.first.called
