from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from astock.broker import AShareSimBroker
from astock.data.quality import compare_quotes, validate_quote
from astock.data.tdx import TdxClient
from astock.data.ths import ThsClient
from astock.fees import FeeSchedule
from astock.models import AccountSnapshot, Bar, OrderStatus, Quote, Side, TradeIntent
from astock.oms import OMS
from astock.raw_store import JsonlRawStore
from astock.replay import ReplayEngine
from astock.risk import RiskEngine, RiskLimits
from astock.storage import Repository
from astock.strategy import MomentumTrendStrategy


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 10, 10, 0, tzinfo=TZ)


def quote(symbol: str = "000001.SZ", price: str = "10", volume: int = 100_000) -> Quote:
    return Quote(
        symbol=symbol,
        received_at=NOW,
        source_at=NOW,
        last=Decimal(price),
        prev_close=Decimal(price),
        bid_price=Decimal(price),
        ask_price=Decimal(price),
        bid_volume=volume,
        ask_volume=volume,
        volume=volume,
        source="test",
    )


def intent(order_id: str, side: Side, quantity: int = 1000, price: str = "10") -> TradeIntent:
    return TradeIntent(order_id, "000001.SZ", side, quantity, Decimal(price), NOW, "test")


class BrokerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.repository = Repository(self.db_path)
        self.broker = AShareSimBroker(self.repository, Decimal("100000"), participation_rate=Decimal("0.01"))

    def tearDown(self) -> None:
        self.repository.close()
        self.temp.cleanup()

    def test_buy_partial_fill_fee_and_restart(self) -> None:
        order = self.broker.submit(intent("buy-1", Side.BUY), quote(volume=50_000), NOW.date())
        self.assertEqual(order.status, OrderStatus.ACCEPTED)
        first = self.broker.match("buy-1", quote(volume=50_000), NOW)
        self.assertIsNotNone(first)
        self.assertEqual(first.quantity, 500)
        self.assertEqual(first.commission, Decimal("5.00"))
        second = self.broker.match("buy-1", quote(volume=50_000), NOW + timedelta(minutes=1))
        self.assertEqual(second.commission, Decimal("0.00"))
        self.assertEqual(order.status, OrderStatus.FILLED)
        expected_cash = Decimal("100000") - Decimal("10000") - Decimal("5.10")
        self.assertEqual(self.broker.cash, expected_cash)
        self.repository.close()
        self.repository = Repository(self.db_path)
        restored = AShareSimBroker(self.repository, Decimal("1"))
        self.assertEqual(restored.cash, expected_cash)
        self.assertEqual(restored.snapshot(NOW.date()).positions["000001.SZ"], 1000)
        self.assertEqual(restored.orders["buy-1"].status, OrderStatus.FILLED)

    def test_t_plus_one_and_sell_tax(self) -> None:
        self.broker.submit(intent("buy", Side.BUY), quote(), NOW.date())
        self.broker.match("buy", quote(), NOW)
        same_day = self.broker.submit(intent("sell-now", Side.SELL), quote(), NOW.date())
        self.assertEqual(same_day.reject_reason, "insufficient_sellable_position")
        next_day = date(2026, 7, 13)
        sell_intent = TradeIntent("sell-next", "000001.SZ", Side.SELL, 1000, Decimal("10"), NOW, "test")
        sell_order = self.broker.submit(sell_intent, quote(), next_day)
        self.assertEqual(sell_order.status, OrderStatus.ACCEPTED)
        fill = self.broker.match("sell-next", quote(), datetime(2026, 7, 13, 10, tzinfo=TZ))
        self.assertEqual(fill.stamp_tax, Decimal("5.00"))
        self.assertNotIn("000001.SZ", self.broker.snapshot(next_day).positions)

    def test_validation_cancel_and_idempotency(self) -> None:
        odd = self.broker.submit(intent("odd", Side.BUY, 101), quote(), NOW.date())
        self.assertEqual(odd.reject_reason, "buy_quantity_not_board_lot")
        poor = self.broker.submit(intent("poor", Side.BUY, 100_000), quote(), NOW.date())
        self.assertEqual(poor.reject_reason, "insufficient_cash")
        halted_quote = Quote(**{**quote().__dict__, "suspended": True})
        halted = self.broker.submit(intent("halted", Side.BUY), halted_quote, NOW.date())
        self.assertEqual(halted.reject_reason, "suspended")
        limited_quote = Quote(**{**quote().__dict__, "upper_limit": Decimal("9.99")})
        limited = self.broker.submit(intent("limited", Side.BUY), limited_quote, NOW.date())
        self.assertEqual(limited.reject_reason, "above_upper_limit")
        accepted = self.broker.submit(intent("cancel", Side.BUY), quote(), NOW.date())
        self.assertIs(accepted, self.broker.submit(intent("cancel", Side.BUY), quote(), NOW.date()))
        self.assertEqual(self.broker.cancel("cancel", NOW).status, OrderStatus.CANCELED)

    def test_reserved_cash_blocks_second_order_but_not_own_fill(self) -> None:
        first = self.broker.submit(intent("large", Side.BUY, 9000), quote(), NOW.date())
        self.assertEqual(first.status, OrderStatus.ACCEPTED)
        second = self.broker.submit(intent("second", Side.BUY, 1100), quote(), NOW.date())
        self.assertEqual(second.reject_reason, "insufficient_cash")
        self.assertIsNotNone(self.broker.match("large", quote(volume=1_000_000), NOW))


