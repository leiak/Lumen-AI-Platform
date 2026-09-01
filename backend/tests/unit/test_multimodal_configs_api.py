"""M38.4 Step 5b: Multimodal Config CRUD API tests.

Mirror the ``test_models_endpoints`` style — import endpoint functions
directly and mock ``db`` / ``current_user`` so we don't need a running
FastAPI server or DB connection.

Key implementation notes for these tests:

- ``_fake_cfg`` builds a real ``MultimodalEmbeddingConfig`` (not a
  MagicMock) so ``model_validate`` from Pydantic reads the typed
  attributes and the response model serialises cleanly. MagicMock
  would fail validation because the schema has ``Literal[...]`` /
  ``datetime`` / etc fields.
- Patches target the source module path
  (``lumen_services.multimodal_embedders``) not the endpoint module,
  because endpoints ``from lumen_services.multimodal_embedders import
  ...`` inside the function body — patching the endpoint module path
  misses the local name binding.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig
from lumen_schemas.multimodal_embedding_config import (
    MultimodalEmbeddingConfigCreate,
    MultimodalEmbeddingConfigUpdate,
)


# --- helpers ---------------------------------------------------------------


def _admin_user(tenant_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = 1
    u.tenant_id = tenant_id
    u.is_superuser = True
    u.is_active = True
    return u


def _regular_user(tenant_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = 2
    u.tenant_id = tenant_id
    u.is_superuser = False
    u.is_active = True
    return u


def _fake_cfg(
    id_: int = 1,
    tenant_id=None,
    enabled: bool = True,
    dim: int | None = 1024,
    name: str | None = None,
    provider: str = "jina_clip_v2",
):
    """Build a ``SimpleNamespace`` shaped like a row.

    We can't use a real ``MultimodalEmbeddingConfig()`` because
    SQLAlchemy's mapper requires ``_sa_instance_state`` (set by
    ``Session.add``); constructing one outside a session raises
    ``AttributeError``. ``Mock(spec=...)`` doesn't work either —
    ``from_attributes=True`` walks ``__getattr__`` and ends up
    looking at MagicMock descriptors that Pydantic rejects.

    ``SimpleNamespace`` is the cleanest stand-in: real attributes
    that Pydantic can read with full type validation.
    """
    return SimpleNamespace(
        id=id_,
        name=name or f"fake-{id_}",
        description=None,
        provider=provider,
        model_name="jinaai/jina-clip-v2",
        config=None,
        base_url=None,
        api_key=None,
        enabled=enabled,
        is_default=False,
        dimension=dim,
        tenant_id=tenant_id,
        created_at=datetime(2026, 9, 1, 0, 0, 0),
        updated_at=datetime(2026, 9, 1, 0, 0, 0),
    )


# --- list ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_tenant_visible_rows():
    """``list`` runs the tenant-visible query and returns PaginatedResponse."""
    from lumen_api.v1.multimodal_configs import list_multimodal_configs

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.count.return_value = 2
    q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        _fake_cfg(1, tenant_id=None),
        _fake_cfg(2, tenant_id=1),
    ]

    with patch("lumen_api.v1.multimodal_configs._tenant_visible_query", return_value=q):
        result = await list_multimodal_configs(
            page=1, page_size=20, provider=None, enabled=None, is_default=None,
            current_user=_regular_user(), db=db,
        )

    assert result.total == 2
    assert len(result.data) == 2


@pytest.mark.asyncio
async def test_list_with_filters_chains_query():
    """``enabled`` / ``is_default`` / ``provider`` filters call ``.filter()``."""
    from lumen_api.v1.multimodal_configs import list_multimodal_configs

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.count.return_value = 0
    q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

    with patch("lumen_api.v1.multimodal_configs._tenant_visible_query", return_value=q):
        await list_multimodal_configs(
            page=1, page_size=10, provider="jina_clip_v2", enabled=True, is_default=False,
            current_user=_regular_user(), db=db,
        )

    assert q.filter.call_count >= 3


# --- get -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_404_when_not_visible():
    from fastapi import HTTPException

    from lumen_api.v1.multimodal_configs import get_multimodal_config

    db = MagicMock()
    q = MagicMock()
    # ``_tenant_visible_query`` returns ``q`` already filtered once
    # (by the tenant-visible clause). The endpoint then chains
    # ``.filter(id == config_id)`` → ``.first()``. We want both
    # ``filter()`` calls (the inside helper's + the endpoint's) to
    # resolve to the same chain so ``.first()`` returns None here.
    q.filter.return_value = q  # subsequent .filter() = same q
    q.first.return_value = None

    with patch("lumen_api.v1.multimodal_configs._tenant_visible_query", return_value=q):
        with pytest.raises(HTTPException) as exc:
            await get_multimodal_config(
                config_id=999, current_user=_regular_user(), db=db,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_returns_row_when_visible():
    from lumen_api.v1.multimodal_configs import get_multimodal_config

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = _fake_cfg(7)

    with patch("lumen_api.v1.multimodal_configs._tenant_visible_query", return_value=q):
        result = await get_multimodal_config(
            config_id=7, current_user=_regular_user(), db=db,
        )
    assert result.data.id == 7
    assert result.data.provider == "jina_clip_v2"


# --- create (admin) --------------------------------------------------------


@pytest.mark.asyncio
async def test_create_admin_sets_tenant_id_none_and_clears_defaults():
    """Admin create: ``tenant_id=NULL``, ``is_default=True`` clears others."""
    from lumen_api.v1.multimodal_configs import create_multimodal_config

    db = MagicMock()
    data = MultimodalEmbeddingConfigCreate(
        name="new-jina", provider="jina_clip_v2",
        model_name="jinaai/jina-clip-v2", is_default=True,
    )
    # The endpoint constructs an ORM instance, calls ``db.add`` then
    # ``db.refresh``. With MagicMock ``db.refresh`` is a no-op so the
    # autoincrement ``id`` / default ``created_at`` stay None — not a
    # realistic shape for ``model_validate``. Use a side_effect that
    # fills those three fields, mirroring what a real Session would
    # do after ``flush``.
    def fake_refresh(row):
        row.id = 42
        row.created_at = datetime(2026, 9, 1, 0, 0, 0)
        row.updated_at = datetime(2026, 9, 1, 0, 0, 0)
    db.refresh.side_effect = fake_refresh

    result = await create_multimodal_config(
        data=data, current_user=_admin_user(), db=db,
    )
    # UPDATE statement was issued to clear other defaults
    db.execute.assert_called_once()
    # The created row has tenant_id=None (multimodal configs are global builtin)
    added_obj = db.add.call_args[0][0]
    assert added_obj.tenant_id is None
    assert added_obj.name == "new-jina"
    assert result.data.id == 42
    assert result.data.name == "new-jina"


@pytest.mark.asyncio
async def test_create_admin_duplicate_name_raises_409():
    """UNIQUE constraint surfaces as 409."""
    from fastapi import HTTPException

    from lumen_api.v1.multimodal_configs import create_multimodal_config

    db = MagicMock()
    db.commit.side_effect = Exception(
        "(pymysql.err.IntegrityError) (1062, \"Duplicate entry 'foo' for key 'uq_mec_tenant_name'\")"
    )
    data = MultimodalEmbeddingConfigCreate(
        name="foo", provider="jina_clip_v2", model_name="x",
    )

    with pytest.raises(HTTPException) as exc:
        await create_multimodal_config(
            data=data, current_user=_admin_user(), db=db,
        )
    assert exc.value.status_code == 409
    db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_create_admin_validation_error_passes_through():
    """Non-uniqueness DB errors bubble up — we don't swallow them silently."""
    from lumen_api.v1.multimodal_configs import create_multimodal_config

    db = MagicMock()
    db.commit.side_effect = RuntimeError("connection lost")
    data = MultimodalEmbeddingConfigCreate(
        name="x", provider="jina_clip_v2", model_name="x",
    )

    with pytest.raises(RuntimeError, match="connection lost"):
        await create_multimodal_config(
            data=data, current_user=_admin_user(), db=db,
        )


