from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from astock.dashboard.app import create_app
from astock.dashboard.storage import DashboardStore
from astock.dashboard.backup import create_backup, restore_backup, verify_backup
from astock.observability.bundle import build_live_status, build_review_bundle, validate_review_bundle, write_review_bundle
from astock.observability.repository import ObservabilityRepository, SCHEMA_VERSION
from astock.observability.research_bundle import build_research_bundle, validate_research_bundle
from astock.observability.report import build_offline_report
from astock.observability.snapshot import capture_account_snapshot, initialize_observation_set
from astock.observability.sync import dispatch_sync
from astock.observability.runner import Runner
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


def sample_research_bundle() -> dict:
    return build_research_bundle(
        category="TOPIC",
        title="执行链专题",
        summary="复核执行链。",
        conclusion="继续观察。",
        status="OBSERVE",
        source_path="docs/topic.md",
        source_commit="abc123",
        data_cutoff="2026-07-12",
        published_at=NOW.isoformat(),
        body_markdown="# 执行链专题\n\n正文",
    )


class ObservabilityCase(unittest.TestCase):
    def test_research_bundle_is_deterministic_and_verified(self) -> None:
        first = sample_research_bundle()
        second = sample_research_bundle()
        self.assertEqual(first, second)
        validate_research_bundle(first)
        changed = dict(first)
        changed["title"] = "被篡改"
        with self.assertRaisesRegex(ValueError, "content hash mismatch"):
            validate_research_bundle(changed)

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
            with self.assertRaises(ValueError):
                write_review_bundle(later, root / "bundles")
            altered = dict(first)
            altered["health"] = {"tdx": "bad"}
            with self.assertRaises(ValueError):
                validate_review_bundle(altered)
            repository.close()

    def test_conflicting_idempotent_writes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            with self.assertRaises(ValueError):
                repository.register_strategy_set("set-demo", "b" * 64, "abc", {}, NOW)
            repository.append_event("ORDER", NOW, {"status": "NEW"}, event_id="order-1")
            with self.assertRaises(ValueError):
                repository.append_event("ORDER", NOW, {"status": "FILLED"}, event_id="order-1")
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

    def test_tdx_sim_outbox_is_never_reclaimed_after_send_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            order = {
                "client_order_id": "set-demo:20260714:000001.SZ:BUY",
                "strategy_set_id": "set-demo",
                "strategy": "combined_observer",
                "signal_date": "2026-07-13",
                "symbol": "000001.SZ",
                "side": "BUY",
                "quantity": 100,
                "limit_price": "10.01",
                "created_at": NOW.isoformat(),
            }
            repository.enqueue_tdx_sim_order(order)
            repository.enqueue_tdx_sim_order(order)
            claimed = repository.claim_tdx_sim_orders(NOW)
            self.assertEqual(len(claimed), 1)
            self.assertEqual(repository.claim_tdx_sim_orders(NOW), [])
            repository.finish_tdx_sim_order(
                order["client_order_id"], "ACK", NOW, tdx_order_id="SIM-1", response={"Value": 2}
            )
            self.assertEqual(repository.tdx_sim_orders()[0]["tdx_order_id"], "SIM-1")
            repository.close()

    def test_tdx_sim_outbox_claim_is_scoped_to_current_plan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            for signal_date in ("2026-07-12", "2026-07-13"):
                repository.enqueue_tdx_sim_order({
                    "client_order_id": f"set-demo:{signal_date}",
                    "strategy_set_id": "set-demo",
                    "strategy": "combined_observer",
                    "signal_date": signal_date,
                    "symbol": "000001.SZ",
                    "side": "BUY",
                    "quantity": 100,
                    "limit_price": "10",
                    "created_at": NOW.isoformat(),
                })
            claimed = repository.claim_tdx_sim_orders(
                NOW, strategy_set_id="set-demo", signal_date="2026-07-13"
            )
            self.assertEqual([item["signal_date"] for item in claimed], ["2026-07-13"])
            self.assertEqual(
                [item["signal_date"] for item in repository.tdx_sim_orders("PENDING")],
                ["2026-07-12"],
            )
            repository.close()

    def test_tdx_sim_daily_facts_are_immutable_versions(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = ObservabilityRepository(Path(folder) / "observability.db")
            fact = {
                "trading_day": "2026-07-14",
                "captured_at": NOW.isoformat(),
                "asset": {"Cash": "100000"},
                "positions": [],
                "orders": [],
                "review": {"ok": True},
            }
            first = repository.save_tdx_sim_daily_fact(fact)
            self.assertEqual(repository.save_tdx_sim_daily_fact(fact), first)
            changed = {**fact, "captured_at": NOW.replace(second=1).isoformat()}
            second = repository.save_tdx_sim_daily_fact(changed)
            self.assertNotEqual(second, first)
            self.assertEqual(len(repository.tdx_sim_daily_facts("2026-07-14")), 2)
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

    def test_runner_renews_lease_while_child_job_is_running(self) -> None:
        class Process:
            returncode = 0
            calls = 0

            def communicate(self, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(["python"], timeout)
                return "{}", ""

            def kill(self):
                raise AssertionError("successful child must not be killed")

        class Lease:
            def __init__(self):
                self.renewals = []

            def acquire_lease(self, name, owner, now, expires_at):
                self.renewals.append((name, owner, now, expires_at))
                return True

        runner = object.__new__(Runner)
        runner.workspace = Path.cwd()
        runner.owner_id = "runner-test"
        runner.observability = Lease()
        process = Process()
        with patch("astock.observability.runner.subprocess.Popen", return_value=process):
            completed = runner._run_command(["python", "job.py"])
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(len(runner.observability.renewals), 1)
        self.assertEqual(runner.observability.renewals[0][0:2], ("primary-runner", "runner-test"))

    def test_runner_does_not_send_orders_after_close_and_runs_review(self) -> None:
        class Lease:
            @staticmethod
            def acquire_lease(name, owner, now, expires_at):
                return True

        runner = object.__new__(Runner)
        runner.observability = Lease()
        runner.owner_id = "runner-test"
        runner.settings = SimpleNamespace(paper_execution_enabled=True)
        calls = []
        runner._run_cli_job = lambda job_type, command, now: calls.append((job_type, command)) or True
        runner._publish_status = lambda now: calls.append(("status", "publish"))
        runner.tick(datetime(2026, 7, 14, 15, 21, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertNotIn(("paper_execute", "paper-execute"), calls)
        self.assertIn(("tdx_sim_review", "paper-review"), calls)
        self.assertNotIn(("account_snapshot", "account_snapshot"), calls)

    def test_runner_sends_orders_only_in_continuous_auction_window(self) -> None:
        class Lease:
            @staticmethod
            def acquire_lease(name, owner, now, expires_at):
                return True

        runner = object.__new__(Runner)
        runner.observability = Lease()
        runner.owner_id = "runner-test"
        runner.settings = SimpleNamespace(paper_execution_enabled=True)
        calls = []
        runner._run_cli_job = lambda job_type, command, now: calls.append((job_type, command)) or True
        runner._publish_status = lambda now: None
        runner.tick(datetime(2026, 7, 14, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertIn(("paper_execute", "paper-execute"), calls)

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
            repeated_set_id, _ = initialize_observation_set(
                repository, report, paper, Decimal("100000"), Path.cwd(), NOW.replace(second=1)
            )
            self.assertEqual(len(repository.accounts("LEGACY")), 1)
            self.assertEqual(len(repository.accounts()), 3)
            self.assertEqual(repeated_set_id, set_id)
            self.assertEqual(len(repository.events()), 1)
            self.assertEqual(repository.events()[0]["event_type"], "STALE_SIGNAL_PLAN")
            self.assertTrue(set_id.startswith("set-"))
            repository.close()


class DashboardApiCase(unittest.TestCase):
    def test_dashboard_store_migrates_v1_index_to_v2(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            connection = sqlite3.connect(root / "server.db")
            connection.execute("CREATE TABLE schema_meta(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            connection.execute("INSERT INTO schema_meta VALUES(1,?)", (NOW.isoformat(),))
            connection.commit()
            connection.close()
            store = DashboardStore(root / "server.db", root / "bundles")
            try:
                version = store.connection.execute("SELECT max(version) FROM schema_meta").fetchone()[0]
                table = store.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='research_reports'"
                ).fetchone()
                self.assertEqual(version, 2)
                self.assertIsNotNone(table)
            finally:
                store.close()

    def test_research_ingest_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(
                data_dir=root,
                static_dir=root / "missing",
                allowed_users={"yancey@example.com"},
                ingest_token="secret",
            )
            report = sample_research_bundle()
            auth = {"Authorization": "Bearer secret"}
            browser = {"Tailscale-User-Login": "yancey@example.com"}
            with TestClient(app) as client:
                response = client.put(
                    f"/api/v1/ingest/research/{report['report_id']}", json=report, headers=auth
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["created"])
                listing = client.get("/api/v1/research", headers=browser).json()
                self.assertEqual(listing[0]["category"], "TOPIC")
                detail = client.get(
                    f"/api/v1/research/{report['report_id']}", headers=browser
                ).json()
                self.assertEqual(detail["body_markdown"], report["body_markdown"])

    def test_auth_ingest_and_queries(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(data_dir=root, static_dir=root / "missing", allowed_users={"yancey@example.com"}, ingest_token="secret")
            with TestClient(app) as client:
                self.assertEqual(client.get("/healthz").status_code, 200)
                self.assertEqual(client.get("/openapi.json").status_code, 404)
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
                self.assertTrue(status["status_id"].startswith("status-"))
                changed = dict(status)
                changed["runner"] = {"status": "OFFLINE"}
                self.assertEqual(
                    client.put(
                        "/api/v1/ingest/live-status/windows-primary",
                        json=changed,
                        headers={"Authorization": "Bearer secret"},
                    ).status_code,
                    400,
                )
                overview = client.get("/api/v1/overview", headers=headers).json()
                self.assertEqual(overview["bundle"]["bundle_id"], bundle["bundle_id"])
                self.assertIn("TEST", [item["code"] for item in overview["alerts"]])

    def test_overview_projects_large_activity_payload_but_review_keeps_full_fact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(
                data_dir=root,
                static_dir=root / "missing",
                allowed_users={"yancey@example.com"},
                ingest_token="secret",
            )
            bundle = build_review_bundle(
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
                known_limitations=[],
                activity=[{
                    "event_id": "event-large",
                    "event_type": "SIGNAL_PLAN",
                    "occurred_at": NOW.isoformat(),
                    "payload": {"status": "READY", "raw": "x" * 100_000},
                }],
            )
            browser = {"Tailscale-User-Login": "yancey@example.com"}
            with TestClient(app) as client:
                response = client.put(
                    f"/api/v1/ingest/bundles/{bundle['bundle_id']}",
                    json=bundle,
                    headers={"Authorization": "Bearer secret"},
                )
                self.assertEqual(response.status_code, 200)
                overview = client.get("/api/v1/overview", headers=browser)
                detail = client.get(
                    f"/api/v1/reviews/{bundle['bundle_id']}", headers=browser
                )
                self.assertEqual(overview.status_code, 200)
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(
                    overview.json()["bundle"]["activity"][0]["payload"], {"status": "READY"}
                )
                self.assertEqual(
                    detail.json()["activity"][0]["payload"]["raw"], "x" * 100_000
                )
                self.assertLess(len(overview.content), len(detail.content) // 10)

    def test_existing_bundle_file_bytes_must_match_idempotent_upload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            app = create_app(data_dir=root, static_dir=root / "missing", ingest_token="secret")
            bundle = sample_bundle()
            path = f"/api/v1/ingest/bundles/{bundle['bundle_id']}"
            headers = {"Authorization": "Bearer secret"}
            with TestClient(app) as client:
                self.assertEqual(client.put(path, json=bundle, headers=headers).status_code, 200)
                stored = root / "bundles" / bundle["trading_day"] / f"{bundle['bundle_id']}.json"
                stored.write_bytes(b"{}")
                response = client.put(path, json=bundle, headers=headers)
                self.assertEqual(response.status_code, 409)
                self.assertIn("different file bytes", response.json()["detail"])

    def test_late_old_status_does_not_replace_latest_view(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = DashboardStore(root / "server.db", root / "bundles")
            newer = build_live_status(
                source_id="windows-primary", generated_at=NOW + timedelta(seconds=30),
                runner={"status": "NEW"}, sources={}, jobs={}, sync={}, alerts=[],
            )
            older = build_live_status(
                source_id="windows-primary", generated_at=NOW,
                runner={"status": "OLD"}, sources={}, jobs={}, sync={}, alerts=[],
            )
            store.save_live_status("windows-primary", newer, NOW)
            store.save_live_status("windows-primary", older, NOW + timedelta(seconds=1))
            self.assertEqual(store.live_statuses()[0]["runner"]["status"], "NEW")
            receipt_count = store.connection.execute(
                "SELECT COUNT(*) FROM ingest_receipts WHERE object_type='LIVE_STATUS'"
            ).fetchone()[0]
            self.assertEqual(receipt_count, 2)
            store.close()

    def test_equal_time_status_order_is_deterministic(self) -> None:
        statuses = [
            build_live_status(
                source_id="windows-primary", generated_at=NOW, runner={"status": label},
                sources={}, jobs={}, sync={}, alerts=[],
            )
            for label in ("A", "B")
        ]
        expected = max(statuses, key=lambda item: item["status_id"])["status_id"]
        for order in (statuses, list(reversed(statuses))):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                store = DashboardStore(root / "server.db", root / "bundles")
                for index, status in enumerate(order):
                    store.save_live_status("windows-primary", status, NOW + timedelta(seconds=index))
                self.assertEqual(store.live_statuses()[0]["status_id"], expected)
                store.close()

    def test_static_assets_require_tailscale_identity(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            static = root / "web"
            (static / "assets").mkdir(parents=True)
            (static / "index.html").write_text("index", encoding="utf-8")
            (static / "assets" / "app.js").write_text("app", encoding="utf-8")
            app = create_app(
                data_dir=root / "data", static_dir=static,
                allowed_users={"yancey@example.com"}, ingest_token="secret",
            )
            with TestClient(app) as client:
                self.assertEqual(client.get("/assets/app.js").status_code, 403)
                response = client.get(
                    "/assets/app.js", headers={"Tailscale-User-Login": "yancey@example.com"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.text, "app")

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

    def test_complete_backup_has_hash_manifest_and_restores_independently(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = DashboardStore(root / "live" / "server.db", root / "live" / "bundles")
            store.save_bundle(sample_bundle(), NOW)
            target = create_backup(store, root / "backup")
            store.close()
            result = verify_backup(target)
            self.assertEqual(result["bundles"], 1)
            self.assertGreaterEqual(result["files"], 3)
            version = json.loads((target / "version.json").read_text(encoding="utf-8"))
            self.assertEqual(version["application"], "astock")
            self.assertEqual(version["backup_schema_version"], 1)
            manifest_path = target / "manifest.sha256.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            incomplete_manifest = dict(manifest)
            incomplete_manifest.pop("server.db")
            manifest_path.write_text(json.dumps(incomplete_manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest file set mismatch"):
                verify_backup(target)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            restored_root = root / "restored"
            restored_result = restore_backup(target, restored_root)
            self.assertEqual(restored_result["bundles"], 1)
            restored = DashboardStore(restored_root / "server.db", restored_root / "bundles")
            self.assertEqual(restored.load_bundle(sample_bundle()["bundle_id"])["content_sha256"], sample_bundle()["content_sha256"])
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
