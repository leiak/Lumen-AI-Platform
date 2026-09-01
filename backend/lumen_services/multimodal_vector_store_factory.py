"""M38.4: Multimodal vector store factory.

镜像 ``lumen_tools.vector_store_factory.VectorStoreFactory`` 的 cache
模式 —— process-wide singleton + ``invalidate(kb_id)`` 给 admin 调。

为什么单独建一个 factory(而不是给 VectorStoreFactory 加 multimodal 分支):

- **生命周期不同** — text store 跟 ``model_config_id`` 绑定(切 embedding
  模型 = 重建);multimodal store 跟 KB 绑定(切 multimodal config 时,
  spec 设计是新建 revision 而不是重建,所以 multimodal store 不动)。
- **持久化路径不同** — text store 走 ES / ``data/faiss/``;
  multimodal store 走 ``data/multimodal/``。两套 cache 互不污染。
- **依赖注入不同** — text store 持 ``Embeddings`` 实例;multimodal
  store 只收 ``vectors`` 参数(在 add_texts 调用前已算好)。

简单 key 缓存 + lazy construction,无 ES fallback(规模小且 text-only
fallback 已够用,见 ``lumen_api/v1/knowledge.py:/{kb_id}/image-search``
的 ``search_mode='text_fallback'`` 路径)。
"""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from .multimodal_vector_store import MultimodalVectorStore

logger = logging.getLogger(__name__)


class MultimodalVectorStoreFactory:
    """Process-wide cache of ``MultimodalVectorStore`` per ``kb_id``.

    Cache key is just ``kb_id`` — not ``(kb_id, dim)`` — because the
    factory rebuilds the index when ``dim`` mismatches what's persisted
    (see ``MultimodalVectorStore.__init__`` warning). Two callers within
    the same process asking for the same kb with different dims see the
    same store object; the constructor's dim-mismatch check then forces
    a rebuild on the first ``add_texts`` call. This avoids accidental
    cache fragmentation in tests where the dim is determined lazily.
    """

    _cache: Dict[int, MultimodalVectorStore] = {}
    _lock = threading.Lock()

    @classmethod
    def get_store(cls, kb_id: int, dim: int) -> MultimodalVectorStore:
        """Return the per-KB ``MultimodalVectorStore`` (lazy build).

        First call constructs; subsequent calls return the cached
        instance. ``dim`` is only used on first construction; later
        callers with a different dim still hit the same object — see
        class docstring on the dim-mismatch handling.
        """
        cached = cls._cache.get(kb_id)
        if cached is not None:
            return cached

        with cls._lock:
            cached = cls._cache.get(kb_id)
            if cached is not None:
                return cached
            store = MultimodalVectorStore(kb_id=kb_id, dim=dim)
            cls._cache[kb_id] = store
            return store

    @classmethod
    def invalidate(cls, kb_id: Optional[int] = None) -> None:
        """Drop cached store(s).

        ``kb_id=None`` clears the whole cache; pass a specific id when
        an admin operation needs to force a reload (e.g. KB deleted
        or multimodal config switched).
        """
        with cls._lock:
            if kb_id is None:
                cls._cache.clear()
            else:
                cls._cache.pop(kb_id, None)


__all__ = ["MultimodalVectorStoreFactory"]
