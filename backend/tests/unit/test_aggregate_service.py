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


def test_tenant_user_growth_top_tenants_messages_count():
    """2.1 C.9: top_active_tenants 的 messages 应该真算,不是 None。

    场景:3 个租户,t1 audit 调用 5 次 + messages 12 条,t2 audit 3 次 +
    messages 0 条,t3 audit 1 次 + messages 4 条。验证每个 tenant 的 messages
    字段跟 messages 表聚合结果对齐;audit 调用为 0 / messages 为 0 都不
    该是 None。
    """
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta

    # tenant_user_growth 内部按顺序调 4 个 query:
    #   1. Tenant.count() — 触发 tenant_growth 时间序列
    #   2. User.count()   — 触发 user_growth 时间序列
    #   3. AuditLog group_by tenant_id top 5 — top_active_tenants 的 calls
    #   4. Conversation JOIN Message group_by tenant_id — 真算 messages
    fake_db = _DispatchFakeDB([
        _FakeQuery(rows=[], count=1),                       # Tenant.count() = 1
        _FakeQuery(rows=[], count=1),                       # User.count() = 1
        _FakeQuery(rows=[(1, 5), (2, 3), (3, 1)]),          # audit top rows
        _FakeQuery(rows=[(1, 12), (3, 4)]),                 # msg_rows per tenant
    ])
    svc = AggregateService(db=fake_db)
    out = svc.tenant_user_growth(timedelta(hours=24))

    assert out["top_active_tenants"] == [
        {"tenant_id": 1, "calls": 5, "messages": 12},
        {"tenant_id": 2, "calls": 3, "messages": 0},  # t2 没 messages,但仍是 0 不是 None
        {"tenant_id": 3, "calls": 1, "messages": 4},
    ]


def test_tenant_user_growth_messages_zero_is_zero_not_none():
    """2.1 C.9 关键 regression:即使 messages 数为 0,也该返 int 0 而不是 None。
    前端 dashboard 之前一直显示 null,这个 case 锁死修复语义。
    """
    from lumen_services.aggregate_service import AggregateService
    from datetime import timedelta

    fake_db = _DispatchFakeDB([
        _FakeQuery(rows=[], count=1),     # Tenant.count() = 1
        _FakeQuery(rows=[], count=1),     # User.count() = 1
        _FakeQuery(rows=[(1, 1)]),        # audit: 1 个 tenant, 1 次调用
        _FakeQuery(rows=[]),              # messages: 没有任何 tenant 有消息
    ])
    svc = AggregateService(db=fake_db)
    out = svc.tenant_user_growth(timedelta(hours=24))

    assert len(out["top_active_tenants"]) == 1
    assert out["top_active_tenants"][0] == {"tenant_id": 1, "calls": 1, "messages": 0}


# ---- helpers ----
class _FakeQuery:
    def __init__(self, rows=None, count=0):
        self._rows = rows or []
        self._count = count

    def filter(self, *a, **k): return self
    def join(self, *a, **k): return self
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


class _DispatchFakeDB(_FakeDB):
    """按调用顺序返回不同 row set 的 fake,支持多 query 串行的测试场景。

    比如 ``tenant_user_growth`` 会发两个 query:
      1. audit_logs top
      2. Conversation JOIN Message messages per tenant

    普通的 _FakeDB 不区分 query,会返相同的 rows,只能验 happy path 不能验
    两条 query 各自的语义。本 fake 维护一个 pop 队列,每次 ``query()`` 消耗
    一个 row set;队列空时返空(跟没数据时一样)。
    """

    def __init__(self, queue):
        super().__init__(counts={}, rows=[])
        self._queue = list(queue)

    def query(self, *args):
        if not self._queue:
            return _FakeQuery(rows=[])
        item = self._queue.pop(0)
        if isinstance(item, _FakeQuery):
            return item
        # 兼容纯 row 列表的旧用法
        return _FakeQuery(rows=item)
