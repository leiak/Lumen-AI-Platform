"""M36 T4: Tests for the video_compose workflow node.

These exercise the orchestration that resolves image-URL templates →
local paths → creates the mp4 row → exposes the standard 5 outputs to
the variable pool. The actual FFmpeg compose is mocked to keep the
unit test fast and offline.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.workflow.entities import BaseNodeData
from lumen_core.workflow.nodes.video_compose import (
    VideoComposeNode, VideoComposeNodeData, _resolve_image_to_local_path,
)
from lumen_core.workflow.variable_pool import VariablePool


# ---------- helpers ----------------------------------------------------

def _query_session(mapping):
    """Build a fake Session where ``db.query(X).filter(...).first()`` returns
    a row matching a numeric id extracted from the filter expression.

    Robust to SQLAlchemy 2.x's bind-param stringification (which hides the
    literal value behind ``:id_1``): we walk each filter argument and pull
    the literal via ``BinaryExpression.right.value`` when possible.
    """
    sess = MagicMock()

    def _extract_id_from_arg(arg):
        # BinaryExpression: column == literal — read the literal.
        try:
            from sqlalchemy.sql.elements import BinaryExpression
        except Exception:
            BinaryExpression = None
        if BinaryExpression is not None and isinstance(arg, BinaryExpression):
            try:
                v = arg.right.value
                if isinstance(v, int):
                    return v
            except Exception:
                pass
        # Fallback: regex the str (works for some Column objects, won't
        # be needed for the resolver under test but is harmless).
        import re
        for m in re.finditer(r"(?<![0-9])([0-9]{1,10})(?![0-9])", str(arg)):
            # skip bind-param suffixes like :id_1 — those are placeholder
            # integers we don't want to mistake for the literal.
            tail = str(arg)[max(0, m.start() - 1):m.end() + 1]
            if tail.startswith(":") or tail.endswith("_"):
                continue
            return int(m.group(1))
        return None

    def query(_model):
        q = MagicMock()
        def filter_(*args, **kwargs):
            captured = None
            for a in args:
                captured = _extract_id_from_arg(a)
                if captured is not None:
                    break
            if captured is None:
                for v in kwargs.values():
                    captured = _extract_id_from_arg(v)
                    if captured is not None:
                        break
            if captured is None:
                captured = -1
            f = MagicMock()
            row = mapping.get(captured)
            if row is None:
                f.first.return_value = None
            else:
                f.first.return_value = SimpleNamespace(file_path=row)
            return f
        q.filter.side_effect = filter_
        return q

    sess.query.side_effect = query
    return sess


# ---------- 1. init_node_data + outputs (cheap, no I/O) ---------------

def test_node_init_node_data_parses_config():
    node = VideoComposeNode(
        node_id="vc1",
        config={
            "source_images": ["/tmp/a.png", "/tmp/b.png"],
            "resolution": "640x480",
            "fps": 30,
        },
        pool=VariablePool(),
        db=None, tenant_id=None,
    )
    assert isinstance(node._data, VideoComposeNodeData)
    assert node._data.source_images == ["/tmp/a.png", "/tmp/b.png"]
    assert node._data.resolution == "640x480"
    assert node._data.fps == 30
    assert node._data.audio_path is None


def test_node_outputs_declares_five_vars():
    node = VideoComposeNode(
        node_id="vc1", config={"source_images": []},
        pool=VariablePool(), db=None, tenant_id=None,
    )
    names = [o.name for o in node.outputs()]
    assert names == ["video_id", "video_url", "status", "duration_ms", "file_size"]


# ---------- 2. _resolve_image_to_local_path (3 branches) --------------

def test_resolve_image_to_local_path_returns_none_for_blank():
    db = _query_session({42: "/storage/img/42.png"})
    assert _resolve_image_to_local_path(db, tenant_id=1, value="") is None
    assert _resolve_image_to_local_path(db, tenant_id=1, value="   ") is None


def test_resolve_image_to_local_path_handles_id_only():
    db = _query_session({42: "img/42.png"})
    out = _resolve_image_to_local_path(db, tenant_id=1, value="42")
    # The function returns settings.STORAGE_DIR / <row.file_path>; the exact
    # separator depends on the OS, so accept either Windows or POSIX form.
    assert out is not None
    assert out.replace("\\", "/").endswith("img/42.png")


def test_resolve_image_to_local_path_handles_url_pattern():
    db = _query_session({42: "img/42.png"})
    out = _resolve_image_to_local_path(
        db, tenant_id=1, value="/api/v1/image-generation/42/image",
    )
    assert out is not None
    assert out.replace("\\", "/").endswith("img/42.png")


def test_resolve_image_to_local_path_passes_through_literal_path():
    db = _query_session({})
    out = _resolve_image_to_local_path(
        db, tenant_id=1, value="/some/literal/path.png",
    )
    assert out == "/some/literal/path.png"


def test_resolve_image_to_local_path_returns_none_when_id_missing():
    db = _query_session({})
    out = _resolve_image_to_local_path(
        db, tenant_id=1, value="/api/v1/image-generation/99/image",
    )
    assert out is None


# ---------- 3. _run() end-to-end with mocked compose -------------------

class FakeComposeService:
    last_kwargs = None

    def create_sync_for_workflow(self, db, **kwargs):
        FakeComposeService.last_kwargs = kwargs
        return SimpleNamespace(
            id=123, status="completed",
            duration_ms=4321, file_size=9999,
        ), None


@pytest.mark.asyncio
async def test_node_run_populates_pool_with_all_five_outputs():
    pool = VariablePool()
    pool.add(["in", "image"], "/tmp/upstream.png")

    fake_svc = FakeComposeService()
    with patch(
        "lumen_core.workflow.nodes.video_compose._resolve_image_to_local_path",
        return_value="/tmp/upstream.png",
    ), patch(
        "lumen_core.workflow.nodes.video_compose._resolve_user_id",
        return_value=999,
    ), patch(
        "lumen_services.video_compose_service.VideoComposeService",
        return_value=fake_svc,
    ):
        node = VideoComposeNode(
            node_id="vc",
            config={
                "source_images": ["{{#in.image#}}"],
                "resolution": "640x480",
                "fps": 24,
            },
            pool=pool,
            db=_query_session({}),
            tenant_id=1,
        )
        result = await node._run()

    assert result.error is None
    assert result.output_values == {
        "video_id": 123,
        "video_url": "/api/v1/videos/123/download",
        "status": "completed",
        "duration_ms": 4321,
        "file_size": 9999,
    }
    assert FakeComposeService.last_kwargs["payload"].source_images == ["/tmp/upstream.png"]
    assert FakeComposeService.last_kwargs["tenant_id"] == 1
    assert FakeComposeService.last_kwargs["user_id"] == 999


@pytest.mark.asyncio
async def test_node_run_raises_when_source_images_empty():
    pool = VariablePool()
    node = VideoComposeNode(
        node_id="vc",
        config={"source_images": [], "resolution": "640x480", "fps": 24},
        pool=pool, db=_query_session({}), tenant_id=1,
    )
    with pytest.raises(ValueError, match="source_images 不能为空"):
        await node._run()


@pytest.mark.asyncio
async def test_node_run_raises_when_upstream_image_unresolvable():
    pool = VariablePool()
    pool.add(["in", "image"], "/api/v1/image-generation/999/image")
    with patch(
        "lumen_core.workflow.nodes.video_compose._resolve_image_to_local_path",
        return_value=None,
    ), patch(
        "lumen_core.workflow.nodes.video_compose._resolve_user_id",
        return_value=1,
    ):
        node = VideoComposeNode(
            node_id="vc",
            config={"source_images": ["{{#in.image#}}"]},
            pool=pool, db=_query_session({}), tenant_id=1,
        )
        with pytest.raises(ValueError, match="无法解析"):
            await node._run()


@pytest.mark.asyncio
async def test_node_run_raises_when_no_db_no_tenant():
    """Defensive: the node must require db + tenant_id or refuse to run."""
    pool = VariablePool()
    pool.add(["in", "image"], "/tmp/upstream.png")
    node = VideoComposeNode(
        node_id="vc",
        config={"source_images": ["{{#in.image#}}"]},
        pool=pool, db=None, tenant_id=None,
    )
    with pytest.raises(ValueError, match="必须在工作流执行上下文"):
        await node._run()
