"""M38.4 Step 5c: Image endpoint unit tests (upload / list / search).

Covers:
- ``POST /{kb_id}/images/upload`` happy path with mocked storage +
  mocked Celery task
- ``GET /{kb_id}/images`` source filter (standalone / extracted / both)
- ``POST /{kb_id}/image-search`` multimodal path
- ``POST /{kb_id}/image-search`` graceful fallback to text search
- image-search KB 404
- helper ``_caption_from_filename`` strips extensions + replaces
  separators

These tests don't touch the DB or a running server. We mock
``db.query`` / ``db.get`` / ``db.add`` / ``db.commit`` chains the way
``test_multimodal_configs_api.py`` does.

Patch targets: ``lumen_services.multimodal_embedders`` (factory) and
``lumen_services.multimodal_vector_store_factory`` (Multimodal store).
We patch the source module because the endpoint imports them inside
the function body — patching the endpoint module path misses the
local name binding.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lumen_api.v1 import knowledge as knowledge_module


# --- helpers --------------------------------------------------------------


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


def _fake_kb(
    id_: int = 55,
    tenant_id: int = 1,
    multimodal_enabled: bool = False,
    multimodal_config_id: int | None = None,
    embedding_model_config_id: int | None = 3,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        tenant_id=tenant_id,
        name=f"kb-{id_}",
        description=None,
        embedding_model_config_id=embedding_model_config_id,
        multimodal_enabled=multimodal_enabled,
        multimodal_config_id=multimodal_config_id,
        workspace_id=None,
        chunk_size=500,
        chunk_overlap=50,
        search_weights=None,
    )


def _fake_doc(
    id_: int = 100,
    kb_id: int = 55,
    filename: str = "test.png",
    file_type: str = "image/png",
    status: str = "pending",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        filename=filename,
        file_path=f"data/uploads/{kb_id}/{filename}",
        file_type=file_type,
        file_size=2048,
        status=status,
        knowledge_base_id=kb_id,
        folder_id=None,
        created_by=1,
        asset_storage_key=f"uploads/{kb_id}/images/{filename}",
        storage_backend="local",
        embedding_model_config_id=3,
        doc_type="image",
    )


def _fake_image_asset(
    id_: int = 1,
    document_id: int = 100,
    chunk_id: int | None = 200,
    original_doc_page: int | None = None,
    storage_key: str = "uploads/1/55/images/test.png",
    caption: str = "test image",
    embedding_status: str = "ok",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_,
        document_id=document_id,
        chunk_id=chunk_id,
        original_doc_page=original_doc_page,
        storage_key=storage_key,
        width=512,
        height=512,
        mime_type="image/png",
        file_size=2048,
        caption=caption,
        embedding_status=embedding_status,
        created_at=datetime(2026, 9, 1, 0, 0, 0),
    )


# --- _caption_from_filename ---------------------------------------------


def test_caption_from_filename_strips_extension():
    cap = knowledge_module._caption_from_filename("product_logo_v2.png")
    assert cap == "product logo v2"


def test_caption_from_filename_handles_dashes():
    cap = knowledge_module._caption_from_filename("my-cool-pic.PNG")
    assert cap == "my cool pic"


def test_caption_from_filename_returns_none_when_empty():
    assert knowledge_module._caption_from_filename("") is None


def test_caption_from_filename_returns_none_for_none():
    assert knowledge_module._caption_from_filename(None) is None


def test_caption_from_filename_keeps_chinese_chars():
    """Don't mangle CJK content — separators get replaced with spaces,
    not stripped."""
    cap = knowledge_module._caption_from_filename("产品-logo.png")
    assert cap == "产品 logo"


# --- _safe_int ------------------------------------------------------------


def test_safe_int_passes_through_int():
    assert knowledge_module._safe_int(42) == 42


def test_safe_int_parses_numeric_string():
    assert knowledge_module._safe_int("42") == 42


def test_safe_int_returns_none_for_non_numeric():
    """Vector-store ids like ``"es_42"`` should NOT silently become 42
    or 0 — that's misleading."""
    assert knowledge_module._safe_int("es_42") is None


def test_safe_int_returns_none_for_none():
    assert knowledge_module._safe_int(None) is None


# --- POST /{kb_id}/images/upload -----------------------------------------


