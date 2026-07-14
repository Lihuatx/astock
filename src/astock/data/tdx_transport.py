from __future__ import annotations

import atexit
import contextlib
import importlib.util
import io
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any


class TdxSdkTransport:
    """把客户端自带 tqcenter.py 的返回值标准化为 TDX HTTP 响应结构。"""

    def __init__(self, plugin_dir: Path, sdk: Any | None = None) -> None:
        self.plugin_dir = plugin_dir.resolve()
        self._sdk = sdk
        self._lock = threading.RLock()

    def _load_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        module_path = self.plugin_dir / "tqcenter.py"
        if not module_path.is_file():
            raise RuntimeError(f"TDX SDK not found: {module_path}")
        module_name = f"_astock_tqcenter_{abs(hash(str(module_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"TDX SDK cannot be loaded: {module_path}")
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
            module.tq.initialize(str(module_path))
            atexit.register(_quiet_close, module.tq)
        self._sdk = module.tq
        return self._sdk

    def __call__(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            sdk = self._load_sdk()
            function = getattr(sdk, method, None)
            if function is None:
                raise RuntimeError(f"TDX SDK method is unavailable: {method}")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                value = function(**params)
            result = (
                {"ErrorId": "SDK_DISCONNECTED", "Error": f"TDX SDK disconnected during {method}"}
                if getattr(sdk, "_initialized", True) is False
                else self._normalize(method, value, params)
            )
            return {"id": 0, "result": result}

    @staticmethod
    def _normalize(method: str, value: Any, params: dict[str, Any]) -> dict[str, Any]:
        if method == "stock_account":
            handle = int(value) if isinstance(value, int) else -1
            return (
                {"ErrorId": "0", "Value": handle}
                if handle > 0
                else {"ErrorId": "SDK_ACCOUNT", "Error": "current TDX account is unavailable"}
            )
        if method in {"query_stock_positions", "query_stock_orders", "get_stock_list"}:
            if not isinstance(value, list):
                return {"ErrorId": "SDK_TYPE", "Error": f"{method} did not return a list"}
            return {"ErrorId": "0", "Value": value}
        if method == "get_trading_dates":
            if not isinstance(value, list):
                return {"ErrorId": "SDK_TYPE", "Error": "get_trading_dates did not return a list"}
            return {"ErrorId": "0", "Date": value}
        if method == "get_market_data":
            return TdxSdkTransport._normalize_market_data(value, params)
        if method in {"order_stock", "cancel_order_stock"} and not isinstance(value, dict):
            return {"ErrorId": "SDK_ORDER", "Error": f"{method} was rejected by the TDX SDK"}
        if not isinstance(value, dict) or not value:
            return {"ErrorId": "SDK_EMPTY", "Error": f"{method} returned no data"}
        return value

    @staticmethod
    def _normalize_market_data(value: Any, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            return {"ErrorId": "SDK_EMPTY", "Error": "get_market_data returned no data"}
        symbols = [str(item) for item in params.get("stock_list", [])]
        normalized: dict[str, dict[str, list[str]]] = {
            symbol: {"Date": [], "Time": []} for symbol in symbols
        }
        first_frame = next(iter(value.values()), None)
        indexes = list(getattr(first_frame, "index", []))
        for symbol in symbols:
            for item in indexes:
                day, time_text = _format_index(item)
                normalized[symbol]["Date"].append(day)
                normalized[symbol]["Time"].append(time_text)
            for field, frame in value.items():
                columns = {str(column) for column in getattr(frame, "columns", [])}
                normalized[symbol][str(field)] = (
                    [_string_value(frame.at[item, symbol]) for item in indexes]
                    if symbol in columns
                    else []
                )
        return {"ErrorId": "0", "Value": normalized}


def _format_index(value: Any) -> tuple[str, str]:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d"), value.strftime("%H%M%S")
    if isinstance(value, date):
        return value.strftime("%Y%m%d"), "000000"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeError(f"unsupported TDX SDK time index: {text}") from exc
    return parsed.strftime("%Y%m%d"), parsed.strftime("%H%M%S")


def _string_value(value: Any) -> str:
    if hasattr(value, "item"):
        value = value.item()
    return str(value)


def _quiet_close(sdk: Any) -> None:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        sdk.close()
