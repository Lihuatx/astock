from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from astock.models import Bar
from astock.raw_store import JsonlRawStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
KLINE_5_MINUTES = 0
PAGE_SIZE = 800
MAX_PAGES = 16
PREFERRED_HOSTS = (
    ("上海电信主站Z1", "180.153.18.170", 7709),
    ("上海电信主站Z2", "180.153.18.171", 7709),
    ("上海电信主站Z80", "180.153.18.172", 7709),
)


class PytdxError(RuntimeError):
    pass


class PytdxMinuteClient:
    """只读分页获取通达信公开行情服务器的历史 5 分钟线。"""

    def __init__(
        self,
        raw_store: JsonlRawStore | None = None,
        *,
        hosts: Iterable[tuple[str, str, int]] | None = None,
        api_factory: Callable[..., Any] | None = None,
        timeout: float = 3.0,
    ) -> None:
        self.raw_store = raw_store
        self.hosts = tuple(hosts or PREFERRED_HOSTS)
        self.api_factory = api_factory
        self.timeout = timeout

    def _new_api(self) -> Any:
        if self.api_factory is not None:
            return self.api_factory()
        try:
            from pytdx.hq import TdxHq_API
        except ImportError as exc:
            raise PytdxError("pytdx==1.72 is required for historical minute backfill") from exc
        return TdxHq_API(heartbeat=True, auto_retry=True, raise_exception=True)

    def _connect(self) -> tuple[Any, tuple[str, str, int]]:
        last_error: Exception | None = None
        for host in self.hosts:
            api = self._new_api()
            try:
                if api.connect(host[1], host[2], time_out=self.timeout):
                    return api, host
            except Exception as exc:
                last_error = exc
            try:
                api.disconnect()
            except Exception:
                pass
        raise PytdxError(f"pytdx connection failed: {last_error or 'no host accepted the connection'}")

    def get_bars(self, symbol: str, start: str, end: str) -> list[Bar]:
        start_date = datetime.strptime(start, "%Y%m%d").date()
        end_date = datetime.strptime(end, "%Y%m%d").date()
        market = 1 if symbol.endswith(".SH") else 0
        code = symbol.split(".", 1)[0]
        rows: list[dict[str, Any]] = []
        api, host = self._connect()
        try:
            for page in range(MAX_PAGES):
                offset = page * PAGE_SIZE
                page_rows: list[dict[str, Any]] | None = None
                last_error: Exception | None = None
                for attempt in range(3):
                    try:
                        page_rows = list(api.get_security_bars(KLINE_5_MINUTES, market, code, offset, PAGE_SIZE) or [])
                        break
                    except Exception as exc:
                        last_error = exc
                        if attempt < 2:
                            time.sleep(2**attempt)
                if page_rows is None:
                    raise PytdxError(f"pytdx page failed for {symbol} offset={offset}: {last_error}")
                if self.raw_store:
                    self.raw_store.append(
                        "pytdx",
                        "get_security_bars",
                        {
                            "request": {"symbol": symbol, "period": "5m", "offset": offset, "count": PAGE_SIZE},
                            "host": {"name": host[0], "ip": host[1], "port": host[2]},
                            "response": page_rows,
                        },
                        datetime.now(SHANGHAI),
                    )
                if not page_rows:
                    break
                rows.extend(page_rows)
                earliest = min(datetime.strptime(str(item["datetime"]), "%Y-%m-%d %H:%M") for item in page_rows)
                if earliest.date() <= start_date:
                    break
            else:
                raise PytdxError(f"pytdx pagination limit reached before {start} for {symbol}")
        finally:
            api.disconnect()

        bars: dict[datetime, Bar] = {}
        for row in rows:
            timestamp = datetime.strptime(str(row["datetime"]), "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)
            if not start_date <= timestamp.date() <= end_date:
                continue
            bars[timestamp] = Bar(
                symbol=symbol,
                trading_day=timestamp.date(),
                timestamp=timestamp,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=int(Decimal(str(row["vol"]))),
                amount=Decimal(str(row["amount"])),
                source="pytdx",
            )
        return [bars[key] for key in sorted(bars)]
