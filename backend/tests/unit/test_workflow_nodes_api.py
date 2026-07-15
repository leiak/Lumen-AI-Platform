"""P2 workflow node preview endpoints: HTTPNode preview happy/error path.

We mock HTTPNode._run() in the workflow_nodes module so the test never
hits the network — the goal is to verify the preview endpoint's contract
(envelope shape + 500-on-error) end-to-end, not re-test the HTTPNode
itself (already covered by test_workflow_node_p2.py and
test_workflow_node_p2_http_integration.py).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_preview_http_happy_path(client, auth_header, monkeypatch):
    """Mocked _run returns a known NodeRunResult; endpoint should surface
    it as 200 with the expected SingleResponse envelope shape."""
    from lumen_core.workflow import nodes as nodes_pkg
    from lumen_core.workflow.entities import NodeRunResult

    captured: dict = {}

    class _FakeHTTPNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            captured["node_id"] = node_id
            captured["config"] = config
            captured["pool_type"] = type(pool).__name__
            captured["db"] = db
            captured["tenant_id"] = tenant_id

        async def _run(self):
            return NodeRunResult(
                node_id=captured["node_id"],
                output_values={
                    "status_code": 200,
                    "headers": {"content-type": "application/json"},
                    "body": {"ok": True, "echoed": captured["config"]["url"]},
                    "error": None,
                },
            )

    # Patch both the symbol in workflow_nodes and in the http submodule,
    # since `from lumen_core.workflow.nodes.http import HTTPNode` rebinds the
    # name in the http module's namespace.
    monkeypatch.setattr("lumen_api.v1.workflow_nodes.HTTPNode", _FakeHTTPNode)
    monkeypatch.setattr(nodes_pkg.http, "HTTPNode", _FakeHTTPNode)

    r = client.post(
        "/api/v1/workflows/nodes/http/preview",
        headers=auth_header,
        json={"method": "GET", "url": "https://example.test/api"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["message"] == "ok"
    data = body["data"]
    assert data["status_code"] == 200
    assert data["headers"] == {"content-type": "application/json"}
    assert data["body"] == {"ok": True, "echoed": "https://example.test/api"}
    assert data["error"] is None

    # Verify the endpoint wired the node correctly: empty pool, real db
    # session, real tenant_id from the JWT user, payload dumped as config.
    assert captured["node_id"] == "preview"
    assert captured["config"]["method"] == "GET"
    assert captured["config"]["url"] == "https://example.test/api"
    assert captured["pool_type"] == "VariablePool"
    assert captured["tenant_id"] == 1
    assert captured["db"] is not None


def test_preview_http_error_returns_500(client, auth_header, monkeypatch):
    """A network error inside _run() must surface as HTTP 500 with the
    exception message, NOT a 200 with an embedded error string."""
    from lumen_core.workflow import nodes as nodes_pkg

    class _BoomNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            pass

        async def _run(self):
            # Simulate httpx.ConnectError shape (message matters for the
            # contract: callers read the detail string).
            raise ConnectionError("Failed to connect to example.test:443")

    monkeypatch.setattr("lumen_api.v1.workflow_nodes.HTTPNode", _BoomNode)
    monkeypatch.setattr(nodes_pkg.http, "HTTPNode", _BoomNode)

    r = client.post(
        "/api/v1/workflows/nodes/http/preview",
        headers=auth_header,
        json={"method": "GET", "url": "https://example.test/api"},
    )
    assert r.status_code == 500
    assert "HTTP preview failed" in r.json()["detail"]
    assert "example.test:443" in r.json()["detail"]


def test_preview_http_requires_auth(client):
    """No Authorization header → 401 from get_current_user."""
    r = client.post(
        "/api/v1/workflows/nodes/http/preview",
        json={"method": "GET", "url": "https://example.test/api"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# KnowledgeRetrievalNode preview
# ---------------------------------------------------------------------------


def test_preview_kb_happy_path(client, auth_header, monkeypatch):
    """Mocked _run returns a known NodeRunResult; endpoint should surface
    it as 200 with chunks/count/error in the envelope."""
    from lumen_core.workflow import nodes as nodes_pkg
    from lumen_core.workflow.entities import NodeRunResult

    captured: dict = {}

    class _FakeKBNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            captured["node_id"] = node_id
            captured["config"] = config
            captured["pool_type"] = type(pool).__name__
            captured["db"] = db
            captured["tenant_id"] = tenant_id

        async def _run(self):
            return NodeRunResult(
                node_id=captured["node_id"],
                output_values={
                    "chunks": [
                        {
                            "chunk_id": "c1",
                            "content": "first chunk text",
                            "score": 0.92,
                            "source": "doc-1",
                            "metadata": {"page": 1},
                        },
                        {
                            "chunk_id": "c2",
                            "content": "second chunk text",
                            "score": 0.81,
                            "source": "doc-1",
                            "metadata": {"page": 2},
                        },
                        {
                            "chunk_id": "c3",
                            "content": "third chunk text",
                            "score": 0.74,
                            "source": "doc-2",
                            "metadata": {"page": 5},
                        },
                    ],
                    "merged_text": "should not leak into response",
                    "count": 3,
                    "error": None,
                },
            )

    # Patch both the symbol in workflow_nodes and in the knowledge_retrieval
    # submodule (mirror of the HTTP dual-patch).
    monkeypatch.setattr("lumen_api.v1.workflow_nodes.KnowledgeRetrievalNode", _FakeKBNode)
    monkeypatch.setattr(nodes_pkg.knowledge_retrieval, "KnowledgeRetrievalNode", _FakeKBNode)

    r = client.post(
        "/api/v1/workflows/nodes/knowledge-retrieval/preview",
        headers=auth_header,
        json={"kb_id": 3, "query": "what is RAG?", "top_k": 5, "score_threshold": 0.0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["message"] == "ok"
    data = body["data"]
    assert data["count"] == 3
    assert data["error"] is None
    assert isinstance(data["chunks"], list)
    assert len(data["chunks"]) == 3
    assert data["chunks"][0]["chunk_id"] == "c1"
    assert data["chunks"][0]["content"] == "first chunk text"
    # merged_text is intentionally NOT exposed by KBPreviewResponse (per plan).
    assert "merged_text" not in data

    # Verify the endpoint wired the node correctly.
    assert captured["node_id"] == "preview"
    assert captured["config"]["kb_id"] == 3
    assert captured["config"]["query"] == "what is RAG?"
    assert captured["config"]["top_k"] == 5
    assert captured["config"]["score_threshold"] == 0.0
    assert captured["pool_type"] == "VariablePool"
    assert captured["tenant_id"] == 1
    assert captured["db"] is not None


def test_preview_kb_error_returns_500(client, auth_header, monkeypatch):
    """A missing/inactive KB or other failure inside _run() must surface as
    HTTP 500 with the exception message, NOT a 200 with an embedded error."""
    from lumen_core.workflow import nodes as nodes_pkg

    class _BoomKBNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            pass

        async def _run(self):
            raise ValueError("KB 999 not found or inactive")

    monkeypatch.setattr("lumen_api.v1.workflow_nodes.KnowledgeRetrievalNode", _BoomKBNode)
    monkeypatch.setattr(nodes_pkg.knowledge_retrieval, "KnowledgeRetrievalNode", _BoomKBNode)

    r = client.post(
        "/api/v1/workflows/nodes/knowledge-retrieval/preview",
        headers=auth_header,
        json={"kb_id": 999, "query": "anything", "top_k": 5, "score_threshold": 0.0},
    )
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "KB preview failed" in detail
    assert "KB 999 not found or inactive" in detail


def test_preview_kb_requires_auth(client):
    """No Authorization header → 401 from get_current_user."""
    r = client.post(
        "/api/v1/workflows/nodes/knowledge-retrieval/preview",
        json={"kb_id": 3, "query": "what is RAG?", "top_k": 5, "score_threshold": 0.0},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# TemplateTransformNode preview
# ---------------------------------------------------------------------------


def test_preview_template_happy_path(client, auth_header, monkeypatch):
    """Mocked _run returns a known NodeRunResult; endpoint should surface
    it as 200 with output/error in the envelope.

    Also verifies that `sample_context` is translated into VariablePool
    entries (per the plan: top-level keys → node_ids, inner dict keys →
    var_names), so designers can preview a template with realistic
    upstream-node values.
    """
    from lumen_core.workflow import nodes as nodes_pkg
    from lumen_core.workflow.entities import NodeRunResult

    captured: dict = {}

    class _FakeTemplateNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            captured["node_id"] = node_id
            captured["config"] = config
            captured["pool_type"] = type(pool).__name__
            captured["db"] = db
            captured["tenant_id"] = tenant_id
            captured["pool_snapshot"] = pool.snapshot()

        async def _run(self):
            return NodeRunResult(
                node_id=captured["node_id"],
                output_values={
                    "output": (
                        "Hello "
                        + captured["pool_snapshot"]
                        .get("llm", {})
                        .get("response", "?")
                    ),
                    "error": None,
                },
            )

    # Patch both the symbol in workflow_nodes and in the template_transform
    # submodule (mirror of the HTTP/KB dual-patch).
    monkeypatch.setattr(
        "lumen_api.v1.workflow_nodes.TemplateTransformNode", _FakeTemplateNode
    )
    monkeypatch.setattr(
        nodes_pkg.template_transform, "TemplateTransformNode", _FakeTemplateNode
    )

    r = client.post(
        "/api/v1/workflows/nodes/template-transform/preview",
        headers=auth_header,
        json={
            "template": "Hello {{ llm.response }}",
            "sample_context": {"llm": {"response": "world"}},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["message"] == "ok"
    data = body["data"]
    assert data["output"] == "Hello world"
    assert data["error"] is None

    # Verify the endpoint wired the node correctly: config holds ONLY the
    # template (NOT the sample_context, which is for pool population only).
    assert captured["node_id"] == "preview"
    assert captured["config"] == {"template": "Hello {{ llm.response }}"}
    assert captured["pool_type"] == "VariablePool"
    assert captured["tenant_id"] == 1
    assert captured["db"] is not None
    # sample_context was translated into VariablePool entries.
    assert captured["pool_snapshot"] == {"llm": {"response": "world"}}


def test_preview_template_error_returns_500(client, auth_header, monkeypatch):
    """A Jinja2 undefined-variable / template-syntax error inside _run()
    must surface as HTTP 500 with the exception message, NOT a 200 with
    an embedded error string."""
    from lumen_core.workflow import nodes as nodes_pkg

    class _BoomTemplateNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            pass

        async def _run(self):
            # Mirrors the ValueError raised by TemplateTransformNode._run
            # when a Jinja2 StrictUndefined variable is missing.
            raise ValueError("Template error: undefined variable")

    monkeypatch.setattr(
        "lumen_api.v1.workflow_nodes.TemplateTransformNode", _BoomTemplateNode
    )
    monkeypatch.setattr(
        nodes_pkg.template_transform, "TemplateTransformNode", _BoomTemplateNode
    )

    r = client.post(
        "/api/v1/workflows/nodes/template-transform/preview",
        headers=auth_header,
        json={"template": "Hello {{ missing.x }}"},
    )
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "Template preview failed" in detail
    assert "Template error" in detail


def test_preview_template_requires_auth(client):
    """No Authorization header → 401 from get_current_user."""
    r = client.post(
        "/api/v1/workflows/nodes/template-transform/preview",
        json={"template": "Hello world"},
    )
    assert r.status_code == 401


def test_preview_template_with_scalars_uses_value_key(client, auth_header, monkeypatch):
    """When `sample_context` has a non-dict value for a node_id (e.g. a
    scalar), the endpoint must wrap it under the "value" key so the pool
    can index it. This is the plan's `else` branch:
        pool.add([k, "value"], v)
    """
    from lumen_core.workflow import nodes as nodes_pkg

    captured: dict = {}

    class _FakeTemplateNode:
        def __init__(self, node_id, config, pool, db, tenant_id):
            captured["pool_snapshot"] = pool.snapshot()

        async def _run(self):
            # Return a placeholder; we only care about the pool.
            from lumen_core.workflow.entities import NodeRunResult
            return NodeRunResult(
                node_id="preview",
                output_values={"output": "ok", "error": None},
            )

    monkeypatch.setattr(
        "lumen_api.v1.workflow_nodes.TemplateTransformNode", _FakeTemplateNode
    )
    monkeypatch.setattr(
        nodes_pkg.template_transform, "TemplateTransformNode", _FakeTemplateNode
    )

    r = client.post(
        "/api/v1/workflows/nodes/template-transform/preview",
        headers=auth_header,
        json={
            "template": "ok",
            "sample_context": {"llm": "hello"},  # scalar, not dict
        },
    )
    assert r.status_code == 200, r.text
    # Scalar wrapped under "value" key.
    assert captured["pool_snapshot"] == {"llm": {"value": "hello"}}
