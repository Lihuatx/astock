from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.intraday_review import ReviewOrder, load_intraday_bars, run_intraday_review, write_intraday_report
from astock.data.pytdx import PytdxMinuteClient
from astock.models import Bar


SHANGHAI = ZoneInfo("Asia/Shanghai")


def bars(symbol: str, day: str, *, low: str = "10", high: str = "10.03", volume: int = 100_000) -> list[Bar]:
    trading_day = date.fromisoformat(day)
    start = datetime.combine(trading_day, datetime.strptime("09:35", "%H:%M").time(), SHANGHAI)
    return [
        Bar(
            symbol=symbol,
            trading_day=trading_day,
            timestamp=start + timedelta(minutes=5 * index),
            open=Decimal("10"),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal("10.01"),
            volume=volume,
            amount=Decimal("100"),
            source="tdx",
        )
        for index in range(6)
    ]


class IntradayReviewCase(unittest.TestCase):
    def test_historical_fallback_merges_without_overwriting_tdx(self) -> None:
        tdx_bar = bars("000001.SZ", "2026-07-10")[0]
        fallback_bars = [
            *[
                Bar(**{**item.__dict__, "source": "pytdx"})
                for item in bars("000001.SZ", "2026-07-09")
            ],
            Bar(**{**tdx_bar.__dict__, "open": Decimal("9"), "source": "pytdx"}),
        ]

        class TdxStub:
            def get_bars(self, *args, **kwargs):
                return [tdx_bar]

        class FallbackStub:
            def get_bars(self, *args, **kwargs):
                return fallback_bars

        with tempfile.TemporaryDirectory() as folder:
            result = load_intraday_bars(
                TdxStub(),
                ["000001.SZ"],
                ["2026-07-09", "2026-07-10"],
                Path(folder),
                refresh=True,
                fallback_client=FallbackStub(),
            )["000001.SZ"]
            payload = json.loads((Path(folder) / "000001.SZ.json").read_text(encoding="utf-8"))
        overlap = next(item for item in result if item.timestamp == tdx_bar.timestamp)
        self.assertEqual(overlap.source, "tdx")
        self.assertEqual(overlap.open, Decimal("10"))
        self.assertEqual(payload["sources"], ["pytdx", "tdx"])

    def test_pytdx_paginates_until_requested_start(self) -> None:
        def row(timestamp: str) -> dict:
            return {
                "datetime": timestamp,
                "open": 10,
                "high": 10.1,
                "low": 9.9,
                "close": 10,
                "vol": 1000,
                "amount": 10000,
            }

        class ApiStub:
            def connect(self, *args, **kwargs):
                return self

            def get_security_bars(self, category, market, code, offset, count):
                return {
                    0: [row("2026-03-01 09:35")],
                    800: [row("2026-02-06 09:35")],
                }.get(offset, [])

            def disconnect(self):
                return None

        client = PytdxMinuteClient(hosts=[("test", "127.0.0.1", 7709)], api_factory=ApiStub)
        result = client.get_bars("000001.SZ", "20260206", "20260301")
        self.assertEqual([item.timestamp.strftime("%Y-%m-%d %H:%M") for item in result], ["2026-02-06 09:35", "2026-03-01 09:35"])
        self.assertTrue(all(item.source == "pytdx" for item in result))

    def test_volume_is_not_reused_across_accounts(self) -> None:
        orders = [
            ReviewOrder(strategy, "2026-07-09", "2026-07-10", "000001.SZ", "BUY", 6000, "10.02")
            for strategy in ("alpha", "beta")
        ]
        day_bars = bars("000001.SZ", "2026-07-10", volume=10_000)
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            report.write_text("{}", encoding="utf-8")
            result = run_intraday_review(
                orders,
                ["2026-07-10"],
                {"000001.SZ": day_bars},
                ["alpha", "beta"],
                report_path=report,
                git_sha="abc",
            )
        details = result["windows"]["30"]["details"]
        self.assertEqual(sum(item["filled_quantity"] for item in details), 6000)
        self.assertEqual(details[0]["filled_quantity"], 6000)
        self.assertEqual(details[1]["filled_quantity"], 0)

    def test_limit_and_window_are_enforced(self) -> None:
        order = ReviewOrder("alpha", "2026-07-09", "2026-07-10", "000001.SZ", "BUY", 1000, "10.02")
        day_bars = bars("000001.SZ", "2026-07-10", low="10.03", high="10.10")
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            report.write_text("{}", encoding="utf-8")
            result = run_intraday_review(
                [order],
                ["2026-07-10"],
                {"000001.SZ": day_bars},
                ["alpha"],
                report_path=report,
                git_sha="abc",
            )
        detail = result["windows"]["30"]["details"][0]
        self.assertEqual(detail["filled_quantity"], 0)
        self.assertEqual(detail["result"], "limit_not_touched")

    def test_missing_direction_and_data_cannot_pass(self) -> None:
        order = ReviewOrder("alpha", "2026-07-09", "2026-07-10", "000001.SZ", "BUY", 1000, "10.02")
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            report.write_text(json.dumps({"selected": []}), encoding="utf-8")
            result = run_intraday_review(
                [order],
                ["2026-07-10"],
                {},
                ["alpha"],
                report_path=report,
                git_sha="abc",
            )
            write_intraday_report(result, Path(folder) / "result.json", Path(folder) / "result.md")
            self.assertTrue((Path(folder) / "result.md").exists())
        metrics = result["windows"]["30"]["strategies"][0]
        self.assertFalse(metrics["passed"])
        self.assertEqual(metrics["coverage"]["ratio"], 0)
        self.assertFalse(metrics["direction_evidence"]["SELL"])


if __name__ == "__main__":
    unittest.main()
