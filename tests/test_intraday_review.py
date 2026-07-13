from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.intraday_review import ReviewOrder, run_intraday_review, write_intraday_report
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
