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
    # (is_chat + is_embedding + is_active) — assert it called filter
    # at least 3x. Model configs are GLOBAL (tenant_id NULL is allowed)
    # so no tenant-scope clause is added; this is M13's design.
    assert query.filter.call_count >= 3, (
        f"Expected >=3 filter() calls (is_chat + is_embedding + is_active), "
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

    # Only is_active applied (= 1 filter call). Model configs are
    # GLOBAL so no tenant-scope clause; is_chat NOT applied.
    assert query.filter.call_count == 1, (
        f"Expected exactly 1 filter() call (is_active only), "
        f"got {query.filter.call_count}. The is_chat clause must NOT be "
        f"applied when the caller doesn't pass is_chat."
    )


@pytest.mark.asyncio
async def test_list_models_coerces_null_temperature_max_tokens_timeout():
    """Workflow designer 500 fix: 历史 row 允许 temperature/max_tokens/timeout
    为 NULL(`model_configs` 三列 nullable=True,早期 fixture 直插 SQL 跳过
    ORM 默认值),Pydantic 严格 float/int 校验 None 会让 GET /models/ 整
    endpoint 500。Schema validator 把 None 兜底成 Field 默认值(0.7/4096/120),
    验证 model_validate 不再 500,响应保持类型对齐。
    """
    from datetime import datetime
    from lumen_schemas.model_config import ModelConfigResponse

    # 模拟 ORM row:三列都是 None,is_default 也为 None(双重覆盖)
    fake_row = MagicMock()
    fake_row.id = 7
    fake_row.name = "legacy-row"
    fake_row.model_type = "ollama"
    fake_row.model_name = "qwen2.5:7b"
    fake_row.base_url = None
    fake_row.api_key = None
    fake_row.api_version = None
    fake_row.temperature = None
    fake_row.max_tokens = None
    fake_row.timeout = None
    fake_row.is_default = None
    fake_row.is_active = True
    fake_row.tenant_id = 1
    fake_row.created_at = datetime(2026, 1, 1)
    fake_row.updated_at = datetime(2026, 1, 1)
    fake_row.is_chat = True
    fake_row.is_embedding = False
    fake_row.is_image_generation = False
    fake_row.is_tts = False
    fake_row.is_subtitle_generation = False
    fake_row.is_video = False
    fake_row.description = None

    # model_validate 不能再炸 ValidationError;None 已被 validator 兜底
    parsed = ModelConfigResponse.model_validate(fake_row)
    assert parsed.temperature == 0.7
    assert parsed.max_tokens == 4096
    assert parsed.timeout == 120
    assert parsed.is_default is False  # 跟 _coerce_is_default 同模式
    assert parsed.id == 7

    # 同样的兜底对 endpoint list_models 也得生效:模拟 list endpoint 调
    # ModelConfigResponse.model_validate(m) 时不抛。
    from lumen_api.v1.models import list_models

    db = MagicMock()
    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.count.return_value = 1
    # list_models 真实链:query.order_by(...).slice(start, end).all()
    # 现有两个 is_chat 测试只验证 filter 链路所以漏了 order_by/slice 链,
    # 我们要拿到 row 让 ModelConfigResponse.model_validate 真跑一遍。
    query.order_by.return_value = query
    query.slice.return_value.all.return_value = [fake_row]

    current_user = MagicMock(tenant_id=1)

    result = await list_models(
        page=1, page_size=10,
        is_active=True,
        current_user=current_user, db=db,
    )
    # endpoint 没炸,信封 round-trip 干净
    assert result.total == 1
    assert result.data[0].temperature == 0.7
    assert result.data[0].max_tokens == 4096
    assert result.data[0].timeout == 120

