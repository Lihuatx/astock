from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from astock.broker import AShareSimBroker
from astock.models import Bar, Quote
from astock.oms import OMS
from astock.risk import RiskEngine
from astock.strategy import MomentumTrendStrategy


SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class EquityPoint:
    trading_day: str
    equity: Decimal
    cash: Decimal
    reconciled: bool


class ReplayEngine:
    def __init__(self, broker: AShareSimBroker, oms: OMS, risk: RiskEngine, strategy: MomentumTrendStrategy) -> None:
        self.broker = broker
        self.oms = oms
        self.risk = risk
        self.strategy = strategy

    def run(self, bars_by_symbol: dict[str, list[Bar]]) -> list[EquityPoint]:
        by_day: dict = {}
        for symbol, bars in bars_by_symbol.items():
            for bar in bars:
                by_day.setdefault(bar.trading_day, {})[symbol] = bar
        days = sorted(by_day)
        history: dict[str, list[Bar]] = {symbol: [] for symbol in bars_by_symbol}
        curve: list[EquityPoint] = []
        daily_orders = 0
        for index, trading_day in enumerate(days):
            today = by_day[trading_day]
            prices = {symbol: bar.open for symbol, bar in today.items()}
            account = self.broker.snapshot(trading_day)
            equity = account.cash + sum(
                Decimal(quantity) * prices.get(symbol, Decimal("0")) for symbol, quantity in account.positions.items()
            )
            if index >= 60 and index % 5 == 0:
                selected = self.strategy.select(history)
                created_at = datetime.combine(trading_day, time(9, 35), SHANGHAI)
                intents = self.strategy.rebalance_intents(selected, account.positions, prices, equity, created_at)
                quotes: dict[str, Quote] = {}
                accepted = []
                for intent in intents:
                    bar = today.get(intent.symbol)
                    if not bar:
                        continue
                    decision = self.risk.evaluate(intent, account, prices, daily_orders)
                    if not decision.allowed:
                        continue
                    quotes[intent.symbol] = Quote(
                        symbol=intent.symbol,
                        received_at=created_at,
                        source_at=created_at,
                        last=bar.open,
                        prev_close=history[intent.symbol][-1].close,
                        bid_price=bar.open,
                        ask_price=bar.open,
                        bid_volume=max(100, bar.volume),
                        ask_volume=max(100, bar.volume),
                        volume=bar.volume,
                        source="replay",
                    )
                    self.oms.enqueue(intent)
                    daily_orders += 1
                accepted = self.oms.dispatch(quotes, trading_day, created_at)
                next_day = days[index + 1] if index + 1 < len(days) else trading_day
                for order in accepted:
                    self.broker.match(order.client_order_id, quotes[order.symbol], created_at, sellable_on=next_day)
            for symbol in history:
                if symbol in today:
                    history[symbol].append(today[symbol])
            close_prices = {symbol: bar.close for symbol, bar in today.items()}
            account = self.broker.snapshot(trading_day)
            equity = account.cash + sum(
                Decimal(quantity) * close_prices.get(symbol, Decimal("0"))
                for symbol, quantity in account.positions.items()
            )
            curve.append(EquityPoint(trading_day.isoformat(), equity, account.cash, self.broker.reconcile(trading_day).ok))
            daily_orders = 0
        return curve
