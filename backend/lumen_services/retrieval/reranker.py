"""
Pluggable rerankers for the hybrid retrieval pipeline.

A reranker takes a query and a list of candidate results (with ``text`` and
``metadata`` fields) and returns them re-ordered by relevance. Three concrete
implementations are provided:

* :class:`NoopReranker` - passthrough (returns the input unchanged).
* :class:`JinaReranker` - cross-encoder via the ``jina`` package (optional).
* :class:`LLMReranker` - uses the existing project LLM service to score each
  candidate; useful as a fallback when no cross-encoder model is available
  locally.

A factory :func:`get_reranker` selects the right implementation based on
configuration / environment.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Reranker:
    """Abstract base for rerankers."""

    @property
    def name(self) -> str:  # pragma: no cover - trivial
        return self.__class__.__name__

    @property
    def is_available(self) -> bool:
        return True

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


class NoopReranker(Reranker):
    """Pass-through reranker that simply truncates the input list."""

    @property
    def name(self) -> str:
        return "noop"

    @property
    def is_available(self) -> bool:
        return True

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []
        out: List[Dict[str, Any]] = []
        for doc in documents[: max(0, top_k)]:
            entry = dict(doc)
            entry.setdefault("relevance_score", None)
            out.append(entry)
        return out


class JinaReranker(Reranker):
    """Reranker using the optional ``jina`` package (cross-encoder)."""

    def __init__(self, model: str = "jina-reranker-v2-base-multilingual") -> None:
        self.model = model
        self._client: Any = None
        self._available = False
        try:
            from jina import JinaReranker  # type: ignore
            try:
                self._client = JinaReranker(model=model)
                self._available = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to initialise JinaReranker: %s", exc)
                self._client = None
        except ImportError:
            self._client = None
            self._available = False

    @property
    def name(self) -> str:
        return f"jina:{self.model}"

    @property
    def is_available(self) -> bool:
        return self._available and self._client is not None

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        if not self.is_available or not documents:
            return [dict(d) for d in documents[: max(0, top_k)]]
        try:
            texts = [str(d.get("text", "")) for d in documents]
            results = self._client.rank(
                query=query,
                documents=texts,
                top_n=max(0, top_k),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("JinaReranker.rerank failed: %s", exc)
            return [dict(d) for d in documents[: max(0, top_k)]]

        reranked: List[Dict[str, Any]] = []
        for result in results:
            idx = getattr(result, "index", None)
            if idx is None or idx >= len(documents):
                continue
            entry = dict(documents[idx])
            entry["relevance_score"] = float(
                getattr(result, "relevance_score", 0.0) or 0.0
            )
            reranked.append(entry)
        return reranked


class LLMReranker(Reranker):
    """LLM-based reranker.

    Calls the project's existing LLM service to score each candidate. Each
    candidate is scored independently on a 0-3 scale; the LLM is asked to
    return a single integer which we then convert to a ``relevance_score``.
    The implementation is conservative: it falls back to a passthrough on
    any error so the pipeline never fails outright.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        max_concurrency: int = 4,
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.max_concurrency = max(1, int(max_concurrency))
        self.timeout = float(timeout)

    @property
    def name(self) -> str:
        return f"llm:{self.model or 'default'}"

    def _score_with_llm(self, query: str, text: str) -> float:
        """Ask the LLM to score a single (query, document) pair.

        Returns a float in ``[0, 1]``.
        """
        # Lazy import to avoid hard dependencies at module import time.
        try:
            from lumen_services.model_loader import get_chat_model  # type: ignore
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("LLM model loader not available: %s", exc)
            return 0.5

        prompt = (
            "You are a relevance scoring assistant. Given a user query and a "
            "passage, rate how relevant the passage is to the query on an "
            "integer scale from 0 (irrelevant) to 3 (highly relevant). "
            "Respond with ONLY a single digit (0, 1, 2, or 3).\n\n"
            f"Query: {query.strip()}\n\n"
            f"Passage: {text.strip()[:1500]}\n\n"
            "Relevance:"
        )

        try:
            llm = get_chat_model(model=self.model) if self.model else get_chat_model()
            response = llm.invoke(prompt)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("LLM rerank score call failed: %s", exc)
            return 0.5

        # Parse the response
        try:
            text_out = getattr(response, "content", str(response))
        except Exception:  # pragma: no cover
            text_out = str(response)
        if isinstance(text_out, list):
            # Some chat models return a list of content parts
            text_out = "".join(str(p) for p in text_out)
        text_out = (text_out or "").strip()
        # Extract first digit
        for ch in text_out:
            if ch in "0123":
                score = int(ch) / 3.0
                return score
        return 0.5

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        if not documents:
            return []
        scored: List[Dict[str, Any]] = []
        for doc in documents:
            text = str(doc.get("text", ""))
            score = self._score_with_llm(query, text)
            entry = dict(doc)
            entry["relevance_score"] = float(score)
            scored.append(entry)
        scored.sort(key=lambda d: d.get("relevance_score", 0.0), reverse=True)
        return scored[: max(0, top_k)]


def get_reranker(
    enabled: bool = True,
    preferred: str = "auto",
    model: Optional[str] = None,
) -> Reranker:
    """Return a configured :class:`Reranker` instance.

    Args:
        enabled: when ``False``, returns a :class:`NoopReranker` (passthrough).
        preferred: one of ``"auto"``, ``"jina"``, ``"llm"``, ``"noop"``.
            ``"auto"`` picks JinaReranker if available, otherwise LLMReranker.
        model: optional model name to pass to the underlying reranker.
    """
    if not enabled:
        return NoopReranker()

    pref = (preferred or "auto").lower()

    if pref == "jina":
        r = JinaReranker(model=model or "jina-reranker-v2-base-multilingual")
        return r if r.is_available else NoopReranker()
    if pref == "llm":
        return LLMReranker(model=model)
    if pref == "noop":
        return NoopReranker()

    # auto
    jina = JinaReranker(model=model or "jina-reranker-v2-base-multilingual")
    if jina.is_available:
        return jina
    # Honour the env override for the LLM reranker model
    env_model = os.environ.get("RERANK_LLM_MODEL")
    return LLMReranker(model=model or env_model)
