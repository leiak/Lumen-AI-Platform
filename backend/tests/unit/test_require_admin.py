import pytest
from fastapi import HTTPException


def _admin_user():
    from lumen_models.user import User
    u = User()
    u.id = 1
    u.username = "root"
    u.is_superuser = True
    u.is_active = True
    return u


def _normal_user():
    from lumen_models.user import User
    u = User()
    u.id = 2
    u.username = "alice"
    u.is_superuser = False
    u.is_active = True
    return u


def test_require_admin_passes_for_superuser():
    from lumen_api.v1.auth import require_admin
    u = _admin_user()
    # 返回的应当是传入的同一对象(透传),防止未来误改成 model_validate
    assert require_admin(u) is u


def test_require_admin_rejects_normal_user():
    from lumen_api.v1.auth import require_admin
    with pytest.raises(HTTPException) as exc:
        require_admin(_normal_user())
    assert exc.value.status_code == 403


def test_require_admin_rejects_when_is_superuser_not_set():
    """不显式设 is_superuser —— 模拟老 DB 行缺字段,getattr 回退 False 路径"""
    from lumen_models.user import User
    from lumen_api.v1.auth import require_admin
    u = User()
    # 不设 u.is_superuser,也不 del;让 getattr 走 default=False
    with pytest.raises(HTTPException) as exc:
        require_admin(u)
    assert exc.value.status_code == 403


def test_require_admin_rejects_inactive_superuser():
    from lumen_api.v1.auth import require_admin
    u = _admin_user()
    u.is_active = False
    with pytest.raises(HTTPException) as exc:
        require_admin(u)
    assert exc.value.status_code == 403
