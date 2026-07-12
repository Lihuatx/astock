from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class ObservabilityRepository:
    """独立观测事实库，不修改交易账户数据库。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS strategy_sets (
                strategy_set_id TEXT PRIMARY KEY,
                report_sha256 TEXT NOT NULL,
                git_sha TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS account_registry (
                account_id TEXT PRIMARY KEY,
                strategy_set_id TEXT,
                strategy TEXT NOT NULL,
                generation INTEGER NOT NULL,
                db_path TEXT NOT NULL,
                initial_cash TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(strategy_set_id) REFERENCES strategy_sets(strategy_set_id)
            );
            CREATE TABLE IF NOT EXISTS run_records (
                run_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error_class TEXT,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT,
                account_id TEXT,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES run_records(run_id),
                FOREIGN KEY(account_id) REFERENCES account_registry(account_id)
            );
            CREATE INDEX IF NOT EXISTS audit_events_time_idx ON audit_events(occurred_at);
            CREATE TABLE IF NOT EXISTS account_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                trading_day TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                cash TEXT NOT NULL,
                frozen_cash TEXT NOT NULL,
                market_value TEXT NOT NULL,
                equity TEXT NOT NULL,
                fees TEXT NOT NULL,
                drawdown TEXT NOT NULL,
                positions TEXT NOT NULL,
                reconciliation_ok INTEGER NOT NULL,
                UNIQUE(account_id, trading_day, captured_at),
                FOREIGN KEY(account_id) REFERENCES account_registry(account_id)
            );
            CREATE INDEX IF NOT EXISTS snapshots_account_day_idx
                ON account_snapshots(account_id, trading_day, captured_at);
            CREATE TABLE IF NOT EXISTS sync_outbox (
                outbox_id TEXT PRIMARY KEY,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                payload_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                UNIQUE(object_type, object_id)
            );
            CREATE TABLE IF NOT EXISTS runner_lease (
                lease_name TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO schema_meta(version, applied_at) VALUES(?, ?)",
            (SCHEMA_VERSION, datetime.now().astimezone().isoformat()),
        )
        self.connection.commit()

    def register_strategy_set(
        self,
        strategy_set_id: str,
        report_sha256: str,
        git_sha: str,
        payload: dict[str, Any],
        created_at: datetime,
        status: str = "OBSERVATION",
    ) -> None:
        values = (strategy_set_id, report_sha256, git_sha, status, _json(payload), created_at.isoformat())
        self._insert_exact(
            "strategy_sets",
            "strategy_set_id",
            strategy_set_id,
            """INSERT INTO strategy_sets
               (strategy_set_id, report_sha256, git_sha, status, payload, created_at)
               VALUES(?,?,?,?,?,?)""",
            values,
        )
        self.connection.commit()

    def activate_strategy_set(self, strategy_set_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE strategy_sets SET status='LEGACY' WHERE strategy_set_id<>? AND status='OBSERVATION'",
                (strategy_set_id,),
            )
            self.connection.execute(
                "UPDATE account_registry SET status='LEGACY' WHERE strategy_set_id IS NOT NULL AND strategy_set_id<>? AND status='CURRENT'",
                (strategy_set_id,),
            )

    def register_account(
        self,
        account_id: str,
        strategy: str,
        generation: int,
        db_path: Path,
        initial_cash: Decimal,
        created_at: datetime,
        strategy_set_id: str | None = None,
        status: str = "CURRENT",
    ) -> None:
        values = (
            account_id, strategy_set_id, strategy, generation, str(db_path), str(initial_cash),
            status, created_at.isoformat(),
        )
        self._insert_exact(
            "account_registry",
            "account_id",
            account_id,
            """INSERT INTO account_registry
               (account_id, strategy_set_id, strategy, generation, db_path, initial_cash, status, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            values,
        )
        self.connection.commit()

    def accounts(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM account_registry"
        args: tuple[str, ...] = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY created_at, account_id"
        return [dict(row) for row in self.connection.execute(sql, args)]

    def start_run(self, job_type: str, started_at: datetime, run_id: str | None = None) -> str:
        run_id = run_id or uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO run_records(run_id,job_type,status,started_at) VALUES(?,?,?,?)",
            (run_id, job_type, "RUNNING", started_at.isoformat()),
        )
        self.connection.commit()
        return run_id

    def finish_run(self, run_id: str, finished_at: datetime, error: Exception | None = None) -> None:
        self.connection.execute(
            """UPDATE run_records SET status=?, finished_at=?, error_class=?, error_message=? WHERE run_id=?""",
            (
                "FAILED" if error else "SUCCEEDED",
                finished_at.isoformat(),
                type(error).__name__ if error else None,
                str(error) if error else None,
                run_id,
            ),
        )
        self.connection.commit()

    def has_successful_run(self, job_type: str, day: str) -> bool:
        row = self.connection.execute(
            """SELECT 1 FROM run_records
               WHERE job_type=? AND status='SUCCEEDED' AND substr(started_at,1,10)=? LIMIT 1""",
            (job_type, day),
        ).fetchone()
        return row is not None

    def run_attempts(self, job_type: str, day: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.connection.execute(
                """SELECT status,started_at,finished_at,error_class,error_message FROM run_records
                   WHERE job_type=? AND substr(started_at,1,10)=? ORDER BY started_at""",
                (job_type, day),
            )
        ]

    def append_event(
        self,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        run_id: str | None = None,
        account_id: str | None = None,
    ) -> str:
        raw_id = event_id or uuid.uuid4().hex
        event_id = f"{account_id}:{raw_id}" if account_id and not raw_id.startswith(f"{account_id}:") else raw_id
        self._insert_exact(
            "audit_events", "event_id", event_id,
            "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
            (event_id, run_id, account_id, event_type, occurred_at.isoformat(), _json(payload)),
        )
        self.connection.commit()
        return event_id

    def events(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM audit_events"
        args: tuple[str, ...] = ()
        if account_id:
            sql += " WHERE account_id=?"
            args = (account_id,)
        sql += " ORDER BY occurred_at, event_id"
        result = []
        for row in self.connection.execute(sql, args):
            item = dict(row)
            item["payload"] = json.loads(item["payload"])
            result.append(item)
        return result

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        values = (
            snapshot["snapshot_id"], snapshot["account_id"], snapshot["trading_day"], snapshot["captured_at"],
            str(snapshot["cash"]), str(snapshot["frozen_cash"]), str(snapshot["market_value"]),
            str(snapshot["equity"]), str(snapshot.get("fees", "0")), str(snapshot.get("drawdown", "0")),
            _json(snapshot.get("positions", {})), int(bool(snapshot["reconciliation_ok"])),
        )
        self._insert_exact(
            "account_snapshots", "snapshot_id", snapshot["snapshot_id"],
            """INSERT INTO account_snapshots
               (snapshot_id,account_id,trading_day,captured_at,cash,frozen_cash,market_value,equity,
                fees,drawdown,positions,reconciliation_ok)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
        self.connection.commit()

    def snapshots(self, account_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM account_snapshots"
        args: tuple[str, ...] = ()
        if account_id:
            sql += " WHERE account_id=?"
            args = (account_id,)
        sql += " ORDER BY trading_day, captured_at, snapshot_id"
        result = []
        for row in self.connection.execute(sql, args):
            item = dict(row)
            item["positions"] = json.loads(item["positions"])
            item["reconciliation_ok"] = bool(item["reconciliation_ok"])
            result.append(item)
        return result

    def enqueue_sync(
        self,
        object_type: str,
        object_id: str,
        payload_path: Path,
        next_attempt_at: datetime,
    ) -> None:
        outbox_id = f"{object_type}:{object_id}"
        values = (
            outbox_id, object_type, object_id, str(payload_path), next_attempt_at.isoformat(),
            datetime.now().astimezone().isoformat(),
        )
        existing = self.connection.execute(
            "SELECT object_type,object_id,payload_path FROM sync_outbox WHERE outbox_id=?", (outbox_id,)
        ).fetchone()
        if existing:
            if (existing["object_type"], existing["object_id"], existing["payload_path"]) != values[1:4]:
                raise ValueError(f"sync_outbox key {outbox_id!r} already has different payload")
            return
        self.connection.execute(
            """INSERT INTO sync_outbox
               (outbox_id,object_type,object_id,payload_path,next_attempt_at,created_at)
               VALUES(?,?,?,?,?,?)""",
            values,
        )
        self.connection.commit()

    def pending_sync(self, now: datetime) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """SELECT * FROM sync_outbox
               WHERE status='PENDING' AND next_attempt_at<=? ORDER BY created_at""",
            (now.isoformat(),),
        ).fetchall()
        return [dict(row) for row in rows]

    def acquire_lease(self, lease_name: str, owner_id: str, now: datetime, expires_at: datetime) -> bool:
        with self.connection:
            row = self.connection.execute(
                "SELECT owner_id,expires_at FROM runner_lease WHERE lease_name=?", (lease_name,)
            ).fetchone()
            if row and row["owner_id"] != owner_id and datetime.fromisoformat(row["expires_at"]) > now:
                return False
            self.connection.execute(
                """INSERT INTO runner_lease VALUES(?,?,?)
                   ON CONFLICT(lease_name) DO UPDATE SET owner_id=excluded.owner_id,expires_at=excluded.expires_at""",
                (lease_name, owner_id, expires_at.isoformat()),
            )
        return True

    def mark_sync_sent(self, outbox_id: str, sent_at: datetime) -> None:
        self.connection.execute(
            "UPDATE sync_outbox SET status='SENT', sent_at=?, last_error=NULL WHERE outbox_id=?",
            (sent_at.isoformat(), outbox_id),
        )
        self.connection.commit()

    def mark_sync_failed(self, outbox_id: str, error: str, next_attempt_at: datetime) -> None:
        self.connection.execute(
            """UPDATE sync_outbox SET attempts=attempts+1,last_error=?,next_attempt_at=? WHERE outbox_id=?""",
            (error, next_attempt_at.isoformat(), outbox_id),
        )
        self.connection.commit()

    def _insert_exact(
        self, table: str, key_column: str, key: str, sql: str, values: tuple[Any, ...]
    ) -> None:
        existing = self.connection.execute(
            f"SELECT * FROM {table} WHERE {key_column}=?", (key,)
        ).fetchone()
        if existing:
            if tuple(existing) != values:
                raise ValueError(f"{table} key {key!r} already has different payload")
            return
        self.connection.execute(sql, values)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)
