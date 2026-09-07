"""2.1 C.4:STORAGE_BACKEND runtime toggle 测试。

覆盖:
- ``toggle_storage_backend('local')`` 切到 local backend
- ``toggle_storage_backend('s3')`` 切到 s3 (mock AWS moto)
- invalid backend name 抛 ValueError
- ``apply_storage_config_overrides`` 跳 None,保留旧值;设非 None 覆盖
- 集成:endpoint 调通整个 toggle 流程(monkeypatch auth + reset)
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _reset_storage_singleton():
    """每个 test 前后 reset singleton 避免污染。"""
    from lumen_services.storage import reset_storage_backend
    reset_storage_backend()
    yield
    reset_storage_backend()


@pytest.fixture(autouse=True)
def _clean_storage_env(monkeypatch):
    """清掉所有 STORAGE_* + S3_* env,test 自己按需 set。"""
    for var in (
        "STORAGE_BACKEND", "STORAGE_LOCAL_ROOT",
        "S3_BUCKET", "S3_ENDPOINT", "S3_REGION",
        "S3_ACCESS_KEY", "S3_SECRET_KEY",
        "S3_USE_SSL", "S3_PATH_STYLE", "S3_PRESIGNED_URL_EXPIRY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ---- apply_storage_config_overrides ----


def test_apply_overrides_skips_none_values(monkeypatch):
    """None 值跳过,不覆盖现有 env。"""
    monkeypatch.setenv("S3_BUCKET", "existing-bucket")
    from lumen_services.storage import apply_storage_config_overrides

    applied = apply_storage_config_overrides(
        {"S3_BUCKET": None, "S3_REGION": "us-east-1"},
    )
    # None 跳过 → 不返 applied entry
    assert "S3_BUCKET" not in applied
    # 新值覆盖
    assert "S3_REGION" in applied
    assert applied["S3_REGION"] == "<unset>"
    # env 被正确设
    import os
    assert os.environ["S3_BUCKET"] == "existing-bucket"
    assert os.environ["S3_REGION"] == "us-east-1"


def test_apply_overrides_records_previous_values(monkeypatch):
    """每个被覆盖的 key 记录之前的值,给 caller log / 回滚用。"""
    monkeypatch.setenv("S3_BUCKET", "old-bucket")
    from lumen_services.storage import apply_storage_config_overrides

    applied = apply_storage_config_overrides({"S3_BUCKET": "new-bucket"})
    assert applied == {"S3_BUCKET": "old-bucket"}


def test_apply_overrides_empty_dict_noop(monkeypatch):
    """空 dict / None 不动 env。"""
    from lumen_services.storage import apply_storage_config_overrides

    assert apply_storage_config_overrides(None) == {}
    assert apply_storage_config_overrides({}) == {}


# ---- toggle_storage_backend ----


def test_toggle_to_local_backend(tmp_path, monkeypatch):
    """``backend=local`` 切到 LocalBackend,根目录走默认或 STORAGE_LOCAL_ROOT。"""
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    from lumen_services.storage import toggle_storage_backend, get_storage_backend
    from lumen_services.storage.local_backend import LocalBackend

    backend = toggle_storage_backend("local")
    assert isinstance(backend, LocalBackend)
    assert get_storage_backend().backend_name == "local"

    # 同一进程再切一次仍 idempotent
    backend2 = toggle_storage_backend("local")
    assert backend2.backend_name == "local"


def test_toggle_unknown_backend_raises_value_error():
    """Unknown backend name 抛 ValueError,singleton 不被破坏。"""
    from lumen_services.storage import toggle_storage_backend, get_storage_backend

    with pytest.raises(ValueError, match="unknown backend"):
        toggle_storage_backend("not_a_backend")
    # singleton 仍是未初始化 → 下次 get 返默认 local
    backend = get_storage_backend()
    assert backend.backend_name == "local"


def test_toggle_uppercase_backend_name(monkeypatch):
    """backend 名大小写容错。"""
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", "/tmp")
    from lumen_services.storage import toggle_storage_backend

    backend = toggle_storage_backend("LOCAL")
    assert backend.backend_name == "local"


def test_toggle_to_s3_requires_credentials(monkeypatch):
    """``backend=s3`` 但没设 S3_* env → S3BackendError actionable。"""
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_ACCESS_KEY", raising=False)
    monkeypatch.delenv("S3_SECRET_KEY", raising=False)
    from lumen_services.storage import toggle_storage_backend
    from lumen_services.storage.s3_backend import S3BackendError

    with pytest.raises(S3BackendError, match="S3_BUCKET"):
        toggle_storage_backend("s3")


def test_toggle_to_s3_success_with_moto(monkeypatch):
    """``backend=s3`` + mock AWS moto → 切到 S3Backend,health_check 通。"""
    pytest.importorskip("boto3")
    pytest.importorskip("moto")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY", "k")
    monkeypatch.setenv("S3_SECRET_KEY", "s")

    import moto

    from lumen_services.storage import toggle_storage_backend
    from lumen_services.storage.s3_backend import S3Backend

    with moto.mock_aws():
        backend = toggle_storage_backend("s3")
        assert isinstance(backend, S3Backend)
        report = backend.health_check()
        assert report["backend"] == "s3"


# ---- endpoint 集成 ----


def test_endpoint_toggle_to_local_returns_info(tmp_path, monkeypatch):
    """``POST /api/v1/storage/backend {backend:'local'}`` → 200 + info。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))

    from lumen_main import app
    from lumen_api.v1.auth import get_current_user
    from lumen_models.user import User

    fake_admin = User(
        id=1, username="admin", email="a@x", tenant_id=1,
        is_superuser=True, is_active=True,
    )

    app.dependency_overrides[get_current_user] = lambda: fake_admin
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/storage/backend",
            json={"backend": "local"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["backend"] == "local"
        assert "latency_ms" in body["data"]
    finally:
        app.dependency_overrides.clear()


def test_endpoint_toggle_unknown_backend_returns_422():
    """``backend='not_a_backend'`` → 422(Pydantic Literal validation)。"""
    from fastapi.testclient import TestClient

    from lumen_main import app
    from lumen_api.v1.auth import get_current_user
    from lumen_models.user import User

    fake_admin = User(
        id=1, username="admin", email="a@x", tenant_id=1,
        is_superuser=True, is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/storage/backend",
            json={"backend": "foo"},
        )
        # Pydantic Literal validation kicks in BEFORE the handler runs,
        # so the response is 422 not 400 — both are valid FastAPI error
        # codes for bad request bodies.
        assert resp.status_code == 422, resp.text
        body = resp.json()
        # Detail is a list of validation errors
        assert "detail" in body
        assert "local" in str(body["detail"]) or "s3" in str(body["detail"])
    finally:
        app.dependency_overrides.clear()


def test_endpoint_toggle_to_s3_without_credentials_returns_400(monkeypatch):
    """``backend='s3'`` 没 creds → 400 S3BackendError 透传 detail。"""
    from fastapi.testclient import TestClient

    from lumen_main import app
    from lumen_api.v1.auth import get_current_user
    from lumen_models.user import User

    fake_admin = User(
        id=1, username="admin", email="a@x", tenant_id=1,
        is_superuser=True, is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/storage/backend",
            json={"backend": "s3"},
        )
        assert resp.status_code == 400, resp.text
        # 详情应该是 S3BackendError 消息
        assert "S3_BUCKET" in str(resp.json()["detail"])
    finally:
        app.dependency_overrides.clear()


def test_endpoint_toggle_with_config_overrides_applies_env(monkeypatch):
    """``config`` dict 设的 key 写到 env,然后触发 backend init。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("STORAGE_LOCAL_ROOT", "/tmp")

    from lumen_main import app
    from lumen_api.v1.auth import get_current_user
    from lumen_models.user import User

    fake_admin = User(
        id=1, username="admin", email="a@x", tenant_id=1,
        is_superuser=True, is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/v1/storage/backend",
            json={
                "backend": "local",
                "config": {"STORAGE_LOCAL_ROOT": "/tmp/lumen-toggle-test"},
            },
        )
        assert resp.status_code == 200, resp.text
        # env 应被覆盖
        import os
        assert os.environ["STORAGE_LOCAL_ROOT"] == "/tmp/lumen-toggle-test"
    finally:
        app.dependency_overrides.clear()


def test_endpoint_toggle_to_s3_success_returns_info(monkeypatch):
    """``backend='s3'`` + mock AWS moto → 200 + info,health_check 通过。"""
    pytest.importorskip("boto3")
    pytest.importorskip("moto")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY", "k")
    monkeypatch.setenv("S3_SECRET_KEY", "s")

    from fastapi.testclient import TestClient
    import boto3
    import moto

    from lumen_main import app
    from lumen_api.v1.auth import get_current_user
    from lumen_models.user import User

    fake_admin = User(
        id=1, username="admin", email="a@x", tenant_id=1,
        is_superuser=True, is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: fake_admin
    try:
        with moto.mock_aws():
            # moto 不自动建 bucket,HeadBucket 会 404 → endpoint 返 503。
            # 提前建好让 health_check 通。
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket="test-bucket")

            client = TestClient(app)
            resp = client.post(
                "/api/v1/storage/backend",
                json={"backend": "s3"},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["data"]["backend"] == "s3"
            assert body["data"]["ok"] is True
    finally:
        app.dependency_overrides.clear()


# ---- module import smoke ----


def test_storage_module_imports_clean():
    """module 导入 + schema 导入不抛。"""
    importlib.import_module("lumen_schemas.storage_backend")
    importlib.import_module("lumen_services.storage")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])