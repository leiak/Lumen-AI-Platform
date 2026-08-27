"""KnowledgeRetrievalNode — 复用 P1 RAG retrieval pipeline。

P1 spec:``docs/2026-05-27-vector-search-upgrades.md`` + ``services/retrieval/pipeline.py``。
跨租户隔离:``KnowledgeBase.tenant_id == self.tenant_id`` 且 ``status == "active"``。

设计要点:
- ``get_retrieval_pipeline`` 是模块级 import(在文件顶部),测试通过
  ``monkeypatch.setattr("lumen_services.retrieval.get_retrieval_pipeline", ...)`` 替换。
- 真实 ``RetrievalPipeline.search`` 的签名是
  ``(query, k=5, filter_expr=None, rerank=None)``,本节点:
  * 把 ``tenant_id`` / ``kb_id`` / ``score_threshold`` 折叠进 ``filter_expr``;
  * ``rerank_enabled`` 透传到 ``rerank``;
  * ``hybrid_search`` 是 ``**kwargs`` 透传 — 真实 pipeline 暂时忽略(它本身永远是 hybrid),
    fake pipeline 记录下来给测试断言。
- 真实 pipeline 不支持额外 kwargs 时,使用 ``inspect`` 过滤,避免 ``TypeError``。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any

from pydantic import ConfigDict

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_models.knowledge import KnowledgeBase
# 通过模块引用而不是 ``from ... import`` 局部绑定,这样
# ``monkeypatch.setattr("lumen_services.retrieval.get_retrieval_pipeline", ...)``
# 才能在本节点上看到效果(局部导入是早绑定的)。
from lumen_services import retrieval as _retrieval_svc  # noqa: F401  (re-exported for tests)
from lumen_services.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)


class KnowledgeRetrievalNodeData(BaseNodeData):
    """KnowledgeRetrievalNode 的强类型配置。

    Fields
    ------
    kb_id:
        引用 ``KnowledgeBase.id``。0/未设置 = 未选择,运行时会抛 ``ValueError``。
    kb_name_cache:
        前端展示用名称(供 UI 回显,不影响执行)。
    query:
        检索 query 模板,字符串值会通过 ``VariableTemplateParser`` 渲染
        ``{{#node_id.var#}}`` 模板。
    top_k:
        召回 chunk 数。
    score_threshold:
        最低分阈值(0.0 = 不过滤)。大于 0 时折叠进 filter_expr。
    rerank_enabled:
        是否启用 rerank。透传到 ``RetrievalPipeline.search(rerank=...)``。
    hybrid_search:
        是否启用 hybrid 检索(向量 + BM25)。真实 pipeline 始终 hybrid,
        此字段为 ``**kwargs`` 透传给 pipeline 留作未来扩展;fake pipeline 记录下来给测试。
    """

    model_config = ConfigDict(extra="ignore")
    kb_id: int = 0
    kb_name_cache: str = ""
    query: str = ""
    top_k: int = 5
    score_threshold: float = 0.0
    rerank_enabled: bool = True
    hybrid_search: bool = True


class KnowledgeRetrievalNode(BaseNode):
    """对选定的知识库做 hybrid + rerank + score-threshold 检索。"""

    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return KnowledgeRetrievalNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="chunks", type=SegmentType.ARRAY_OBJECT, description="检索结果数组"),
            OutputVar(name="merged_text", type=SegmentType.STRING, description="拼接后文本"),
            OutputVar(name="count", type=SegmentType.NUMBER, description="chunk 数"),
            OutputVar(name="error", type=SegmentType.STRING, description="错误信息"),
        ]

    def _build_filter_expr(self, kb_id: int) -> str:
        """把 ``tenant_id`` / ``kb_id`` / ``score_threshold`` 拼成 filter_expr。

        真实 ``RetrievalPipeline.search`` 通过 ``_normalise_filter`` 解析
        ``tenant_id == X and kb_id == Y``,score 部分被忽略(预留给 ES DSL 扩展)。
        """
        assert isinstance(self._data, KnowledgeRetrievalNodeData)
        d = self._data
        parts = [
            f"tenant_id == {self.tenant_id}",
            f"kb_id == {kb_id}",
        ]
        if d.score_threshold > 0:
            parts.append(f"score >= {d.score_threshold}")
        return " and ".join(parts)

    def _build_search_kwargs(self, query: str, kb_id: int) -> dict[str, Any]:
        """构造 ``pipeline.search(**kwargs)`` 调用的 kwargs,过滤真实签名不支持的键。"""
        assert isinstance(self._data, KnowledgeRetrievalNodeData)
        d = self._data

        # ``search_weights`` 从 KB row 读取 — M28 之前这个值已经存到
        # ``KnowledgeBase.search_weights`` (JSON column),但检索子系统忽略。
        # 这里只是把它从调用方传到 pipeline;真实签名(``RetrievalPipeline.search``)
        # 才有这个 kwarg,``_FakePipeline`` 通过 ``**kw`` 也接住。
        kb_search_weights = None
        if self.db is not None:
            try:
                _kb = (
                    self.db.query(KnowledgeBase)
                    .filter(KnowledgeBase.id == kb_id)
                    .first()
                )
                if _kb is not None:
                    kb_search_weights = getattr(_kb, "search_weights", None)
            except Exception:  # pragma: no cover - 防御性
                kb_search_weights = None

        base_kwargs: dict[str, Any] = {
            "query": query,
            "k": d.top_k,
            "filter_expr": self._build_filter_expr(kb_id),
            "rerank": d.rerank_enabled,
            "score_threshold": d.score_threshold,
            "hybrid": d.hybrid_search,
            "tenant_id": self.tenant_id,
            "kb_id": kb_id,
            "search_weights": kb_search_weights,
        }

        # 如果真实 pipeline 用 **kwargs 接住 extras(fake pipeline 也是),全传;
        # 否则只传真实签名支持的 4 个键,避免 TypeError。
        # 直接读 class-level 签名(无需实例化,避免触发 BM25Index / HybridRetriever / reranker 初始化,
        # 也避免污染 ``_pipelines`` 缓存)。
        try:
            sig = inspect.signature(RetrievalPipeline.search)
        except (TypeError, ValueError):  # pragma: no cover - 防御性
            sig = None

        if sig is None:
            return base_kwargs
        has_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if has_var_kw:
            return base_kwargs
        # 只保留真实签名里的关键字参数
        real_params = {p for p in sig.parameters if p != "self"}
        return {k: v for k, v in base_kwargs.items() if k in real_params}

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, KnowledgeRetrievalNodeData)
        d: KnowledgeRetrievalNodeData = self._data

        # M38.2.x v2: 未选 KB 不再 throw,改为返空 result(spec §5.2.1 graceful skip)
        # —— workflow 不应该因为一个空配置节点就整个中断。
        empty_result = lambda reason: NodeRunResult(  # noqa: E731
            node_id=self.node_id,
            output_values={
                "chunks": [],
                "merged_text": "",
                "count": 0,
                "error": reason,
            },
        )
        if not d.kb_id:
            return empty_result(f"KB {d.kb_id} not found or inactive")

        if self.db is None:
            return empty_result("KnowledgeRetrievalNode 需要 db session 才能查找知识库")

        kb = (
            self.db.query(KnowledgeBase)
            .filter(KnowledgeBase.id == d.kb_id, KnowledgeBase.status == "active")
            .first()
        )
        # 跨租户隔离:即使 SQL 命中,tenant_id 不匹配也视为未找到。
        if kb is not None and self.tenant_id is not None and kb.tenant_id != self.tenant_id:
            kb = None
        if not kb:
            return empty_result(f"KB {d.kb_id} not found or inactive")

        # M38.2.x v2: per-KB ``kb.read`` 过滤。``user is None`` 走 graceful open
        # (widget / 系统 cron / 老 fixture 不传 user)。
        kb_workspace_id = getattr(kb, "workspace_id", None)
        if self.user is not None and kb_workspace_id is not None:
            from lumen_services.permission_service import PermissionService
            if not PermissionService().check(
                self.db, self.user, "kb.read", kb_workspace_id,
            ):
                logger.info(
                    "KnowledgeRetrievalNode skip KB %s: user %s no kb.read",
                    kb.id, getattr(self.user, "id", None),
                )
                return empty_result("permission_denied")

        query = VariableTemplateParser(d.query).format(self.pool)
        # M28 后 ``get_retrieval_pipeline`` 签名是 3-arg ``(kb_id, model_config_id, db)``,
        # 走 per-(kb_id) 缓存 + per-(kb_id, model_config_id) 的 ES collection name。
        pipeline = _retrieval_svc.get_retrieval_pipeline(
            kb_id=kb.id,
            model_config_id=kb.embedding_model_config_id,
            db=self.db,
        )
        call_kwargs = self._build_search_kwargs(query, kb.id)  # type: ignore[arg-type]
        # 真实 ``RetrievalPipeline.search`` 是同步方法,测试 fake 是 async;
        # 两种都支持 — 用 ``isawaitable`` 决定要不要 await。
        _search_result = pipeline.search(**call_kwargs)
        if inspect.isawaitable(_search_result):
            results: list[dict[str, Any]] = await _search_result
        else:
            results = _search_result

        chunks = [
            {
                "chunk_id": r.get("id"),
                "content": r.get("text", r.get("content", "")),
                "score": r.get("score", r.get("distance", 0.0)),
                "source": r.get("source"),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ]
        merged = "\n\n---\n\n".join(c["content"] for c in chunks)
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "chunks": chunks,
                "merged_text": merged,
                "count": len(chunks),
                "error": None,
            },
        )
