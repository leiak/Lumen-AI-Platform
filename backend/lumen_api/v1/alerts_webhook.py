"""Phase 1 Group B 2.4.7 / B2c (2026-09-04):Alertmanager webhook receiver.

Webhook sink for the Alertmanager → Lumen pipeline. Alertmanager POSTs an array
of ``Alert`` objects (``{"status": "firing"|"resolved", "labels": {...},
"annotations": {...}, "startsAt": "...", "endsAt": "..."}``) to
``/api/v1/alerts/webhook``.

Local dev: the Alertmanager container (port 19093) is wired to ``host.docker
.internal:11335`` (the uvicorn host port). Production: the same URL shape,
swap the host. No JWT — the route is reachable only from inside the docker
network, and the Alertmanager instance is the only client.

For each firing alert we:

1. Write ``backend/storage/alerts/<fingerprint>.json`` with the full payload
   so an external script can aggregate / forward to PagerDuty / Slack.
2. Log one structured line per alert via the root logger (uvicorn picks it
   up under the JSON formatter) — operator dashboards grep for
   ``alerts_webhook received``.
3. Return ``200 OK`` with an envelope describing how many alerts were
   persisted so Alertmanager marks the notification as delivered.

Resolved alerts (``status == "resolved"``) are also logged + written so a
postmortem timeline can show "fired at X, resolved at Y".
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request, status

from lumen_core.config import settings
from lumen_schemas.common import SingleResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


# Alertmanager ``fingerprint`` is documented to be a stable hash of labels —
# safe to use as a filename. Defensively strip any path separators that an
# attacker-supplied label value might smuggle in (defence in depth even
# though AM is the only caller).
_SAFE_FINGERPRINT = re.compile(r"[^A-Za-z0-9_\-.]")


def _get_alerts_dir() -> Path:
    """Return the directory where the webhook receiver persists alerts.

    Wrapped in a function (instead of reading ``settings.ALERTS_DIR``
    directly in the handler) so tests can ``monkeypatch.setattr`` this
    one symbol without fighting Pydantic's property accessor.

    Mirrors the lazy-``mkdir`` semantics of ``Settings.STORAGE_DIR`` —
    always returns an existing directory so the caller can write without
    a separate ``makedirs`` step.
    """
    d = settings.ALERTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_fingerprint(fp: str | None, fallback: str) -> str:
    """Normalize an Alertmanager fingerprint into a safe filename stem.

    Alertmanager's own fingerprints are stable hex hashes, but we don't want
    a misconfigured label value (e.g. ``fingerprint = "../../etc/passwd"``)
    to escape the alerts dir. If sanitisation removes everything, fall back
    to ``fallback`` (``alert-<index>``).
    """
    if not fp:
        return fallback
    cleaned = _SAFE_FINGERPRINT.sub("_", fp)
    if not cleaned:
        return fallback
    return cleaned


@router.post("/webhook", response_model=SingleResponse[Dict[str, Any]])
async def receive_alertmanager_webhook(request: Request) -> SingleResponse[Dict[str, Any]]:
    """Receive an Alertmanager webhook payload.

    Body schema (see https://prometheus.io/docs/alerting/latest/configuration/#webhook_config):

    ::

        {
          "version": "4",
          "groupKey": "<string>",
          "status": "<resolved|firing>",
          "receiver": "<string>",
          "groupLabels": {"<labelname>": "<labelvalue>"},
          "commonLabels": {"<labelname>": "<labelvalue>"},
          "commonAnnotations": {"<annotationname>": "<annotationvalue>"},
          "externalURL": "<string>",
          "alerts": [{
            "status": "<resolved|firing>",
            "labels": {"<labelname>": "<labelvalue>"},
            "annotations": {"<annotationname>": "<annotationvalue>"},
            "startsAt": "<rfc3339>",
            "endsAt": "<rfc3339>",
            "generatorURL": "<string>",
            "fingerprint": "<string>"
          }]
        }
    """
    if not settings.ALERTS_WEBHOOK_ENABLED:
        # Don't silently swallow — let Alertmanager retry. Operators can
        # disable via env when rehearsing a webhook drain.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="alerts webhook disabled (ALERTS_WEBHOOK_ENABLED=false)",
        )

    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        logger.warning("alerts_webhook received invalid JSON: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid JSON body: {e}",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook body must be a JSON object",
        )

    alerts: List[Dict[str, Any]] = payload.get("alerts") or []
    if not alerts:
        # An empty ``alerts`` array is unusual but not an error — log and
        # ack so AM doesn't keep retrying.
        logger.info("alerts_webhook received empty alerts array (status=%s)", payload.get("status"))
        return SingleResponse(
            data={"received": 0, "persisted": 0, "firing": 0, "resolved": 0},
            message="empty alerts array, nothing to persist / Accepted",
        )

    alerts_dir: Path = _get_alerts_dir()
    persisted = 0
    firing = 0
    resolved = 0

    for idx, alert in enumerate(alerts):
        if not isinstance(alert, dict):
            logger.warning("alerts_webhook: skipping non-dict alert #%d", idx)
            continue

        alert_status = alert.get("status", "unknown")
        if alert_status == "firing":
            firing += 1
        elif alert_status == "resolved":
            resolved += 1

        labels = alert.get("labels") or {}
        annotations = alert.get("annotations") or {}
        alert_name = labels.get("alertname", "<unknown>")
        severity = labels.get("severity", "unknown")
        slo = labels.get("slo", "-")

        fp = _safe_fingerprint(alert.get("fingerprint"), fallback=f"alert-{idx}")
        path = alerts_dir / f"{fp}.json"

        # Include the envelope fields too — gives external consumers the
        # ``status`` / ``externalURL`` / ``commonLabels`` without needing
        # the original AM tree.
        envelope = {
            "received_at": alert.get("startsAt"),
            "status": alert_status,
            "alert": alert,
            "envelope": {
                "status": payload.get("status"),
                "receiver": payload.get("receiver"),
                "externalURL": payload.get("externalURL"),
                "commonLabels": payload.get("commonLabels") or {},
                "commonAnnotations": payload.get("commonAnnotations") or {},
                "groupKey": payload.get("groupKey"),
            },
        }

        try:
            path.write_text(
                json.dumps(envelope, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            persisted += 1
        except OSError as e:
            # Log and continue — one failed file shouldn't drop the whole batch.
            logger.error(
                "alerts_webhook failed to persist alert fp=%s alertname=%s: %s",
                fp, alert_name, e,
            )
            continue

        # Structured log line for uvicorn / log shippers.
        summary = annotations.get("summary") or annotations.get("description") or ""
        logger.warning(
            "alerts_webhook received alertname=%s severity=%s slo=%s status=%s "
            "fp=%s summary=%s",
            alert_name, severity, slo, alert_status, fp, summary,
        )

    logger.info(
        "alerts_webhook batch done: received=%d persisted=%d firing=%d resolved=%d",
        len(alerts), persisted, firing, resolved,
    )
    return SingleResponse(
        data={
            "received": len(alerts),
            "persisted": persisted,
            "firing": firing,
            "resolved": resolved,
        },
        message=f"Accepted {persisted}/{len(alerts)} alerts / 已接收 {persisted}/{len(alerts)} 条告警",
    )