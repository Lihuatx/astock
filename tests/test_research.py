from __future__ import annotations

import unittest
import json
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from datetime import date, datetime

import numpy as np

from astock.research import TARGET_ANNUAL_RETURN, TARGET_MAX_DRAWDOWN, FactorSpec, MarketPanel, _wilder_rsi, backtest, factor_specs, fundamental_factor_specs, select_symbols, select_symbols_with_audit
from astock.data.tushare import FundamentalPanel, build_fundamental_panel
from astock.paper import MultiStrategyPaperAccounts
from astock.aggressive_research import _monthly_statistics
from astock.data.industry import IndustryPanel, build_industry_panel
from astock.industry_research import industry_relative_spec, industry_rotation_spec
from astock.cgo_research import TurnoverPanel, capital_gains_overhang, cgo_spec


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
    def test_stable_account_research_targets(self) -> None:
        self.assertEqual(TARGET_ANNUAL_RETURN, 0.15)
        self.assertEqual(TARGET_MAX_DRAWDOWN, 0.25)

    def test_selection_audit_matches_selected_symbols(self) -> None:
        panel = synthetic_panel(days=260, symbols=8)
        spec = replace(factor_specs()[0], top_n=3, minimum_market_breadth=0.0)
        selected, audit = select_symbols_with_audit(panel, spec, 200)
        np.testing.assert_array_equal(selected, select_symbols(panel, spec, 200))
        audited = {item.symbol for item in audit if item.selected}
        self.assertEqual(audited, set(panel.symbols[selected]))
        self.assertTrue(all(item.reason for item in audit))

    @staticmethod
    def _rotating_spec() -> FactorSpec:
        def scorer(panel: MarketPanel, index: int) -> np.ndarray:
            score = np.full(len(panel.symbols), -100.0)
            if index % 2 == 0:
                score[15:20] = np.arange(5)
            else:
                score[13:18] = np.arange(5)
            return score

        return FactorSpec(
            "rotating_test",
            "test",
            "fixed rotating targets",
            120,
            scorer,
            rebalance_days=1,
            top_n=5,
            minimum_market_breadth=0.30,
        )

    def test_open_execution_sizing_ignores_same_day_close(self) -> None:
        panel = synthetic_panel(days=300, symbols=20)
        changed_close = panel.close.copy()
        changed_close[182, 15:18] *= 100
        changed = MarketPanel(
            panel.dates, panel.symbols, panel.open, panel.high, panel.low,
            changed_close, panel.volume, panel.amount,
        )
        dates = (str(panel.dates[180]), str(panel.dates[183]))
        _, _, original_audit = backtest(panel, self._rotating_spec(), *dates)
        _, _, changed_audit = backtest(changed, self._rotating_spec(), *dates)
        original_orders = [(item.execution_date, item.symbol, item.side, item.quantity, item.price) for item in original_audit]
        changed_orders = [(item.execution_date, item.symbol, item.side, item.quantity, item.price) for item in changed_audit]
        self.assertEqual(original_orders, changed_orders)

    def test_open_execution_does_not_use_same_day_high_low(self) -> None:
        panel = synthetic_panel(days=300, symbols=20)
        open_ = panel.open.copy()
        open_[182, 13:15] = panel.close[181, 13:15] * 1.10
        changed_high = panel.high.copy()
        changed_low = panel.low.copy()
        changed_high[182, 13:15] = open_[182, 13:15]
        changed_low[182, 13:15] = open_[182, 13:15]
        original = MarketPanel(
            panel.dates, panel.symbols, open_, panel.high, panel.low,
            panel.close, panel.volume, panel.amount,
        )
        changed = MarketPanel(
            panel.dates, panel.symbols, open_, changed_high, changed_low,
            panel.close, panel.volume, panel.amount,
        )
        dates = (str(panel.dates[180]), str(panel.dates[183]))
        _, _, original_audit = backtest(original, self._rotating_spec(), *dates)
        _, _, changed_audit = backtest(changed, self._rotating_spec(), *dates)
        original_orders = [(item.execution_date, item.symbol, item.side) for item in original_audit]
        changed_orders = [(item.execution_date, item.symbol, item.side) for item in changed_audit]
        self.assertEqual(original_orders, changed_orders)

    def test_cgo_reference_price_and_future_data_are_causal(self) -> None:
        panel = synthetic_panel(days=300, symbols=20)
        turnover = np.full_like(panel.close, 0.02)
        score = capital_gains_overhang(panel.close, turnover, 180, 126)
        self.assertTrue(np.all(np.isfinite(score)))
        self.assertTrue(np.all(score > 0))
        changed_turnover = turnover.copy()
        changed_turnover[181:] = 0.90
        changed = TurnoverPanel(panel.dates, panel.symbols, changed_turnover)
        original = cgo_spec(TurnoverPanel(panel.dates, panel.symbols, turnover), 126).scorer(panel, 180)
        mutated = cgo_spec(changed, 126).scorer(panel, 180)
        np.testing.assert_allclose(original, mutated, equal_nan=True)

    def test_industry_membership_is_point_in_time(self) -> None:
        class FakeClient:
            def query(self, api_name, params, fields):
                self.assert_equal(api_name, "index_classify")
                return [
                    {
                        "index_code": "801010.SI",
                        "industry_name": "industry_a",
                        "industry_code": "110000",
                        "is_pub": "1",
                    },
                    {
                        "index_code": "801020.SI",
                        "industry_name": "industry_b",
                        "industry_code": "120000",
                        "is_pub": "1",
                    },
                ]

            def query_many(self, api_name, requests_, fields):
                if api_name == "index_member_all":
                    return [
                        {
                            "l1_code": "801010.SI",
                            "ts_code": "000001.SZ",
                            "in_date": "20250102",
                            "out_date": "20250103",
                        },
                        {
                            "l1_code": "801020.SI",
                            "ts_code": "000001.SZ",
                            "in_date": "20250106",
                            "out_date": None,
                        },
                    ]
                return []

            @staticmethod
            def assert_equal(left, right):
                if left != right:
                    raise AssertionError((left, right))

        with tempfile.TemporaryDirectory() as folder:
            dates = np.array(["2025-01-02", "2025-01-03", "2025-01-06"], dtype="U10")
            symbols = np.array(["000001.SZ"], dtype="U12")
            closes = np.array([[10.0], [10.1], [10.2]])
            panel = build_industry_panel(FakeClient(), dates, symbols, closes, Path(folder) / "industry.npz")
            self.assertEqual(panel.membership[:, 0].tolist(), [0, 0, 1])
            self.assertTrue(np.all(np.isfinite(panel.close)))

    def test_industry_relative_signal_does_not_use_future_data(self) -> None:
        panel = synthetic_panel(symbols=10)
        membership = np.tile(np.array([0] * 5 + [1] * 5, dtype=np.int16), (len(panel.dates), 1))
        industries = IndustryPanel(
            panel.dates,
            panel.symbols,
            np.array(["801010.SI", "801020.SI"]),
            np.array(["a", "b"]),
            membership,
            np.tile(np.linspace(1000, 1200, len(panel.dates))[:, None], (1, 2)),
        )
        spec = industry_relative_spec(factor_specs()[0], industries)
        changed_close = panel.close.copy()
        changed_close[181:] *= 100
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
        np.testing.assert_allclose(spec.scorer(panel, 180), spec.scorer(changed, 180), equal_nan=True)

        rotation = industry_rotation_spec(industries, factor_specs()[3], 2, 20)
        np.testing.assert_allclose(rotation.scorer(panel, 180), rotation.scorer(changed, 180), equal_nan=True)

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
        self.assertTrue(all(set(item.available_fields) <= {"previous_close", "open"} for item in audit))
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

    def test_aggressive_position_limit_and_monthly_statistics(self) -> None:
        panel = synthetic_panel()
        performance, curve, audit = backtest(
            panel,
            replace(factor_specs()[0], top_n=3, rebalance_days=2),
            "2025-01-01",
            "2025-09-17",
            initial_cash=30_000,
            max_position_weight=0.25,
            slippage=0.002,
        )
        stats = _monthly_statistics(panel.dates, curve, "2025-01-01", "2025-09-17")
        self.assertTrue(performance.reconciled)
        self.assertTrue(all(item.signal_date < item.execution_date for item in audit))
        self.assertGreater(stats["month_count"], 1)
        self.assertLessEqual(stats["worst_month"], stats["best_month"])

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

    def test_paper_plan_respects_each_strategy_rebalance_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            panel = synthetic_panel(days=260, symbols=20)
            selected = [spec.name for spec in factor_specs()[:3]]
            report = root / "report.json"
            report.write_text(
                json.dumps({
                    "selected": [
                        {"strategy": name, "top_n": 5, "rebalance_days": 20, "minimum_market_breadth": 0.3}
                        for name in selected
                    ]
                }),
                encoding="utf-8",
            )
            schedule_root = root / "paper"
            state_path = schedule_root / selected[0] / "schedule.json"
            state_path.parent.mkdir(parents=True)
            state_path.write_text(
                json.dumps({"last_signal_date": str(panel.dates[-2])}),
                encoding="utf-8",
            )
            plan = MultiStrategyPaperAccounts.create_signal_plan(
                report,
                panel,
                root / "plan.json",
                schedule_root=schedule_root,
            )
            self.assertEqual([item["strategy"] for item in plan["strategies"]], selected[1:])
            self.assertEqual(plan["skipped"][0]["strategy"], selected[0])
            self.assertEqual(plan["skipped"][0]["reason"], "rebalance_not_due")

    def test_paper_execution_persists_schedule_and_is_idempotent(self) -> None:
        class FakeClient:
            @staticmethod
            def get_trading_dates(start, end):
                return [date(2025, 1, 3)]

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / "report.json"
            report.write_text(
                json.dumps({"selected": [{"strategy": name} for name in ("alpha", "beta", "gamma")]}),
                encoding="utf-8",
            )
            manager = MultiStrategyPaperAccounts(root / "paper", Decimal("100000"))
            manager.prepare(report)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps({
                    "signal_date": "2025-01-02",
                    "strategies": [{"strategy": "alpha", "symbols": [], "rebalance_days": 20}],
                }),
                encoding="utf-8",
            )
            first = manager.execute_plan(
                plan_path,
                FakeClient(),
                date(2025, 1, 3),
                datetime(2025, 1, 3, 9, 31),
            )
            self.assertTrue(first[0]["reconciled"])
            state = json.loads((root / "paper" / "alpha" / "schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(state["last_signal_date"], "2025-01-02")
            second = manager.execute_plan(
                plan_path,
                FakeClient(),
                date(2025, 1, 3),
                datetime(2025, 1, 3, 9, 32),
            )
            self.assertEqual(second[0]["reason"], "signal_already_executed")

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
                            "ocf_to_opincome": 15,
                            "arturn_days": 30,
                            "invturn_days": 45,
                            "n_op_profit_of_ebt": 2,
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
            self.assertEqual(panel.ocf_to_opincome[1, 0], 15)
            self.assertEqual(panel.arturn_days[1, 0], 30)
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

    def test_v7_factors_are_finite_and_directional(self) -> None:
        market = synthetic_panel(symbols=24)
        shape = market.close.shape
        values = np.tile(np.linspace(1, 8, shape[1]), (shape[0], 1))
        fundamentals = FundamentalPanel(
            market.dates, market.symbols, values, values, values, values, values, values, values,
            values + 5, values, values,
            ocf_to_opincome=values,
            arturn_days=values[:, ::-1].copy(),
            invturn_days=values[:, ::-1].copy(),
            n_op_profit_of_ebt=values,
        )
        specs = {spec.name: spec for spec in fundamental_factor_specs(fundamentals)}
        for name in ("cash_conversion", "receivable_efficiency", "inventory_efficiency", "working_capital_efficiency", "non_operating_independence", "cash_quality_value"):
            self.assertTrue(np.isfinite(specs[name].scorer(market, 180)).any(), name)
        self.assertGreater(specs["cash_conversion"].scorer(market, 180)[-1], specs["cash_conversion"].scorer(market, 180)[0])


if __name__ == "__main__":
    unittest.main()
