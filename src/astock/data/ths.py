from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from astock.models import Quote
from astock.raw_store import JsonlRawStore


SHANGHAI = ZoneInfo("Asia/Shanghai")


class ThsError(RuntimeError):
    pass


class ThsClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        raw_store: JsonlRawStore | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not api_key:
            raise ValueError("THS_API_KEY is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.raw_store = raw_store
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        received_at = datetime.now(SHANGHAI)
        url = f"{self.base_url}{path}?{urlencode(params)}"
        request = Request(url, headers={"X-api-key": self.api_key, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ThsError(f"THS request failed: {path}: {exc}") from exc
        if self.raw_store:
            self.raw_store.append("ths", path.rsplit("/", 1)[-1], payload, received_at)
        if payload.get("code") != 0:
            raise ThsError(f"THS business error: {payload.get('code')}: {payload.get('message')}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ThsError("THS invalid data envelope")
        return data

    def get_snapshot(self, symbol: str) -> Quote:
        data = self._get("/api/a-share/prices/snapshot", {"thscodes": symbol})
        items = data.get("item") or []
        if not items:
            raise ThsError(f"THS empty snapshot: {symbol}")
        item = items[0]
        now = datetime.now(SHANGHAI)
        source_at = None
        if data.get("timestamp"):
            source_at = datetime.fromtimestamp(int(data["timestamp"]) / 1000, SHANGHAI)
        last = Decimal(str(item.get("last_price", "0")))
        return Quote(
            symbol=symbol,
            received_at=now,
            source_at=source_at,
            last=last,
            prev_close=Decimal(str(item.get("prev_price", "0"))),
            bid_price=last,
            ask_price=last,
            bid_volume=0,
            ask_volume=0,
            volume=int(Decimal(str(item.get("volume", "0")))),
            source="ths",
        )

    def doctor(self) -> dict[str, Any]:
        quote = self.get_snapshot("000001.SZ")
        return {"ok": quote.last > 0, "symbol": quote.symbol, "has_source_time": quote.source_at is not None}

