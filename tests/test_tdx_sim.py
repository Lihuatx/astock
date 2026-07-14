from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from astock.data.tdx_sim import JsonlErrorLog, TdxSimClient, TdxSimError, TdxSimulationGuardError, TdxSimSnapshot
from astock.cli import _tdx_task_exit_code
from astock.models import Quote, Side
from astock.observability.repository import ObservabilityRepository
from astock.tdx_sim_execution import execute_tdx_sim_plan, review_tdx_sim_day


NOW = datetime.fromisoformat("2026-07-14T09:35:00+08:00")


class TdxSimClientCase(unittest.TestCase):
    def test_task_exit_code_only_fails_for_top_level_execution_or_unsaved_review(self) -> None:
        self.assertEqual(_tdx_task_exit_code({"errors": 1}), 0)
        self.assertEqual(_tdx_task_exit_code({"reason": "account unavailable"}), 1)
        self.assertEqual(_tdx_task_exit_code({"saved": True, "ok": False}, requires_saved=True), 0)
        self.assertEqual(_tdx_task_exit_code({"saved": False}, requires_saved=True), 1)

    def test_unconfirmed_account_is_rejected_and_logged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            called = []
            client = TdxSimClient(
                "http://unused",
                "demo",
                False,
                error_log=JsonlErrorLog(Path(folder)),
                transport=lambda method, params: called.append((method, params)),  # type: ignore[arg-type]
            )
            with self.assertRaises(TdxSimulationGuardError):
                client.account_handle()
            self.assertEqual(called, [])
            record = json.loads(next(Path(folder).glob("*.jsonl")).read_text(encoding="utf-8"))
            self.assertEqual(record["operation"], "stock_account")

    def test_real_account_confirmation_response_is_rejected(self) -> None:
        responses = iter([
            {"result": {"ErrorId": "0", "Value": 7}},
            {"result": {"ErrorId": "0", "Value": 1, "Msg": "待用户确认"}},
        ])
        with tempfile.TemporaryDirectory() as folder:
            client = TdxSimClient(
                "http://unused",
                "demo",
                True,
                error_log=JsonlErrorLog(Path(folder)),
                transport=lambda method, params: next(responses),
            )
            with self.assertRaises(TdxSimulationGuardError):
                client.submit_limit_order("000001.SZ", Side.BUY, 100, Decimal("10.00"))

    def test_simulation_order_and_snapshot_preserve_tdx_facts(self) -> None:
        requests: list[tuple[str, dict]] = []

        def transport(method, params):
            requests.append((method, params))
            values = {
                "stock_account": {"ErrorId": "0", "Value": 9},
                "order_stock": {"ErrorId": "0", "Value": 2, "Wtbh": "SIM-1", "Msg": "成功"},
                "query_stock_asset": {"ErrorId": "0", "Cash": "90000", "Asset": "100000"},
                "query_stock_positions": {
                    "ErrorId": "0", "Value": [{"Code": "000001.SZ", "TotalVol": "100"}]
                },
                "query_stock_orders": {
                    "ErrorId": "0", "Value": [{"Wtbh": "SIM-1", "Status": 3, "CjVol": "100"}]
                },
            }
            return {"result": values[method]}

        client = TdxSimClient("http://unused", "demo", True, transport=transport)
        result = client.submit_limit_order("000001.SZ", Side.BUY, 100, Decimal("10.00"))
        snapshot = client.snapshot()
        self.assertEqual(result["Wtbh"], "SIM-1")
        self.assertEqual(snapshot.asset["Cash"], "90000")
        self.assertEqual(snapshot.positions[0]["TotalVol"], "100")
        self.assertEqual(snapshot.orders[0]["CjVol"], "100")
        self.assertEqual([item[0] for item in requests], [
            "stock_account", "order_stock", "query_stock_asset", "query_stock_positions", "query_stock_orders"
        ])

    def test_confirmed_current_simulation_account_can_use_empty_account_name(self) -> None:
        requests = []

        def transport(method, params):
            requests.append((method, params))
            return {"result": {"ErrorId": "0", "Value": 9}}

        client = TdxSimClient("http://unused", None, True, transport=transport)
        self.assertEqual(client.account_handle(), 9)
        self.assertEqual(requests, [("stock_account", {"account": "", "account_type": "STOCK"})])

    def test_business_error_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client = TdxSimClient(
                "http://unused",
                "demo",
                True,
                error_log=JsonlErrorLog(Path(folder)),
                transport=lambda method, params: {"result": {"ErrorId": "9", "Error": "账户未登录"}},
            )
            with self.assertRaises(TdxSimError):
                client.account_handle()
            record = json.loads(next(Path(folder).glob("*.jsonl")).read_text(encoding="utf-8"))
            self.assertIn("business error", record["message"])

    def test_executor_continues_after_one_order_error(self) -> None:
        class FakeMarket:
            @staticmethod
            def get_snapshot(symbol):
                return Quote(
                    symbol=symbol, received_at=NOW, last=Decimal("10"), prev_close=Decimal("9.9"),
                    bid_price=Decimal("9.99"), ask_price=Decimal("10.01"), bid_volume=10000,
                    ask_volume=10000, volume=100000, source="tdx",
                )

        class FakeSim:
            def __init__(self):
                self.calls = 0

            @staticmethod
            def snapshot():
                return TdxSimSnapshot(NOW, {"Asset": "100000"}, [], [])

            def submit_limit_order(self, symbol, side, quantity, price):
                self.calls += 1
                if self.calls == 1:
                    raise TdxSimError("first order failed")
                return {"Value": 2, "Wtbh": "SIM-2", "Msg": "成功"}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "strategy_set_id": "set-demo",
                "signal_date": "2026-07-13",
                "strategies": [
                    {"strategy": "one", "symbols": ["000001.SZ"]},
                    {"strategy": "two", "symbols": ["600000.SH"]},
                ],
            }), encoding="utf-8")
            repository = ObservabilityRepository(root / "observability.db")
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            result = execute_tdx_sim_plan(
                plan, "set-demo", FakeMarket(), FakeSim(), repository, JsonlErrorLog(root / "logs"), NOW
            )
            self.assertEqual(result["enqueued"], 2)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(result["acknowledged"], 1)
            self.assertEqual(
                [item["limit_price"] for item in repository.tdx_sim_orders()],
                ["10.04", "10.04"],
            )
            self.assertEqual([item["status"] for item in repository.tdx_sim_orders()], ["ERROR", "ACK"])
            repository.close()

    def test_daily_review_saves_tdx_facts_and_reports_unknown(self) -> None:
        class FakeSim:
            @staticmethod
            def snapshot():
                return TdxSimSnapshot(
                    NOW,
                    {"Cash": "90000", "Asset": "100000"},
                    [{"Code": "000001.SZ", "TotalVol": "100"}],
                    [{"Wtbh": "SIM-1", "Status": 3, "CjVol": "100"}],
                )

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repository = ObservabilityRepository(root / "observability.db")
            repository.register_strategy_set("set-demo", "a" * 64, "abc", {}, NOW)
            repository.enqueue_tdx_sim_order({
                "client_order_id": "set-demo:unknown",
                "strategy_set_id": "set-demo",
                "strategy": "combined_observer",
                "signal_date": "2026-07-13",
                "symbol": "000001.SZ",
                "side": "BUY",
                "quantity": 100,
                "limit_price": "10",
                "created_at": NOW.isoformat(),
            })
            repository.claim_tdx_sim_orders(NOW)
            repository.finish_tdx_sim_order("set-demo:unknown", "UNKNOWN", NOW, error="timeout")
            result = review_tdx_sim_day(
                FakeSim(), repository, JsonlErrorLog(root / "logs"), root / "reviews", NOW
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["uncertain_orders"], ["set-demo:unknown"])
            self.assertEqual(len(repository.tdx_sim_daily_facts()), 1)
            self.assertTrue(Path(result["path"]).exists())
            repository.close()


if __name__ == "__main__":
    unittest.main()
