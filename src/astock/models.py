from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


ZERO = Decimal("0")


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Quote:
    symbol: str
    received_at: datetime
    last: Decimal
    prev_close: Decimal
    bid_price: Decimal
    ask_price: Decimal
    bid_volume: int
    ask_volume: int
    volume: int
    source: str
    source_at: datetime | None = None
    upper_limit: Decimal | None = None
    lower_limit: Decimal | None = None
    suspended: bool = False


@dataclass(frozen=True)
class Bar:
    symbol: str
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    amount: Decimal
    source: str
    timestamp: datetime | None = None


@dataclass(frozen=True)
class TradeIntent:
    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    created_at: datetime
    reason: str


@dataclass
class Order:
    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    status: OrderStatus
    created_at: datetime
    filled_quantity: int = 0
    average_price: Decimal = ZERO
    reject_reason: str | None = None

    @property
    def remaining_quantity(self) -> int:
        return self.quantity - self.filled_quantity


@dataclass(frozen=True)
class Fill:
    fill_id: str
    client_order_id: str
    symbol: str
    side: Side
    quantity: int
    price: Decimal
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal
    filled_at: datetime

    @property
    def total_fee(self) -> Decimal:
        return self.commission + self.stamp_tax + self.transfer_fee


@dataclass
class PositionLot:
    lot_id: str
    symbol: str
    quantity: int
    available_quantity: int
    cost_price: Decimal
    acquired_on: date
    sellable_on: date


@dataclass
class AccountSnapshot:
    cash: Decimal
    frozen_cash: Decimal
    positions: dict[str, int] = field(default_factory=dict)
    sellable_positions: dict[str, int] = field(default_factory=dict)

    @property
    def available_cash(self) -> Decimal:
        return self.cash - self.frozen_cash