# --- update (admin) --------------------------------------------------------


@pytest.mark.asyncio
async def test_update_invalidates_cache_on_embedder_affected_fields():
    """Changing ``provider`` / ``model_name`` / ``enabled`` / ``api_key``
    should drop the cached embedder so the next call rebuilds."""
    from lumen_api.v1.multimodal_configs import update_multimodal_config

    db = MagicMock()
    db.get.return_value = _fake_cfg(5)
    data = MultimodalEmbeddingConfigUpdate(provider="clip_base_32", enabled=True)

    with patch("lumen_services.multimodal_embedders.invalidate_multimodal_cache") as inv:
        result = await update_multimodal_config(
            config_id=5, data=data, current_user=_admin_user(), db=db,
        )
    inv.assert_called_once_with(5)
    assert result.data.id == 5


@pytest.mark.asyncio
async def test_update_does_not_invalidate_when_only_metadata_changes():
    """Changing ``name`` / ``description`` / ``is_default`` shouldn't
    touch the cached embedder."""
    from lumen_api.v1.multimodal_configs import update_multimodal_config

    db = MagicMock()
    db.get.return_value = _fake_cfg(5)
    data = MultimodalEmbeddingConfigUpdate(name="renamed", description="new desc")

    with patch("lumen_services.multimodal_embedders.invalidate_multimodal_cache") as inv:
        await update_multimodal_config(
            config_id=5, data=data, current_user=_admin_user(), db=db,
        )
    inv.assert_not_called()


