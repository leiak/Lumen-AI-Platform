"""M31: FAQService unit tests.

Exercises the create / get / list / update / delete / bulk-import
paths against a real dev DB session. Vector writes are mocked
out — the embedding pipeline is exercised by the existing
``test_kb_document_propagates_embedding`` style tests, and we
don't want every FAQService unit test to require a live
Ollama. The chunk.embedding_status / chunk.vector_id branching
is what matters here, not the FAISS internals.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from lumen_core.database import SessionLocal
from lumen_models.agent import Agent  # noqa: F401  — register table metadata
from lumen_models.knowledge import (
    Document,
    DocumentChunk,
    FAQEntry,
    KnowledgeBase,
)
from lumen_models.model_config import ModelConfig
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_schemas.knowledge import (
    FAQBulkImportRequest,
    FAQEntryCreate,
    FAQEntryUpdate,
)
from lumen_services.faq_service import FAQService, FAQ_FILE_PATH_PREFIX


# --------------------------------------------------------------------- fixtures


@pytest.fixture
def db_session():
    """Yield a real DB session. Caller responsible for cleaning up
    rows it inserts; the fixture just sets up tenant + admin so
    the FK chain is intact.
    """
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if tenant is None:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
        user = db.query(User).filter(User.id == 1).first()
        if user is None:
            user = User(
                id=1,
                tenant_id=1,
                username="admin",
                email="admin@example.com",
                hashed_password="x",
                is_active=1,
            )
            db.add(user)
            db.commit()
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def embedding_config(db_session):
    """Pick the first active embedding ModelConfig on the dev DB.

    Returns ``None`` and skips the test if the dev DB hasn't
    been initialised (CI without init script). The fixture
    itself is read-only — it doesn't create rows.
    """
    cfg = (
        db_session.query(ModelConfig)
        .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
        .order_by(ModelConfig.id)
        .first()
    )
    if cfg is None:
        pytest.skip("dev DB has no active embedding ModelConfig")
    return cfg


@pytest.fixture
def kb(db_session, embedding_config):
    """Create a throwaway KB to attach FAQs to. Auto-cleaned on teardown."""
    kb = KnowledgeBase(
        name=f"m31-faq-test-kb-{uuid.uuid4().hex[:8]}",
        description="M31 FAQService test",
        tenant_id=1,
        status="active",
        embedding_model_config_id=embedding_config.id,
    )
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)
    yield kb
    # Hard cleanup. Cascade will take the FAQs and chunks
    # with it. Best-effort — if the test crashed, the dev
    # DB will have an extra row, which is harmless.
    try:
        db_session.query(KnowledgeBase).filter(
            KnowledgeBase.id == kb.id
        ).delete()
        db_session.commit()
    except Exception:
        db_session.rollback()


@pytest.fixture
def admin_user(db_session):
    user = db_session.query(User).filter(User.id == 1).first()
    assert user is not None, "dev DB missing admin user id=1"
    return user


@pytest.fixture
def service():
    return FAQService()


def _fake_vector_ids(n: int) -> List[str]:
    return [f"vec_{i}_{uuid.uuid4().hex[:6]}" for i in range(n)]


# --------------------------------------------------------------------- tests


class TestCreateEntry:
    """Single-row create path. Verifies the virtual Document /
    chunk wiring, the metadata fields, and the idempotency of
    the data side (no vector side here, that's mocked).
    """

    def test_create_entry_persists_doc_chunk_faq(
        self, db_session, kb, admin_user, service
    ):
        # Patch the vector write so we don't need Ollama. The
        # service layer should still produce a complete row
        # with a real vector_id and a non-failed chunk.
        vids = _fake_vector_ids(1)
        with patch.object(
            service, "_index_chunks", return_value=vids
        ) as mock_idx:
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(
                    question="如何申请退货?",
                    answer="请在 7 天内联系客服",
                    category="退货政策",
                    tags=["急"],
                ),
                admin_user,
            )

        assert isinstance(faq, FAQEntry)
        assert faq.id is not None
        assert faq.knowledge_base_id == kb.id
        assert faq.question == "如何申请退货?"
        assert faq.answer == "请在 7 天内联系客服"
        assert faq.category == "退货政策"
        assert faq.tags == ["急"]
        assert faq.vector_id == vids[0]
        assert faq.embedding_model_config_id == kb.embedding_model_config_id

        # The virtual Document is also persisted.
        doc = db_session.get(Document, faq.document_id)
        assert doc is not None
        assert doc.file_type == "qa_pair"
        assert doc.file_path.startswith(FAQ_FILE_PATH_PREFIX)
        assert doc.status == "completed"
        assert doc.chunk_count == 1
        assert (doc.doc_metadata or {}).get("doc_type") == "qa_pair"

        # The chunk has the right content + metadata.
        chunk = db_session.get(DocumentChunk, faq.chunk_id)
        assert chunk is not None
        assert "如何申请退货?" in chunk.content
        assert "请在 7 天内联系客服" in chunk.content
        assert chunk.chunk_index == 0
        assert chunk.embedding_status == "ok"
        assert chunk.vector_id == vids[0]
        meta = chunk.chunk_metadata or {}
        assert meta.get("source_type") == "faq"
        assert meta.get("question_category") == "退货政策"
        assert meta.get("question_preview") == "如何申请退货?"
        assert meta.get("faq_id") == faq.id

        # Vector write called with chunk + metadata.
        mock_idx.assert_called_once()
        _, kwargs = mock_idx.call_args
        assert kwargs["metadatas"][0]["source_type"] == "faq"

    def test_create_entry_without_category_uses_uncategorised_label(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        doc = db_session.get(Document, faq.document_id)
        # filename uses "未分类" sentinel — same as the doc parser
        # for uncategorised Q&As.
        assert doc.filename == "FAQ/未分类"
        chunk = db_session.get(DocumentChunk, faq.chunk_id)
        assert (chunk.chunk_metadata or {}).get("question_category") is None

    def test_create_entry_marks_chunk_failed_when_vector_write_fails(
        self, db_session, kb, admin_user, service
    ):
        # Simulate the embedder being down — _index_chunks
        # returns [] on failure. The service should still
        # commit, but the chunk should be marked failed so
        # search won't return it.
        with patch.object(service, "_index_chunks", return_value=[]):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        chunk = db_session.get(DocumentChunk, faq.chunk_id)
        assert chunk.embedding_status == "failed"
        assert chunk.vector_id.startswith("error_")
        # The FAQ row itself is still created — the user can
        # edit + retry.
        assert faq.id is not None

    def test_create_entry_tags_default_to_empty_list(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        assert faq.tags == []


class TestListAndGet:
    """Read paths: list with filters, single get with tenant scope."""

    def test_list_entries_paginates(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            for i in range(5):
                service.create_entry(
                    db_session,
                    kb,
                    FAQEntryCreate(
                        question=f"Q{i}",
                        answer=f"A{i}",
                        category="退货政策" if i % 2 == 0 else "物流时效",
                    ),
                    admin_user,
                )

        rows, total = service.list_entries(
            db_session, kb_id=kb.id, tenant_id=kb.tenant_id, page=1, page_size=3
        )
        assert total == 5
        assert len(rows) == 3
        rows2, _ = service.list_entries(
            db_session, kb_id=kb.id, tenant_id=kb.tenant_id, page=2, page_size=3
        )
        assert len(rows2) == 2

    def test_list_entries_filter_by_category(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            for cat in ("退货政策", "退货政策", "物流时效"):
                service.create_entry(
                    db_session,
                    kb,
                    FAQEntryCreate(question="Q", answer="A", category=cat),
                    admin_user,
                )
        rows, total = service.list_entries(
            db_session,
            kb_id=kb.id,
            tenant_id=kb.tenant_id,
            category="退货政策",
        )
        assert total == 2
        assert {r.category for r in rows} == {"退货政策"}

    def test_list_entries_search_matches_question_and_answer(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="如何申请退货?", answer="请在 7 天内联系客服"),
                admin_user,
            )
            service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="运费多少?", answer="包邮订单免运费"),
                admin_user,
            )
        rows, total = service.list_entries(
            db_session,
            kb_id=kb.id,
            tenant_id=kb.tenant_id,
            search="运费",
        )
        # "运费" appears in the question of row 2 and the
        # answer of row 2 (and the answer of row 1 doesn't
        # contain it). So only row 2 matches.
        assert total == 1
        assert rows[0].question == "运费多少?"

    def test_list_entries_returns_empty_for_other_tenant(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        # tenant_id=999 doesn't own this KB; list must return
        # [] not the real rows (tenant isolation).
        rows, total = service.list_entries(
            db_session, kb_id=kb.id, tenant_id=999
        )
        assert total == 0
        assert rows == []

    def test_get_entry_returns_none_for_wrong_kb(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        # Look up against a different (non-existent) KB id.
        assert (
            service.get_entry(
                db_session, faq.id, kb_id=9999, tenant_id=kb.tenant_id
            )
            is None
        )
        # Correct KB id returns the row.
        assert (
            service.get_entry(
                db_session, faq.id, kb_id=kb.id, tenant_id=kb.tenant_id
            )
            is not None
        )


class TestUpdateEntry:
    """Update path: PATCH-style fields, chunk re-render, vector swap."""

    def test_update_question_rewrites_chunk_content_and_vector(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="原问题", answer="原答案"),
                admin_user,
            )
        old_vid = faq.vector_id
        old_doc_id = faq.document_id
        old_chunk_id = faq.chunk_id

        new_vid = "vec_new_999"
        with patch.object(service, "_index_chunks", return_value=[new_vid]):
            updated = service.update_entry(
                db_session,
                faq,
                FAQEntryUpdate(question="新问题"),
            )

        assert updated.question == "新问题"
        assert updated.vector_id == new_vid

        # Chunk text + metadata updated; chunk_id and
        # document_id stable (no row recreation).
        chunk = db_session.get(DocumentChunk, old_chunk_id)
        assert "新问题" in chunk.content
        assert "原答案" in chunk.content
        assert chunk.vector_id == new_vid
        assert chunk.embedding_status == "ok"
        assert (chunk.chunk_metadata or {}).get("question_preview") == "新问题"
        # document_id unchanged
        assert updated.document_id == old_doc_id

        # Old vector is best-effort cleaned up. The mock
        # service._delete_vectors is a no-op so the test
        # doesn't assert on it (covered separately in the
        # deletion test).

    def test_update_only_category_does_not_reembed(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A", category="原分类"),
                admin_user,
            )
        old_vid = faq.vector_id

        with patch.object(
            service, "_index_chunks"
        ) as mock_idx:
            updated = service.update_entry(
                db_session,
                faq,
                FAQEntryUpdate(category="新分类"),
            )

        # No re-embed call because chunk text didn't change.
        mock_idx.assert_not_called()
        assert updated.category == "新分类"
        # Vector unchanged.
        assert updated.vector_id == old_vid

    def test_update_too_many_tags_raises(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        # 21 tags exceeds MAX_TAGS_PER_ENTRY (20).
        too_many = [f"t{i}" for i in range(21)]
        with pytest.raises(ValueError, match="tags"):
            service.update_entry(
                db_session, faq, FAQEntryUpdate(tags=too_many)
            )


class TestDeleteEntry:
    """Hard delete + vector cleanup."""

    def test_delete_entry_removes_row_and_cascades(
        self, db_session, kb, admin_user, service
    ):
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            faq = service.create_entry(
                db_session,
                kb,
                FAQEntryCreate(question="Q", answer="A"),
                admin_user,
            )
        doc_id = faq.document_id
        chunk_id = faq.chunk_id
        # Mock the vector delete so we don't need FAISS.
        with patch.object(service, "_delete_vectors") as mock_del:
            service.delete_entry(db_session, faq)
        mock_del.assert_called_once()
        # FAQ row gone. Use a fresh query instead of
        # ``db_session.get`` so the identity map doesn't
        # return the cached object after the COMMIT (SQLAlchemy
        # leaves expunged objects in the identity map until
        # the session is rolled back / closed).
        db_session.expire_all()
        assert (
            db_session.query(FAQEntry).filter(FAQEntry.id == faq.id).first()
            is None
        )
        # Chunk + Document cascaded away.
        assert (
            db_session.query(DocumentChunk)
            .filter(DocumentChunk.id == chunk_id)
            .first()
            is None
        )
        assert (
            db_session.query(Document)
            .filter(Document.id == doc_id)
            .first()
            is None
        )


class TestBulkImport:
    """JSON / CSV parsing + validation, plus happy-path insert."""

    def test_bulk_import_json_happy_path(
        self, db_session, kb, admin_user, service
    ):
        payload = [
            {
                "question": "Q1",
                "answer": "A1",
                "category": "退货政策",
                "tags": ["急", "VIP"],
            },
            {"question": "Q2", "answer": "A2"},
        ]
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            result = service.bulk_import(
                db_session,
                kb,
                FAQBulkImportRequest(format="json", content=json.dumps(payload)),
                admin_user,
            )
        assert result.inserted == 2
        assert result.failed == []

    def test_bulk_import_csv_happy_path(
        self, db_session, kb, admin_user, service
    ):
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["question", "answer", "category", "tags"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "question": "Q1",
                "answer": "A1",
                "category": "退货政策",
                "tags": "急,VIP",  # CSV stores tags as comma-joined
            }
        )
        writer.writerow({"question": "Q2", "answer": "A2", "category": "", "tags": ""})

        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            result = service.bulk_import(
                db_session,
                kb,
                FAQBulkImportRequest(format="csv", content=buf.getvalue()),
                admin_user,
            )
        assert result.inserted == 2
        assert result.failed == []

    def test_bulk_import_collects_validation_errors(
        self, db_session, kb, admin_user, service
    ):
        payload = [
            {"question": "Q-good", "answer": "A-good"},
            {"question": "", "answer": "A-bad"},       # missing question
            {"question": "Q-bad", "answer": ""},        # missing answer
            {"question": "Q-tags", "answer": "A-tags",
             "tags": ",".join(f"t{i}" for i in range(21))},  # too many tags
        ]
        with patch.object(service, "_index_chunks", return_value=_fake_vector_ids(1)):
            result = service.bulk_import(
                db_session,
                kb,
                FAQBulkImportRequest(format="json", content=json.dumps(payload)),
                admin_user,
            )
        assert result.inserted == 1
        assert len(result.failed) == 3
        reasons = {f["reason"] for f in result.failed}
        assert any("问题不能为空" in r for r in reasons)
        assert any("答案不能为空" in r for r in reasons)
        assert any("标签数量" in r for r in reasons)

    def test_bulk_import_malformed_json_returns_zero_inserted(
        self, db_session, kb, admin_user, service
    ):
        result = service.bulk_import(
            db_session,
            kb,
            FAQBulkImportRequest(format="json", content="not json{{{"),
            admin_user,
        )
        assert result.inserted == 0
        assert len(result.failed) == 1
        assert "JSON" in result.failed[0]["reason"]

    def test_bulk_import_csv_missing_required_columns(
        self, db_session, kb, admin_user, service
    ):
        bad = "foo,bar\n1,2\n"
        result = service.bulk_import(
            db_session,
            kb,
            FAQBulkImportRequest(format="csv", content=bad),
            admin_user,
        )
        assert result.inserted == 0
        assert "question" in result.failed[0]["reason"]
        assert "answer" in result.failed[0]["reason"]

    def test_bulk_import_json_not_a_list(
        self, db_session, kb, admin_user, service
    ):
        result = service.bulk_import(
            db_session,
            kb,
            FAQBulkImportRequest(format="json", content='{"question": "Q"}'),
            admin_user,
        )
        assert result.inserted == 0
        assert "数组" in result.failed[0]["reason"]
