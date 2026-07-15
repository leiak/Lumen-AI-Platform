"""Regression test: upload_document must copy the KB's
``embedding_model_config_id`` onto the new ``Document`` row.

Background — the bug this guards against (2026-06-08):
The Celery worker ``process_document_task`` resolves the embedder via
``doc.embedding_model_config_id``. The async upload path used to leave
this column NULL, so the worker crashed with
``ValueError: ModelConfig None not found`` and the upload's
``error_message`` read ``向量化失败: ValueError: ModelConfig None not found``.

The fix is in ``upload_document`` — when building the ``Document``,
set ``embedding_model_config_id=kb.embedding_model_config_id`` so the
worker (and retry/rechunk/delete paths) can find the embedder via
the per-doc FK even if the KB row changes later.
"""
import pytest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_models.knowledge import Document, KnowledgeBase
from lumen_models.model_config import ModelConfig
from lumen_services.auth_service import create_access_token


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def tmp_embedding_config():
    """Reuse the dev DB's existing embedding ModelConfig (id=4:
    ``nomic-embed-text`` / ollama / is_embedding=1 / is_active=1) so
    we don't have to insert and clean up a row. The fixture only
    yields — it does not delete the row on teardown, because the row
    is shared with other tests / the running dev server.

    If the row isn't there (fresh CI DB), the test that depends on
    this fixture is skipped.
    """
    db = SessionLocal()
    try:
        cfg = db.get(ModelConfig, 4)
        if cfg is None or not cfg.is_embedding or not cfg.is_active:
            pytest.skip("dev DB ModelConfig id=4 (nomic-embed-text) not present")
        yield cfg
    finally:
        db.close()


@pytest.fixture
def tmp_kb_with_embedding(tmp_user, tmp_embedding_config):
    """KB whose ``embedding_model_config_id`` is a real ModelConfig row.

    The default ``tmp_kb`` fixture doesn't set the FK — uploads against
    that KB are exactly the failure case the bug is about, but for the
    assertion to be meaningful the KB row must point at a config so
    we can verify the doc inherits it.
    """
    db = SessionLocal()
    kb = None
    try:
        kb = KnowledgeBase(
            name=f"unit_test_kb_emb_{uuid.uuid4().hex[:8]}",
            tenant_id=tmp_user.tenant_id,
            embedding_model_config_id=tmp_embedding_config.id,
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)
        yield kb
    finally:
        try:
            if kb is not None:
                # KB may already be deleted by test's own cleanup
                db.delete(kb)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def _auth(user):
    token = create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_upload_propagates_embedding_config_to_document(
    client, tmp_user, tmp_kb_with_embedding
):
    """The new ``Document`` row's ``embedding_model_config_id`` must
    equal its parent KB's. This is what the async worker reads to
    load the embedder."""
    # Avoid hitting Celery / the parser / the embedder — we only want
    # to observe what the upload endpoint writes to the DB.
    with patch("lumen_tasks.document_tasks.process_document_task"):
        with open(__file__, "rb") as f:
            r = client.post(
                f"/api/v1/knowledge/{tmp_kb_with_embedding.id}/documents",
                headers=_auth(tmp_user),
                files={"file": ("a.txt", f, "text/plain")},
                data={"doc_type": "txt", "async_process": "true"},
            )
    assert r.status_code == 200, r.text

    db = SessionLocal()
    try:
        doc = (
            db.query(Document)
            .filter(Document.knowledge_base_id == tmp_kb_with_embedding.id)
            .order_by(Document.id.desc())
            .first()
        )
        assert doc is not None, "Document row was not created"
        assert doc.embedding_model_config_id == tmp_kb_with_embedding.embedding_model_config_id, (
            f"expected doc.embedding_model_config_id="
            f"{tmp_kb_with_embedding.embedding_model_config_id}, "
            f"got {doc.embedding_model_config_id}"
        )
    finally:
        db.close()


def test_process_document_task_falls_back_to_kb_when_doc_fk_is_null(
    tmp_user, tmp_kb_with_embedding, tmp_embedding_config
):
    """Legacy documents (uploaded before the upload fix) have
    ``embedding_model_config_id IS NULL``. The async worker must
    still be able to find the embedder by falling back to the parent
    KB's FK; otherwise the user can never re-process a stuck legacy
    document and the embed error recurs forever.

    We drive ``process_document_task`` with a doc whose FK is NULL,
    return one chunk from the parser, and assert the worker called
    ``VectorStoreFactory.get_store`` with the **KB's** FK (not None)
    — that's the call that previously raised
    ``ValueError: ModelConfig None not found``.
    """
    from unittest.mock import MagicMock, patch as _patch
    from lumen_tasks import document_tasks

    # Build a legacy doc row (FK NULL) before invoking the task.
    db = SessionLocal()
    try:
        legacy_doc = Document(
            filename="legacy.txt",
            file_path="/nonexistent/legacy.txt",
            file_type="text/plain",
            file_size=0,
            status="pending",
            knowledge_base_id=tmp_kb_with_embedding.id,
            created_by=tmp_user.id,
            embedding_model_config_id=None,  # <-- the legacy state
        )
        db.add(legacy_doc)
        db.commit()
        db.refresh(legacy_doc)
        doc_id = legacy_doc.id
    finally:
        db.close()

    # Parser returns ONE pre-chunked chunk (so the worker reaches the
    # embed path) but never actually reads the file. BM25 is stubbed
    # so we don't try to load the index. The vector store is fully
    # mocked — we only want to observe the model_config_id argument.
    captured: dict = {}

    def fake_get_store(*, kb_id, model_config_id, db):
        captured["kb_id"] = kb_id
        captured["model_config_id"] = model_config_id
        store = MagicMock()
        store.add_texts.return_value = ["v0"]
        return store

    with _patch(
        "lumen_tools.vector_store_factory.VectorStoreFactory.get_store",
        side_effect=fake_get_store,
    ), _patch(
        "lumen_services.document_parser.DocumentParser"
    ) as mock_parser_cls, _patch(
        "lumen_services.retrieval.get_retrieval_pipeline"
    ):
        mock_parser = MagicMock()
        mock_parser.parse.return_value = {
            "text": "hello world",
            "chunks": [
                {
                    "content": "hello world",
                    "chunk_index": 0,
                    "strategy": "parser",
                    "length": 11,
                }
            ],
            "metadata": {},
        }
        mock_parser_cls.return_value = mock_parser

        result = document_tasks.process_document_task.run(  # type: ignore[attr-defined]
            {
                "document_id": doc_id,
                "file_path": "/nonexistent/legacy.txt",
                "file_content_type": "text/plain",
                "tenant_id": tmp_user.tenant_id,
                "kb_id": tmp_kb_with_embedding.id,
                "chunking_strategy": "fixed",
                "chunking_params": {},
            }
        )

    # The embed path must have been reached with the KB's FK, not None.
    assert captured.get("model_config_id") == tmp_kb_with_embedding.embedding_model_config_id, (
        f"expected VectorStoreFactory.get_store to receive "
        f"model_config_id={tmp_kb_with_embedding.embedding_model_config_id}, "
        f"got {captured.get('model_config_id')!r}"
    )
    # Task should succeed (not the legacy "ModelConfig None not found").
    assert result["status"] == "completed", result
    assert "ModelConfig" not in (result.get("error") or "")
