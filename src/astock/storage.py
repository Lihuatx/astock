from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from astock.models import Fill, Order, OrderStatus, PositionLot, Side, TradeIntent


class Repository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def close(self) -> None:
        self.connection.close()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS account_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                limit_price TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                filled_quantity INTEGER NOT NULL,
                average_price TEXT NOT NULL,
                reject_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS fills (
                fill_id TEXT PRIMARY KEY,
                client_order_id TEXT NOT NULL REFERENCES orders(client_order_id),
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                price TEXT NOT NULL,
                commission TEXT NOT NULL,
                stamp_tax TEXT NOT NULL,
                transfer_fee TEXT NOT NULL,
                filled_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS position_lots (
                lot_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                available_quantity INTEGER NOT NULL,
                cost_price TEXT NOT NULL,
                acquired_on TEXT NOT NULL,
                sellable_on TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                client_order_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                dispatched_at TEXT
            );
            CREATE TABLE IF NOT EXISTS ledger (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def initialize_account(self, cash: Decimal) -> None:
        self.connection.execute("INSERT OR IGNORE INTO account_state(id, cash) VALUES(1, ?)", (str(cash),))
        self.connection.commit()

    def load_cash(self) -> Decimal:
        row = self.connection.execute("SELECT cash FROM account_state WHERE id=1").fetchone()
        if not row:
            raise RuntimeError("account is not initialized")
        return Decimal(row["cash"])

    def save_cash(self, cash: Decimal) -> None:
        self.connection.execute("UPDATE account_state SET cash=? WHERE id=1", (str(cash),))
        self.connection.commit()

    def save_order(self, order: Order) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(client_order_id) DO UPDATE SET
                status=excluded.status,
                filled_quantity=excluded.filled_quantity,
                average_price=excluded.average_price,
                reject_reason=excluded.reject_reason
            """,
            (
                order.client_order_id,
                order.symbol,
                order.side.value,
                order.quantity,
                str(order.limit_price),
                order.status.value,
                order.created_at.isoformat(),
                order.filled_quantity,
                str(order.average_price),
                order.reject_reason,
            ),
        )
        self.connection.commit()

    def get_order(self, client_order_id: str) -> Order | None:
        row = self.connection.execute("SELECT * FROM orders WHERE client_order_id=?", (client_order_id,)).fetchone()
        return self._row_to_order(row) if row else None

    def load_orders(self) -> list[Order]:
        return [self._row_to_order(row) for row in self.connection.execute("SELECT * FROM orders ORDER BY created_at")]

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> Order:
        return Order(
            client_order_id=row["client_order_id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            quantity=row["quantity"],
            limit_price=Decimal(row["limit_price"]),
            status=OrderStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            filled_quantity=row["filled_quantity"],
            average_price=Decimal(row["average_price"]),
            reject_reason=row["reject_reason"],
        )

    def save_fill(self, fill: Fill) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO fills VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                fill.fill_id,
                fill.client_order_id,
                fill.symbol,
                fill.side.value,
                fill.quantity,
                str(fill.price),
                str(fill.commission),
                str(fill.stamp_tax),
                str(fill.transfer_fee),
                fill.filled_at.isoformat(),
            ),
        )
        self.connection.commit()

    def load_fills(self, client_order_id: str | None = None) -> list[Fill]:
        sql = "SELECT * FROM fills"
        args: tuple[str, ...] = ()
        if client_order_id:
            sql += " WHERE client_order_id=?"
            args = (client_order_id,)
        sql += " ORDER BY filled_at"
        return [
            Fill(
                fill_id=row["fill_id"],
                client_order_id=row["client_order_id"],
                symbol=row["symbol"],
                side=Side(row["side"]),
                quantity=row["quantity"],
                price=Decimal(row["price"]),
                commission=Decimal(row["commission"]),
                stamp_tax=Decimal(row["stamp_tax"]),
                transfer_fee=Decimal(row["transfer_fee"]),
                filled_at=datetime.fromisoformat(row["filled_at"]),
            )
            for row in self.connection.execute(sql, args)
        ]

    def save_lots(self, lots: Iterable[PositionLot]) -> None:
        with self.connection:
            self.connection.execute("DELETE FROM position_lots")
            self.connection.executemany(
                "INSERT INTO position_lots VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        lot.lot_id,
                        lot.symbol,
                        lot.quantity,
                        lot.available_quantity,
                        str(lot.cost_price),
                        lot.acquired_on.isoformat(),
                        lot.sellable_on.isoformat(),
                    )
                    for lot in lots
                ],
            )

    def load_lots(self) -> list[PositionLot]:
        return [
            PositionLot(
                lot_id=row["lot_id"],
                symbol=row["symbol"],
                quantity=row["quantity"],
                available_quantity=row["available_quantity"],
                cost_price=Decimal(row["cost_price"]),
                acquired_on=date.fromisoformat(row["acquired_on"]),
                sellable_on=date.fromisoformat(row["sellable_on"]),
            )
            for row in self.connection.execute("SELECT * FROM position_lots ORDER BY acquired_on, lot_id")
        ]

    def enqueue(self, intent: TradeIntent) -> None:
        payload = {
            "client_order_id": intent.client_order_id,
            "symbol": intent.symbol,
            "side": intent.side.value,
            "quantity": intent.quantity,
            "limit_price": str(intent.limit_price),
            "created_at": intent.created_at.isoformat(),
            "reason": intent.reason,
        }
        self.connection.execute(
            "INSERT OR IGNORE INTO outbox(client_order_id,payload,created_at) VALUES(?,?,?)",
            (intent.client_order_id, json.dumps(payload, separators=(",", ":")), intent.created_at.isoformat()),
        )
        self.connection.commit()

    def pending_intents(self) -> list[TradeIntent]:
        rows = self.connection.execute("SELECT payload FROM outbox WHERE status='PENDING' ORDER BY created_at").fetchall()
        intents = []
        for row in rows:
            item = json.loads(row["payload"])
            intents.append(
                TradeIntent(
                    client_order_id=item["client_order_id"],
                    symbol=item["symbol"],
                    side=Side(item["side"]),
                    quantity=int(item["quantity"]),
                    limit_price=Decimal(item["limit_price"]),
                    created_at=datetime.fromisoformat(item["created_at"]),
                    reason=item["reason"],
                )
            )
        return intents

    def mark_dispatched(self, client_order_id: str, dispatched_at: datetime) -> None:
        self.connection.execute(
            "UPDATE outbox SET status='DISPATCHED', dispatched_at=? WHERE client_order_id=?",
            (dispatched_at.isoformat(), client_order_id),
        )
        self.connection.commit()

    def append_ledger(self, event_id: str, event_type: str, payload: dict, created_at: datetime) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO ledger VALUES(?,?,?,?)",
            (event_id, event_type, json.dumps(payload, separators=(",", ":"), default=str), created_at.isoformat()),
        )
        self.connection.commit()

