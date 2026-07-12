from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from astock.dashboard.app import create_app
from astock.dashboard.storage import DashboardStore
from astock.observability.bundle import build_live_status, build_review_bundle, validate_review_bundle, write_review_bundle
from astock.observability.repository import ObservabilityRepository, SCHEMA_VERSION
from astock.observability.report import build_offline_report
from astock.observability.snapshot import capture_account_snapshot, initialize_observation_set
from astock.observability.sync import dispatch_sync
from astock.storage import Repository
from astock.broker import AShareSimBroker
from astock.paper import MultiStrategyPaperAccounts


NOW = datetime(2026, 7, 12, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def sample_bundle() -> dict:
    return build_review_bundle(
        trading_day="2026-07-12",
        generated_at=NOW,
        git_sha="abc123",
        data_cutoff=NOW.isoformat(),
        report_sha256="r" * 64,
        strategy_set_id="set-demo",
        strategy_set={"selected": []},
        accounts=[],
        signals=[],
        risk_decisions=[],
        orders=[],
        fills=[],
        equity_curve=[],
        reconciliation=[],
        health={},
        alerts=[],
        known_limitations=["demo"],
    )


class ObservabilityCase(unittest.TestCase):
    def test_schema_bundle_stability_and_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repository = ObservabilityRepository(root / "observability.db")
            version = repository.connection.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            first = sample_bundle()
            second = sample_bundle()
            self.assertEqual(first["bundle_id"], second["bundle_id"])
            self.assertEqual(first["content_sha256"], second["content_sha256"])
            path = write_review_bundle(first, root / "bundles")
            self.assertEqual(path, write_review_bundle(second, root / "bundles"))
            later = dict(second)
            later["generated_at"] = "2026-07-12T17:00:00+08:00"
            self.assertEqual(path, write_review_bundle(later, root / "bundles"))
            altered = dict(first)
            altered["health"] = {"tdx": "bad"}
            with self.assertRaises(ValueError):
                validate_review_bundle(altered)
            repository.close()

    def test_decimal_snapshot_and_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            observability = ObservabilityRepository(root / "observability.db")
            observability.register_strategy_set("set-demo", "r" * 64, "abc", {}, NOW)
            account_path = root / "account.db"
            observability.register_account(
                "set-demo:alpha:g1", "alpha", 1, account_path, Decimal("100000"), NOW, "set-demo"
            )
            trading = Repository(account_path)
            AShareSimBroker(trading, Decimal("100000"))
            trading.close()
            account = observability.accounts("CURRENT")[0]
            snapshot = capture_account_snapshot(observability, account, date(2026, 7, 12), NOW, {})
            self.assertEqual(snapshot["equity"], Decimal("100000"))
            self.assertTrue(snapshot["reconciliation_ok"])
            self.assertEqual(observability.snapshots()[0]["equity"], "100000")
            observability.close()

    def test_sync_outbox_is_retryable_and_idempotent(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.uploads = 0

            def upload_bundle(self, payload: dict) -> None:
                self.uploads += 1

            def upload_live_status(self, payload: dict) -> None:
                self.uploads += 1

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repository = ObservabilityRepository(root / "observability.db")
            path = root / "bundle.json"
            path.write_text(json.dumps(sample_bundle()), encoding="utf-8")
            repository.enqueue_sync("BUNDLE", sample_bundle()["bundle_id"], path, NOW)
            repository.enqueue_sync("BUNDLE", sample_bundle()["bundle_id"], path, NOW)
            client = FakeClient()
            self.assertEqual(dispatch_sync(repository, client, NOW), 1)
            self.assertEqual(dispatch_sync(repository, client, NOW), 0)
            self.assertEqual(client.uploads, 1)
            repository.close()

    def test_offline_report_embeds_verified_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(sample_bundle()), encoding="utf-8")
            assets = root / "assets"
            assets.mkdir()
            (assets / "report.js").write_text("document.body.dataset.ready='1'", encoding="utf-8")
            (assets / "report.css").write_text("body{color:#123}", encoding="utf-8")
            target = build_offline_report(bundle_path, assets, root / "report.html")
            output = target.read_text(encoding="utf-8")
            self.assertIn(sample_bundle()["content_sha256"], output)
            self.assertIn("document.body.dataset.ready", output)
            self.assertNotIn("http://", output)
            self.assertNotIn("https://", output)

    def test_stale_signal_plan_is_rejected_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            observability = ObservabilityRepository(root / "observability.db")
            plan = root / "pending.json"
            plan.write_text(
                json.dumps({"strategy_set_id": "set-old", "signal_date": "2026-07-10", "strategies": []}),
                encoding="utf-8",
            )
            manager = MultiStrategyPaperAccounts(root / "paper", Decimal("100000"), observability, "set-current")
            with self.assertRaisesRegex(ValueError, "does not match"):
                manager.execute_plan(plan, object(), date(2026, 7, 13), NOW, "set-current")  # type: ignore[arg-type]
            self.assertEqual(observability.events()[0]["event_type"], "STALE_SIGNAL_PLAN")
            observability.close()

    def test_runner_lease_allows_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            self.assertTrue(repository.acquire_lease("runner", "one", NOW, NOW.replace(minute=1)))
            self.assertFalse(repository.acquire_lease("runner", "two", NOW, NOW.replace(minute=1)))
            repository.close()

    def test_new_strategy_set_retires_old_current_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            repository.register_strategy_set("set-old", "a" * 64, "abc", {}, NOW)
            repository.register_account("set-old:a:g1", "a", 1, Path(folder) / "a.db", Decimal("100000"), NOW, "set-old")
            repository.register_strategy_set("set-new", "b" * 64, "def", {}, NOW)
            repository.activate_strategy_set("set-new")
            self.assertEqual(repository.accounts()[0]["status"], "LEGACY")
            repository.close()

    def test_initialization_registers_legacy_and_stale_plan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "reports" / "strategy_research.json"
            report.parent.mkdir()
            report.write_text(json.dumps({"selected": [{"strategy": "alpha"}]}), encoding="utf-8")
            paper = root / "paper"
            legacy = paper / "old"
            legacy.mkdir(parents=True)
            Repository(legacy / "account.db").close()
            (paper / "pending_signals.json").write_text(
                json.dumps({"signal_date": "2026-07-10", "strategies": [{"strategy": "old"}]}), encoding="utf-8"
            )
            repository = ObservabilityRepository(root / "observability.db")
            set_id, _ = initialize_observation_set(
                repository, report, paper, Decimal("100000"), Path.cwd(), NOW
            )
            self.assertEqual(len(repository.accounts("LEGACY")), 1)
            self.assertEqual(repository.events()[0]["event_type"], "STALE_SIGNAL_PLAN")
            self.assertTrue(set_id.startswith("set-"))
            repository.close()


class DashboardApiCase(unittest.TestCase):
    def test_auth_ingest_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(data_dir=root, static_dir=root / "missing", allowed_users={"yancey@example.com"}, ingest_token="secret")
            with TestClient(app) as client:
                self.assertEqual(client.get("/healthz").status_code, 200)
                self.assertEqual(client.get("/api/v1/overview").status_code, 403)
                headers = {"Tailscale-User-Login": "yancey@example.com"}
                self.assertEqual(client.get("/api/v1/overview", headers=headers).status_code, 200)
                bundle = sample_bundle()
                self.assertEqual(
                    client.put(
                        f"/api/v1/ingest/bundles/{bundle['bundle_id']}",
                        json=bundle,
                        headers={"Authorization": "Bearer wrong"},
                    ).status_code,
                    401,
                )
                response = client.put(
                    f"/api/v1/ingest/bundles/{bundle['bundle_id']}",
                    json=bundle,
                    headers={"Authorization": "Bearer secret"},
                )
                self.assertTrue(response.json()["created"])
                response = client.put(
                    f"/api/v1/ingest/bundles/{bundle['bundle_id']}",
                    json=bundle,
                    headers={"Authorization": "Bearer secret"},
                )
                self.assertFalse(response.json()["created"])
                status = build_live_status(
                    source_id="windows-primary",
                    generated_at=NOW,
                    runner={"status": "ONLINE"},
                    sources={},
                    jobs={},
                    sync={"pending": 0},
                    alerts=[{"code": "TEST", "severity": "WARNING", "message": "test"}],
                )
                self.assertEqual(
                    client.put(
                        "/api/v1/ingest/live-status/windows-primary",
                        json=status,
                        headers={"Authorization": "Bearer secret"},
                    ).status_code,
                    200,
                )
                overview = client.get("/api/v1/overview", headers=headers).json()
                self.assertEqual(overview["bundle"]["bundle_id"], bundle["bundle_id"])
                self.assertIn("TEST", [item["code"] for item in overview["alerts"]])

    def test_online_backup_restores_bundle_index(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = DashboardStore(root / "server.db", root / "bundles")
            store.save_bundle(sample_bundle(), NOW)
            backup = root / "backup.db"
            store.backup(backup)
            store.close()
            restored = DashboardStore(backup, root / "restored-bundles")
            self.assertEqual(restored.bundles()[0]["bundle_id"], sample_bundle()["bundle_id"])
            restored.close()

    def test_runner_becomes_offline_after_ninety_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = DashboardStore(root / "server.db", root / "bundles")
            status = build_live_status(
                source_id="windows-primary", generated_at=NOW, runner={"status": "ONLINE"},
                sources={}, jobs={}, sync={"pending": 0}, alerts=[],
            )
            store.save_live_status("windows-primary", status, NOW)
            codes = [item["code"] for item in store.effective_alerts(NOW + timedelta(seconds=91))]
            self.assertIn("RUNNER_OFFLINE", codes)
            store.close()


if __name__ == "__main__":
    unittest.main()
