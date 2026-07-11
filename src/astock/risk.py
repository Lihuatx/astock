from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from astock.models import AccountSnapshot, Side, TradeIntent


@dataclass(frozen=True)
class RiskLimits:
    max_total_position_pct: Decimal = Decimal("0.90")
    max_single_position_pct: Decimal = Decimal("0.15")
    max_order_amount: Decimal = Decimal("15000")
    max_daily_orders: int = 10
    daily_loss_stop_pct: Decimal = Decimal("0.02")


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = "allowed"


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(
        self,
        intent: TradeIntent,
        account: AccountSnapshot,
        prices: dict[str, Decimal],
        daily_order_count: int,
        daily_pnl_pct: Decimal = Decimal("0"),
    ) -> RiskDecision:
        if daily_pnl_pct <= -self.limits.daily_loss_stop_pct:
            return RiskDecision(False, "daily_loss_stop")
        if daily_order_count >= self.limits.max_daily_orders:
            return RiskDecision(False, "daily_order_limit")
        amount = intent.limit_price * intent.quantity
        if amount > self.limits.max_order_amount:
            return RiskDecision(False, "order_amount_limit")
        if intent.side is Side.SELL:
            return RiskDecision(True)
        market_value = sum(Decimal(quantity) * prices.get(symbol, Decimal("0")) for symbol, quantity in account.positions.items())
        equity = account.cash + market_value
        if equity <= 0:
            return RiskDecision(False, "invalid_equity")
        symbol_value = Decimal(account.positions.get(intent.symbol, 0)) * prices.get(intent.symbol, intent.limit_price)
        if (symbol_value + amount) / equity > self.limits.max_single_position_pct:
            return RiskDecision(False, "single_position_limit")
        if (market_value + amount) / equity > self.limits.max_total_position_pct:
            return RiskDecision(False, "total_position_limit")
        return RiskDecision(True)

