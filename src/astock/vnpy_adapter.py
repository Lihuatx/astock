from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from astock.models import Bar, Quote


def quote_to_vnpy(quote: Quote):
    try:
        from vnpy.trader.constant import Exchange
        from vnpy.trader.object import TickData
    except ImportError as exc:
        raise RuntimeError("Install the 'vnpy' optional dependency to use this adapter") from exc
    code, suffix = quote.symbol.split(".", 1)
    exchange = Exchange.SSE if suffix == "SH" else Exchange.SZSE
    return TickData(
        symbol=code,
        exchange=exchange,
        datetime=quote.source_at or quote.received_at,
        gateway_name="TDX",
        last_price=float(quote.last),
        volume=float(quote.volume),
        bid_price_1=float(quote.bid_price),
        ask_price_1=float(quote.ask_price),
        bid_volume_1=float(quote.bid_volume),
        ask_volume_1=float(quote.ask_volume),
    )


def bar_to_vnpy(bar: Bar):
    try:
        from vnpy.trader.constant import Exchange, Interval
        from vnpy.trader.object import BarData
    except ImportError as exc:
        raise RuntimeError("Install the 'vnpy' optional dependency to use this adapter") from exc
    code, suffix = bar.symbol.split(".", 1)
    exchange = Exchange.SSE if suffix == "SH" else Exchange.SZSE
    return BarData(
        symbol=code,
        exchange=exchange,
        datetime=bar.timestamp or datetime.combine(bar.trading_day, time(), ZoneInfo("Asia/Shanghai")),
        interval=Interval.DAILY,
        gateway_name=bar.source.upper(),
        open_price=float(bar.open),
        high_price=float(bar.high),
        low_price=float(bar.low),
        close_price=float(bar.close),
        volume=float(bar.volume),
        turnover=float(bar.amount),
    )
