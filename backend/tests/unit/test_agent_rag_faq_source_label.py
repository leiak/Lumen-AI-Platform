"""M31: agent_rag source-label branching for FAQ chunks.

Locks the contract that ``_render_context_markdown`` picks the
``Q&A: <category>`` label when ``chunk_metadata.source_type ==
"faq"`` and falls back to the legacy ``Document: <filename> |
Chunk #<idx>`` label otherwise.
"""
from typing import Any, Dict, List

from lumen_models.knowledge import KnowledgeBase
from lumen_services.agent_rag import _render_context_markdown


def _kb(id: int = 1, name: str = "FAQ KB") -> KnowledgeBase:
    """Build a KnowledgeBase stand-in without hitting the DB.

    ``_render_context_markdown`` only reads ``kb.id`` (via the
    ``kb_id_to_name`` dict) so we don't need a real ORM row.
    A MagicMock is overkill — a tiny stub is enough.
    """

    class _Stub:
        pass

    s = _Stub()
    s.id = id
    s.name = name
    return s  # type: ignore[return-value]


def _make_chunk(
    text: str,
    source_type: str | None = None,
    question_category: str | None = None,
    question_preview: str | None = None,
    kb_id: int = 1,
    filename: str = "manual.pdf",
    chunk_index: int = 0,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "kb_id": kb_id,
        "filename": filename,
        "chunk_index": chunk_index,
    }
    if source_type is not None:
        meta["source_type"] = source_type
    if question_category is not None:
        meta["question_category"] = question_category
    if question_preview is not None:
        meta["question_preview"] = question_preview
    return {
        "id": f"vec_{chunk_index}",
        "text": text,
        "distance": 0.1,
        "metadata": meta,
    }


class TestRenderFAQSourceLabel:
    def test_faq_chunk_renders_with_qa_prefix(self):
        chunks = [
            _make_chunk(
                "问题: 如何申请退货?\n\n答案: 请在 7 天内联系客服",
                source_type="faq",
                question_category="退货政策",
                question_preview="如何申请退货?",
            )
        ]
        out = _render_context_markdown(
            chunks, kbs=[_kb()], kb_id_to_name={1: "FAQ KB"}
        )
        # The label format: [Source: <KB> | Q&A: <category>] <preview>
        assert "[Source: FAQ KB | Q&A: 退货政策] 如何申请退货?" in out
        # The chunk body is rendered too
        assert "请在 7 天内联系客服" in out
        # And the legacy "Document:" prefix is NOT used for FAQ hits
        assert "Document:" not in out

    def test_faq_chunk_without_category_uses_uncategorised_sentinel(self):
        chunks = [
            _make_chunk(
                "Q&A body",
                source_type="faq",
                question_category=None,
                question_preview="hi",
            )
        ]
        out = _render_context_markdown(
            chunks, kbs=[_kb()], kb_id_to_name={1: "FAQ KB"}
        )
        assert "Q&A: 未分类" in out
        # The preview is still in the label.
        assert "] hi" in out

    def test_document_chunk_uses_legacy_label(self):
        """Regression: the pre-M31 ``Document: <filename> | Chunk
        #<idx>`` label is unchanged for non-FAQ chunks so any
        downstream prompt that parses it is unaffected.
        """
        chunks = [
            _make_chunk(
                "doc body",
                # No source_type — default to the document
                # path.
                filename="manual.pdf",
                chunk_index=7,
            )
        ]
        out = _render_context_markdown(
            chunks, kbs=[_kb()], kb_id_to_name={1: "FAQ KB"}
        )
        assert "[Source: FAQ KB | Document: manual.pdf | Chunk #7]" in out
        # The Q&A branch is not triggered.
        assert "Q&A:" not in out

    def test_mixed_chunks_render_with_correct_prefix(self):
        chunks = [
            _make_chunk(
                "FAQ body",
                source_type="faq",
                question_category="物流时效",
                question_preview="运费多少?",
            ),
            _make_chunk(
                "doc body",
                filename="guide.md",
                chunk_index=12,
            ),
        ]
        out = _render_context_markdown(
            chunks, kbs=[_kb()], kb_id_to_name={1: "FAQ KB"}
        )
        # Both labels appear; order follows the chunk list.
        faq_idx = out.find("Q&A: 物流时效")
        doc_idx = out.find("Document: guide.md")
        assert faq_idx != -1, f"FAQ label missing in: {out}"
        assert doc_idx != -1, f"Document label missing in: {out}"
        assert faq_idx < doc_idx, "FAQ chunk should come before doc chunk in the output"

    def test_empty_chunks_returns_empty_string(self):
        assert _render_context_markdown([], kbs=[_kb()], kb_id_to_name={1: "x"}) == ""

    def test_unknown_kb_id_renders_unknown_kb(self):
        """A chunk whose kb_id isn't in ``kb_id_to_name``
        gracefully falls back to "Unknown KB" (same as
        document chunks).
        """
        chunks = [
            _make_chunk(
                "FAQ body",
                source_type="faq",
                question_category="X",
                question_preview="p",
                kb_id=999,  # not in the map
            )
        ]
        out = _render_context_markdown(
            chunks, kbs=[_kb()], kb_id_to_name={1: "FAQ KB"}
        )
        assert "[Source: Unknown KB | Q&A: X] p" in out
