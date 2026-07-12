from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests


class TushareProxyError(RuntimeError):
    pass


class TushareProxyClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        cache_dir: Path,
        minimum_interval: float = 1.0,
        timeout: float = 45.0,
    ) -> None:
        if not token:
            raise ValueError("TUSHARE_BASE_TOKEN is required")
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.cache_dir = cache_dir
        self.minimum_interval = minimum_interval
        self.timeout = timeout
        self._rate_lock = threading.Lock()
        self._last_request = 0.0

    def _cache_path(self, api_name: str, params: dict[str, Any], fields: str) -> Path:
        key = json.dumps([api_name, params, fields], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / api_name / f"{digest}.json"

    def _wait_for_slot(self) -> None:
        with self._rate_lock:
            remaining = self.minimum_interval - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
            self._last_request = time.monotonic()

    def query(self, api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        cache_path = self._cache_path(api_name, params, fields)
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))
        payload = {"api_name": api_name, "token": self._token, "params": params, "fields": fields}
        last_error: Exception | None = None
        for attempt in range(3):
            self._wait_for_slot()
            try:
                response = requests.post(
                    f"{self.base_url}/{api_name}",
                    json=payload,
                    headers={"Accept-Encoding": "gzip", "User-Agent": "astock/0.1"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                envelope = response.json()
                if envelope.get("code") != 0:
                    raise TushareProxyError(f"{api_name} business error: {envelope.get('code')}: {envelope.get('msg')}")
                data = envelope.get("data") or {}
                names = data.get("fields") or []
                rows = [dict(zip(names, item, strict=True)) for item in (data.get("items") or [])]
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                return rows
            except (requests.RequestException, ValueError, TushareProxyError) as exc:
                last_error = exc
                if isinstance(exc, TushareProxyError) or attempt == 2:
                    break
                time.sleep(2**attempt)
        message = str(last_error).replace(self._token, "[REDACTED]")
        raise TushareProxyError(f"{api_name} request failed: {message}") from last_error

    def query_many(
        self,
        api_name: str,
        requests_: Iterable[dict[str, Any]],
        fields: str,
        workers: int = 4,
    ) -> list[dict[str, Any]]:
        params_list = list(requests_)
        rows: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self.query, api_name, params, fields): params for params in params_list}
            completed = 0
            for future in as_completed(futures):
                rows.extend(future.result())
                completed += 1
                if completed % 10 == 0 or completed == len(params_list):
                    print(f"Tushare {api_name} {completed}/{len(params_list)}")
        return rows


@dataclass(frozen=True)
class FundamentalPanel:
    dates: np.ndarray
    symbols: np.ndarray
    roe: np.ndarray
    roic: np.ndarray
    grossprofit_margin: np.ndarray
    debt_to_assets: np.ndarray
    ocf_to_or: np.ndarray
    q_sales_yoy: np.ndarray
    q_netprofit_yoy: np.ndarray
    pe_ttm: np.ndarray
    pb: np.ndarray
    dv_ttm: np.ndarray
    ocf_to_opincome: np.ndarray | None = None
    arturn_days: np.ndarray | None = None
    invturn_days: np.ndarray | None = None
    n_op_profit_of_ebt: np.ndarray | None = None

    def __post_init__(self) -> None:
        shape = (len(self.dates), len(self.symbols))
        for name in ("ocf_to_opincome", "arturn_days", "invturn_days", "n_op_profit_of_ebt"):
            if getattr(self, name) is None:
                object.__setattr__(self, name, np.full(shape, np.nan, dtype=np.float64))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **self.__dict__)

    @classmethod
    def load(cls, path: Path) -> "FundamentalPanel":
        with np.load(path, allow_pickle=False) as data:
            return cls(**{field: data[field] for field in cls.__dataclass_fields__})


def _safe_float(value: Any) -> float:
    try:
        return float(value) if value is not None else np.nan
    except (TypeError, ValueError):
        return np.nan


