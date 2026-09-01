"""M38.4: Multimodal-only FAISS vector store.

独立于 ``lumen_tools.vector_store.FAISSVectorStore`` 的轻量 FAISS
wrapper — 因为:

- **Dim 不同** — text 用 ``nomic-embed-text`` 768 dim,multimodal
  用 ``jina-clip-v2`` 1024 dim 或 ``clip_base_32`` 512 dim。共用一个
  IndexFlatL2 会在 add 时炸 ``AssertionError: dim mismatch``。
- **数据形态不同** — 这里只存 image chunks(text 是 caption,不是
  全文检索)。不需要 BM25 corpus、rerank、hybrid search —— 单一
  内积 top-K 足够(spec §3.5 "image-search 用 query 图命中相似图")。
- **持久化路径独立** — ``data/multimodal/kb-{id}-mm.faiss`` 而非
  ``data/faiss/kb_{id}_mc_{mc_id}``,避免 KB 切 multimodal config
  时污染 text index(切配置 = 重建向量库,multimodal index 不受影响)。

为什么不直接 extend ``FAISSVectorStore``?那个类绑了 LangChain
``Embeddings``(必须 ``embed_query(text)`` 拿向量);multimodal 是
PIL Image 或 path,API 不一样。复用会带一堆无用的 BM25 / rerank
基础设施。

实现要点:

- **IndexFlatIP** 而非 IndexFlatL2:CLIP-style 训练用内积当 cosine
  similarity,内积直接出 score;L2 是欧氏距离,与检索质量不对齐。
- **Vectors 预先算好** — ``add_texts`` 收 ``vectors`` 参数,不调
  embedder。worker 走 ``embed_text(caption)`` 后再传向量进来 —
  这是设计决策,因为 ``add_texts`` 不知道 multimodal embedder 该
  走 image 还是 text 输入(``embed_text_batch`` 走 caption,语义对)。
- **Meta JSON 持久化** — FAISS 不能存 metadata,走单独 JSON 文件。
  跟主 vector_store 的 pickle 形态不同,但语义一致。规模小(< 100K
  image / KB)时 IO 完全 OK。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import faiss
    import numpy as np

    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - dependency miss
    FAISS_AVAILABLE = False


class MultimodalVectorStore:
    """Per-KB FAISS index dedicated to multimodal (image) chunk vectors.

    Persistent layout under ``persist_dir``:

    - ``<persist_dir>/kb-{kb_id}-mm.faiss``     — FAISS IndexFlatIP
    - ``<persist_dir>/kb-{kb_id}-mm.meta.json`` — {next_id, vectors: [{id, metadata, text}]}

    Both files are written on every ``add_texts`` call; on construction
    we either read them back (warm) or start fresh (cold).
    """

    def __init__(self, kb_id: int, dim: int, persist_dir: str = "./data/multimodal"):
        self.kb_id = kb_id
        self.dim = dim
        self.persist_dir = persist_dir
        self.index_path = os.path.join(persist_dir, f"kb-{kb_id}-mm.faiss")
        self.meta_path = os.path.join(persist_dir, f"kb-{kb_id}-mm.meta.json")

        self._next_id = 0
        # ``records`` is a list aligned with the FAISS index position
        # (so position N in FAISS == records[N]). Each record is a
        # dict ``{id, text, metadata}``. We use a list (not dict) so
        # we can rebuild FAISS by re-adding in order.
        self.records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._connected = False

        if not FAISS_AVAILABLE:
            logger.warning(
                "FAISS not available — MultimodalVectorStore for kb %s "
                "will be a no-op stub (all add_texts/search return empty)",
                kb_id,
            )
            return

        try:
            os.makedirs(persist_dir, exist_ok=True)
            if os.path.exists(self.index_path) and os.path.exists(self.meta_path):
                self.index = faiss.read_index(self.index_path)
                # Validate dim — old index might have been built under
                # a different multimodal config (KB 切 multimodal config
                # 时应新建 index,但老文件残留时主动 reject 比静默错配
                # 安全)。
                if self.index.d != dim:
                    logger.warning(
                        "MultimodalVectorStore dim mismatch for kb %s: "
                        "persisted=%d, requested=%d. Rebuilding fresh.",
                        kb_id, self.index.d, dim,
                    )
                    self.index = faiss.IndexFlatIP(dim)
                    self.records = []
                    self._next_id = 0
                else:
                    with open(self.meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    self.records = list(meta.get("records", []))
                    self._next_id = int(meta.get("next_id", len(self.records)))
            else:
                self.index = faiss.IndexFlatIP(dim)
            self._connected = True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to init MultimodalVectorStore for kb %s: %s", kb_id, exc
            )
            self._connected = False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not self._connected:
            return
        try:
            faiss.write_index(self.index, self.index_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("FAISS write failed for kb %s: %s", self.kb_id, exc)
            return
        try:
            tmp = self.meta_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"next_id": self._next_id, "records": self.records}, f)
            os.replace(tmp, self.meta_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "meta.json write failed for kb %s: %s", self.kb_id, exc
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        vectors: List[List[float]],
    ) -> List[str]:
        """Add caption + pre-computed vectors to the index.

        The caller MUST pass ``vectors`` already computed (typically via
        ``multimodal_embedder.embed_text(caption)`` — the text branch
        gives the same cross-modal vector as ``embed_image`` would
        per Step 3 ABC design). This decouples vector computation from
        index mutation so a model-load failure can't leave the index
        half-written.

        Returns the assigned vector ids (e.g. ``"mm-12"``).
        """
        if not self._connected:
            return [f"mock_{i}" for i in range(len(texts))]
        if not texts:
            return []
        if len(texts) != len(metadatas) or len(texts) != len(vectors):
            raise ValueError(
                f"add_texts length mismatch: texts={len(texts)}, "
                f"metadatas={len(metadatas)}, vectors={len(vectors)}"
            )

        with self._lock:
            ids: List[str] = []
            # Validate + convert in one batched numpy op — 100× faster
            # than per-row ``np.array(...)`` when the caller has many
            # captions.
            try:
                matrix = np.asarray(vectors, dtype="float32")
            except Exception as exc:
                raise ValueError(f"vectors could not be coerced to float32: {exc}")
            if matrix.ndim != 2 or matrix.shape[1] != self.dim:
                raise ValueError(
                    f"vector dim mismatch: expected ({self.dim},), got "
                    f"{matrix.shape if matrix.ndim == 2 else (matrix.shape,)}"
                )

            for i, (text, meta) in enumerate(zip(texts, metadatas)):
                chunk_id = str(self._next_id)
                self._next_id += 1
                ids.append(f"mm-{chunk_id}")
                self.records.append({
                    "id": f"mm-{chunk_id}",
                    "text": text,
                    "metadata": meta,
                })

            self.index.add(matrix)
            self._save()
        return ids

    def search(
        self,
        query_vec: List[float],
        k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Top-K inner-product nearest neighbours.

        Returns ``[{"id": ..., "distance": ..., "text": ..., "metadata": ...}, ...]``
        sorted by inner product (higher = closer in cosine-similarity
        space; CLIP-style embeddings are unit-norm, so dot ~ cosine).

        Distance field is the negative inner product — consistent with
        the text ``FAISSVectorStore.similarity_search`` convention where
        *smaller = closer*. Callers that want raw score can read
        ``score`` (positive, higher = better) instead.
        """
        if not self._connected or self.index.ntotal == 0:
            return []
        try:
            q = np.asarray([query_vec], dtype="float32")
            k_search = min(k, self.index.ntotal)
            scores, indices = self.index.search(q, k_search)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "MultimodalVectorStore.search failed for kb %s: %s",
                self.kb_id, exc,
            )
            return []
        out: List[Dict[str, Any]] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.records):
                continue
            rec = self.records[idx]
            out.append({
                "id": rec["id"],
                "text": rec["text"],
                "metadata": rec.get("metadata", {}),
                "score": float(score),
                "distance": float(-score),
            })
        return out

    @property
    def ntotal(self) -> int:
        """Number of vectors in the index. Mirrors ``faiss.Index.ntotal``."""
        if not self._connected:
            return 0
        return int(self.index.ntotal)

    @property
    def is_connected(self) -> bool:
        return self._connected


__all__ = ["MultimodalVectorStore", "FAISS_AVAILABLE"]