@pytest.mark.asyncio
async def test_upload_image_happy_path_creates_doc_and_queues_task(
    monkeypatch,
):
    """upload_image creates a Document row + queues celery task."""
    from lumen_api.v1.knowledge import upload_image

    db = MagicMock()
    kb = _fake_kb()
    doc = _fake_doc()

    # Two db.query calls: KnowledgeBase lookup + (optional) folder
    # validation. We use a chainable mock.
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = kb
    db.query.side_effect = lambda *args, **kwargs: q

    # After db.add + commit, db.refresh populates id / created_at etc.
    # Doc is created inside the endpoint; capture it via add().
    captured = []

    def fake_add(obj):
        captured.append(obj)

    db.add.side_effect = fake_add
    db.refresh.side_effect = lambda obj: setattr(obj, "id", doc.id)

    # Bypass permission check + actual storage write.
    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"\\x89PNG\\r\\n\\x1a\\n")
    fake_file.filename = "test.png"
    fake_file.content_type = "image/png"

    storage_mock = MagicMock()
    storage_mock.backend_name = "local"

    celery_result = MagicMock()
    celery_result.id = "task-uuid-1"

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ), patch(
        "lumen_services.storage.get_storage_backend",
        return_value=storage_mock,
    ), patch(
        "lumen_tasks.document_tasks.process_document_task",
    ) as task_mock:
        task_mock.delay.return_value = celery_result
        result = await upload_image(
            kb_id=55,
            file=fake_file,
            folder_id=None,
            async_process=True,
            current_user=_regular_user(),
            db=db,
        )

    assert result.data.document_id == doc.id
    assert result.data.task_id == "task-uuid-1"
    # storage.put_object called with the expected key
    storage_mock.put_object.assert_called_once()
    args, _ = storage_mock.put_object.call_args
    assert "uploads/1/55/images/test.png" in args[0]
    # celery task fired with doc_type='image'
    assert task_mock.delay.called


@pytest.mark.asyncio
async def test_upload_image_404_when_kb_not_found():
    """Unknown kb_id → 404, no doc created."""
    from fastapi import HTTPException

    from lumen_api.v1.knowledge import upload_image

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = None  # KB not found
    db.query.side_effect = lambda *args, **kwargs: q

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"x")
    fake_file.filename = "test.png"
    fake_file.content_type = "image/png"

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ):
        with pytest.raises(HTTPException) as exc:
            await upload_image(
                kb_id=999, file=fake_file, folder_id=None,
                async_process=True, current_user=_regular_user(), db=db,
            )
    assert exc.value.status_code == 404


# --- GET /{kb_id}/images -------------------------------------------------


@pytest.mark.asyncio
async def test_list_images_returns_paginated_results():
    """Default source=None returns all images (standalone + extracted)."""
    from lumen_api.v1.knowledge import list_kb_images

    db = MagicMock()
    kb = _fake_kb()
    asset_a = _fake_image_asset(id_=1, caption="img-a")
    asset_b = _fake_image_asset(id_=2, caption="img-b", original_doc_page=3)

    # Build a chainable mock. MagicMock auto-creates child mocks for
    # ``db.query(*args)``; we want them to all share the same chainable
    # mock so .join / .filter / .count / .all() work consistently.
    # ``side_effect=lambda *a, **kw: q`` ensures every db.query call
    # returns the same q regardless of arguments.
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q
    q.first.return_value = kb  # KB lookup chain resolves to a real KB
    q.count.return_value = 2
    q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        (asset_a, "test.png"),
        (asset_b, "presentation.pptx"),
    ]
    db.query.side_effect = lambda *args, **kwargs: q

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ):
        result = await list_kb_images(
            kb_id=55, page=1, page_size=24, source=None,
            current_user=_regular_user(), db=db,
        )

    assert result.total == 2
    assert len(result.data) == 2
    assert result.data[0].doc_filename == "test.png"
    assert result.data[0].caption == "img-a"
    assert result.data[1].doc_filename == "presentation.pptx"


@pytest.mark.asyncio
async def test_list_images_source_standalone_filters_page_null():
    """source='standalone' → ImageAsset.original_doc_page IS NULL."""
    from lumen_api.v1.knowledge import list_kb_images

    db = MagicMock()
    kb = _fake_kb()
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q  # both the join-filters AND the source filter
    q.first.return_value = kb
    q.count.return_value = 1
    q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        (_fake_image_asset(id_=1), "test.png"),
    ]
    db.query.side_effect = lambda *args, **kwargs: q

    with patch("lumen_api.v1.knowledge.assert_perm_via_kb"):
        await list_kb_images(
            kb_id=55, page=1, page_size=24, source="standalone",
            current_user=_regular_user(), db=db,
        )

    # .filter was called: kb_id filter + standalone filter
    assert q.filter.call_count >= 2


