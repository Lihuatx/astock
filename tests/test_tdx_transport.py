from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from astock.data.tdx import TdxClient
from astock.data.tdx_transport import TdxSdkTransport


class _At:
    def __init__(self, values):
        self.values = values

    def __getitem__(self, key):
        return self.values[key]


class _Frame:
    def __init__(self, symbol: str, index: datetime, value: str) -> None:
        self.index = [index]
        self.columns = [symbol]
        self.at = _At({(index, symbol): value})


class _Sdk:
    @staticmethod
    def stock_account(account: str, account_type: str) -> int:
        return 9 if account == "" and account_type == "STOCK" else -1

    @staticmethod
    def query_stock_asset(account_id: int):
        return {"ErrorId": "0", "Cash": "1000000", "Asset": "1000000"}

    @staticmethod
    def query_stock_positions(account_id: int):
        return []

    @staticmethod
    def query_stock_orders(account_id: int, stock_code: str, cancelable_only: bool):
        return []

    @staticmethod
    def get_market_data(**params):
        timestamp = datetime(2026, 7, 14)
        symbol = params["stock_list"][0]
        return {
            "Open": _Frame(symbol, timestamp, "10.53"),
            "High": _Frame(symbol, timestamp, "10.70"),
            "Low": _Frame(symbol, timestamp, "10.48"),
            "Close": _Frame(symbol, timestamp, "10.69"),
            "Volume": _Frame(symbol, timestamp, "119371536"),
            "Amount": _Frame(symbol, timestamp, "126751.12"),
        }


class TdxSdkTransportCase(unittest.TestCase):
    def test_current_account_and_empty_account_facts_are_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            transport = TdxSdkTransport(Path(folder), sdk=_Sdk())
            account = transport("stock_account", {"account": "", "account_type": "STOCK"})
            positions = transport("query_stock_positions", {"account_id": 9})
            orders = transport(
                "query_stock_orders",
                {"account_id": 9, "stock_code": "", "cancelable_only": False},
            )
            self.assertEqual(account["result"]["Value"], 9)
            self.assertEqual(positions["result"]["Value"], [])
            self.assertEqual(orders["result"]["Value"], [])

    def test_sdk_market_frames_feed_existing_tdx_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            transport = TdxSdkTransport(Path(folder), sdk=_Sdk())
            client = TdxClient("http://unused", transport=transport)
            bars = client.get_bars("000001.SZ", count_=1)
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0].trading_day.isoformat(), "2026-07-14")
            self.assertEqual(bars[0].close, Decimal("10.69"))
            self.assertEqual(bars[0].volume, 119_371_536)
            self.assertEqual(bars[0].amount, Decimal("1267511200.00"))

    def test_missing_sdk_file_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            transport = TdxSdkTransport(Path(folder))
            with self.assertRaisesRegex(RuntimeError, "SDK not found"):
                transport("get_stock_list", {"market": "5", "list_type": 0})

    def test_empty_list_after_sdk_disconnect_is_an_error(self) -> None:
        class DisconnectedSdk:
            _initialized = False

            @staticmethod
            def query_stock_positions(account_id: int):
                return []

        with tempfile.TemporaryDirectory() as folder:
            transport = TdxSdkTransport(Path(folder), sdk=DisconnectedSdk())
            result = transport("query_stock_positions", {"account_id": 9})
            self.assertEqual(result["result"]["ErrorId"], "SDK_DISCONNECTED")


if __name__ == "__main__":
    unittest.main()
