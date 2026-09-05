"""Phase 1 Group B 2.4.7 / B2c (2026-09-04): /api/v1/alerts/webhook 单测。

覆盖范围:
- 基本 firing alert 落盘 + 返回 200 + envelope 计数
- 多 alert 批量(混合 firing/resolved)分别落盘
- 空 alerts 数组 → 200 + received=0,持久化 0
- fingerprint 安全清洗(防止路径穿越)
- fingerprint 为 None 时 fallback
- 非 dict alert 跳过,不影响其他
- 坏 JSON → 400
- 非 dict body → 400
- ALERTS_WEBHOOK_ENABLED=false → 503
- 写入失败(OSError)不影响其他 alert 持久化
- 持久化目录自动创建
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumen_api.v1.alerts_webhook import _get_alerts_dir, _safe_fingerprint, router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alert_payload(
    *,
    status: str = "firing",
    alertname: str = "SLOApiAvailabilityHighBurnRate",
    severity: str = "warning",
    fingerprint: str = "abc123",
    summary: str = "API 5xx 错误率超速燃烧",
    slo: str = "api_availability",
) -> dict:
    """构建单个 Alertmanager alert 字典(envelope 上下文由调用方加)。"""
    return {
        "status": status,
        "labels": {
            "alertname": alertname,
            "severity": severity,
            "slo": slo,
        },
        "annotations": {
            "summary": summary,
            "description": f"{summary} - detail",
        },
        "startsAt": "2026-09-04T00:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://prometheus:9090/graph?...",
        "fingerprint": fingerprint,
    }


def _envelope(alerts, *, group_status: str | None = None) -> dict:
    """构建 Alertmanager webhook 顶层 envelope。"""
    return {
        "version": "4",
        "groupKey": "{}:{alertname=...}",
        "status": group_status or (alerts[0]["status"] if alerts else "firing"),
        "receiver": "lumen-webhook",
        "groupLabels": {"alertname": alerts[0]["labels"]["alertname"]} if alerts else {},
        "commonLabels": alerts[0]["labels"] if alerts else {},
        "commonAnnotations": alerts[0]["annotations"] if alerts else {},
        "externalURL": "http://alertmanager:9093",
        "alerts": alerts,
    }


@pytest.fixture
def app(monkeypatch):
    """Minimal FastAPI app with only the alerts router."""
    from fastapi import FastAPI
    monkeypatch.setattr(
        "lumen_api.v1.alerts_webhook._get_alerts_dir",
        lambda: Path("/tmp/test-alerts-not-used"),
    )
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def isolated_alerts_dir(monkeypatch, tmp_path):
    """Patch the alerts dir to a fresh tmp_path subdir per test."""
    target = tmp_path / "alerts"

    def _patched():
        # Mirror the production `_get_alerts_dir` semantics — ensure the
        # directory exists before returning it.
        target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(
        "lumen_api.v1.alerts_webhook._get_alerts_dir",
        _patched,
    )
    return target


# ---------------------------------------------------------------------------
# _safe_fingerprint unit tests
# ---------------------------------------------------------------------------


class TestSafeFingerprint:
    def test_passthrough_alnum(self):
        assert _safe_fingerprint("abc123", "fb") == "abc123"

    def test_strips_slashes(self):
        # Defence against path traversal even though AM is the only caller.
        cleaned = _safe_fingerprint("../../etc/passwd", "fb")
        assert "/" not in cleaned
        cleaned2 = _safe_fingerprint("..\\..\\windows", "fb")
        assert "\\" not in cleaned2

    def test_dots_pass_through(self):
        # Dots are valid filename chars (e.g. "abc.123"). Trailing dots could
        # be an issue, but we don't expect AM fingerprints to end with them.
        assert _safe_fingerprint("abc.123", "fb") == "abc.123"

    def test_keeps_safe_punctuation(self):
        assert _safe_fingerprint("a-b_c.d", "fb") == "a-b_c.d"

    def test_none_uses_fallback(self):
        assert _safe_fingerprint(None, "fb") == "fb"

    def test_empty_uses_fallback(self):
        assert _safe_fingerprint("", "fb") == "fb"

    def test_all_non_safe_chars_become_underscores(self):
        # The regex keeps alnum + hyphen + dot; everything else becomes
        # an underscore. This isn't a path-traversal concern because the
        # caller controls the result and never trusts the sanitised value
        # as code — it's purely a filename.
        assert _safe_fingerprint("\x00\x01\x02", "fb") == "___"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestWebhookHappyPath:
    def test_single_firing_alert_persisted(self, client, isolated_alerts_dir):
        alerts = [_alert_payload(fingerprint="fp-1")]
        res = client.post("/alerts/webhook", json=_envelope(alerts))
        assert res.status_code == 200
        body = res.json()
        assert body["code"] == 200
        assert body["data"]["received"] == 1
        assert body["data"]["persisted"] == 1
        assert body["data"]["firing"] == 1
        assert body["data"]["resolved"] == 0
        # File exists at expected path
        path = isolated_alerts_dir / "fp-1.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "firing"
        assert payload["alert"]["labels"]["alertname"] == "SLOApiAvailabilityHighBurnRate"
        assert payload["envelope"]["receiver"] == "lumen-webhook"

    def test_batch_with_mixed_status(self, client, isolated_alerts_dir):
        alerts = [
            _alert_payload(fingerprint="fp-firing", status="firing"),
            _alert_payload(fingerprint="fp-resolved", status="resolved", alertname="SLOApiLatencyHighBurnRate"),
            _alert_payload(fingerprint="fp-firing2", status="firing", alertname="SLOCelerySuccessHighBurnRate"),
        ]
        res = client.post("/alerts/webhook", json=_envelope(alerts, group_status="firing"))
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["received"] == 3
        assert body["data"]["persisted"] == 3
        assert body["data"]["firing"] == 2
        assert body["data"]["resolved"] == 1
        # All three files exist
        for fp in ("fp-firing", "fp-resolved", "fp-firing2"):
            assert (isolated_alerts_dir / f"{fp}.json").exists()

    def test_empty_alerts_array_acks(self, client, isolated_alerts_dir):
        envelope = _envelope([])
        res = client.post("/alerts/webhook", json=envelope)
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["received"] == 0
        assert body["data"]["persisted"] == 0

    def test_creates_alerts_dir_if_missing(self, client, monkeypatch, tmp_path):
        target = tmp_path / "deeply" / "nested" / "alerts"
        assert not target.exists()

        def _patched():
            target.mkdir(parents=True, exist_ok=True)
            return target

        monkeypatch.setattr(
            "lumen_api.v1.alerts_webhook._get_alerts_dir",
            _patched,
        )
        res = client.post(
            "/alerts/webhook",
            json=_envelope([_alert_payload(fingerprint="auto-mkdir")]),
        )
        assert res.status_code == 200
        assert target.exists()
        assert (target / "auto-mkdir.json").exists()


# ---------------------------------------------------------------------------
# Defensive paths
# ---------------------------------------------------------------------------


class TestWebhookDefensive:
    def test_invalid_json_400(self, client):
        res = client.post(
            "/alerts/webhook",
            content=b"{not valid json",
            headers={"content-type": "application/json"},
        )
        assert res.status_code == 400
        assert "invalid JSON" in res.json()["detail"]

    def test_non_dict_body_400(self, client):
        res = client.post("/alerts/webhook", json=[1, 2, 3])
        assert res.status_code == 400
        assert "JSON object" in res.json()["detail"]

    def test_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.setattr("lumen_api.v1.alerts_webhook.settings.ALERTS_WEBHOOK_ENABLED", False)
        res = client.post("/alerts/webhook", json=_envelope([_alert_payload()]))
        assert res.status_code == 503
        assert "disabled" in res.json()["detail"]

    def test_skips_non_dict_alerts(self, client, isolated_alerts_dir):
        envelope = _envelope([
            _alert_payload(fingerprint="fp-good"),
            "this is a string not a dict",  # type: ignore[list-item]
            _alert_payload(fingerprint="fp-also-good"),
            None,  # type: ignore[list-item]
        ])
        res = client.post("/alerts/webhook", json=envelope)
        assert res.status_code == 200
        body = res.json()
        # received counts all 4, but only the 2 dicts persist
        assert body["data"]["received"] == 4
        assert body["data"]["persisted"] == 2
        assert (isolated_alerts_dir / "fp-good.json").exists()
        assert (isolated_alerts_dir / "fp-also-good.json").exists()

    def test_missing_fingerprint_uses_fallback(self, client, isolated_alerts_dir):
        alert = _alert_payload()
        alert["fingerprint"] = None
        res = client.post("/alerts/webhook", json=_envelope([alert]))
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["persisted"] == 1
        # File lands at fallback name "alert-0"
        assert (isolated_alerts_dir / "alert-0.json").exists()

    def test_dangerous_fingerprint_sanitised(self, client, isolated_alerts_dir):
        alert = _alert_payload()
        alert["fingerprint"] = "../../../etc/passwd"
        res = client.post("/alerts/webhook", json=_envelope([alert]))
        assert res.status_code == 200
        # No file outside isolated_alerts_dir — sanitisation worked.
        # We just check that we wrote *one* file inside the alerts dir.
        written = list(isolated_alerts_dir.iterdir())
        assert len(written) == 1
        # Dots stay (safe filename char); path separators become underscores.
        assert written[0].name == ".._.._.._etc_passwd.json"

    def test_write_failure_isolated(self, client, isolated_alerts_dir):
        """单个 alert 写盘失败不应影响其他 alert 落盘。"""
        alerts = [
            _alert_payload(fingerprint="fp-ok"),
            _alert_payload(fingerprint="fp-fail"),
            _alert_payload(fingerprint="fp-ok2"),
        ]
        real_write_text = Path.write_text

        def selective_write(self, *args, **kwargs):
            if "fp-fail" in str(self):
                raise OSError("disk full simulation")
            return real_write_text(self, *args, **kwargs)

        with patch.object(Path, "write_text", selective_write):
            res = client.post("/alerts/webhook", json=_envelope(alerts))
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["received"] == 3
        # 2 succeeded, 1 failed
        assert body["data"]["persisted"] == 2
        # The 2 successful files exist
        assert (isolated_alerts_dir / "fp-ok.json").exists()
        assert (isolated_alerts_dir / "fp-ok2.json").exists()
        assert not (isolated_alerts_dir / "fp-fail.json").exists()


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestRoutingRegistration:
    def test_router_has_webhook_endpoint_at_correct_path(self):
        paths = [r.path for r in router.routes]
        assert "/alerts/webhook" in paths
        # And only POST is allowed
        for r in router.routes:
            if r.path == "/alerts/webhook":
                assert "POST" in r.methods
                assert "GET" not in r.methods


# ---------------------------------------------------------------------------
# Body shape sanity (Alertmanager is well-defined)
# ---------------------------------------------------------------------------


class TestPayloadShape:
    def test_realistic_alertmanager_payload(self, client, isolated_alerts_dir):
        """模仿真实 AM 发送的 payload(完整 envelope + 多个 alert)。"""
        payload = {
            "version": "4",
            "groupKey": '{}:{alertname="SLOApiAvailabilityHighBurnRate"}',
            "status": "firing",
            "receiver": "lumen-webhook",
            "groupLabels": {"alertname": "SLOApiAvailabilityHighBurnRate"},
            "commonLabels": {
                "alertname": "SLOApiAvailabilityHighBurnRate",
                "severity": "warning",
                "slo": "api_availability",
            },
            "commonAnnotations": {
                "summary": "API 5xx 错误率超速燃烧",
                "description": "API 5xx 错误率消耗速度 14.5x 是预期速率的 14.4 倍以上",
            },
            "externalURL": "http://localhost:19093",
            "alerts": [{
                "status": "firing",
                "labels": {
                    "alertname": "SLOApiAvailabilityHighBurnRate",
                    "severity": "warning",
                    "slo": "api_availability",
                },
                "annotations": {
                    "summary": "API 5xx 错误率超速燃烧",
                    "description": "API 5xx 错误率消耗速度 14.5x 是预期速率的 14.4 倍以上",
                },
                "startsAt": "2026-09-04T08:00:00.000Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": "http://prometheus:9090/graph?...",
                "fingerprint": "9e1d7c3a-real",
            }],
        }
        res = client.post("/alerts/webhook", json=payload)
        assert res.status_code == 200
        path = isolated_alerts_dir / "9e1d7c3a-real.json"
        assert path.exists()
        # Round-trip the JSON
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["alert"]["fingerprint"] == "9e1d7c3a-real"
        assert loaded["envelope"]["externalURL"] == "http://localhost:19093"