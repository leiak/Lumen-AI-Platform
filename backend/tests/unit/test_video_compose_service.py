"""M36 T3: Tests for VideoComposeService business logic.

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md §4
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock

# M36 video FK resolution: pre-import every model that GeneratedVideo
# FKs into. Without this, Base.metadata is missing the target tables
# when create_all() runs (NoReferencedTableError, see MEMORY 2026-06-26).
import lumen_models.chat  # noqa: F401  (generated_videos.conversation_id)
import lumen_models.model_config  # noqa: F401
import lumen_models.playbook  # noqa: F401
import lumen_models.tts  # noqa: F401  (generated_videos.source_audio_id)
import lumen_models.subtitle  # noqa: F401  (generated_videos.source_subtitle_id)
import lumen_models.video  # noqa: F401  (this module)

import pytest
from fastapi import BackgroundTasks

from lumen_core.database import SessionLocal, ensure_generated_videos_table
from lumen_core.security import get_password_hash
from lumen_core.config import settings
from lumen_schemas.video import VideoComposeCreate
from lumen_services.video_compose_service import (
    AssetNotFound,
    VideoComposeService,
    _resolve_asset_to_path,
    _resolve_image_paths,
    _resolve_image_to_local_path,
    _resolve_image_gen_to_path,
    _resolve_stock_image_to_path,
)
from lumen_models.video import GeneratedVideo
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    ensure_generated_videos_table()
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            t = Tenant(id=1, name="Default Tenant", code="default")
            db.add(t); db.commit(); db.refresh(t)
        yield db
    finally:
        db.close()


def _make_tenant_user(db, suffix):
    t = Tenant(name=f"vcs_t_{suffix}", code=f"vcs_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    u = User(
        username=f"vcs_u_{suffix}",
        email=f"vcs_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t.id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return t, u


@pytest.fixture
def clean_rows():
    rows = []
    yield rows
    if not rows:
        return
    db = SessionLocal()
    try:
        db.query(GeneratedVideo).filter(GeneratedVideo.id.in_(rows)).delete(
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def test_create_empty_sources_returns_empty_sources_err(db_session):
    svc = VideoComposeService()
    payload = VideoComposeCreate(source_images=[])
    bg = BackgroundTasks()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1, payload=payload, background_tasks=bg,
    )
    assert row is None
    assert err == "empty_sources"


def test_create_writes_pending_row_and_schedules_bg_task(db_session, clean_rows):
    """create() persists the row in pending and adds a _run_composition task."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    try:
        svc = VideoComposeService()
        payload = VideoComposeCreate(source_images=["/tmp/a.png"])
        bg = BackgroundTasks()
        row, err = svc.create(
            db_session,
            tenant_id=tenant.id, user_id=user.id,
            payload=payload, background_tasks=bg,
        )
        assert err is None
        assert row is not None
        assert row.status == "pending"
        assert row.source_images == ["/tmp/a.png"]
        # Background task is queued.
        assert len(bg.tasks) == 1
        clean_rows.append(row.id)
    finally:
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_create_sync_for_workflow_returns_compose_inline_error_on_empty(db_session):
    """sync variant mirrors the empty_sources error tag."""
    svc = VideoComposeService()
    payload = VideoComposeCreate(source_images=[])
    row, err = svc.create_sync_for_workflow(
        db_session, tenant_id=1, user_id=1, payload=payload,
    )
    assert row is None
    assert err == "empty_sources"


def test_resolve_asset_to_path_returns_none_for_blank_string(db_session):
    """None / "" / "  " → returns None (caller treats as no asset)."""
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value=None) is None
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value="") is None
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value="  ") is None


def test_resolve_asset_to_path_passes_through_literal_path(db_session):
    """Non-numeric strings are returned as-is (treated as local paths)."""
    p = "/tmp/audio_that_does_not_exist.mp3"
    out = _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value=p)
    assert out == p


def test_resolve_asset_to_path_audio_id_not_found_raises(db_session):
    """Numeric audio id with no row → AssetNotFound('audio_not_found')."""
    with pytest.raises(AssetNotFound) as info:
        _resolve_asset_to_path(
            db_session, tenant_id=1, kind="audio", value="999999",
        )
    assert info.value.tag == "audio_not_found"


