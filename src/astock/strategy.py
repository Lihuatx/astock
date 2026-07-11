from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_FLOOR

from astock.models import Bar, Side, TradeIntent


class MomentumTrendStrategy:
    def __init__(self, top_n: int = 6, momentum_window: int = 20, trend_window: int = 60) -> None:
        self.top_n = top_n
        self.momentum_window = momentum_window
        self.trend_window = trend_window

    def select(self, histories: dict[str, list[Bar]]) -> list[str]:
        ranked: list[tuple[Decimal, str]] = []
        required = max(self.momentum_window + 1, self.trend_window)
        for symbol, bars in histories.items():
            if len(bars) < required:
                continue
            closes = [bar.close for bar in bars]
            latest = closes[-1]
            trend = sum(closes[-self.trend_window :], Decimal("0")) / self.trend_window
            if latest <= trend or closes[-self.momentum_window - 1] <= 0:
                continue
            momentum = latest / closes[-self.momentum_window - 1] - Decimal("1")
            ranked.append((momentum, symbol))
        ranked.sort(reverse=True)
        return [symbol for _, symbol in ranked[: self.top_n]]

    def rebalance_intents(
        self,
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
                        reason="weekly_rebalance_exit",
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
                        reason="momentum_trend_entry",
                    )
                )
        return intents

