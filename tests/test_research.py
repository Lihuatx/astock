from __future__ import annotations

import unittest
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from datetime import date, datetime

import numpy as np

from astock.research import MarketPanel, backtest, factor_specs, select_symbols
from astock.paper import MultiStrategyPaperAccounts


def synthetic_panel(days: int = 260, symbols: int = 8) -> MarketPanel:
    dates = np.arange(np.datetime64("2025-01-01"), np.datetime64("2025-01-01") + days).astype("datetime64[D]").astype("U10")
    base = np.arange(days, dtype=np.float64)[:, None]
    slopes = np.linspace(0.01, 0.08, symbols)[None, :]
    close = 10.0 + base * slopes
    open_ = close * 1.001
    high = close * 1.01
    low = close * 0.99
    volume = np.full_like(close, 5_000_000.0)
    amount = volume * close
    names = np.array([f"{index:06d}.SZ" for index in range(symbols)], dtype="U12")
    return MarketPanel(dates, names, open_, high, low, close, volume, amount)


class ResearchCausalityCase(unittest.TestCase):
    def test_future_mutation_does_not_change_existing_signal(self) -> None:
        panel = synthetic_panel()
        spec = factor_specs()[0]
        original = select_symbols(panel, spec, 180).tolist()
        changed_close = panel.close.copy()
        changed_close[181:] = changed_close[181:, ::-1] * 100
        changed = MarketPanel(
            panel.dates,
            panel.symbols,
            panel.open,
            panel.high,
            panel.low,
            changed_close,
            panel.volume,
            panel.amount,
        )
        self.assertEqual(original, select_symbols(changed, spec, 180).tolist())

    def test_every_execution_is_after_signal(self) -> None:
        panel = synthetic_panel()
        performance, curve, audit = backtest(panel, factor_specs()[0], "2025-01-01", "2025-09-17")
        self.assertTrue(audit)
        self.assertTrue(all(item.signal_date < item.execution_date for item in audit))
        self.assertTrue(performance.reconciled)
        self.assertEqual(len(curve), len(panel.dates))

    def test_all_candidate_factors_are_finite_when_history_exists(self) -> None:
        panel = synthetic_panel()
        for spec in factor_specs():
            selected = select_symbols(panel, spec, 180)
            self.assertLessEqual(len(selected), 5, spec.name)
            self.assertTrue(np.all(selected >= 0), spec.name)

    def test_paper_accounts_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "report.json"
            report.write_text(
                json.dumps({"selected": [{"strategy": name} for name in ("alpha", "beta", "gamma")]}),
                encoding="utf-8",
            )
            statuses = MultiStrategyPaperAccounts(root / "paper", Decimal("100000")).prepare(report)
            self.assertEqual(len(statuses), 4)
            self.assertEqual(len({status.db_path for status in statuses}), 4)
            self.assertTrue(all(status.cash == "100000" for status in statuses))
            selected = [spec.name for spec in factor_specs()[:3]]
            report.write_text(
                json.dumps(
                    {
                        "selected": [
                            {"strategy": name, "top_n": 5, "rebalance_days": 20, "minimum_market_breadth": 0.3}
                            for name in selected
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan = MultiStrategyPaperAccounts.create_signal_plan(report, synthetic_panel(), root / "plan.json")
            self.assertEqual(plan["signal_date"], "2025-09-17")
            self.assertEqual(len(plan["strategies"]), 3)
            with self.assertRaisesRegex(ValueError, "after the signal date"):
                MultiStrategyPaperAccounts(root / "paper", Decimal("100000")).execute_plan(
                    root / "plan.json", object(), date(2025, 9, 17), datetime(2025, 9, 17, 10)
                )


if __name__ == "__main__":
    unittest.main()
