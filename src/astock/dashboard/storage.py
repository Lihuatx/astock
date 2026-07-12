from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from astock.observability.bundle import canonical_json, validate_live_status, validate_review_bundle


SCHEMA_VERSION = 1


class DashboardStore:
    def __init__(self, path: Path, bundle_root: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        bundle_root.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.bundle_root = bundle_root
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bundles (
                bundle_id TEXT PRIMARY KEY,
                trading_day TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                strategy_set_id TEXT NOT NULL,
                path TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS bundles_day_idx ON bundles(trading_day, received_at);
            CREATE TABLE IF NOT EXISTS live_status (
                source_id TEXT PRIMARY KEY,
                generated_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                code TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS alerts_status_idx ON alerts(status, severity, last_seen_at);
            CREATE TABLE IF NOT EXISTS ingest_receipts (
                receipt_id TEXT PRIMARY KEY,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_meta(version,applied_at) VALUES(?,?)",
            (SCHEMA_VERSION, datetime.now().astimezone().isoformat()),
        )
        self.connection.commit()

    def save_bundle(self, bundle: dict[str, Any], received_at: datetime) -> bool:
        with self._lock:
            return self._save_bundle(bundle, received_at)

    def _save_bundle(self, bundle: dict[str, Any], received_at: datetime) -> bool:
        validate_review_bundle(bundle)
        target = self.bundle_root / bundle["trading_day"] / f"{bundle['bundle_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json(bundle)
        existing = self.connection.execute(
            "SELECT content_sha256,path FROM bundles WHERE bundle_id=?", (bundle["bundle_id"],)
        ).fetchone()
        if existing:
            if existing["content_sha256"] != bundle["content_sha256"]:
                raise ValueError("bundle id already exists with different content")
            return False
        target.write_bytes(encoded)
        with self.connection:
            self.connection.execute(
                "INSERT INTO bundles VALUES(?,?,?,?,?,?,?)",
                (
                    bundle["bundle_id"],
                    bundle["trading_day"],
                    bundle["content_sha256"],
                    bundle["strategy_set_id"],
                    str(target),
                    bundle["generated_at"],
                    received_at.isoformat(),
                ),
            )
            self.connection.execute(
                "INSERT INTO ingest_receipts VALUES(?,?,?,?)",
                (f"bundle:{bundle['bundle_id']}", "BUNDLE", bundle["bundle_id"], received_at.isoformat()),
            )
        return True

    def bundles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self.connection.execute(
                "SELECT bundle_id,trading_day,content_sha256,strategy_set_id,generated_at,received_at "
                "FROM bundles ORDER BY trading_day DESC,received_at DESC"
            )]

    def load_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute("SELECT path FROM bundles WHERE bundle_id=?", (bundle_id,)).fetchone()
            if not row:
                return None
            return json.loads(Path(row["path"]).read_text(encoding="utf-8"))

    def latest_bundle(self) -> dict[str, Any] | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT bundle_id FROM bundles ORDER BY trading_day DESC,received_at DESC LIMIT 1"
            ).fetchone()
            return self.load_bundle(row["bundle_id"]) if row else None

    def save_live_status(self, source_id: str, payload: dict[str, Any], received_at: datetime) -> None:
        validate_live_status(payload)
        if payload.get("source_id") != source_id:
            raise ValueError("invalid live status")
        with self._lock, self.connection:
            receipt_id = f"status:{payload['status_id']}"
            receipt = self.connection.execute(
                "SELECT object_id FROM ingest_receipts WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
            if receipt:
                if receipt["object_id"] != source_id:
                    raise ValueError("live status id already exists with different source")
                return
            self.connection.execute(
                """INSERT INTO live_status VALUES(?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                   generated_at=excluded.generated_at,received_at=excluded.received_at,payload=excluded.payload""",
                (source_id, payload["generated_at"], received_at.isoformat(), _json(payload)),
            )
            self.connection.execute(
                "INSERT INTO ingest_receipts VALUES(?,?,?,?)",
                (receipt_id, "LIVE_STATUS", source_id, received_at.isoformat()),
            )
            self._replace_alerts(source_id, payload.get("alerts", []), received_at)

    def _replace_alerts(self, source_id: str, alerts: list[dict[str, Any]], received_at: datetime) -> None:
        active_ids = set()
        for alert in alerts:
            alert_id = str(alert.get("alert_id") or f"{source_id}:{alert['code']}")
            active_ids.add(alert_id)
            self.connection.execute(
                """INSERT INTO alerts VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(alert_id) DO UPDATE SET severity=excluded.severity,message=excluded.message,
                   status='ACTIVE',last_seen_at=excluded.last_seen_at,payload=excluded.payload""",
                (
                    alert_id,
                    source_id,
                    alert["code"],
                    alert.get("severity", "WARNING"),
                    alert.get("message", alert["code"]),
                    "ACTIVE",
                    alert.get("first_seen_at", received_at.isoformat()),
                    received_at.isoformat(),
                    _json(alert),
                ),
            )
        rows = self.connection.execute(
            "SELECT alert_id FROM alerts WHERE source_id=? AND status='ACTIVE'", (source_id,)
        ).fetchall()
        for row in rows:
            if row["alert_id"] not in active_ids:
                self.connection.execute(
                    "UPDATE alerts SET status='RESOLVED',last_seen_at=? WHERE alert_id=?",
                    (received_at.isoformat(), row["alert_id"]),
                )

    def live_statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for row in self.connection.execute("SELECT * FROM live_status ORDER BY source_id"):
                item = json.loads(row["payload"])
                item["received_at"] = row["received_at"]
                result.append(item)
            return result

    def alerts(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self.connection.execute(
                "SELECT alert_id,source_id,code,severity,message,status,first_seen_at,last_seen_at "
                "FROM alerts ORDER BY status, CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END, last_seen_at DESC"
            )]

    def effective_alerts(self, now: datetime) -> list[dict[str, Any]]:
        alerts = self.alerts()
        with self._lock:
            rows = self.connection.execute("SELECT source_id,received_at FROM live_status ORDER BY source_id").fetchall()
        if not rows:
            alerts.insert(
                0,
                {
                    "alert_id": "server:no-runner-status",
                    "source_id": "server",
                    "code": "RUNNER_OFFLINE",
                    "severity": "CRITICAL",
                    "message": "尚未收到 Windows runner 状态",
                    "status": "ACTIVE",
                    "first_seen_at": now.isoformat(),
                    "last_seen_at": now.isoformat(),
                },
            )
        for row in rows:
            received = datetime.fromisoformat(row["received_at"])
            if (now - received).total_seconds() > 90:
                alerts.insert(
                    0,
                    {
                        "alert_id": f"server:{row['source_id']}:offline",
                        "source_id": row["source_id"],
                        "code": "RUNNER_OFFLINE",
                        "severity": "CRITICAL",
                        "message": "Windows runner 心跳超过 90 秒未更新",
                        "status": "ACTIVE",
                        "first_seen_at": row["received_at"],
                        "last_seen_at": now.isoformat(),
                    },
                )
        return alerts

    def backup(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            destination = sqlite3.connect(target)
            try:
                self.connection.backup(destination)
            finally:
                destination.close()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
