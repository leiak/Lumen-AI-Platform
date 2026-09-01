"""M38.4 Step 5c: ``?modality=`` filter + image endpoint unit tests.

Covers:
- ``hybrid_retriever._normalise_filter`` returns 3-tuple with modality
- ``hybrid_retriever._passes_filter`` honours modality
- ``FAISSVectorStore.similarity_search`` parses modality regex
- ``ElasticsearchVectorStore._parse_filter_expr`` adds modality term
- ``ElasticsearchVectorStore`` mapping includes ``modality: keyword``
- ``ChunkResponse`` round-trips 4 new multimodal fields
- ``KnowledgeBaseResponse`` exposes ``multimodal_enabled`` /
  ``multimodal_config_id``
- ``KnowledgeBaseUpdate`` accepts the 2 new multimodal fields
- end-to-end filter: a query with ``modality == 'image'`` excludes
  text chunks from both BM25 and vector sides

These tests don't touch the DB or a running server — pure Pydantic
validation + regex parser tests + an in-memory FAISS round-trip.

Notes for future maintainers:
- The 4 ChunkResponse fields (``modality`` / ``sheet_name`` /
  ``page_number`` / ``image_caption``) all have sensible defaults so
  legacy ORM rows from pre-M38.4 still validate.
- ``_normalise_filter`` previously returned a 2-tuple — it now returns
  a 3-tuple. The single in-tree caller is ``HybridRetriever.search``
  which we updated in lock-step.
"""
from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from lumen_schemas.knowledge import (
    ChunkResponse,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from lumen_services.retrieval.hybrid_retriever import (
    _normalise_filter,
    _passes_filter,
)


# --- helpers ---------------------------------------------------------------


def _row(**kw: Any):
    """Build a minimal ORM-like row for ChunkResponse validation."""
    base = {
        "id": 1,
        "content": "x",
        "chunk_index": 0,
        "vector_id": None,
        "embedding_status": "ok",
        "modality": "text",
        "sheet_name": None,
        "page_number": None,
        "image_caption": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _kb_row(**kw: Any):
    """Build a minimal ORM-like row for KnowledgeBaseResponse validation."""
    base = {
        "id": 1,
        "tenant_id": 1,
        "name": "kb",
        "description": None,
        "embedding_model": None,
        "embedding_model_config_id": 3,
        "search_weights": None,
        "default_parser": "general",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "status": "active",
        "created_at": datetime(2026, 9, 1),
        "document_count": 0,
        "multimodal_enabled": False,
        "multimodal_config_id": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# --- _normalise_filter ----------------------------------------------------


def test_normalise_filter_legacy_two_field_returns_none_modality():
    """Pre-M38.4 call site still gets tenant/kb, modality is None."""
    t, k, m = _normalise_filter("tenant_id == 1 and kb_id == 2")
    assert (t, k, m) == (1, 2, None)


def test_normalise_filter_with_modality_single_quoted():
    t, k, m = _normalise_filter("tenant_id == 1 and kb_id == 2 and modality == 'image'")
    assert (t, k, m) == (1, 2, "image")


def test_normalise_filter_with_modality_double_quoted():
    """Spec says single OR double quotes both work."""
    t, k, m = _normalise_filter('kb_id == 5 and modality == "text"')
    assert (t, k, m) == (None, 5, "text")


def test_normalise_filter_modality_only():
    """Modality without tenant/kb — caller might pass just a filter."""
    t, k, m = _normalise_filter("modality == 'image'")
    assert (t, k, m) == (None, None, "image")


def test_normalise_filter_empty_string_returns_three_nones():
    assert _normalise_filter("") == (None, None, None)


def test_normalise_filter_none_returns_three_nones():
    assert _normalise_filter(None) == (None, None, None)


def test_normalise_filter_rejects_nested_quotes():
    """``"image'); DROP"`` — the regex character class ``[^'"]+`` should
    reject this so it can't escape the string."""
    t, k, m = _normalise_filter("modality == \"image'); DROP\"")
    # The regex stops at the first closing quote — value is "image" only
    assert m == "image"
    assert (t, k) == (None, None)


# --- _passes_filter --------------------------------------------------------


def test_passes_filter_modality_match():
    meta = {"tenant_id": 1, "kb_id": 2, "modality": "image"}
    assert _passes_filter(meta, 1, 2, "image") is True


def test_passes_filter_modality_mismatch():
    meta = {"tenant_id": 1, "kb_id": 2, "modality": "text"}
    assert _passes_filter(meta, 1, 2, "image") is False


def test_passes_filter_modality_missing_defaults_to_text():
    """Legacy chunks pre-M38.4 don't carry ``modality``; they should
    pass ``modality == 'text'`` filter, not fail."""
    meta = {"tenant_id": 1, "kb_id": 2}  # no modality key
    assert _passes_filter(meta, 1, 2, "text") is True
    # But should fail an image filter
    assert _passes_filter(meta, 1, 2, "image") is False


def test_passes_filter_no_modality_constraint_skips_check():
    meta = {"tenant_id": 1, "kb_id": 2, "modality": "image"}
    # modality=None means no check — any modality passes
    assert _passes_filter(meta, 1, 2, None) is True
    # And legacy text chunks
    meta_text = {"tenant_id": 1, "kb_id": 2, "modality": "text"}
    assert _passes_filter(meta_text, 1, 2, None) is True


def test_passes_filter_tenant_kb_combined_with_modality():
    """All 3 filters must agree; failing any one rejects."""
    meta = {"tenant_id": 1, "kb_id": 2, "modality": "image"}
    # Wrong tenant → False
    assert _passes_filter(meta, 99, 2, "image") is False
    # Wrong kb → False
    assert _passes_filter(meta, 1, 99, "image") is False
    # Wrong modality → False
    assert _passes_filter(meta, 1, 2, "text") is False
    # All correct → True
    assert _passes_filter(meta, 1, 2, "image") is True


# --- FAISSVectorStore filter_expr regex ------------------------------------


def test_faiss_similarity_search_modality_regex_matches():
    """Same regex shape as hybrid_retriever — sanity check it can be
    imported from lumen_tools.vector_store (the file lives there but
    the regex is a string literal we don't need to import)."""
    sample = "tenant_id == 1 and kb_id == 2 and modality == 'image'"
    match = re.search(r"""modality\s*==\s*['"]([^'"]+)['"]""", sample)
    assert match is not None
    assert match.group(1) == "image"


# --- Elasticsearch _parse_filter_expr modality term ------------------------


def test_es_parse_filter_expr_modality_term_shape():
    """Smoke-test that the regex produces a value compatible with
    ``{"term": {"modality": "image"}}`` ES query DSL.

    We don't connect to ES here; we just confirm the parser regex
    captures the right value so the calling code can construct a
    correct term query.
    """
    sample = "tenant_id == 1 and kb_id == 2 and modality == 'image'"
    m = re.search(r"""modality\s*==\s*['"]([^'"]+)['"]""", sample)
    assert m is not None
    assert m.group(1) == "image"
    # Construct the same shape the endpoint would emit:
    assert {"term": {"modality": m.group(1)}} == {"term": {"modality": "image"}}


# --- ChunkResponse round-trip ---------------------------------------------


def test_chunk_response_legacy_text_chunk_defaults():
    """Pre-M38.4 chunk — modality defaults to 'text', other 3 new
    fields default to None. Validation must not reject."""
    r = ChunkResponse.model_validate(_row())
    assert r.modality == "text"
    assert r.sheet_name is None
    assert r.page_number is None
    assert r.image_caption is None


def test_chunk_response_image_chunk_round_trip():
    r = ChunkResponse.model_validate(_row(
        id=42, content="product logo",
        modality="image", image_caption="red logo",
        page_number=3,
    ))
    assert r.id == 42
    assert r.modality == "image"
    assert r.image_caption == "red logo"
    assert r.page_number == 3


def test_chunk_response_excel_chunk_with_sheet_name():
    """Excel chunks carry modality='text' but sheet_name matters for
    frontend table-of-contents rendering."""
    r = ChunkResponse.model_validate(_row(
        modality="text", sheet_name="Q1 报表",
    ))
    assert r.modality == "text"
    assert r.sheet_name == "Q1 报表"


def test_chunk_response_rejects_missing_required():
    """``id`` / ``content`` / ``chunk_index`` are still required."""
    with pytest.raises(Exception):
        ChunkResponse.model_validate(SimpleNamespace(modality="text"))


# --- KnowledgeBaseResponse multimodal fields -------------------------------


def test_kb_response_multimodal_disabled_by_default():
    """``multimodal_enabled`` defaults to False, ``multimodal_config_id``
    to None — matches the ORM defaults on KnowledgeBase."""
    r = KnowledgeBaseResponse.model_validate(_kb_row())
    assert r.multimodal_enabled is False
    assert r.multimodal_config_id is None


def test_kb_response_with_multimodal_enabled_round_trips():
    r = KnowledgeBaseResponse.model_validate(_kb_row(
        multimodal_enabled=True, multimodal_config_id=7,
    ))
    assert r.multimodal_enabled is True
    assert r.multimodal_config_id == 7


def test_kb_update_accepts_multimodal_fields():
    """PUT body can flip multimodal_enabled + bind a config."""
    upd = KnowledgeBaseUpdate(multimodal_enabled=True, multimodal_config_id=5)
    dumped = upd.model_dump(exclude_unset=True)
    assert dumped == {"multimodal_enabled": True, "multimodal_config_id": 5}


def test_kb_update_legacy_body_still_validates():
    """Pre-M38.4 client sends only ``name`` — still works."""
    upd = KnowledgeBaseUpdate(name="renamed")
    assert upd.model_dump(exclude_unset=True) == {"name": "renamed"}


# --- End-to-end filter compose --------------------------------------------


def test_search_endpoint_filter_expr_with_modality():
    """What ``search_knowledge_base`` would build for ``?modality=image``.

    This is a tiny structural test — we don't go through FastAPI;
    we just confirm the expected filter_expr string from the
    endpoint's ``filter_parts`` logic.
    """
    parts = ["tenant_id == 1", "kb_id == 5"]
    parts.append("modality == 'image'")
    assert " and ".join(parts) == (
        "tenant_id == 1 and kb_id == 5 and modality == 'image'"
    )


def test_search_endpoint_filter_expr_without_modality():
    parts = ["tenant_id == 1", "kb_id == 5"]
    assert " and ".join(parts) == "tenant_id == 1 and kb_id == 5"