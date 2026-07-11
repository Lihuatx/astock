from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.broker import AShareSimBroker
from astock.data.tdx import TdxClient
from astock.oms import OMS
from astock.research import MarketPanel, factor_specs, select_symbols
from astock.risk import RiskEngine, RiskLimits
from astock.storage import Repository
from astock.strategy import MomentumTrendStrategy


@dataclass(frozen=True)
class PaperAccountStatus:
    strategy: str
    db_path: str
    cash: str
    position_count: int
    order_count: int
    fill_count: int


class MultiStrategyPaperAccounts:
    def __init__(self, root: Path, initial_cash: Decimal) -> None:
        self.root = root
        self.initial_cash = initial_cash

    @staticmethod
    def selected_strategies(report_path: Path) -> list[str]:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        selected = report.get("selected") or []
        strategies = [item["strategy"] if isinstance(item, dict) else str(item) for item in selected]
        if len(strategies) != 3:
            raise ValueError("research report must contain exactly three selected strategies")
        return strategies

    def prepare(self, report_path: Path) -> list[PaperAccountStatus]:
        strategies = [*self.selected_strategies(report_path), "combined_observer"]
        statuses: list[PaperAccountStatus] = []
        for strategy in strategies:
            path = self.root / strategy / "account.db"
            repository = Repository(path)
            broker = AShareSimBroker(repository, self.initial_cash)
            snapshot = broker.snapshot(date.today())
            statuses.append(
                PaperAccountStatus(
                    strategy=strategy,
                    db_path=str(path),
                    cash=str(snapshot.cash),
                    position_count=len(snapshot.positions),
                    order_count=len(repository.load_orders()),
                    fill_count=len(repository.load_fills()),
                )
            )
            repository.close()
        return statuses

    @staticmethod
    def create_signal_plan(report_path: Path, panel: MarketPanel, target_path: Path) -> dict:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        specs = {spec.name: spec for spec in factor_specs()}
        signal_index = len(panel.dates) - 1
        strategies = []
        for selected in report.get("selected") or []:
            name = selected["strategy"]
            spec = replace(
                specs[name],
                top_n=int(selected["top_n"]),
                rebalance_days=int(selected["rebalance_days"]),
                minimum_market_breadth=float(selected["minimum_market_breadth"]),
            )
            columns = select_symbols(panel, spec, signal_index)
            strategies.append({"strategy": name, "symbols": panel.symbols[columns].tolist()})
        plan = {
            "signal_date": str(panel.dates[signal_index]),
            "earliest_execution_date": None,
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "rule": "T close signal; execution is forbidden before the next trading day",
            "strategies": strategies,
        }
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan

    def execute_plan(self, plan_path: Path, client: TdxClient, trading_day: date, executed_at: datetime) -> list[dict]:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        signal_day = date.fromisoformat(plan["signal_date"])
        if trading_day <= signal_day:
            raise ValueError("paper execution must be after the signal date")
        confirmed = client.get_trading_dates(
            (signal_day + timedelta(days=1)).strftime("%Y%m%d"), trading_day.strftime("%Y%m%d")
        )
        if trading_day not in confirmed:
            raise ValueError("paper execution date is not confirmed by TDX trading calendar")
        results: list[dict] = []
        for strategy_plan in plan["strategies"]:
            strategy = strategy_plan["strategy"]
            repository = Repository(self.root / strategy / "account.db")
            broker = AShareSimBroker(repository, self.initial_cash)
            account = broker.snapshot(trading_day)
            symbols = sorted(set(strategy_plan["symbols"]) | set(account.positions))
            quotes = {symbol: client.get_snapshot(symbol) for symbol in symbols}
            prices = {symbol: quote.last for symbol, quote in quotes.items()}
            equity = account.cash + sum(Decimal(quantity) * prices[symbol] for symbol, quantity in account.positions.items())
            intents = MomentumTrendStrategy().rebalance_intents(
                strategy_plan["symbols"], account.positions, prices, equity, executed_at
            )
            oms = OMS(repository, broker)
            risk = RiskEngine(RiskLimits(max_daily_orders=25))
            daily_order_count = 0
            for intent in intents:
                if risk.evaluate(intent, account, prices, daily_order_count).allowed:
                    oms.enqueue(intent)
                    daily_order_count += 1
            orders = oms.dispatch(quotes, trading_day, executed_at)
            fills = [broker.match(order.client_order_id, quotes[order.symbol], executed_at) for order in orders]
            results.append(
                {
                    "strategy": strategy,
                    "order_count": len(orders),
                    "fill_count": sum(fill is not None for fill in fills),
                    "reconciled": broker.reconcile(trading_day).ok,
                }
            )
            repository.close()
        return results
