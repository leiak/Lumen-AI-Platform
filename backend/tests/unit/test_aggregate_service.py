from datetime import timedelta
import pytest


def test_range_to_window_1h():
    from lumen_services.aggregate_service import AggregateService
    assert AggregateService.range_to_window("1h") == timedelta(hours=1)


def test_range_to_window_24h():
    from lumen_services.aggregate_service import AggregateService
    assert AggregateService.range_to_window("24h") == timedelta(hours=24)


def test_range_to_window_7d():
    from lumen_services.aggregate_service import AggregateService
    assert AggregateService.range_to_window("7d") == timedelta(days=7)


def test_range_to_window_30d():
    from lumen_services.aggregate_service import AggregateService
    assert AggregateService.range_to_window("30d") == timedelta(days=30)


def test_range_to_window_invalid_raises():
    from lumen_services.aggregate_service import AggregateService
    with pytest.raises(ValueError):
        AggregateService.range_to_window("99h")


def test_aggregate_service_can_be_constructed():
    from lumen_services.aggregate_service import AggregateService
    svc = AggregateService(db=None)
    assert svc is not None


def test_overview_empty_db_returns_zeros(monkeypatch):
    from lumen_services.aggregate_service import AggregateService
    from datetime import datetime, timedelta
    fake_db = _FakeDB(counts={}, rows=[])
    svc = AggregateService(db=fake_db)
    out = svc.overview(timedelta(hours=24))
    assert out["total_tenants"] == 0
    assert out["active_tenants"] == 0
    assert out["total_agents"] == 0
    assert out["ai_calls"] == 0
    assert out["ai_errors"] == 0
    assert out["ai_error_rate"] == 0.0
    assert out["top_tenants"] == []
    assert "audit" in out["data_source_note"]


def test_knowledge_summary_empty_db(monkeypatch):
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta
    fake_db = _FakeDB(counts={}, rows=[])
    svc = AggregateService(db=fake_db)
    out = svc.knowledge_summary(timedelta(hours=24))
    assert out["total_kbs"] == 0
    assert out["total_documents"] == 0
    assert out["total_chunks"] == 0
    assert out["parse_failed"] == 0
    assert out["by_status"] == []


def test_ai_calls_series_empty_db():
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta
    fake_db = _FakeDB(counts={}, rows=[])
    svc = AggregateService(db=fake_db)
    out = svc.ai_calls_series(timedelta(hours=24), "hour")
    assert out["series"] == []
    assert out["by_model"] == []


def test_workflow_summary_empty_db():
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta
    fake_db = _FakeDB(counts={}, rows=[])
    svc = AggregateService(db=fake_db)
    out = svc.workflow_summary(timedelta(hours=24))
    assert out["total_workflows"] == 0
    assert out["total_runs"] == 0
    assert out["success"] == 0
    assert out["failed"] == 0
    assert out["cancelled"] == 0
    assert out["by_node_type"] == []


def test_tenant_user_growth_empty_db():
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta
    fake_db = _FakeDB(counts={}, rows=[])
    svc = AggregateService(db=fake_db)
    out = svc.tenant_user_growth(timedelta(hours=24))
    assert out["tenant_growth"] == []
    assert out["user_growth"] == []
    assert out["top_active_tenants"] == []


# ---- helpers ----
class _FakeQuery:
    def __init__(self, rows=None, count=0):
        self._rows = rows or []
        self._count = count

    def filter(self, *a, **k): return self
    def group_by(self, *a): return self
    def order_by(self, *a): return self
    def limit(self, *a): return self
    def all(self): return self._rows
    def count(self): return self._count
    def scalar(self): return None


class _FakeDB:
    def __init__(self, counts=None, rows=None):
        self._counts = counts or {}
        self._rows = rows or []

    def query(self, *args):
        key = getattr(args[0], "__name__", str(args[0])) if args else "Unknown"
        return _FakeQuery(rows=self._rows, count=self._counts.get(key, 0))
