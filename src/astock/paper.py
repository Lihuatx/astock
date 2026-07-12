from __future__ import annotations

import json
import numpy as np
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.broker import AShareSimBroker
from astock.data.tdx import TdxClient
from astock.oms import OMS
from astock.models import Side, TradeIntent
from astock.data.tushare import FundamentalPanel
from astock.research import MarketPanel, factor_specs, fundamental_factor_specs
from astock.risk import RiskEngine, RiskLimits
from astock.storage import Repository
from astock.observability.bundle import sha256_file, strategy_set_id as report_strategy_set_id
from astock.observability.repository import ObservabilityRepository
from astock.research import select_symbols_with_audit


PAPER_SLIPPAGE = Decimal("0.002")


def _rebalance_intents(
    strategy: str,
    selected: list[str],
    positions: dict[str, int],
    prices: dict[str, Decimal],
    equity: Decimal,
    created_at: datetime,
) -> list[TradeIntent]:
    intents: list[TradeIntent] = []
    selected_set = set(selected)
    for symbol, quantity in sorted(positions.items()):
        if quantity > 0 and symbol not in selected_set:
            intents.append(
                TradeIntent(
                    client_order_id=f"{created_at:%Y%m%d}-{symbol}-SELL",
                    symbol=symbol,
                    side=Side.SELL,
                    quantity=quantity,
                    limit_price=prices[symbol],
                    created_at=created_at,
                    reason=f"{strategy}_rebalance_exit",
                )
            )
    if not selected:
        return intents
    target_value = min(equity * Decimal("0.90") / len(selected), equity * Decimal("0.15"))
    for symbol in selected:
        price = prices[symbol]
        target_quantity = int((target_value / price / 100).to_integral_value(rounding=ROUND_FLOOR)) * 100
        delta = target_quantity - positions.get(symbol, 0)
        if delta >= 100:
            intents.append(
                TradeIntent(
                    client_order_id=f"{created_at:%Y%m%d}-{symbol}-BUY",
                    symbol=symbol,
                    side=Side.BUY,
                    quantity=delta,
                    limit_price=price,
                    created_at=created_at,
                    reason=f"{strategy}_rebalance_entry",
                )
            )
    return intents


@dataclass(frozen=True)
class PaperAccountStatus:
    strategy: str
    db_path: str
    cash: str
    position_count: int
    order_count: int
    fill_count: int


