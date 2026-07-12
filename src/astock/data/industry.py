from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from astock.data.tushare import TushareProxyClient


@dataclass(frozen=True)
class IndustryPanel:
    dates: np.ndarray
    symbols: np.ndarray
    industry_codes: np.ndarray
    industry_names: np.ndarray
    membership: np.ndarray
    close: np.ndarray

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **self.__dict__)

    @classmethod
    def load(cls, path: Path) -> "IndustryPanel":
        with np.load(path, allow_pickle=False) as data:
            return cls(**{field: data[field] for field in cls.__dataclass_fields__})


def build_industry_panel(
    client: TushareProxyClient,
    dates: np.ndarray,
    symbols: np.ndarray,
    stock_close: np.ndarray,
    cache_path: Path,
) -> IndustryPanel:
    classification = client.query(
        "index_classify",
        {"level": "L1", "src": "SW2021"},
        "index_code,industry_name,parent_code,level,industry_code,is_pub,src",
    )
    classification = sorted(
        (row for row in classification if str(row.get("is_pub")) == "1"),
        key=lambda row: str(row.get("index_code")),
    )
    industry_codes = np.asarray([str(row["index_code"]) for row in classification], dtype="U12")
    industry_names = np.asarray([str(row["industry_name"]) for row in classification], dtype="U16")
    code_index = {code: index for index, code in enumerate(industry_codes.tolist())}
    symbol_index = {symbol: index for index, symbol in enumerate(symbols.tolist())}

    member_fields = "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new"
    member_groups = client.query_many(
        "index_member_all",
        [{"l1_code": code} for code in industry_codes.tolist()],
        member_fields,
    )
    grouped_members = {code: [] for code in industry_codes.tolist()}
    for row in member_groups:
        code = str(row.get("l1_code"))
        if code in grouped_members:
            grouped_members[code].append(row)
    missing_codes = [code for code, rows in grouped_members.items() if not rows]
    if missing_codes:
        level_two = client.query(
            "index_classify",
            {"level": "L2", "src": "SW2021"},
            "index_code,industry_name,parent_code,level,industry_code,is_pub,src",
        )
        industry_roots = {str(row["index_code"]): str(row["industry_code"]) for row in classification}
        fallback_requests = [
            {"l2_code": str(row["index_code"])}
            for code in missing_codes
            for row in level_two
            if str(row.get("parent_code")) == industry_roots[code]
        ]
        if fallback_requests:
            for row in client.query_many("index_member_all", fallback_requests, member_fields):
                code = str(row.get("l1_code"))
                if code in grouped_members:
                    grouped_members[code].append(row)
    member_rows = [row for rows in grouped_members.values() for row in rows]
    membership = np.full((len(dates), len(symbols)), -1, dtype=np.int16)
    member_rows.sort(key=lambda row: str(row.get("in_date") or ""))
    for row in member_rows:
        column = symbol_index.get(str(row.get("ts_code")))
        industry = code_index.get(str(row.get("l1_code")))
        if column is None or industry is None:
            continue
        start_text = str(row.get("in_date") or "")
        end_text = str(row.get("out_date") or "")
        start = f"{start_text[:4]}-{start_text[4:6]}-{start_text[6:8]}" if len(start_text) == 8 else str(dates[0])
        end = f"{end_text[:4]}-{end_text[4:6]}-{end_text[6:8]}" if len(end_text) == 8 else str(dates[-1])
        active = (dates >= start) & (dates <= end)
        membership[active, column] = industry

    daily_fields = "ts_code,trade_date,name,open,high,low,close,pct_change,vol,amount"
    daily_rows = client.query_many(
        "sw_daily",
        [
            {
                "ts_code": code,
                "start_date": str(dates[0]).replace("-", ""),
                "end_date": str(dates[-1]).replace("-", ""),
            }
            for code in industry_codes.tolist()
        ],
        daily_fields,
    )
    close = np.full((len(dates), len(industry_codes)), np.nan, dtype=np.float64)
    date_index = {day: index for index, day in enumerate(dates.tolist())}
    for row in daily_rows:
        day = str(row.get("trade_date") or "")
        iso_day = f"{day[:4]}-{day[4:6]}-{day[6:8]}" if len(day) == 8 else ""
        row_index = date_index.get(iso_day)
        column = code_index.get(str(row.get("ts_code")))
        if row_index is None or column is None:
            continue
        try:
            close[row_index, column] = float(row.get("close"))
        except (TypeError, ValueError):
            pass

    with np.errstate(divide="ignore", invalid="ignore"):
        stock_returns = stock_close[1:] / stock_close[:-1] - 1.0
    for industry in range(len(industry_codes)):
        synthetic = np.full(len(dates), np.nan, dtype=np.float64)
        synthetic[0] = 1000.0
        for row_index in range(1, len(dates)):
            members = membership[row_index - 1] == industry
            returns = stock_returns[row_index - 1, members]
            finite = returns[np.isfinite(returns)]
            synthetic[row_index] = (
                synthetic[row_index - 1] * (1.0 + float(np.mean(finite)))
                if len(finite)
                else synthetic[row_index - 1]
            )
        if float(np.mean(np.isfinite(close[:, industry]))) < 0.90:
            close[:, industry] = synthetic

    panel = IndustryPanel(
        dates.copy(),
        symbols.copy(),
        industry_codes,
        industry_names,
        membership,
        close,
    )
    panel.save(cache_path)
    return panel
