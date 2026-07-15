"""
BM25 lexical index with optional Chinese (jieba) tokenization.

The index stores a list of tokenized documents and exposes a `search` method
that returns documents ranked by BM25 score. The index can be persisted to
disk via pickle so it survives process restarts.
"""
from __future__ import annotations

import logging
import os
import pickle
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    BM25_AVAILABLE = False
    BM25Okapi = None  # type: ignore[assignment]

try:
    import jieba
    # Silence jieba's noisy initialisation log
    jieba.setLogLevel(logging.WARNING)
    JIEBA_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    JIEBA_AVAILABLE = False
    jieba = None  # type: ignore[assignment]


# A minimal English stopword list. Intentionally small so we don't over-filter
# for short queries. Chinese has no stopword filtering by default since jieba
# already produces reasonable segments.
_DEFAULT_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "to",
    "is", "are", "was", "were", "be", "been", "being",
    "it", "this", "that", "these", "those",
    "with", "as", "at", "by", "from", "but", "if",
}


_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]"
)


def _contains_cjk(text: str) -> bool:
    """Return True if the input contains any CJK characters."""
    return bool(_CJK_RE.search(text))


def _simple_tokenize(text: str) -> List[str]:
    """Tokenisation for non-CJK text. Lowercases, splits on non-word chars."""
    text = text.lower()
    # Keep alphanumerics, split on anything else
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if t and t not in _DEFAULT_STOPWORDS]


