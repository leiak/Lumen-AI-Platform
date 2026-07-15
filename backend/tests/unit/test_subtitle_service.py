"""Tests for SubtitleService and pure-Python SRT generation.

Spec: docs-internal/superpowers/specs/M35-overview.md §5
"""
import uuid

import pytest

from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.subtitle import Subtitle
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.subtitle_service import (
    build_srt,
    _total_duration_from_srt,
    SubtitleService,
)


@pytest.fixture
def db_session():
    """Yield a fresh SessionLocal, ensuring tenant id=1 exists.

    The M35 table chain (subtitles → generated_audios → conversations)
    requires all parent tables to be loaded into ``Base.metadata``
    before ``create_all`` runs. We import the model modules in
    dependency order, then ``create_all`` resolves the FK graph.
    Idempotent in MySQL.
    """
    from lumen_core.database import Base, engine
    # Register all M35 FK chain in Base.metadata
    from lumen_models.chat import Conversation
    from lumen_models.model_config import ModelConfig
    from lumen_models.tts import GeneratedAudio
    from lumen_models.subtitle import Subtitle
    from lumen_models.playbook import Playbook
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant); db.commit(); db.refresh(tenant)
        yield db
    finally:
        db.close()


# ---- SRT builder -----------------------------------------------------------

def test_build_srt_basic_zh():
    """Basic Chinese script produces SRT with correct structure."""
    srt = build_srt("你好世界。这是第二句话。", total_duration_ms=4000, language="zh-CN")
    assert "-->" in srt
    # 2 sentences → 2 cues
    assert srt.count("-->") == 2
    # CRLF line endings (SRT spec requirement)
    assert "\r\n" in srt
    # End timestamp matches target within 0ms (last cue exactly hits target)
    total = _total_duration_from_srt(srt)
    assert total == 4000


def test_build_srt_basic_en():
    """Basic English script produces SRT."""
    srt = build_srt(
        "Hello world. This is the second sentence.",
        total_duration_ms=5000, language="en-US",
    )
    assert "-->" in srt
    assert _total_duration_from_srt(srt) == 5000


def test_build_srt_empty_script_raises():
    with pytest.raises(ValueError):
        build_srt("", total_duration_ms=5000)


def test_build_srt_too_short_duration_raises():
    with pytest.raises(ValueError):
        build_srt("hello", total_duration_ms=500)


def test_build_srt_long_sentence_split():
    """Long sentence (60+ chars) splits into smaller cues via commas.

    The splitter first splits on sentence-final punctuation, then falls
    back to commas / whitespace, and finally to a hard char-boundary
    split when nothing else applies. We use a text with commas here
    because that's the realistic case for a long narration.
    """
    long_sentence = (
        "这是第一段非常非常非常非常非常非常非常非常非常非常非常长的描述，"
        "这是第二段内容，也是非常长的描述，"
        "这是第三段内容，继续非常长的描述，"
        "这是最后一段话。"
    )
    srt = build_srt(long_sentence, total_duration_ms=30000, language="zh-CN")
    # Should produce more than 1 cue due to comma splits
    assert srt.count("-->") > 1
    assert _total_duration_from_srt(srt) == 30000


def test_build_srt_total_duration_exact():
    """End timestamp equals total_duration_ms exactly (0ms error)."""
    for dur in (1000, 3000, 7000, 12345):
        srt = build_srt("第一句。第二句。第三句。", total_duration_ms=dur)
        assert _total_duration_from_srt(srt) == dur


def test_build_srt_mixed_zh_en():
    """Mixed zh/en script handles without error."""
    srt = build_srt(
        "你好 world. 这是一个 AI 助手。",
        total_duration_ms=5000, language="zh-CN",
    )
    assert "-->" in srt
    assert _total_duration_from_srt(srt) == 5000


def test_build_srt_newline_separator():
    """Newlines also split cues."""
    srt = build_srt("第一行\n第二行\n第三行", total_duration_ms=3000)
    assert srt.count("-->") >= 2


def test_build_srt_timestamp_format():
    """SRT timestamps are HH:MM:SS,mmm."""
    import re
    srt = build_srt("测试。", total_duration_ms=2500)
    # Match `00:00:00,000 --> 00:00:02,500` style
    pat = re.compile(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")
    assert pat.search(srt), f"No valid timestamp in: {srt}"


# ---- SubtitleService (DB-backed) ------------------------------------------

def test_subtitle_service_persists_row(db_session):
    """SubtitleService.generate_from_script persists a Subtitle row."""
    suffix = uuid.uuid4().hex[:8]
    db = db_session
    tenant = Tenant(name=f"sub_test_{suffix}", code=f"sub_test_{suffix}")
    db.add(tenant); db.commit(); db.refresh(tenant)
    user = User(
        username=f"sub_user_{suffix}",
        email=f"sub_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant.id, is_active=True,
    )
    db.add(user); db.commit(); db.refresh(user)

    svc = SubtitleService()
    row = svc.generate_from_script(
        db, tenant_id=tenant.id, user_id=user.id,
        script="测试脚本。", total_duration_ms=2000,
    )
    assert row.id is not None
    assert row.cue_count == 1
    assert row.duration_ms == 2000
    assert row.language == "zh-CN"
    assert row.tenant_id == tenant.id

    # Cleanup
    db.query(Subtitle).filter(Subtitle.id == row.id).delete(synchronize_session=False)
    db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
    db.commit()


def test_subtitle_service_list_tenant_isolation(db_session):
    """list_for_tenant filters by tenant_id."""
    suffix = uuid.uuid4().hex[:8]
    db = db_session
    t1 = Tenant(name=f"sub_iso_t1_{suffix}", code=f"sub_iso_t1_{suffix}")
    t2 = Tenant(name=f"sub_iso_t2_{suffix}", code=f"sub_iso_t2_{suffix}")
    db.add_all([t1, t2]); db.commit()
    db.refresh(t1); db.refresh(t2)
    u1 = User(
        username=f"sub_iso_u1_{suffix}",
        email=f"sub_iso_u1_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t1.id, is_active=True,
    )
    db.add(u1); db.commit(); db.refresh(u1)

    svc = SubtitleService()
    sub = svc.generate_from_script(
        db, tenant_id=t1.id, user_id=u1.id,
        script="测试。", total_duration_ms=1000,
    )

    rows_t1, total_t1 = svc.list_for_tenant(db, tenant_id=t1.id)
    rows_t2, total_t2 = svc.list_for_tenant(db, tenant_id=t2.id)
    assert total_t1 >= 1
    assert all(r.tenant_id == t1.id for r in rows_t1)
    # Tenant 2 sees nothing of tenant 1's subtitles
    assert not any(r.tenant_id == t1.id for r in rows_t2)

    # Cleanup
    db.query(Subtitle).filter(Subtitle.id == sub.id).delete(synchronize_session=False)
    db.query(User).filter(User.id == u1.id).delete(synchronize_session=False)
    db.query(Tenant).filter(Tenant.id.in_([t1.id, t2.id])).delete(synchronize_session=False)
    db.commit()