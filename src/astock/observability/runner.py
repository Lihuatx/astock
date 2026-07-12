from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, time as clock_time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.broker import AShareSimBroker
from astock.config import Settings
from astock.data.tdx import TdxClient
from astock.observability.bundle import build_live_status, strategy_set_id
from astock.observability.repository import ObservabilityRepository
from astock.observability.snapshot import capture_account_snapshot, create_review_bundle_from_repository
from astock.observability.sync import SyncClient, dispatch_sync
from astock.storage import Repository


SHANGHAI = ZoneInfo("Asia/Shanghai")


class Runner:
    def __init__(self, settings: Settings, workspace: Path, env_file: Path | None = None) -> None:
        self.settings = settings
        self.workspace = workspace
        self.env_file = env_file
        self.observability = ObservabilityRepository(settings.data_dir / "observability" / "observability.db")
        self.owner_id = uuid.uuid4().hex
        self.live_root = settings.data_dir / "observability" / "live-status"
        self.live_root.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.observability.close()

    def _run_cli_job(self, job_type: str, command: str, now: datetime) -> bool:
        if self.observability.has_successful_run(job_type, now.date().isoformat()):
            return True
        attempts = self.observability.run_attempts(job_type, now.date().isoformat())
        if len(attempts) >= 3:
            return False
        if attempts and attempts[-1]["finished_at"]:
            last = datetime.fromisoformat(attempts[-1]["finished_at"])
            if now - last < timedelta(minutes=10):
                return False
        run_id = self.observability.start_run(job_type, now)
        args = [sys.executable, "-m", "astock.cli", command]
        if self.env_file:
            args.extend(["--env-file", str(self.env_file)])
        error = None
        completed = None
        try:
            completed = subprocess.run(args, cwd=self.workspace, check=True, timeout=600, capture_output=True, text=True)
        except Exception as exc:
            error = exc
        self.observability.finish_run(run_id, datetime.now(SHANGHAI), error)
        if error:
            self.observability.append_event(
                "TASK_FAILED_ALERT",
                datetime.now(SHANGHAI),
                {"code": f"TASK_FAILED_{job_type}", "severity": "CRITICAL", "message": f"{job_type} failed", "error": str(error), "status": "ACTIVE"},
                event_id=f"task-failed:{job_type}:{now.date().isoformat()}",
                run_id=run_id,
            )
        else:
            if command == "doctor" and completed:
                try:
                    health = json.loads(completed.stdout)
                except json.JSONDecodeError:
                    health = {"ok": True}
                self.observability.append_event(
                    "DATA_SOURCE_HEALTH", datetime.now(SHANGHAI), health,
                    event_id=f"data-health:{now.date().isoformat()}", run_id=run_id,
                )
            self.observability.append_event(
                "ALERT_RESOLVED",
                datetime.now(SHANGHAI),
                {"code": f"TASK_FAILED_{job_type}", "status": "RESOLVED"},
                event_id=f"task-recovered:{job_type}:{now.date().isoformat()}",
                run_id=run_id,
            )
        return error is None

    def _capture_snapshots(self, now: datetime) -> None:
        job_type = "account_snapshot"
        if self.observability.has_successful_run(job_type, now.date().isoformat()):
            return
        run_id = self.observability.start_run(job_type, now)
        error = None
        try:
            client = TdxClient(self.settings.tdx_base_url)
            for account in self.observability.accounts("CURRENT"):
                repository = Repository(Path(account["db_path"]))
                broker = AShareSimBroker(repository, Decimal(account["initial_cash"]))
                symbols = sorted(broker.snapshot(now.date()).positions)
                repository.close()
                prices = {symbol: client.get_snapshot(symbol).last for symbol in symbols}
                capture_account_snapshot(self.observability, account, now.date(), now, prices)
        except Exception as exc:
            error = exc
        self.observability.finish_run(run_id, datetime.now(SHANGHAI), error)
        if error:
            self.observability.append_event(
                "TASK_FAILED_ALERT",
                datetime.now(SHANGHAI),
                {"code": "SNAPSHOT_FAILED", "severity": "CRITICAL", "message": "account snapshot failed", "error": str(error)},
                event_id=f"snapshot-failed:{now.date().isoformat()}",
                run_id=run_id,
            )
        else:
            self.observability.append_event(
                "ALERT_RESOLVED", datetime.now(SHANGHAI), {"code": "SNAPSHOT_FAILED", "status": "RESOLVED"},
                event_id=f"snapshot-recovered:{now.date().isoformat()}", run_id=run_id,
            )

    def _build_bundle(self, now: datetime) -> None:
        job_type = "review_bundle"
        if self.observability.has_successful_run(job_type, now.date().isoformat()):
            return
        run_id = self.observability.start_run(job_type, now)
        error = None
        try:
            report = self.settings.data_dir / "reports" / "strategy_research.json"
            bundle, path = create_review_bundle_from_repository(
                self.observability,
                report,
                self.workspace,
                self.settings.data_dir / "review" / "bundles",
                now.date(),
                now,
                now.isoformat(),
            )
            self.observability.enqueue_sync("BUNDLE", bundle["bundle_id"], path, now)
        except Exception as exc:
            error = exc
        self.observability.finish_run(run_id, datetime.now(SHANGHAI), error)
        if error:
            self.observability.append_event(
                "TASK_FAILED_ALERT",
                datetime.now(SHANGHAI),
                {"code": "BUNDLE_FAILED", "severity": "CRITICAL", "message": "review bundle build failed", "error": str(error)},
                event_id=f"bundle-failed:{now.date().isoformat()}",
                run_id=run_id,
            )
        else:
            self.observability.append_event(
                "ALERT_RESOLVED", datetime.now(SHANGHAI), {"code": "BUNDLE_FAILED", "status": "RESOLVED"},
                event_id=f"bundle-recovered:{now.date().isoformat()}", run_id=run_id,
            )

    def _alerts(self) -> list[dict]:
        active: dict[str, dict] = {}
        for event in self.observability.events():
            payload = event["payload"]
            code = payload.get("code", event["event_type"])
            if payload.get("status") == "RESOLVED":
                active.pop(code, None)
            elif event["event_type"].endswith("ALERT") or event["event_type"] == "STALE_SIGNAL_PLAN":
                active[code] = {
                    "alert_id": event["event_id"],
                    "code": code,
                    "severity": payload.get("severity", "WARNING"),
                    "message": payload.get("message", event["event_type"]),
                    "first_seen_at": event["occurred_at"],
                }
        return list(active.values())[-100:]

    def _publish_status(self, now: datetime) -> None:
        pending = len(self.observability.pending_sync(now + timedelta(days=3650)))
        events = self.observability.events()
        health_events = [item for item in events if item["event_type"] == "DATA_SOURCE_HEALTH"]
        sources = health_events[-1]["payload"] if health_events else {"tdx": {"configured": True, "ok": None}}
        jobs = {}
        for job_type in ("doctor", "paper_execute", "account_snapshot", "paper_signals", "review_bundle"):
            attempts = self.observability.run_attempts(job_type, now.date().isoformat())
            if attempts:
                jobs[job_type] = attempts[-1]
        status = build_live_status(
            source_id=self.settings.source_id,
            generated_at=now,
            runner={"status": "ONLINE", "owner_id": self.owner_id, "paper_execution_enabled": self.settings.paper_execution_enabled},
            sources=sources,
            jobs=jobs,
            sync={"pending": pending},
            alerts=self._alerts(),
        )
        live_path = self.live_root / now.date().isoformat() / f"{status['status_id']}.json"
        live_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(status, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if live_path.exists() and live_path.read_text(encoding="utf-8") != encoded:
            raise ValueError("immutable live status already exists with different content")
        live_path.write_text(encoded, encoding="utf-8")
        self.observability.enqueue_sync("LIVE_STATUS", status["status_id"], live_path, now)
        if self.settings.sync_base_url and self.settings.sync_token:
            dispatch_sync(
                self.observability,
                SyncClient(self.settings.sync_base_url, self.settings.sync_token),
                now,
            )

    def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(SHANGHAI)
        if not self.observability.acquire_lease("primary-runner", self.owner_id, now, now + timedelta(seconds=90)):
            raise RuntimeError("another astock runner owns the active lease")
        current = now.timetz().replace(tzinfo=None)
        weekday = now.weekday() < 5
        if weekday and current >= clock_time(8, 55):
            self._run_cli_job("doctor", "doctor", now)
        if weekday and current >= clock_time(9, 35) and self.settings.paper_execution_enabled:
            self._run_cli_job("paper_execute", "paper-execute", now)
        if weekday and current >= clock_time(15, 20):
            self._capture_snapshots(now)
        if weekday and current >= clock_time(16, 0):
            self._run_cli_job("paper_signals", "paper-signals", now)
            if self.observability.has_successful_run("paper_signals", now.date().isoformat()):
                self._build_bundle(now)
        self._publish_status(now)

    def run_forever(self) -> None:
        try:
            while True:
                self.tick()
                time.sleep(30)
        finally:
            self.close()