class BM25Index:
    """A thin wrapper around :class:`BM25Okapi` with persistence and CJK support.

    The index keeps three parallel structures:

    * ``_doc_ids[i]`` - the canonical id of document i (string)
    * ``_metadatas[i]`` - the metadata dict for document i
    * ``_texts[i]`` - the original text of document i (used for reranking/LLM fallback)

    The tokenized corpus is rebuilt lazily and serialised to disk alongside
    the parallel arrays so that ``add_texts`` becomes fast and we only need to
    call ``BM25Okapi`` on the full corpus when persisting.
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        use_jieba: bool = True,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.persist_path = persist_path
        self.k1 = k1
        self.b = b

        # Determine if we should attempt jieba tokenisation
        self._use_jieba = bool(use_jieba and JIEBA_AVAILABLE)

        # Parallel arrays
        self._doc_ids: List[str] = []
        self._metadatas: List[Dict[str, Any]] = []
        self._texts: List[str] = []
        self._tokenized_corpus: List[List[str]] = []

        self._bm25: Optional[Any] = None  # BM25Okapi or None

        # Auto-load if a path is provided
        if self.persist_path and os.path.exists(self.persist_path):
            try:
                self.load(self.persist_path)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to load BM25 index from %s: %s", self.persist_path, exc)

    # ------------------------------------------------------------------ build

    def _tokenize(self, text: str) -> List[str]:
        """Tokenise a single document/query."""
        if not text:
            return []
        if self._use_jieba and _contains_cjk(text):
            # jieba.cut returns a generator; filter empty strings
            return [tok for tok in jieba.cut(text) if tok.strip()]
        return _simple_tokenize(text)

    def _rebuild_index(self) -> None:
        """Rebuild the BM25Okapi object from the in-memory tokenised corpus."""
        if not BM25_AVAILABLE:
            self._bm25 = None
            return
        if not self._tokenized_corpus:
            self._bm25 = None
            return
        try:
            self._bm25 = BM25Okapi(
                self._tokenized_corpus,
                k1=self.k1,
                b=self.b,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to build BM25 index: %s", exc)
            self._bm25 = None

    def add_texts(
        self,
        texts: Sequence[str],
        metadatas: Optional[Sequence[Dict[str, Any]]] = None,
        ids: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Add documents to the index.

        Returns the list of document ids used (either provided or generated).
        """
        if not texts:
            return []

        if metadatas is None:
            metadatas = [{} for _ in texts]
        if ids is None:
            start = len(self._doc_ids)
            ids = [str(start + i) for i in range(len(texts))]

        result_ids: List[str] = []
        for i, text in enumerate(texts):
            doc_id = ids[i]
            self._doc_ids.append(doc_id)
            self._texts.append(text or "")
            self._metadatas.append(metadatas[i] or {})
            self._tokenized_corpus.append(self._tokenize(text or ""))
            result_ids.append(doc_id)

        self._rebuild_index()
        return result_ids

    def remove_by_ids(self, ids: Iterable[str]) -> int:
        """Remove documents by id. Returns the number of documents removed."""
        target = set(ids)
        if not target:
            return 0

        keep_idx = [i for i, d in enumerate(self._doc_ids) if d not in target]
        removed = len(self._doc_ids) - len(keep_idx)
        if removed == 0:
            return 0

        self._doc_ids = [self._doc_ids[i] for i in keep_idx]
        self._texts = [self._texts[i] for i in keep_idx]
        self._metadatas = [self._metadatas[i] for i in keep_idx]
        self._tokenized_corpus = [self._tokenized_corpus[i] for i in keep_idx]
        self._rebuild_index()
        return removed

    def clear(self) -> None:
        self._doc_ids.clear()
        self._texts.clear()
        self._metadatas.clear()
        self._tokenized_corpus.clear()
        self._bm25 = None

    # ------------------------------------------------------------------ search

    def search(self, query: str, k: int = 10) -> List[Tuple[str, float, Dict[str, Any]]]:
        """Search the BM25 index. Returns ``(doc_id, score, metadata)`` tuples.

        Empty queries (or queries that tokenise to nothing) return ``[]``.
        """
        if not self._bm25 or not self._doc_ids:
            return []
        tokens = self._tokenize(query)
        if not tokens:
            return []
        try:
            scores = self._bm25.get_scores(tokens)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BM25 scoring failed: %s", exc)
            return []

        # Get top-k by score (with stable ordering on ties by index)
        scored: List[Tuple[int, float]] = [
            (i, float(s)) for i, s in enumerate(scores) if s > 0
        ]
        scored.sort(key=lambda x: (-x[1], x[0]))
        scored = scored[: max(0, k)]

        results: List[Tuple[str, float, Dict[str, Any]]] = []
        for idx, score in scored:
            results.append(
                (self._doc_ids[idx], score, dict(self._metadatas[idx]))
            )
        return results

    # ------------------------------------------------------------------ access

    @property
    def size(self) -> int:
        return len(self._doc_ids)

    @property
    def is_available(self) -> bool:
        return BM25_AVAILABLE and self._bm25 is not None

    def get_text(self, doc_id: str) -> Optional[str]:
        try:
            idx = self._doc_ids.index(doc_id)
        except ValueError:
            return None
        return self._texts[idx]

    def get_metadata(self, doc_id: str) -> Optional[Dict[str, Any]]:
        try:
            idx = self._doc_ids.index(doc_id)
        except ValueError:
            return None
        return dict(self._metadatas[idx])

    def get_doc_ids(self) -> List[str]:
        return list(self._doc_ids)

    # ---------------------------------------------------------------- persist

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.persist_path
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            payload = {
                "doc_ids": self._doc_ids,
                "texts": self._texts,
                "metadatas": self._metadatas,
                "tokenized_corpus": self._tokenized_corpus,
                "k1": self.k1,
                "b": self.b,
                "use_jieba": self._use_jieba,
            }
            with open(path, "wb") as f:
                pickle.dump(payload, f)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to persist BM25 index to %s: %s", path, exc)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                payload = pickle.load(f)
            self._doc_ids = list(payload.get("doc_ids", []))
            self._texts = list(payload.get("texts", []))
            self._metadatas = list(payload.get("metadatas", []))
            self._tokenized_corpus = list(payload.get("tokenized_corpus", []))
            self.k1 = float(payload.get("k1", self.k1))
            self.b = float(payload.get("b", self.b))
            self._use_jieba = bool(payload.get("use_jieba", self._use_jieba))
            self.persist_path = path
            self._rebuild_index()
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load BM25 index from %s: %s", path, exc)
            return False