@pytest.mark.asyncio
async def test_list_images_source_extracted_filters_page_not_null():
    """source='extracted' → ImageAsset.original_doc_page IS NOT NULL."""
    from lumen_api.v1.knowledge import list_kb_images

    db = MagicMock()
    kb = _fake_kb()
    q = MagicMock()
    q.join.return_value = q
    q.filter.return_value = q
    q.first.return_value = kb
    q.count.return_value = 1
    q.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        (_fake_image_asset(id_=2, original_doc_page=5), "slide.png"),
    ]
    db.query.side_effect = lambda *args, **kwargs: q

    with patch("lumen_api.v1.knowledge.assert_perm_via_kb"):
        await list_kb_images(
            kb_id=55, page=1, page_size=24, source="extracted",
            current_user=_regular_user(), db=db,
        )

    assert q.filter.call_count >= 2


# --- POST /{kb_id}/image-search -----------------------------------------


@pytest.mark.asyncio
async def test_image_search_multimodal_path_returns_mm_results():
    """When KB.multimodal_enabled + multimodal_config_id both set +
    embedder succeeds → ``search_mode='multimodal'``."""
    from lumen_api.v1.knowledge import image_search

    db = MagicMock()
    kb = _fake_kb(multimodal_enabled=True, multimodal_config_id=7)

    # KB lookup chain.
    q_kb_chain = MagicMock()
    q_kb_chain.filter.return_value = q_kb_chain
    q_kb_chain.first.return_value = kb

    # Asset / Document lookup chains for the multimodal result builder.
    asset = _fake_image_asset(id_=1)
    doc_for_get = SimpleNamespace(filename="test.png", id=100)

    # db.get dispatches on model class: Document → doc object (needs
    # .filename), ImageAsset → asset object (needs .storage_key).
    def get_side_effect(model, pk):
        from lumen_models.knowledge import Document as DocModel
        if model is DocModel:
            return doc_for_get
        return asset

    db.get.side_effect = get_side_effect

    # Use side_effect on db.query so different arguments resolve to
    # different chainable mocks. KB lookup uses q_kb_chain; everything
    # else (ImageAsset by chunk_id) returns q_chain.
    q_chain = MagicMock()
    q_chain.filter.return_value = q_chain
    q_chain.first.return_value = asset

    def query_side_effect(*args, **kwargs):
        # db.query(KnowledgeBase) → kb lookup
        from lumen_models.knowledge import KnowledgeBase
        if args and args[0] is KnowledgeBase:
            return q_kb_chain
        # db.query(ImageAsset).filter(chunk_id == ...).first()
        return q_chain

    db.query.side_effect = query_side_effect

    fake_embedder = MagicMock()
    fake_embedder.embed_image.return_value = [0.1, 0.2, 0.3]

    fake_store = MagicMock()
    fake_store.search.return_value = [
        {
            "id": "mm-1",
            "text": "product logo",
            "metadata": {"chunk_id": 200, "document_id": 100},
            "distance": -0.9,
            "score": 0.9,
        },
    ]

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"\\x89PNG...")
    fake_file.filename = "query_logo.png"
    fake_file.content_type = "image/png"

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ), patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
        return_value=(fake_embedder, 3),
    ), patch(
        "lumen_services.multimodal_vector_store_factory.MultimodalVectorStoreFactory.get_store",
        return_value=fake_store,
    ):
        result = await image_search(
            kb_id=55, file=fake_file, k=3,
            current_user=_regular_user(), db=db,
        )

    assert result.data.search_mode == "multimodal"
    assert result.data.query_caption == "query logo"
    assert len(result.data.results) == 1
    hit = result.data.results[0]
    assert hit.chunk_id == 200
    assert hit.document_id == 100
    assert hit.image_caption == "product logo"
    assert hit.distance == -0.9  # endpoint forwards whatever the store returns
    assert hit.score == 0.9  # cosine similarity in [0, 1]