class DataCase(unittest.TestCase):
    def test_quote_quality(self) -> None:
        primary = quote()
        stale = Quote(**{**primary.__dict__, "source_at": NOW - timedelta(minutes=2)})
        self.assertIn("stale_quote", validate_quote(stale, NOW).reasons)
        secondary = Quote(**{**primary.__dict__, "last": Decimal("10.2"), "source": "secondary"})
        self.assertIn("price_divergence", compare_quotes(primary, secondary, Decimal("1")).reasons)

    def test_tdx_normalization(self) -> None:
        client = TdxClient("http://unused")
        client._call = lambda method, params: {  # type: ignore[method-assign]
            "Now": "10.1", "LastClose": "10", "Buyp": ["10.09"], "Sellp": ["10.10"],
            "Buyv": ["20"], "Sellv": ["30"], "Volume": "500"
        }
        result = client.get_snapshot("000001.SZ")
        self.assertEqual(result.bid_volume, 2000)
        self.assertEqual(result.ask_volume, 3000)
        self.assertEqual(result.volume, 50_000)

    def test_raw_store(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = JsonlRawStore(Path(folder)).append("tdx", "snapshot", {"ok": True}, NOW)
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["source"], "tdx")


class OmsRiskStrategyCase(unittest.TestCase):
    def test_oms_outbox_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = Repository(Path(folder) / "oms.db")
            broker = AShareSimBroker(repository, Decimal("100000"))
            oms = OMS(repository, broker)
            item = intent("oms-1", Side.BUY)
            oms.enqueue(item)
            oms.enqueue(item)
            orders = oms.dispatch({item.symbol: quote()}, NOW.date(), NOW)
            self.assertEqual(len(orders), 1)
            self.assertEqual(oms.dispatch({item.symbol: quote()}, NOW.date(), NOW), [])
            repository.close()

    def test_risk_limits(self) -> None:
        risk = RiskEngine(RiskLimits(max_order_amount=Decimal("1000"), max_daily_orders=1))
        account = AccountSnapshot(Decimal("100000"), Decimal("0"))
        self.assertEqual(risk.evaluate(intent("x", Side.BUY), account, {}, 0).reason, "order_amount_limit")
        small = intent("y", Side.BUY, 100)
        self.assertEqual(risk.evaluate(small, account, {}, 1).reason, "daily_order_limit")
        self.assertEqual(risk.evaluate(small, account, {}, 0, Decimal("-0.03")).reason, "daily_loss_stop")
        concentrated = AccountSnapshot(Decimal("85000"), Decimal("0"), {"000001.SZ": 1500}, {})
        normal_risk = RiskEngine()
        self.assertEqual(
            normal_risk.evaluate(small, concentrated, {"000001.SZ": Decimal("10")}, 0).reason,
            "single_position_limit",
        )

    def test_strategy_only_uses_supplied_history(self) -> None:
        strategy = MomentumTrendStrategy(top_n=1)
        start = date(2026, 1, 1)
        rising = [
            Bar("000001.SZ", start + timedelta(days=i), Decimal(i + 1), Decimal(i + 1), Decimal(i + 1),
                Decimal(i + 1), 100_000, Decimal("1"), "test")
            for i in range(60)
        ]
        self.assertEqual(strategy.select({"000001.SZ": rising}), ["000001.SZ"])
        self.assertEqual(strategy.select({"000001.SZ": rising[:59]}), [])

    def test_replay_generates_equity_curve_and_fills(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            repository = Repository(Path(folder) / "replay.db")
            broker = AShareSimBroker(repository, Decimal("100000"))
            engine = ReplayEngine(broker, OMS(repository, broker), RiskEngine(), MomentumTrendStrategy(top_n=1))
            start = date(2026, 1, 1)
            bars = []
            for i in range(70):
                price = Decimal("10") + Decimal(i) / Decimal("10")
                bars.append(Bar("000001.SZ", start + timedelta(days=i), price, price, price, price, 1_000_000,
                                price * 1_000_000, "test"))
            curve = engine.run({"000001.SZ": bars})
            self.assertEqual(len(curve), 70)
            self.assertTrue(repository.load_fills())
            self.assertGreater(curve[-1].equity, Decimal("0"))
            self.assertTrue(all(point.reconciled for point in curve))
            repository.close()


class FeeCase(unittest.TestCase):
    def test_fee_schedule(self) -> None:
        fees = FeeSchedule().calculate(Side.SELL, Decimal("10000"), Decimal("10000"), Decimal("0"))
        self.assertEqual(fees.commission, Decimal("5.00"))
        self.assertEqual(fees.stamp_tax, Decimal("5.00"))
        self.assertEqual(fees.transfer_fee, Decimal("0.10"))


if __name__ == "__main__":
    unittest.main()