class MultiStrategyPaperAccounts:
    def __init__(
        self,
        root: Path,
        initial_cash: Decimal,
        observability: ObservabilityRepository | None = None,
        strategy_set_id: str | None = None,
    ) -> None:
        self.root = root
        self.initial_cash = initial_cash
        self.observability = observability
        self.strategy_set_id = strategy_set_id

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
            if self.observability:
                account_id = f"{self.strategy_set_id or 'legacy'}:{strategy}:g1"
                self.observability.register_account(
                    account_id,
                    strategy,
                    1,
                    path,
                    self.initial_cash,
                    datetime.now(ZoneInfo("Asia/Shanghai")),
                    self.strategy_set_id,
                    "CURRENT",
                )
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
    def create_signal_plan(
        report_path: Path,
        panel: MarketPanel,
        target_path: Path,
        fundamentals: FundamentalPanel | None = None,
        schedule_root: Path | None = None,
    ) -> dict:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_hash = sha256_file(report_path)
        set_id = report_strategy_set_id(report_path)
        available_specs = factor_specs() + (fundamental_factor_specs(fundamentals) if fundamentals is not None else ())
        specs = {spec.name: spec for spec in available_specs}
        signal_index = len(panel.dates) - 1
        strategies = []
        skipped = []
        for selected in report.get("selected") or []:
            name = selected["strategy"]
            rebalance_days = int(selected["rebalance_days"])
            if schedule_root is not None:
                state_path = schedule_root / name / "schedule.json"
                if state_path.exists():
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    last_signal_date = str(state.get("last_signal_date") or "")
                    elapsed = int(np.sum((panel.dates > last_signal_date) & (panel.dates <= panel.dates[signal_index])))
                    if last_signal_date and elapsed < rebalance_days:
                        skipped.append(
                            {
                                "strategy": name,
                                "reason": "rebalance_not_due",
                                "last_signal_date": last_signal_date,
                                "trading_days_elapsed": elapsed,
                                "rebalance_days": rebalance_days,
                            }
                        )
                        continue
            spec = replace(
                specs[name],
                top_n=int(selected["top_n"]),
                rebalance_days=rebalance_days,
                minimum_market_breadth=float(selected["minimum_market_breadth"]),
            )
            columns, selection_audit = select_symbols_with_audit(panel, spec, signal_index)
            strategies.append(
                {
                    "strategy": name,
                    "symbols": panel.symbols[columns].tolist(),
                    "rebalance_days": rebalance_days,
                    "selection_audit": [item.__dict__ for item in selection_audit],
                }
            )
        plan = {
            "schema_version": 1,
            "strategy_set_id": set_id,
            "report_sha256": report_hash,
            "signal_date": str(panel.dates[signal_index]),
            "earliest_execution_date": None,
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "rule": "T close signal; execution is forbidden before the next trading day",
            "strategies": strategies,
            "skipped": skipped,
        }
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return plan

    def execute_plan(
        self,
        plan_path: Path,
        client: TdxClient,
        trading_day: date,
        executed_at: datetime,
        expected_strategy_set_id: str | None = None,
    ) -> list[dict]:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        expected = expected_strategy_set_id or self.strategy_set_id
        if expected and plan.get("strategy_set_id") != expected:
            if self.observability:
                self.observability.append_event(
                    "STALE_SIGNAL_PLAN",
                    executed_at,
                    {"expected_strategy_set_id": expected, "actual_strategy_set_id": plan.get("strategy_set_id")},
                    event_id=f"stale-plan:{plan_path}",
                )
            raise ValueError("pending signal plan does not match the current strategy set")
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
            schedule_path = self.root / strategy / "schedule.json"
            if schedule_path.exists():
                state = json.loads(schedule_path.read_text(encoding="utf-8"))
                if str(state.get("last_signal_date") or "") >= plan["signal_date"]:
                    results.append({"strategy": strategy, "skipped": True, "reason": "signal_already_executed"})
                    continue
            repository = Repository(self.root / strategy / "account.db")
            broker = AShareSimBroker(repository, self.initial_cash)
            account = broker.snapshot(trading_day)
            symbols = sorted(set(strategy_plan["symbols"]) | set(account.positions))
            quotes = {symbol: client.get_snapshot(symbol) for symbol in symbols}
            prices = {symbol: quote.last for symbol, quote in quotes.items()}
            equity = account.cash + sum(Decimal(quantity) * prices[symbol] for symbol, quantity in account.positions.items())
            intents = _rebalance_intents(
                strategy, strategy_plan["symbols"], account.positions, prices, equity, executed_at
            )
            oms = OMS(repository, broker)
            risk = RiskEngine(RiskLimits(max_daily_orders=25))
            daily_order_count = 0
            for intent in intents:
                reference = quotes[intent.symbol]
                execution_price = (
                    reference.ask_price * (Decimal("1") + PAPER_SLIPPAGE)
                    if intent.side is Side.BUY
                    else reference.bid_price * (Decimal("1") - PAPER_SLIPPAGE)
                )
                intent = replace(intent, limit_price=execution_price)
                decision = risk.evaluate(intent, account, prices, daily_order_count)
                if self.observability:
                    self.observability.append_event(
                        "RISK_DECISION",
                        executed_at,
                        {
                            "strategy": strategy,
                            "client_order_id": intent.client_order_id,
                            "allowed": decision.allowed,
                            "reason": decision.reason,
                        },
                        event_id=f"risk:{strategy}:{intent.client_order_id}",
                        account_id=f"{self.strategy_set_id}:{strategy}:g1" if self.strategy_set_id else None,
                    )
                if decision.allowed:
                    oms.enqueue(intent)
                    daily_order_count += 1
            orders = oms.dispatch(quotes, trading_day, executed_at)
            fills = []
            for order in orders:
                quote = quotes[order.symbol]
                execution_quote = (
                    replace(quote, ask_price=quote.ask_price * (Decimal("1") + PAPER_SLIPPAGE))
                    if order.side is Side.BUY
                    else replace(quote, bid_price=quote.bid_price * (Decimal("1") - PAPER_SLIPPAGE))
                )
                fills.append(broker.match(order.client_order_id, execution_quote, executed_at))
            reconciliation = broker.reconcile(trading_day)
            if self.observability:
                account_id = f"{self.strategy_set_id}:{strategy}:g1" if self.strategy_set_id else None
                for order in orders:
                    self.observability.append_event(
                        "ORDER",
                        executed_at,
                        {
                            "strategy": strategy,
                            "client_order_id": order.client_order_id,
                            "symbol": order.symbol,
                            "side": order.side.value,
                            "quantity": order.quantity,
                            "status": order.status.value,
                        },
                        event_id=f"audit-order:{strategy}:{order.client_order_id}",
                        account_id=account_id,
                    )
                for fill in (item for item in fills if item is not None):
                    self.observability.append_event(
                        "FILL",
                        fill.filled_at,
                        {
                            "strategy": strategy,
                            "fill_id": fill.fill_id,
                            "client_order_id": fill.client_order_id,
                            "quantity": fill.quantity,
                            "price": str(fill.price),
                            "total_fee": str(fill.total_fee),
                        },
                        event_id=f"audit-fill:{strategy}:{fill.fill_id}",
                        account_id=account_id,
                    )
                self.observability.append_event(
                    "RECONCILIATION",
                    executed_at,
                    {"strategy": strategy, "ok": reconciliation.ok, "reasons": reconciliation.reasons},
                    event_id=f"reconciliation:{strategy}:{trading_day.isoformat()}",
                    account_id=account_id,
                )
            results.append(
                {
                    "strategy": strategy,
                    "order_count": len(orders),
                    "fill_count": sum(fill is not None for fill in fills),
                    "reconciled": reconciliation.ok,
                }
            )
            if reconciliation.ok:
                schedule_path.parent.mkdir(parents=True, exist_ok=True)
                schedule_path.write_text(
                    json.dumps(
                        {
                            "last_signal_date": plan["signal_date"],
                            "last_execution_date": trading_day.isoformat(),
                            "rebalance_days": int(strategy_plan["rebalance_days"]),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            repository.close()
        return results