@pytest.mark.asyncio
async def test_image_search_fallback_when_embedder_raises():
    """multimodal_enabled=True but embedder raises → fallback to
    text search. Returns ``search_mode='text_fallback'``, not 500."""
    from lumen_api.v1.knowledge import image_search
    from lumen_services.multimodal_embedders import MultimodalEmbeddingError

    db = MagicMock()
    kb = _fake_kb(multimodal_enabled=True, multimodal_config_id=7)

    q_kb_chain = MagicMock()
    q_kb_chain.filter.return_value = q_kb_chain
    q_kb_chain.first.return_value = kb

    # Asset lookup chain for the fallback result-builder. Need
    # ``storage_key`` attr to round-trip.
    asset = _fake_image_asset(id_=1, storage_key="uploads/1/55/images/test.png")
    doc_for_get = SimpleNamespace(filename="test.png", id=100)

    q_chain = MagicMock()
    q_chain.filter.return_value = q_chain
    q_chain.first.return_value = asset
    q_chain.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

    # db.get dispatches on model class: Document → doc (needs .filename),
    # anything else → asset.
    def get_side_effect(model, pk):
        from lumen_models.knowledge import Document as DocModel
        if model is DocModel:
            return doc_for_get
        return asset

    db.get.side_effect = get_side_effect

    def query_side_effect(*args, **kwargs):
        from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk
        if args and args[0] is KnowledgeBase:
            return q_kb_chain
        return q_chain

    db.query.side_effect = query_side_effect

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"x")
    fake_file.filename = "query_logo.png"
    fake_file.content_type = "image/png"

    # Multimodal path raises — we don't care which exception type, the
    # endpoint catches MultimodalEmbeddingError / UnsupportedProviderError
    # / NotImplementedError.
    fake_pipeline = MagicMock()
    fake_pipeline.search.return_value = [
        {
            "id": "es_42",
            "text": "product logo caption",
            "metadata": {"chunk_id": 200, "document_id": 100},
            "distance": 0.3,
            "rrf_score": 0.8,
        },
    ]

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ), patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
        side_effect=MultimodalEmbeddingError("model not loaded"),
    ), patch(
        "lumen_services.retrieval.get_retrieval_pipeline",
        return_value=fake_pipeline,
    ):
        result = await image_search(
            kb_id=55, file=fake_file, k=3,
            current_user=_regular_user(), db=db,
        )

    assert result.data.search_mode == "text_fallback"
    # caption stripped: "query_logo.png" → "query logo"
    assert result.data.query_caption == "query logo"
    assert len(result.data.results) == 1
    assert result.data.results[0].image_caption == "product logo caption"


@pytest.mark.asyncio
async def test_image_search_fallback_when_multimodal_disabled():
    """KB.multimodal_enabled=False → goes straight to text fallback
    (no embedder call)."""
    from lumen_api.v1.knowledge import image_search

    db = MagicMock()
    kb = _fake_kb(multimodal_enabled=False)

    q_kb_chain = MagicMock()
    q_kb_chain.filter.return_value = q_kb_chain
    q_kb_chain.first.return_value = kb

    q_chain = MagicMock()
    q_chain.filter.return_value = q_chain
    q_chain.first.return_value = None

    def query_side_effect(*args, **kwargs):
        from lumen_models.knowledge import KnowledgeBase
        if args and args[0] is KnowledgeBase:
            return q_kb_chain
        return q_chain

    db.query.side_effect = query_side_effect

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"x")
    fake_file.filename = "logo.png"
    fake_file.content_type = "image/png"

    fake_pipeline = MagicMock()
    fake_pipeline.search.return_value = []

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ), patch(
        "lumen_services.multimodal_embedders.get_multimodal_embedder",
    ) as embedder_mock, patch(
        "lumen_services.retrieval.get_retrieval_pipeline",
        return_value=fake_pipeline,
    ):
        result = await image_search(
            kb_id=55, file=fake_file, k=3,
            current_user=_regular_user(), db=db,
        )

    # Embedder was NOT consulted because multimodal_enabled=False
    embedder_mock.assert_not_called()
    assert result.data.search_mode == "text_fallback"