@pytest.mark.asyncio
async def test_update_is_default_clears_other_defaults():
    """is_default=True on PUT clears others."""
    from lumen_api.v1.multimodal_configs import update_multimodal_config

    db = MagicMock()
    db.get.return_value = _fake_cfg(5, enabled=False)
    data = MultimodalEmbeddingConfigUpdate(is_default=True)

    await update_multimodal_config(
        config_id=5, data=data, current_user=_admin_user(), db=db,
    )
    db.execute.assert_called_once()


@pytest.mark.asyncio
async def test_update_404_when_missing():
    from fastapi import HTTPException

    from lumen_api.v1.multimodal_configs import update_multimodal_config

    db = MagicMock()
    db.get.return_value = None
    data = MultimodalEmbeddingConfigUpdate(name="x")

    with pytest.raises(HTTPException) as exc:
        await update_multimodal_config(
            config_id=999, data=data, current_user=_admin_user(), db=db,
        )
    assert exc.value.status_code == 404


# --- delete (admin) --------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_disables_config_when_no_kb_ref():
    """No KB references → enabled=False + cache invalidate."""
    from lumen_api.v1.multimodal_configs import delete_multimodal_config

    cfg = _fake_cfg(8)
    db = MagicMock()
    db.get.return_value = cfg
    # KB ref query chain: db.query → filter → first() → None
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("lumen_services.multimodal_embedders.invalidate_multimodal_cache") as inv:
        result = await delete_multimodal_config(
            config_id=8, current_user=_admin_user(), db=db,
        )
    # The fetched cfg was disabled
    assert cfg.enabled is False
    db.commit.assert_called_once()
    inv.assert_called_once_with(8)
    assert result.data is None  # SingleResponse(message=...) → data is None


@pytest.mark.asyncio
async def test_delete_422_when_kb_still_references():
    from fastapi import HTTPException

    from lumen_api.v1.multimodal_configs import delete_multimodal_config

    db = MagicMock()
    db.get.return_value = _fake_cfg(8)
    db.query.return_value.filter.return_value.first.return_value = (42,)  # KB id 42

    with pytest.raises(HTTPException) as exc:
        await delete_multimodal_config(
            config_id=8, current_user=_admin_user(), db=db,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_delete_404_when_missing():
    from fastapi import HTTPException

    from lumen_api.v1.multimodal_configs import delete_multimodal_config

    db = MagicMock()
    db.get.return_value = None

    with pytest.raises(HTTPException) as exc:
        await delete_multimodal_config(
            config_id=999, current_user=_admin_user(), db=db,
        )
    assert exc.value.status_code == 404


# --- POST /test ------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_endpoint_success_local_provider():
    """Successful probe: ``ok=True``, ``dim`` matches factory return."""
    from lumen_api.v1.multimodal_configs import test_multimodal_config

    db = MagicMock()

    fake_embedder = MagicMock()
    fake_embedder.dimension = 1024
    fake_embedder.is_stub = False

    with patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
        return_value=(fake_embedder, 1024),
    ):
        result = await test_multimodal_config(
            config_id=1, current_user=_admin_user(), db=db,
        )
    assert result.data.ok is True
    assert result.data.dim == 1024
    assert result.data.elapsed_ms is not None
    assert result.data.error is None


@pytest.mark.asyncio
async def test_test_endpoint_cloud_stub_surfaces_note():
    """Cloud stub: factory returns the embedder with ``is_stub=True``;
    the endpoint surfaces this in ``error`` so the admin knows to
    wire credentials / replace the stub."""
    from lumen_api.v1.multimodal_configs import test_multimodal_config

    db = MagicMock()

    fake_embedder = MagicMock()
    fake_embedder.dimension = 1536
    fake_embedder.is_stub = True

    with patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
        return_value=(fake_embedder, 1536),
    ):
        result = await test_multimodal_config(
            config_id=1, current_user=_admin_user(), db=db,
        )
    assert result.data.ok is True
    assert result.data.dim == 1536
    assert "cloud stub" in (result.data.error or "")


@pytest.mark.asyncio
async def test_test_endpoint_failure_returns_200_with_error():
    """Probe failures always return 200 + structured error, never 500.

    The admin UI needs a clean "what went wrong" answer — if the probe
    raised 500 the admin would see a generic error toast.
    """
    from lumen_api.v1.multimodal_configs import test_multimodal_config

    db = MagicMock()

    with patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
        side_effect=Exception("connection refused"),
    ):
        result = await test_multimodal_config(
            config_id=1, current_user=_admin_user(), db=db,
        )
    assert result.data.ok is False
    assert "connection refused" in result.data.error
