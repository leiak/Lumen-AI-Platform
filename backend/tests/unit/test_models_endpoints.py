"""Tests for the /api/v1/models/import-from-ollama and /bulk-create endpoints."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


@pytest.mark.asyncio
async def test_import_from_ollama_happy_path():
    """Successful /api/tags + /api/show response is enriched with capability flags."""
    from lumen_api.v1.models import import_from_ollama

    fake_tags = {
        "models": [
            {"name": "nomic-embed-text:latest", "size": 274_302_336, "modified_at": "2026-05-01T00:00:00Z"},
            {"name": "qwen2.5:7b", "size": 4_000_000_000, "modified_at": "2026-05-02T00:00:00Z"},
        ]
    }
    fake_show_nomic = {"capabilities": ["embedding"], "details": {"family": "nomic-bert"}}
    fake_show_qwen = {"capabilities": ["completion"], "details": {"family": "qwen2"}}

    async def fake_get(url, timeout=None):
        return MagicMock(json=lambda: fake_tags, raise_for_status=lambda: None)

    async def fake_post(url, json=None, timeout=None):
        name = (json or {}).get("name", "")
        body = fake_show_nomic if "nomic" in name else fake_show_qwen
        return MagicMock(json=lambda: body, raise_for_status=lambda: None)

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=fake_get)
    fake_client.post = AsyncMock(side_effect=fake_post)

    current_user = MagicMock()
    current_user.tenant_id = 1
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None  # no existing configs

    with patch("lumen_api.v1.models.httpx.AsyncClient", return_value=fake_client):
        result = await import_from_ollama(
            body=MagicMock(base_url=None), current_user=current_user, db=db,
        )

    assert result.data["reachable"] is True
    assert len(result.data["models"]) == 2
    nomic = next(m for m in result.data["models"] if "nomic" in m["name"])
    assert nomic["is_embedding_capable"] is True
    assert nomic["is_chat_capable"] is False
    qwen = next(m for m in result.data["models"] if "qwen" in m["name"])
    assert qwen["is_embedding_capable"] is False
    assert qwen["is_chat_capable"] is True


@pytest.mark.asyncio
async def test_import_from_ollama_unreachable():
    """If Ollama /api/tags fails, reachable=False and error_message is set."""
    from lumen_api.v1.models import import_from_ollama

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(side_effect=ConnectionError("connection refused"))

    with patch("lumen_api.v1.models.httpx.AsyncClient", return_value=fake_client):
        result = await import_from_ollama(
            body=MagicMock(base_url=None),
            current_user=MagicMock(tenant_id=1),
            db=MagicMock(),
        )
    assert result.data["reachable"] is False
    assert "error_message" in result.data


@pytest.mark.asyncio
async def test_bulk_create_creates_new_skips_duplicates():
    """bulk-create writes new configs, skips duplicates, reports per-row status."""
    from lumen_api.v1.models import bulk_create_models
    from lumen_schemas.model_config import ModelConfigCreate

    rows = [
        ModelConfigCreate(
            name="Ollama nomic",
            model_type="ollama",
            model_name="nomic-embed-text",
            is_chat=False, is_embedding=True,
        ),
        ModelConfigCreate(
            name="Duplicate",
            model_type="ollama",
            model_name="qwen2.5:7b",
            is_chat=True, is_embedding=False,
        ),
    ]

    # First call: no existing config for nomic → create.
    # Second call: existing config for qwen → skip.
    existing_cfg = MagicMock()
    existing_cfg.id = 99

    db = MagicMock()

    # The function calls db.query(ModelConfig).filter(...).first()
    # once per row. Track which row is being processed.
    call_count = {"n": 0}

    def query_filter_first(model):
        m = MagicMock()
        # First row (nomic): no existing → None
        # Second row (qwen): existing
        if call_count["n"] == 0:
            m.filter.return_value.first.return_value = None
        else:
            m.filter.return_value.first.return_value = existing_cfg
        call_count["n"] += 1
        return m

    db.query.side_effect = query_filter_first

    current_user = MagicMock(tenant_id=1)
    created = []

    def add(obj):
        obj.id = 1
        created.append(obj)

    db.add.side_effect = add

    result = await bulk_create_models(rows=rows, current_user=current_user, db=db)

    statuses = {r["requested_model_name"]: r["status"] for r in result.data["results"]}
    assert statuses["nomic-embed-text"] == "created"
    assert statuses["qwen2.5:7b"] == "skipped"


@pytest.mark.asyncio
async def test_list_models_filters_by_is_chat():
    """M31: GET /models/?is_chat=... must apply the is_chat filter.

    The new ``ChatModelSelect`` component hits this endpoint with
    ``is_chat=true&is_active=true``. This test asserts that the
    filter is wired into the query (i.e. ``query.filter`` is called
    at least once for each flag) and that the response envelope's
    ``total`` / ``page`` / ``page_size`` round-trip cleanly through
    the ``PaginatedResponse`` constructor (without validating the
    rows themselves, which is covered by the integration tests).
    """
    from lumen_api.v1.models import list_models

    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    # Each chained filter() returns the same query mock so multiple
    # .filter().filter().filter() chains all resolve to one object.
    query.filter.return_value = query
    query.count.return_value = 3
    # An empty rows list is fine for the filter-chain assertion; we
    # only need the chain shape, not row serialization (that's covered
    # by the integration tests against a real DB).
    query.slice.return_value.all.return_value = []

    current_user = MagicMock(tenant_id=1)

    result = await list_models(
        page=1, page_size=10,
        is_chat=True, is_embedding=False, is_active=True,
        current_user=current_user, db=db,
    )

    # The endpoint applied at least one filter clause per flag
    # (tenant scope + is_chat + is_embedding + is_active) — assert
    # it called filter at least 4x.
    assert query.filter.call_count >= 4, (
        f"Expected >=4 filter() calls (tenant + is_chat + is_embedding + is_active), "
        f"got {query.filter.call_count}"
    )

    # Response envelope round-trip is clean (the empty row list means
    # the per-row ModelConfigResponse.model_validate path is skipped,
    # which is fine for the filter-wiring contract we're verifying).
    assert result.total == 3
    assert result.page == 1
    assert result.page_size == 10


@pytest.mark.asyncio
async def test_list_models_omits_is_chat_filter_when_not_provided():
    """Sanity: ``is_chat`` is optional — omit it and the filter chain
    shouldn't carry the is_chat clause. We verify by counting filter()
    calls — passing only ``is_active=True`` should give 2 calls
    (tenant scope OR + is_active), not 3+ as the is_chat case above.
    """
    from lumen_api.v1.models import list_models

    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 0
    query.slice.return_value.all.return_value = []

    current_user = MagicMock(tenant_id=1)

    await list_models(
        page=1, page_size=10,
        is_active=True,
        current_user=current_user, db=db,
    )

    # tenant scope (OR clause = 1 filter call) + is_active = 2 calls.
    # (is_chat NOT applied.)
    assert query.filter.call_count == 2, (
        f"Expected exactly 2 filter() calls (tenant scope + is_active), "
        f"got {query.filter.call_count}. The is_chat clause must NOT be "
        f"applied when the caller doesn't pass is_chat."
    )

