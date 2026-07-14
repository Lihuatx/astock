from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from itertools import count
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from astock.models import Side
from astock.raw_store import JsonlRawStore


SHANGHAI = ZoneInfo("Asia/Shanghai")
Transport = Callable[[str, dict[str, Any]], dict[str, Any]]


class TdxSimError(RuntimeError):
    pass


class TdxSimulationGuardError(TdxSimError):
    pass


class JsonlErrorLog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def append(
        self,
        operation: str,
        error: Exception,
        occurred_at: datetime,
        context: dict[str, Any] | None = None,
    ) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"tdx-sim-{occurred_at:%Y%m%d}.jsonl"
        record = {
            "occurred_at": occurred_at.isoformat(),
            "operation": operation,
            "error_class": type(error).__name__,
            "message": str(error),
            "context": context or {},
        }
        with self._lock, target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), default=str))
            handle.write("\n")
        return target


@dataclass(frozen=True)
class TdxSimSnapshot:
    captured_at: datetime
    asset: dict[str, Any]
    positions: list[dict[str, Any]]
    orders: list[dict[str, Any]]


class TdxSimClient:
    """TDX 模拟交易 HTTP 适配器；只接受明确确认的模拟账户配置。"""

    def __init__(
        self,
        base_url: str,
        account: str | None,
        simulation_confirmed: bool,
        raw_store: JsonlRawStore | None = None,
        error_log: JsonlErrorLog | None = None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url
        self.account = account
        self.simulation_confirmed = simulation_confirmed
        self.raw_store = raw_store
        self.error_log = error_log
        self.timeout = timeout
        self.transport = transport or self._http_transport
        self._ids = count(1)
        self._account_handle: int | None = None

    def _http_transport(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({"id": next(self._ids), "method": method, "params": params}).encode()
        request = Request(self.base_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _log_error(self, operation: str, error: Exception, context: dict[str, Any] | None = None) -> None:
        if self.error_log:
            self.error_log.append(operation, error, datetime.now(SHANGHAI), context)

    def _call(self, method: str, params: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        received_at = datetime.now(SHANGHAI)
        safe_params = {**params}
        if "account" in safe_params:
            safe_params["account"] = "***"
        try:
            payload = self.transport(method, params)
            if self.raw_store:
                self.raw_store.append(
                    "tdx-sim",
                    method,
                    {"request": safe_params, "response": payload},
                    received_at,
                )
            result = payload.get("result")
            if not isinstance(result, dict):
                raise TdxSimError(f"TDX invalid response: {method}")
            if str(result.get("ErrorId", "0")) != "0":
                raise TdxSimError(f"TDX business error: {method}: {result.get('ErrorId')}: {result.get('Error', '')}")
            return result
        except Exception as exc:
            error = exc if isinstance(exc, TdxSimError) else TdxSimError(f"TDX request failed: {method}: {exc}")
            self._log_error(method, error, context)
            raise error from exc

    def account_handle(self) -> int:
        if not self.simulation_confirmed or not self.account:
            error = TdxSimulationGuardError("TDX simulation account is not explicitly confirmed")
            self._log_error("stock_account", error)
            raise error
        if self._account_handle is not None:
            return self._account_handle
        result = self._call("stock_account", {"account": self.account, "account_type": "STOCK"})
        handle = int(result.get("Value", -1))
        if handle <= 0:
            error = TdxSimError("TDX returned an invalid stock account handle")
            self._log_error("stock_account", error)
            raise error
        self._account_handle = handle
        return handle

    def query_asset(self) -> dict[str, Any]:
        result = self._call("query_stock_asset", {"account_id": self.account_handle()})
        return {key: value for key, value in result.items() if key not in {"ErrorId", "Error"}}

    def query_orders(self) -> list[dict[str, Any]]:
        result = self._call(
            "query_stock_orders",
            {"account_id": self.account_handle(), "stock_code": "", "cancelable_only": False},
        )
        value = result.get("Value", [])
        if not isinstance(value, list):
            error = TdxSimError("TDX order response Value must be a list")
            self._log_error("query_stock_orders", error)
            raise error
        return value

    def query_positions(self) -> list[dict[str, Any]]:
        result = self._call("query_stock_positions", {"account_id": self.account_handle()})
        value = result.get("Value", [])
        if not isinstance(value, list):
            error = TdxSimError("TDX position response Value must be a list")
            self._log_error("query_stock_positions", error)
            raise error
        return value

    def submit_limit_order(
        self,
        symbol: str,
        side: Side,
        quantity: int,
        price: Decimal,
    ) -> dict[str, Any]:
        context = {"symbol": symbol, "side": side.value, "quantity": quantity, "price": str(price)}
        result = self._call(
            "order_stock",
            {
                "account_id": self.account_handle(),
                "stock_code": symbol,
                "order_type": 0 if side is Side.BUY else 1,
                "order_volume": quantity,
                "price_type": 0,
                "price": float(price),
                "notify": 0,
            },
            context,
        )
        outcome = int(result.get("Value", 0))
        if outcome == 1:
            error = TdxSimulationGuardError("TDX requires user confirmation; the account is not accepted as simulation")
            self._log_error("order_stock", error, context)
            raise error
        if outcome != 2 or not str(result.get("Wtbh", "")):
            error = TdxSimError(f"TDX simulation order was not accepted: {result.get('Msg', '')}")
            self._log_error("order_stock", error, context)
            raise error
        return result

    def cancel_order(self, symbol: str, order_id: str) -> dict[str, Any]:
        context = {"symbol": symbol, "order_id": order_id}
        result = self._call(
            "cancel_order_stock",
            {"account_id": self.account_handle(), "stock_code": symbol, "order_id": order_id},
            context,
        )
        if int(result.get("Value", 0)) != 1:
            error = TdxSimError(f"TDX simulation cancel was not accepted: {result.get('Msg', '')}")
            self._log_error("cancel_order_stock", error, context)
            raise error
        return result

    def snapshot(self) -> TdxSimSnapshot:
        return TdxSimSnapshot(
            captured_at=datetime.now(SHANGHAI),
            asset=self.query_asset(),
            positions=self.query_positions(),
            orders=self.query_orders(),
        )