def test_resolve_asset_to_path_subtitle_id_writes_tmp_srt(db_session, clean_rows):
    """Numeric subtitle id → writes SRT body to storage/_tmp/subtitles/ and returns path."""
    from lumen_models.subtitle import Subtitle
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    sub = Subtitle(
        tenant_id=tenant.id, user_id=user.id,
        source_type="script", language="zh-CN", format="srt",
        content="1\n00:00:00,000 --> 00:00:01,000\nhello\n\n",
        cue_count=1, duration_ms=1000,
    )
    db_session.add(sub); db_session.commit(); db_session.refresh(sub)
    try:
        out_path = _resolve_asset_to_path(
            db_session, tenant_id=tenant.id, kind="subtitle", value=str(sub.id),
        )
        assert out_path is not None
        p = Path(out_path)
        assert p.exists()
        # File body matches the row's content.
        assert p.read_text(encoding="utf-8") == sub.content
        assert p.suffix == ".srt"
    finally:
        try:
            db_session.delete(sub); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_cancel_returns_false_for_completed_row(db_session, clean_rows):
    """cancel() refuses to flip rows in terminal status."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    row = GeneratedVideo(
        tenant_id=tenant.id, user_id=user.id,
        source_images=["/tmp/a.png"], resolution="1280x720", fps=24,
        file_path="x.mp4", file_size=1, mime_type="video/mp4",
        status="completed",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    clean_rows.append(row.id)
    try:
        svc = VideoComposeService()
        ok = svc.cancel(
            db_session, tenant_id=tenant.id, user_id=user.id, video_id=row.id,
        )
        assert ok is False
        # Row status did not change.
        db_session.refresh(row)
        assert row.status == "completed"
    finally:
        try:
            db_session.delete(row); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_cancel_flips_pending_row_to_cancelled(db_session, clean_rows):
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    row = GeneratedVideo(
        tenant_id=tenant.id, user_id=user.id,
        source_images=["/tmp/a.png"], resolution="1280x720", fps=24,
        file_path="x.mp4", file_size=1, mime_type="video/mp4",
        status="pending",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    clean_rows.append(row.id)
    try:
        svc = VideoComposeService()
        ok = svc.cancel(
            db_session, tenant_id=tenant.id, user_id=user.id, video_id=row.id,
        )
        assert ok is True
        db_session.refresh(row)
        assert row.status == "cancelled"
        assert row.finished_at is not None
    finally:
        try:
            db_session.delete(row); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


# ======================================================================
# M36.2.1 / follow-up: image URL resolution helpers
# ======================================================================


def test_resolve_image_to_local_path_passes_through_blank(db_session):
    """空白 / None / 不像 URL 也不像 id → None。"""
    assert _resolve_image_to_local_path(db_session, tenant_id=1, value="") is None
    assert _resolve_image_to_local_path(db_session, tenant_id=1, value="   ") is None
    # 字面路径原样返回(workflow node 预解析过的也走这条)
    p = "/tmp/raw_local_path.png"
    assert _resolve_image_to_local_path(db_session, tenant_id=1, value=p) == p


def test_resolve_image_gen_url_to_local_path(db_session, clean_rows):
    """``/api/v1/image-generation/{id}/image`` → 磁盘绝对路径。"""
    from lumen_models.image_generation import GeneratedImage
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    img = GeneratedImage(
        tenant_id=tenant.id, user_id=user.id,
        file_path="generated_images/abc.png",
        mime_type="image/png", width=10, height=10, file_size=100,
    )
    db_session.add(img); db_session.commit(); db_session.refresh(img)
    try:
        url = f"http://localhost:11335/api/v1/image-generation/{img.id}/image"
        out = _resolve_image_to_local_path(db_session, tenant_id=tenant.id, value=url)
        assert out is not None
        # 用 pathlib.Path(随 OS)直接拿 name 和 parts,不被 backslash 翻成根目录。
        from pathlib import Path
        p = Path(out)
        assert p.name == "abc.png"
        assert any(part == "generated_images" for part in p.parts)
        # 完整 STORAGE_DIR 前缀
        expected_abs = str(settings.STORAGE_DIR / "generated_images" / "abc.png")
        assert out == expected_abs
    finally:
        try:
            db_session.delete(img); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_resolve_image_gen_digit_to_local_path(db_session, clean_rows):
    """纯数字字符串(legacy 兼容)→ GeneratedImage.id 查表。"""
    from lumen_models.image_generation import GeneratedImage
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    img = GeneratedImage(
        tenant_id=tenant.id, user_id=user.id,
        file_path="generated_images/digit.png",
        mime_type="image/png", width=10, height=10, file_size=100,
    )
    db_session.add(img); db_session.commit(); db_session.refresh(img)
    try:
        out = _resolve_image_to_local_path(db_session, tenant_id=tenant.id, value=str(img.id))
        assert out is not None
        from pathlib import Path
        p = Path(out)
        assert p.name == "digit.png"
        assert any(part == "generated_images" for part in p.parts)
    finally:
        try:
            db_session.delete(img); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_resolve_stock_url_to_local_path(db_session, clean_rows):
    """``/api/v1/stock-assets/{id}/image`` → StockAsset 路径(M36.2.1)。"""
    # stock_asset 表 ensure_created
    from lumen_core.database import ensure_stock_assets_table
    from lumen_models.stock_asset import StockAsset
    ensure_stock_assets_table()
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    stock = StockAsset(
        tenant_id=tenant.id, name=f"stock_{suffix}", category="风景",
        file_path=f"stock_assets/{suffix}.png",
        mime_type="image/png", width=10, height=10, file_size=100,
        source="tenant",
    )
    db_session.add(stock); db_session.commit(); db_session.refresh(stock)
    try:
        url = f"/api/v1/stock-assets/{stock.id}/image"
        out = _resolve_image_to_local_path(db_session, tenant_id=tenant.id, value=url)
        assert out is not None
        from pathlib import Path
        p = Path(out)
        assert p.name == f"{suffix}.png"
        assert any(part == "stock_assets" for part in p.parts)
    finally:
        try:
            db_session.delete(stock); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_resolve_stock_global_visible_to_any_tenant(db_session, clean_rows):
    """stock tenant_id=NULL 全局 builtin,任何 tenant 都看得见。"""
    from lumen_core.database import ensure_stock_assets_table
    from lumen_models.stock_asset import StockAsset
    ensure_stock_assets_table()
    suffix = uuid.uuid4().hex[:8]
    tenant_a, user_a = _make_tenant_user(db_session, f"a_{suffix}")
    stock = StockAsset(
        tenant_id=None, name=f"global_{suffix}", category="风景",
        file_path=f"stock_assets/global_{suffix}.png",
        mime_type="image/png", width=10, height=10, file_size=100,
        source="builtin",
    )
    db_session.add(stock); db_session.commit(); db_session.refresh(stock)
    try:
        url = f"/api/v1/stock-assets/{stock.id}/image"
        out = _resolve_image_to_local_path(db_session, tenant_id=tenant_a.id, value=url)
        assert out is not None
        from pathlib import Path
        p = Path(out)
        assert p.name == f"global_{suffix}.png"
        assert any(part == "stock_assets" for part in p.parts)
    finally:
        try:
            db_session.delete(stock); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user_a); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant_a); db_session.commit()
        except Exception:
            db_session.rollback()


def test_resolve_image_url_returns_none_for_unknown_id(db_session):
    """不存在的 id → None(由 _resolve_image_paths 抛 AssetNotFound)。"""
    out = _resolve_image_to_local_path(
        db_session, tenant_id=1, value="/api/v1/image-generation/999999/image",
    )
    assert out is None
    out2 = _resolve_image_to_local_path(
        db_session, tenant_id=1, value="/api/v1/stock-assets/999999/image",
    )
    assert out2 is None
    out3 = _resolve_image_to_local_path(db_session, tenant_id=1, value="999999")
    assert out3 is None


def test_resolve_image_gen_to_path_isolated_helper(db_session, clean_rows):
    """``_resolve_image_gen_to_path`` 自身(URL 形态的细节函数)。"""
    from lumen_models.image_generation import GeneratedImage
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    img = GeneratedImage(
        tenant_id=tenant.id, user_id=user.id,
        file_path="generated_images/x.png",
        mime_type="image/png", width=10, height=10, file_size=100,
    )
    db_session.add(img); db_session.commit(); db_session.refresh(img)
    try:
        out = _resolve_image_gen_to_path(
            db_session, tenant_id=tenant.id, image_id=img.id,
        )
        assert out is not None
        from pathlib import Path
        p = Path(out)
        assert p.name == "x.png"
        assert any(part == "generated_images" for part in p.parts)
    finally:
        try:
            db_session.delete(img); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_resolve_image_paths_empty_strings_are_skipped(db_session):
    """空字符串被跳过(workflow template render 出空字符串时不报错)。"""
    out = _resolve_image_paths(
        db_session, tenant_id=1, paths=["", "  ", "/tmp/abc.png"],
    )
    assert out == ["/tmp/abc.png"]


def test_resolve_image_paths_raises_on_unknown_url(db_session):
    """任一 URL/digit 解不到 → AssetNotFound('image_not_found')。"""
    with pytest.raises(AssetNotFound) as info:
        _resolve_image_paths(
            db_session, tenant_id=1,
            paths=["/api/v1/image-generation/999999/image"],
        )
    assert info.value.tag == "image_not_found"


def test_create_image_url_not_found_returns_image_not_found_tag(db_session):
    """service.create() 顶层把 image_not_found 错误 tag 透传出来。"""
    svc = VideoComposeService()
    payload = VideoComposeCreate(
        source_images=["/api/v1/image-generation/999999/image"],
    )
    bg = BackgroundTasks()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1, payload=payload, background_tasks=bg,
    )
    assert row is None
    assert err == "image_not_found"
    assert len(bg.tasks) == 0  # 没排队
