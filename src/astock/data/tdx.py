from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from itertools import count
from typing import Any, Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from astock.models import Bar, Quote
from astock.raw_store import JsonlRawStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
BOARD_LOT = 100
TDX_AMOUNT_UNIT = Decimal("10000")
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


class TdxError(RuntimeError):
    pass


class TdxClient:
    def __init__(
        self,
        base_url: str,
        raw_store: JsonlRawStore | None = None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url
        self.raw_store = raw_store
        self.timeout = timeout
        self.transport = transport
        self._ids = count(1)

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        received_at = datetime.now(SHANGHAI)
        try:
            if self.transport is not None:
                payload = self.transport(method, params)
            else:
                body = json.dumps({"id": next(self._ids), "method": method, "params": params}).encode()
                request = Request(self.base_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise TdxError(f"TDX request failed: {method}: {exc}") from exc
        if self.raw_store:
            self.raw_store.append(
                "tdx",
                method,
                {"request": params, "response": payload},
                received_at,
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TdxError(f"TDX invalid response: {method}")
        error_id = str(result.get("ErrorId", "0"))
        if error_id != "0":
            raise TdxError(f"TDX business error: {method}: {error_id}")
        return result

    def get_snapshot(self, symbol: str) -> Quote:
        result = self._call("get_market_snapshot", {"stock_code": symbol, "field_list": []})
        now = datetime.now(SHANGHAI)
        buy_prices = result.get("Buyp") or ["0"]
        sell_prices = result.get("Sellp") or ["0"]
        buy_volumes = result.get("Buyv") or ["0"]
        sell_volumes = result.get("Sellv") or ["0"]
        return Quote(
            symbol=symbol,
            received_at=now,
            source_at=None,
            last=Decimal(str(result.get("Now", "0"))),
            prev_close=Decimal(str(result.get("LastClose", "0"))),
            bid_price=Decimal(str(buy_prices[0])),
            ask_price=Decimal(str(sell_prices[0])),
            # TDX 快照的量字段单位为手，内部统一为股。
            bid_volume=int(Decimal(str(buy_volumes[0]))) * BOARD_LOT,
            ask_volume=int(Decimal(str(sell_volumes[0]))) * BOARD_LOT,
            volume=int(Decimal(str(result.get("Volume", "0")))) * BOARD_LOT,
            source="tdx",
        )

    def get_bars(
        self,
        symbol: str,
        period: str = "1d",
        start: str = "",
        end: str = "",
        count_: int = -1,
    ) -> list[Bar]:
        result = self._call(
            "get_market_data",
            {
                "field_list": ["Open", "High", "Low", "Close", "Volume", "Amount"],
                "stock_list": [symbol],
                "period": period,
                "start_time": start,
                "end_time": end,
                "count": count_,
                "dividend_type": "none",
                "fill_data": False,
            },
        )
        raw = (result.get("Value") or {}).get(symbol) or {}
        dates = raw.get("Date") or []
        bars: list[Bar] = []
        for index, day_value in enumerate(dates):
            day_text = str(day_value)
            if len(day_text) < 8:
                continue
            trading_day = datetime.strptime(day_text[:8], "%Y%m%d").date()
            timestamp = None
            time_values = raw.get("Time") or []
            if index < len(time_values) and str(time_values[index]).strip("0"):
                time_text = str(time_values[index]).zfill(6)[-6:]
                timestamp = datetime.combine(
                    trading_day,
                    datetime.strptime(time_text, "%H%M%S").time(),
                    SHANGHAI,
                )
            bars.append(
                Bar(
                    symbol=symbol,
                    trading_day=trading_day,
                    open=Decimal(str(raw.get("Open", [])[index])),
                    high=Decimal(str(raw.get("High", [])[index])),
                    low=Decimal(str(raw.get("Low", [])[index])),
                    close=Decimal(str(raw.get("Close", [])[index])),
                    volume=int(Decimal(str(raw.get("Volume", [0])[index]))),
                    # TDX K 线成交量单位为股，成交额单位为万元；内部金额统一为元。
                    amount=Decimal(str(raw.get("Amount", [0])[index])) * TDX_AMOUNT_UNIT,
                    source="tdx",
                    timestamp=timestamp,
                )
            )
        return bars

    def get_stock_list(self) -> list[str]:
        result = self._call("get_stock_list", {"market": "5", "list_type": 0})
        return [str(item) for item in result.get("Value", [])]

    def get_trading_dates(self, start: str, end: str) -> list[date]:
        result = self._call(
            "get_trading_dates",
            {"market": "SH", "start_time": start, "end_time": end, "count": -1},
        )
        return [datetime.strptime(str(item), "%Y%m%d").date() for item in result.get("Date", [])]

    def doctor(self) -> dict[str, Any]:
        quote = self.get_snapshot("000001.SZ")
        symbols = self.get_stock_list()
        bars = self.get_bars("000001.SZ", count_=5)
        today = datetime.now(SHANGHAI).date()
        previous_month_end = today.replace(day=1) - date.resolution
        trading_dates = self.get_trading_dates(previous_month_end.replace(day=1).strftime("%Y%m%d"), today.strftime("%Y%m%d"))
        snapshot_price_ok = quote.last > 0 or (quote.bid_price > 0 and quote.ask_price > 0)
        return {
            "ok": snapshot_price_ok and bool(symbols) and bool(trading_dates),
            "snapshot_fields_ok": quote.bid_price >= 0 and quote.ask_price >= 0,
            "symbol_count": len(symbols),
            "daily_bar_count": len(bars),
            "latest_daily_bar": bars[-1].trading_day.isoformat() if bars else None,
            "trading_date_count": len(trading_dates),
            "latest_trading_date": trading_dates[-1].isoformat() if trading_dates else None,
        }