def build_fundamental_panel(
    client: TushareProxyClient,
    dates: np.ndarray,
    symbols: np.ndarray,
    signal_dates: list[str],
    cache_path: Path,
) -> FundamentalPanel:
    symbol_list = symbols.tolist()
    financial_fields = (
        "ts_code,ann_date,end_date,update_flag,roe,roic,grossprofit_margin,debt_to_assets,"
        "ocf_to_or,q_sales_yoy,q_netprofit_yoy,ocf_to_opincome,arturn_days,invturn_days,n_op_profit_of_ebt"
    )
    financial_requests = [
        {
            "ts_code": ",".join(symbol_list[offset : offset + 50]),
            "start_date": "20200101",
            "end_date": str(dates[-1]).replace("-", ""),
        }
        for offset in range(0, len(symbol_list), 50)
    ]
    financial_rows = client.query_many("fina_indicator", financial_requests, financial_fields)
    valuation_fields = "ts_code,trade_date,pe_ttm,pb,dv_ttm"
    valuation_rows = client.query_many(
        "daily_basic", [{"trade_date": day.replace("-", "")} for day in signal_dates], valuation_fields
    )
    shape = (len(dates), len(symbols))
    metric_names = (
        "roe",
        "roic",
        "grossprofit_margin",
        "debt_to_assets",
        "ocf_to_or",
        "q_sales_yoy",
        "q_netprofit_yoy",
        "ocf_to_opincome",
        "arturn_days",
        "invturn_days",
        "n_op_profit_of_ebt",
        "pe_ttm",
        "pb",
        "dv_ttm",
    )
    arrays = {name: np.full(shape, np.nan, dtype=np.float64) for name in metric_names}
    symbol_index = {symbol: index for index, symbol in enumerate(symbol_list)}
    date_values = dates.tolist()
    # 财务数据在公告日后的首个交易日生效，同报告期的后续修订会覆盖此前版本。
    financial_rows.sort(key=lambda item: (str(item.get("ann_date") or ""), str(item.get("end_date") or "")))
    events: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for row in financial_rows:
        column = symbol_index.get(str(row.get("ts_code")))
        ann_date = str(row.get("ann_date") or "")
        if column is None or len(ann_date) != 8:
            continue
        iso_date = f"{ann_date[:4]}-{ann_date[4:6]}-{ann_date[6:8]}"
        effective = int(np.searchsorted(dates, iso_date, side="right"))
        if effective < len(dates):
            events.setdefault(effective, []).append((column, row))
    current = {name: np.full(len(symbols), np.nan, dtype=np.float64) for name in metric_names[:11]}
    for day_index in range(len(dates)):
        for column, row in events.get(day_index, []):
            for name in current:
                current[name][column] = _safe_float(row.get(name))
        for name in current:
            arrays[name][day_index] = current[name]
    date_index = {day: index for index, day in enumerate(date_values)}
    for row in valuation_rows:
        day = str(row.get("trade_date") or "")
        iso_day = f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else ""
        row_index = date_index.get(iso_day)
        column = symbol_index.get(str(row.get("ts_code")))
        if row_index is None or column is None:
            continue
        for name in ("pe_ttm", "pb", "dv_ttm"):
            arrays[name][row_index, column] = _safe_float(row.get(name))
    panel = FundamentalPanel(dates.copy(), symbols.copy(), **arrays)
    panel.save(cache_path)
    return panel


def update_valuation_date(
    client: TushareProxyClient,
    panel: FundamentalPanel,
    trading_day: str,
    cache_path: Path,
) -> FundamentalPanel:
    row_matches = np.flatnonzero(panel.dates == trading_day)
    if not len(row_matches):
        raise ValueError(f"valuation date is outside fundamental panel: {trading_day}")
    row_index = int(row_matches[0])
    rows = client.query(
        "daily_basic",
        {"trade_date": trading_day.replace("-", "")},
        "ts_code,trade_date,pe_ttm,pb,dv_ttm",
    )
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols.tolist())}
    for row in rows:
        column = symbol_index.get(str(row.get("ts_code")))
        if column is None:
            continue
        panel.pe_ttm[row_index, column] = _safe_float(row.get("pe_ttm"))
        panel.pb[row_index, column] = _safe_float(row.get("pb"))
        panel.dv_ttm[row_index, column] = _safe_float(row.get("dv_ttm"))
    panel.save(cache_path)
    return panel
