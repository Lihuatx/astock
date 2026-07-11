from __future__ import annotations

from datetime import date, datetime

from astock.broker import AShareSimBroker
from astock.models import Order, Quote, TradeIntent
from astock.storage import Repository


class OMS:
    def __init__(self, repository: Repository, broker: AShareSimBroker) -> None:
        self.repository = repository
        self.broker = broker

    def enqueue(self, intent: TradeIntent) -> None:
        self.repository.enqueue(intent)

    def dispatch(self, quotes: dict[str, Quote], trading_day: date, dispatched_at: datetime) -> list[Order]:
        orders: list[Order] = []
        for intent in self.repository.pending_intents():
            quote = quotes.get(intent.symbol)
            if quote is None:
                continue
            order = self.broker.submit(intent, quote, trading_day)
            self.repository.mark_dispatched(intent.client_order_id, dispatched_at)
            orders.append(order)
        return orders

