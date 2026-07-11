from __future__ import annotations

import unittest
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from datetime import date, datetime

import numpy as np

from astock.research import MarketPanel, _wilder_rsi, backtest, factor_specs, fundamental_factor_specs, select_symbols
from astock.data.tushare import FundamentalPanel, build_fundamental_panel
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
        changed_close = panel.close.copy()
        changed_close[181:] = changed_close[181:, ::-1] * 100
        changed_high = panel.high.copy()
        changed_high[181:] *= 50
        changed_low = panel.low.copy()
        changed_low[181:] *= 0.1
        changed_volume = panel.volume.copy()
        changed_volume[181:] *= 100
        changed = MarketPanel(
            panel.dates,
            panel.symbols,
            panel.open,
            changed_high,
            changed_low,
            changed_close,
            changed_volume,
            panel.amount,
        )
        for spec in factor_specs():
            original = select_symbols(panel, spec, 180).tolist()
            self.assertEqual(original, select_symbols(changed, spec, 180).tolist(), spec.name)

    def test_every_execution_is_after_signal(self) -> None:
        panel = synthetic_panel()
        performance, curve, audit = backtest(panel, factor_specs()[0], "2025-01-01", "2025-09-17")
        self.assertTrue(audit)
        self.assertTrue(all(item.signal_date < item.execution_date for item in audit))
        self.assertTrue(performance.reconciled)
        self.assertEqual(len(curve), len(panel.dates))

    def test_wilder_rsi_and_slippage_are_causal(self) -> None:
        rising = np.arange(1, 32, dtype=np.float64)[:, None]
        self.assertEqual(float(_wilder_rsi(rising)[0]), 100.0)
        panel = synthetic_panel()
        spec = factor_specs()[0]
        low_cost, _, _ = backtest(panel, spec, "2025-01-01", "2025-09-17", slippage=0.001)
        high_cost, _, _ = backtest(panel, spec, "2025-01-01", "2025-09-17", slippage=0.003)
        self.assertLessEqual(high_cost.total_return, low_cost.total_return)

    def test_all_candidate_factors_are_finite_when_history_exists(self) -> None:
        panel = synthetic_panel()
        specs = factor_specs()
        self.assertEqual(len(specs), 15)
        for spec in specs:
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

    def test_fundamentals_become_available_after_announcement(self) -> None:
        class FakeClient:
            def query_many(self, api_name, requests_, fields, workers=4):
                if api_name == "fina_indicator":
                    return [
                        {
                            "ts_code": "000001.SZ",
                            "ann_date": "20250102",
                            "end_date": "20241231",
                            "roe": 10,
                            "roic": 8,
                            "grossprofit_margin": 30,
                            "debt_to_assets": 40,
                            "ocf_to_or": 12,
                            "q_sales_yoy": 9,
                            "q_netprofit_yoy": 11,
                        }
                    ]
                return [{"ts_code": "000001.SZ", "trade_date": "20250103", "pe_ttm": 8, "pb": 1.2, "dv_ttm": 2}]

        with tempfile.TemporaryDirectory() as folder:
            dates = np.array(["2025-01-02", "2025-01-03", "2025-01-06"], dtype="U10")
            symbols = np.array(["000001.SZ"], dtype="U12")
            panel = build_fundamental_panel(FakeClient(), dates, symbols, dates.tolist(), Path(folder) / "f.npz")
            self.assertTrue(np.isnan(panel.roe[0, 0]))
            self.assertEqual(panel.roe[1, 0], 10)
            self.assertEqual(panel.roe[2, 0], 10)
            self.assertEqual(panel.pe_ttm[1, 0], 8)
            self.assertTrue(np.isnan(panel.pe_ttm[2, 0]))

    def test_future_fundamentals_do_not_change_existing_signal(self) -> None:
        market = synthetic_panel()
        shape = market.close.shape
        values = np.tile(np.linspace(1, 8, shape[1]), (shape[0], 1))
        fundamentals = FundamentalPanel(
            market.dates,
            market.symbols,
            values,
            values,
            values,
            values,
            values,
            values,
            values,
            values + 5,
            values,
            values,
        )
        changed_values = values.copy()
        changed_values[181:] *= 100
        changed = FundamentalPanel(
            market.dates,
            market.symbols,
            changed_values,
            changed_values,
            changed_values,
            changed_values,
            changed_values,
            changed_values,
            changed_values,
            changed_values + 5,
            changed_values,
            changed_values,
        )
        for original_spec, changed_spec in zip(
            fundamental_factor_specs(fundamentals), fundamental_factor_specs(changed), strict=True
        ):
            self.assertEqual(
                select_symbols(market, original_spec, 180).tolist(),
                select_symbols(market, changed_spec, 180).tolist(),
                original_spec.name,
            )


if __name__ == "__main__":
    unittest.main()
