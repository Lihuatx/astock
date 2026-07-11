from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from uuid import uuid4

from astock.fees import FeeSchedule, money
from astock.models import AccountSnapshot, Fill, Order, OrderStatus, PositionLot, Quote, Side, TradeIntent
from astock.storage import Repository


ACTIVE = {OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED}


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    reasons: tuple[str, ...]


def next_business_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


class AShareSimBroker:
    def __init__(
        self,
        repository: Repository,
        initial_cash: Decimal,
        fee_schedule: FeeSchedule | None = None,
        participation_rate: Decimal = Decimal("0.01"),
    ) -> None:
        self.repository = repository
        self.repository.initialize_account(initial_cash)
        self.cash = self.repository.load_cash()
        self.orders = {order.client_order_id: order for order in self.repository.load_orders()}
        self.lots = self.repository.load_lots()
        self.fee_schedule = fee_schedule or FeeSchedule()
        self.participation_rate = participation_rate

    def snapshot(self, trading_day: date) -> AccountSnapshot:
        positions: dict[str, int] = defaultdict(int)
        sellable: dict[str, int] = defaultdict(int)
        for lot in self.lots:
            positions[lot.symbol] += lot.quantity
            if lot.sellable_on <= trading_day:
                sellable[lot.symbol] += lot.available_quantity
        reserved_cash = Decimal("0")
        for order in self.orders.values():
            if order.status in ACTIVE and order.side is Side.BUY:
                reserved_cash += order.limit_price * order.remaining_quantity
                reserved_cash += self.fee_schedule.minimum_commission
        return AccountSnapshot(self.cash, money(reserved_cash), dict(positions), dict(sellable))

    def _reserved_sell(self, symbol: str) -> int:
        return sum(
            order.remaining_quantity
            for order in self.orders.values()
            if order.symbol == symbol and order.side is Side.SELL and order.status in ACTIVE
        )

    def _reserved_buy_cash(self, excluded_order_id: str | None = None) -> Decimal:
        reserved = Decimal("0")
        for order in self.orders.values():
            if order.client_order_id == excluded_order_id:
                continue
            if order.status in ACTIVE and order.side is Side.BUY:
                reserved += order.limit_price * order.remaining_quantity
                reserved += self.fee_schedule.minimum_commission
        return money(reserved)

    def submit(self, intent: TradeIntent, quote: Quote, trading_day: date) -> Order:
        existing = self.orders.get(intent.client_order_id)
        if existing:
            return existing
        order = Order(
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            limit_price=intent.limit_price,
            status=OrderStatus.ACCEPTED,
            created_at=intent.created_at,
        )
        reason = self._validate(order, quote, trading_day)
        if reason:
            order.status = OrderStatus.REJECTED
            order.reject_reason = reason
        self.orders[order.client_order_id] = order
        self.repository.save_order(order)
        self.repository.append_ledger(
            f"order:{order.client_order_id}",
            "ORDER_ACCEPTED" if not reason else "ORDER_REJECTED",
            {"order_id": order.client_order_id, "reason": reason},
            intent.created_at,
        )
        return order

    def _validate(self, order: Order, quote: Quote, trading_day: date) -> str | None:
        if order.quantity <= 0:
            return "invalid_quantity"
        if order.side is Side.BUY and order.quantity % 100:
            return "buy_quantity_not_board_lot"
        if order.limit_price <= 0:
            return "invalid_limit_price"
        if quote.suspended:
            return "suspended"
        if quote.upper_limit and order.limit_price > quote.upper_limit:
            return "above_upper_limit"
        if quote.lower_limit and order.limit_price < quote.lower_limit:
            return "below_lower_limit"
        account = self.snapshot(trading_day)
        if order.side is Side.BUY:
            required = order.limit_price * order.quantity + self.fee_schedule.minimum_commission
            if account.available_cash < required:
                return "insufficient_cash"
        else:
            sellable = account.sellable_positions.get(order.symbol, 0) - self._reserved_sell(order.symbol)
            if sellable < order.quantity:
                return "insufficient_sellable_position"
        return None

    def match(self, client_order_id: str, quote: Quote, filled_at: datetime, sellable_on: date | None = None) -> Fill | None:
        order = self.orders[client_order_id]
        if order.status not in ACTIVE:
            return None
        if order.side is Side.BUY:
            if quote.ask_price <= 0 or order.limit_price < quote.ask_price or quote.ask_volume <= 0:
                return None
            price = quote.ask_price
            market_volume = quote.ask_volume
        else:
            if quote.bid_price <= 0 or order.limit_price > quote.bid_price or quote.bid_volume <= 0:
                return None
            price = quote.bid_price
            market_volume = quote.bid_volume
        capacity = int((Decimal(market_volume) * self.participation_rate).to_integral_value(rounding=ROUND_FLOOR))
        capacity = max(0, capacity // 100 * 100)
        fill_quantity = min(order.remaining_quantity, capacity)
        if fill_quantity <= 0:
            return None
        existing_fills = self.repository.load_fills(order.client_order_id)
        prior_amount = sum((fill.price * fill.quantity for fill in existing_fills), Decimal("0"))
        prior_commission = sum((fill.commission for fill in existing_fills), Decimal("0"))
        fill_amount = price * fill_quantity
        fees = self.fee_schedule.calculate(order.side, fill_amount, prior_amount + fill_amount, prior_commission)
        if order.side is Side.BUY:
            total = fill_amount + fees.total
            if self.cash - self._reserved_buy_cash(order.client_order_id) < total:
                return None
            self.cash = money(self.cash - total)
            self.lots.append(
                PositionLot(
                    lot_id=uuid4().hex,
                    symbol=order.symbol,
                    quantity=fill_quantity,
                    available_quantity=fill_quantity,
                    cost_price=money(total / fill_quantity),
                    acquired_on=filled_at.date(),
                    sellable_on=sellable_on or next_business_day(filled_at.date()),
                )
            )
        else:
            self._consume_lots(order.symbol, fill_quantity, filled_at.date())
            self.cash = money(self.cash + fill_amount - fees.total)
        new_total = order.filled_quantity + fill_quantity
        order.average_price = (order.average_price * order.filled_quantity + price * fill_quantity) / new_total
        order.filled_quantity = new_total
        order.status = OrderStatus.FILLED if order.remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
        fill = Fill(
            fill_id=uuid4().hex,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=fill_quantity,
            price=price,
            commission=fees.commission,
            stamp_tax=fees.stamp_tax,
            transfer_fee=fees.transfer_fee,
            filled_at=filled_at,
        )
        self._persist(order, fill)
        return fill

    def _consume_lots(self, symbol: str, quantity: int, trading_day: date) -> None:
        remaining = quantity
        for lot in self.lots:
            if lot.symbol != symbol or lot.sellable_on > trading_day or lot.available_quantity <= 0:
                continue
            used = min(remaining, lot.available_quantity)
            lot.available_quantity -= used
            lot.quantity -= used
            remaining -= used
            if remaining == 0:
                break
        if remaining:
            raise RuntimeError("sellable lot invariant violated")
        self.lots = [lot for lot in self.lots if lot.quantity > 0]

    def cancel(self, client_order_id: str, canceled_at: datetime) -> Order:
        order = self.orders[client_order_id]
        if order.status in ACTIVE:
            order.status = OrderStatus.CANCELED
            self.repository.save_order(order)
            self.repository.append_ledger(
                f"cancel:{client_order_id}", "ORDER_CANCELED", {"order_id": client_order_id}, canceled_at
            )
        return order

    def reconcile(self, trading_day: date) -> ReconciliationResult:
        reasons: list[str] = []
        if self.cash < 0:
            reasons.append("negative_cash")
        if self.snapshot(trading_day).available_cash < 0:
            reasons.append("negative_available_cash")
        if any(lot.quantity < 0 or lot.available_quantity < 0 or lot.available_quantity > lot.quantity for lot in self.lots):
            reasons.append("invalid_position_lot")
        for order in self.orders.values():
            fill_quantity = sum(fill.quantity for fill in self.repository.load_fills(order.client_order_id))
            if fill_quantity != order.filled_quantity:
                reasons.append(f"fill_quantity_mismatch:{order.client_order_id}")
            if order.filled_quantity < 0 or order.filled_quantity > order.quantity:
                reasons.append(f"invalid_order_quantity:{order.client_order_id}")
        return ReconciliationResult(not reasons, tuple(reasons))

    def _persist(self, order: Order, fill: Fill) -> None:
        self.repository.save_cash(self.cash)
        self.repository.save_lots(self.lots)
        self.repository.save_order(order)
        self.repository.save_fill(fill)
        self.repository.append_ledger(
            f"fill:{fill.fill_id}",
            "FILL",
            {"order_id": order.client_order_id, "quantity": fill.quantity, "price": str(fill.price)},
            fill.filled_at,
        )
