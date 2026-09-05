"""Phase 1 Group B 4.4 Day 3 (2026-09-05):业务路径 manual spans 单测。

覆盖:
1. ``@traced_span`` 装饰器 6 个 case(sync / async / async generator /
   异常 / dynamic attributes / 默认不读 args)
2. 5 个业务路径(chat.stream / embedding.generate × 4 / retrieval.search /
   workflow.run + workflow.node / chat.endpoint / llm.chat)
3. LLM helper 1 个 case(astream 写 ttfb + tokens)

**Pattern**(镜像 ``tests/unit/test_otel_instrumentations.py``):
- autouse fixture:每 test 前 reset OTel,teardown shutdown provider 防
  BatchSpanProcessor 后台线程在 pytest 关闭 stdout 后写 "I/O on closed file"
- 每个 test:``monkeypatch.setenv("OTEL_EXPORTER", "console")`` + 装
  InMemorySpanExporter via SimpleSpanProcessor + 调函数 + 断言 span

**为什么不用 setup_tracing()**:Day 3 不测 SDK 初始化(那是 Day 1 的范畴),
只测手动 span 创建。每个 test 拿一个干净的 TracerProvider + SimpleSpanProcessor
跑测试,跑完清掉 — 隔离更好,跑得更快。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import asyncio
import inspect
import time
from typing import Any, List

import pytest

from lumen_core import otel
from lumen_core.tracing_decorator import traced_span
from lumen_core.tracing import get_trace_id, clear_trace_id


# ---------------------------------------------------------------------------
# Fixture:每 test 一个干净 TracerProvider + InMemorySpanExporter
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _otel_test_env():
    """reset OTel → 起一个干净的 TracerProvider + InMemorySpanExporter。

    teardown:shutdown provider 防 BatchSpanProcessor 后台线程(此处
    不用 Batch,但 future-proof)。
    """
    otel.reset_for_test()
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    in_mem = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(in_mem))
    trace.set_tracer_provider(provider)
    clear_trace_id()

    yield in_mem

    try:
        provider.shutdown()
    except Exception:
        pass
    otel.reset_for_test()


def _spans_by_name(in_mem, name: str) -> list:
    return [s for s in in_mem.get_finished_spans() if s.name == name]


# ===========================================================================
# Part 1: @traced_span 装饰器 — 6 case
# ===========================================================================


def test_traced_span_sync(_otel_test_env):
    """sync 函数:装饰后开 span,attributes_fn 从 args 派生。"""
    in_mem = _otel_test_env

    @traced_span(
        "test.sync",
        attributes={"test.static": "hello"},
        attributes_fn=lambda x, **_: {"test.dyn_x": x},
    )
    def add_one(x: int) -> int:
        return x + 1

    result = add_one(41)
    assert result == 42

    spans = _spans_by_name(in_mem, "test.sync")
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("test.static") == "hello"
    assert attrs.get("test.dyn_x") == 41


def test_traced_span_async(_otel_test_env):
    """async 函数:await 调用,span 正常开/关。"""

    @traced_span("test.async")
    async def coroutine_func() -> str:
        await asyncio.sleep(0.001)
        return "ok"

    result = asyncio.run(coroutine_func())
    assert result == "ok"

    spans = _spans_by_name(_otel_test_env, "test.async")
    assert len(spans) == 1


def test_traced_span_async_generator(_otel_test_env):
    """async generator:跨 yield 保 span active,generator 退出时关 span。"""

    @traced_span("test.async_gen", attributes={"test.gen": True})
    async def gen3() -> Any:
        for i in range(3):
            yield i

    async def _consume():
        out = []
        async for v in gen3():
            out.append(v)
        return out

    items = asyncio.run(_consume())
    assert items == [0, 1, 2]

    spans = _spans_by_name(_otel_test_env, "test.async_gen")
    assert len(spans) == 1
    # 验证 generator 退出时 span 状态 OK(已 end)
    # InMemoryExporter 只收 end 过的 span — 收到说明 end 成功


def test_traced_span_exception_recorded(_otel_test_env):
    """异常:span.status=ERROR + record_exception + reraise。"""

    @traced_span("test.exc")
    def fail() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        fail()

    spans = _spans_by_name(_otel_test_env, "test.exc")
    assert len(spans) == 1
    assert spans[0].status.status_code.name == "ERROR"
    # record_exception 会把异常写到 events
    events = spans[0].events or []
    assert any(e.name == "exception" for e in events)


def test_traced_span_attributes_fn_dynamic(_otel_test_env):
    """attributes_fn 签名跟被装饰函数一致,*args / **kwargs 都接。"""

    @traced_span(
        "test.dyn",
        attributes_fn=lambda *args, **kwargs: {
            "test.arg_count": len(args),
            "test.kw_count": len(kwargs),
            "test.kw_keys": ",".join(sorted(kwargs.keys())),
        },
    )
    def mixed(a, b, *, foo=1, bar=2) -> int:
        return a + b + foo + bar

    assert mixed(1, 2, foo=10, bar=20) == 33

    spans = _spans_by_name(_otel_test_env, "test.dyn")
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("test.arg_count") == 2  # self + 1 + 2 → 实际是 (1, 2)
    assert attrs.get("test.kw_count") == 2
    assert attrs.get("test.kw_keys") == "bar,foo"


def test_traced_span_no_pii_default(_otel_test_env):
    """PII 安全:默认不读 args — 函数接敏感字符串,span 不会记录。

    attributes_fn 不显式抽 args 时,span attributes 只来自静态 attributes。
    """

    @traced_span("test.no_pii", attributes={"test.safe": True})
    def handle_password(pwd: str) -> bool:
        return bool(pwd)

    handle_password("super-secret-12345")

    spans = _spans_by_name(_otel_test_env, "test.no_pii")
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("test.safe") is True
    # 整个 span attributes 不应该出现密码字符串
    all_attrs_str = str(attrs)
    assert "super-secret-12345" not in all_attrs_str


# ===========================================================================
# Part 2: 5 业务路径
# ===========================================================================


def test_chat_stream_span(_otel_test_env, monkeypatch):
    """chat_service.stream_chat_messages 包 ``chat.stream`` span + ttfb event。

    用 MagicMock 替代 ChatOllama 走 async generator 路径,避免真连 ollama。
    """
    from lumen_services.chat_service import ChatService

    in_mem = _otel_test_env

    # 构造 fake astream 异步迭代器,返回 3 个 chunk
    class _FakeChunk:
        def __init__(self, content: str):
            self.content = content

    async def _fake_astream(messages, **kwargs):
        for c in ["Hel", "lo ", "world"]:
            yield _FakeChunk(c)

    class _FakeChatModel:
        model = "fake-model"
        model_name = "fake-model"

        def bind_tools(self, tools):
            # 走 invoke 路径,这里用不到
            return self

        async def astream(self, messages, **kwargs):
            async for c in _fake_astream(messages, **kwargs):
                yield c

        async def ainvoke(self, messages, **kwargs):
            return _FakeChunk("tool-result")

        def invoke(self, messages, **kwargs):
            return _FakeChunk("tool-result")

    service = ChatService.__new__(ChatService)
    service.chat_model = _FakeChatModel()

    async def _consume():
        out = []
        async for chunk in service.stream_chat_messages([{"role": "user", "content": "hi"}]):
            out.append(chunk)
        return out

    chunks = asyncio.run(_consume())
    assert "".join(chunks) == "Hello world"

    # 验证 chat.stream span + ttfb event
    chat_spans = _spans_by_name(in_mem, "chat.stream")
    assert len(chat_spans) == 1
    attrs = dict(chat_spans[0].attributes or {})
    assert attrs.get("chat.model") == "fake-model"
    assert attrs.get("chat.has_tools") is False
    assert attrs.get("chat.messages_count") == 1
    assert attrs.get("chat.chunk_count") == 3
    assert attrs.get("chat.duration_ms", 0) >= 0

    # ttfb event
    events = chat_spans[0].events or []
    ttfb_events = [e for e in events if e.name == "ttfb"]
    assert len(ttfb_events) == 1
    ttfb_attrs = dict(ttfb_events[0].attributes or {})
    assert "llm.ttfb_ms" in ttfb_attrs
    assert ttfb_attrs["llm.ttfb_ms"] >= 0


def test_embedding_span_4_methods(_otel_test_env):
    """LoggingEmbeddings 4 方法各起 1 个 ``embedding.generate`` span,call_kind 不同。

    用 FakeEmbeddings 替代真 embedder,4 个方法都跑通后断言 span 数量 + call_kind。
    """
    from lumen_services.embedding_logging import LoggingEmbeddings

    in_mem = _otel_test_env

    class _FakeEmbeddings:
        """返回固定 dim=4 的 fake embedding vector。"""

        def embed_query(self, text: str) -> List[float]:
            return [0.1, 0.2, 0.3, 0.4]

        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

        async def aembed_query(self, text: str):
            return [0.1, 0.2, 0.3, 0.4]

        async def aembed_documents(self, texts):
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    proxy = LoggingEmbeddings(
        _FakeEmbeddings(),
        model_type="ollama",
        model_name="nomic-embed-text",
        model_config_id=1,
    )

    # 跑 4 个方法 — 不 set EmbeddingCallContext,所以走 "ctx is None" 分支,
    # 但 span 照常起(我们的目的是测 span,不是测 DB row)
    proxy.embed_query("hi")
    proxy.embed_documents(["a", "b"])
    asyncio.run(proxy.aembed_query("hi"))
    asyncio.run(proxy.aembed_documents(["a", "b"]))

    emb_spans = _spans_by_name(in_mem, "embedding.generate")
    assert len(emb_spans) == 4

    # 验证 4 个 call_kind 各 1 个
    call_kinds = sorted(
        dict(s.attributes or {}).get("embedding.call_kind") for s in emb_spans
    )
    assert call_kinds == ["async_documents", "async_query", "sync_documents", "sync_query"]

    # 验证关键 attribute:model / dim / text_chars / batch_size / duration_ms
    for span in emb_spans:
        a = dict(span.attributes or {})
        assert a.get("embedding.model") == "nomic-embed-text"
        assert a.get("embedding.dim") == 4
        assert a.get("embedding.duration_ms", -1) >= 0
        # batch_size 1 是 query;2 是 documents
        if "query" in a["embedding.call_kind"]:
            assert a.get("embedding.batch_size") == 1
            assert a.get("embedding.text_chars") == 2  # "hi"
        else:
            assert a.get("embedding.batch_size") == 2
            assert a.get("embedding.text_chars") == 1 + 1  # "a" + "b" 各 1


def test_retrieval_pipeline_span(_otel_test_env):
    """RetrievalPipeline.search 包 ``retrieval.search`` span,写 doc_count / top_score。"""
    from lumen_services.retrieval.pipeline import RetrievalPipeline

    in_mem = _otel_test_env

    # 构造 fake HybridRetriever + fake Reranker — 不真做向量检索
    class _FakeHybrid:
        is_available = True  # 满足 hasattr check
        vector_weight = 0.5

        def search(self, query, k, filter_expr=None):
            return [
                {"id": "1", "content": "hit-1", "score": 0.95},
                {"id": "2", "content": "hit-2", "score": 0.81},
                {"id": "3", "content": "hit-3", "score": 0.42},
            ]

    class _FakeReranker:
        is_available = False  # 跳过 rerank,直接 slice

        def rerank(self, query, results, top_k):
            return results[:top_k]

    class _FakeVectorStore:
        pass

    pipeline = RetrievalPipeline(
        collection_name="kb_42_mc_1",
        vector_store=_FakeVectorStore(),
        vector_weight=0.5,
        bm25_weight=0.5,
        rerank_enabled=False,
    )
    # 用 fake 替换 hybrid_retriever + reranker
    pipeline.hybrid_retriever = _FakeHybrid()  # type: ignore[assignment]
    pipeline.reranker = _FakeReranker()  # type: ignore[assignment]

    results = pipeline.search("test query", k=3)
    assert len(results) == 3
    assert results[0]["score"] == 0.95

    spans = _spans_by_name(in_mem, "retrieval.search")
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("retrieval.kb_id") == 42
    assert attrs.get("retrieval.collection_name") == "kb_42_mc_1"
    assert attrs.get("retrieval.backend") == "faiss"
    assert attrs.get("retrieval.k") == 3
    assert attrs.get("retrieval.query_chars") == len("test query")
    assert attrs.get("retrieval.doc_count") == 3
    # top_score: 0.95
    assert abs(float(attrs.get("retrieval.top_score", 0)) - 0.95) < 1e-6
    assert attrs.get("retrieval.duration_ms", -1) >= 0


def test_workflow_run_with_node_children(_otel_test_env):
    """WorkflowExecutor.execute:1 个 workflow.run + N 个 workflow.node 子 span。

    用最小 1-node 跑通 → 验证父子关系正确(root 的 children 含 node span)。
    """
    import asyncio
    from lumen_services.workflow_executor import WorkflowExecutor
    from lumen_core.workflow.entities import NodeRunResult

    in_mem = _otel_test_env

    # Mock _instantiate 返回的对象:run() 直接返 success result
    class _FakeNode:
        def __init__(self, node_id, outputs=None):
            self.node_id = node_id
            self.outputs_called = 0
            self._outputs = outputs or {"value": "ok"}
            # executor 把每个 node 的 outputs 写进 VariablePool,给个最小 mock:
            class _FakePool:
                def __init__(self):
                    self._store: dict = {}
                def add(self, key, value):
                    self._store[tuple(key)] = value
                def get(self, key, default=None):
                    return self._store.get(tuple(key), default)
            self.pool = _FakePool()
            # run_node_with_handling 读 instance._data.timeout / retry_config /
            # error_strategy;给个最小 BaseNodeData 即可
            from lumen_core.workflow.entities import BaseNodeData
            from lumen_core.workflow.retry import RetryConfig
            self._data = BaseNodeData(
                timeout=10.0,
                retry_config=RetryConfig(max_retries=0),
                error_strategy="fail_branch",
            )

        async def _run(self, *args, **kwargs):
            # outputs 字段是 list[OutputVar],data 走 output_values(dict)。
            # 跑最小 happy path 不需要真构造 OutputVar — 留空 list。
            return NodeRunResult(
                node_id=self.node_id,
                output_values=self._outputs,
            )

        def outputs(self):
            self.outputs_called += 1
            return self._outputs

        @property
        def output_values(self):
            return self._outputs

    # 用 MagicMock-style 替换 executor._instantiate 让它返 _FakeNode
    executor = WorkflowExecutor()

    def _fake_instantiate(node, tenant_id, user=None):
        return _FakeNode(node["id"])

    executor._instantiate = _fake_instantiate  # type: ignore[method-assign]

    definition = {
        "workflow_id": 1,
        "nodes": [
            {"id": "n1", "type": "llm"},
            {"id": "n2", "type": "output"},
        ],
        "edges": [{"source": "n1", "target": "n2"}],
    }

    result = asyncio.run(
        executor.execute(
            definition=definition,
            input_data={"x": 1},
            tenant_id=1,
            run_id=999,
            db=None,  # type: ignore[arg-type]
            persist_node_runs=False,  # 跳过 DB 写入
        )
    )

    assert result["status"] == "completed"

    # workflow.run span
    run_spans = _spans_by_name(in_mem, "workflow.run")
    assert len(run_spans) == 1
    attrs = dict(run_spans[0].attributes or {})
    assert attrs.get("workflow.run_id") == 999
    assert attrs.get("workflow.workflow_id") == 1
    assert attrs.get("workflow.tenant_id") == 1
    assert attrs.get("workflow.total_nodes") == 2
    assert attrs.get("workflow.status") == "completed"
    assert attrs.get("workflow.duration_ms", -1) >= 0

    # workflow.node spans — 应该 2 个
    node_spans = _spans_by_name(in_mem, "workflow.node")
    assert len(node_spans) == 2

    # 验证父子关系:每个 workflow.node 的 parent_span_id == workflow.run 的 span_id
    run_span_id = run_spans[0].context.span_id
    for ns in node_spans:
        assert ns.parent is not None
        assert ns.parent.span_id == run_span_id


def test_chat_endpoint_span_inside_generator(_otel_test_env):
    """chat.endpoint span 必须在 generate() 内(Phase 0 已 ship 注释解释了为何)。

    这里直接验证装饰器 + helper 模式:endpoint 起 span / contextvar bridge /
    嵌套 span 都在同一个 trace 内(共享 trace_id)。
    """
    # 不能直接 import /chat/stream 路由函数,因为依赖 SQLAlchemy 等太重。
    # 这里测端到端语义:用 span + contextvar bridge + 同 trace 内 child。
    from lumen_core.tracing_decorator import traced_span

    in_mem = _otel_test_env

    async def _run_endpoint_sim():
        """模拟 chat endpoint 内 generator 模式起 span + 嵌套 child span。

        关键:endpoint span 必须用 ``use_span(span, end_on_exit=False)``
        让它成为 OTel current context,后续 child span 才能继承其 trace_id
        (普通的 ``with start_span()`` 不会让 span 成为 current,这是 OTel SDK
        设计 — use_span 显式 activate)。
        """
        from opentelemetry import trace as _otel_trace
        from opentelemetry.trace import use_span
        from lumen_core.tracing_decorator import _set_contextvar_from_span

        _endpoint_span = _otel_trace.get_tracer("lumen.manual").start_span(
            "chat.endpoint",
            attributes={
                "chat.endpoint": "/chat/stream",
                "chat.user_id": 1,
                "chat.tenant_id": 1,
            },
        )
        _set_contextvar_from_span(_endpoint_span)
        try:
            # use_span 显式 activate,让后续 child span 继承 trace_id
            with use_span(_endpoint_span, end_on_exit=False):
                with _otel_trace.get_tracer("lumen.manual").start_span(
                    "chat.stream", attributes={"chat.has_tools": False}
                ):
                    pass
            return get_trace_id()
        finally:
            _endpoint_span.end()

    tid = asyncio.run(_run_endpoint_sim())
    assert tid is not None  # contextvar 同步成功

    # 验证两个 span 共享 trace_id
    endpoint_span = _spans_by_name(in_mem, "chat.endpoint")[0]
    stream_span = _spans_by_name(in_mem, "chat.stream")[0]
    assert endpoint_span.context.trace_id == stream_span.context.trace_id
    # 父子关系
    assert stream_span.parent is not None
    assert stream_span.parent.span_id == endpoint_span.context.span_id


def test_llm_chat_helper_records_ttfb(_otel_test_env):
    """LoggingChatModel.astream:helper 起 llm.chat span + 写 llm.ttfb_ms + llm.tokens。

    关键 attribute:
    - llm.call_kind == "astream"
    - llm.model
    - llm.ttfb_ms(首 chunk 后)
    - llm.tokens(从 response.usage_metadata 抽)
    - llm.duration_ms
    """
    from lumen_services.model_loader import LoggingChatModel

    in_mem = _otel_test_env

    class _FakeChunk:
        def __init__(self, content: str, usage_metadata: dict = None):
            self.content = content
            self.usage_metadata = usage_metadata or {}
            self.tool_calls: List[dict] = []
            self.response_metadata = {}

    class _FakeInnerModel:
        async def astream(self, messages, **kwargs):
            # 3 chunk 模拟流式 — 第三个 chunk 带 usage_metadata
            yield _FakeChunk("a")
            await asyncio.sleep(0.001)
            yield _FakeChunk("b")
            await asyncio.sleep(0.001)
            yield _FakeChunk(
                "c",
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            )

    proxy = LoggingChatModel(
        _FakeInnerModel(),
        model_type="ollama",
        model_name="qwen2.5:7b",
    )

    async def _consume():
        out = []
        async for chunk in proxy.astream([{"role": "user", "content": "hi"}]):
            out.append(chunk)
        return out

    asyncio.run(_consume())

    spans = _spans_by_name(in_mem, "llm.chat")
    assert len(spans) == 1
    attrs = dict(spans[0].attributes or {})
    assert attrs.get("llm.call_kind") == "astream"
    assert attrs.get("llm.model") == "qwen2.5:7b"
    assert attrs.get("llm.ttfb_ms", -1) >= 0
    # tokens 从 usage_metadata 抽(extract_usage 把 input_tokens→prompt_tokens,
    # output_tokens→completion_tokens,total_tokens 保持)
    assert attrs.get("llm.tokens.total_tokens") == 15
    assert attrs.get("llm.tokens.prompt_tokens") == 10
    assert attrs.get("llm.tokens.completion_tokens") == 5
    # 兼容 attribute:llm.tokens(数字)
    assert attrs.get("llm.tokens") == 15
    assert attrs.get("llm.duration_ms", -1) >= 0