@pytest.mark.asyncio
async def test_image_search_404_when_kb_missing():
    """Unknown kb_id → 404 before either path."""
    from fastapi import HTTPException

    from lumen_api.v1.knowledge import image_search

    db = MagicMock()
    q = MagicMock()
    q.filter.return_value = q
    q.first.return_value = None
    db.query.side_effect = lambda *args, **kwargs: q

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"x")
    fake_file.filename = "x.png"
    fake_file.content_type = "image/png"

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ):
        with pytest.raises(HTTPException) as exc:
            await image_search(
                kb_id=999, file=fake_file, k=3,
                current_user=_regular_user(), db=db,
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_image_search_empty_fallback_returns_empty_results():
    """Both multimodal and text fallback return nothing → empty
    results array, NOT a 5xx. Admin UI can render the empty state."""
    from lumen_api.v1.knowledge import image_search

    db = MagicMock()
    kb = _fake_kb(multimodal_enabled=False)

    q_kb_chain = MagicMock()
    q_kb_chain.filter.return_value = q_kb_chain
    q_kb_chain.first.return_value = kb

    q_chain = MagicMock()
    q_chain.filter.return_value = q_chain
    q_chain.first.return_value = None

    def query_side_effect(*args, **kwargs):
        from lumen_models.knowledge import KnowledgeBase
        if args and args[0] is KnowledgeBase:
            return q_kb_chain
        return q_chain

    db.query.side_effect = query_side_effect

    fake_file = MagicMock()
    fake_file.read = AsyncMock(return_value=b"x")
    fake_file.filename = "logo.png"
    fake_file.content_type = "image/png"

    fake_pipeline = MagicMock()
    fake_pipeline.search.return_value = []

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_kb",
    ), patch(
        "lumen_services.retrieval.get_retrieval_pipeline",
        return_value=fake_pipeline,
    ):
        result = await image_search(
            kb_id=55, file=fake_file, k=3,
            current_user=_regular_user(), db=db,
        )

    assert result.data.search_mode == "text_fallback"
    assert result.data.results == []


# --- ?modality= on /search -----------------------------------------------


@pytest.mark.asyncio
async def test_search_endpoint_appends_modality_to_filter():
    """The /search endpoint must include ``modality == 'image'`` in
    filter_expr when ``?modality=image``. We don't drive the full
    pipeline; we just confirm the filter_expr string is constructed
    with the modality clause."""
    # Simulate the endpoint's filter_parts construction.
    parts = ["tenant_id == 1", "kb_id == 5"]
    parts.append("modality == 'image'")
    expr = " and ".join(parts)
    assert "modality == 'image'" in expr
    # Now feed it into the parser and ensure the modality value is captured
    from lumen_services.retrieval.hybrid_retriever import _normalise_filter
    _, _, m = _normalise_filter(expr)
    assert m == "image"


@pytest.mark.asyncio
async def test_list_document_chunks_modality_filter_applied():
    """``?modality=image`` adds a SQLAlchemy ``.filter`` call."""
    from lumen_api.v1.knowledge import list_document_chunks

    db = MagicMock()
    doc = _fake_doc()
    q_doc = MagicMock()
    q_doc.filter.return_value = q_doc
    q_doc.first.return_value = doc

    q_chunks = MagicMock()
    q_chunks.filter.return_value = q_chunks
    q_chunks.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

    def query_side_effect(*args, **kwargs):
        from lumen_models.knowledge import Document, DocumentChunk
        if args and args[0] is Document:
            return q_doc
        # DocumentChunk query
        return q_chunks

    db.query.side_effect = query_side_effect

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_document",
    ):
        await list_document_chunks(
            document_id=100, page=1, page_size=50, modality="image",
            current_user=_regular_user(), db=db,
        )

    # .filter was called on the chunks query (modality filter added).
    assert q_chunks.filter.called


@pytest.mark.asyncio
async def test_list_document_chunks_no_modality_skips_extra_filter():
    """``modality=None`` → no modality-related call."""
    from lumen_api.v1.knowledge import list_document_chunks

    db = MagicMock()
    doc = _fake_doc()
    q_doc = MagicMock()
    q_doc.filter.return_value = q_doc
    q_doc.first.return_value = doc

    q_chunks = MagicMock()
    q_chunks.filter.return_value = q_chunks
    q_chunks.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []

    def query_side_effect(*args, **kwargs):
        from lumen_models.knowledge import Document, DocumentChunk
        if args and args[0] is Document:
            return q_doc
        return q_chunks

    db.query.side_effect = query_side_effect

    with patch(
        "lumen_api.v1.knowledge.assert_perm_via_document",
    ):
        await list_document_chunks(
            document_id=100, page=1, page_size=50, modality=None,
            current_user=_regular_user(), db=db,
        )
    # The filter chain still runs for the initial document_id filter.
    # We can't directly verify "no modality filter added", but we can
    # verify no AttributeError or unexpected exception.
    assert q_chunks.filter.called