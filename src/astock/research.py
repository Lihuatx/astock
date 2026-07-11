from __future__ import annotations

import json
import math
import sys
import warnings
from dataclasses import replace
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import numpy as np

from astock.data.tdx import TdxClient
from astock.fees import FeeSchedule


INITIAL_CASH = 100_000.0
MAX_POSITION_WEIGHT = 0.15
SLIPPAGE = 0.001
MIN_AVERAGE_AMOUNT = 20_000_000.0
TDX_AMOUNT_UNIT = 10_000.0


@dataclass(frozen=True)
class MarketPanel:
    dates: np.ndarray
    symbols: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    amount: np.ndarray

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **self.__dict__)

    @classmethod
    def load(cls, path: Path) -> "MarketPanel":
        with np.load(path, allow_pickle=False) as data:
            return cls(**{field: data[field] for field in cls.__dataclass_fields__})


def is_main_board(symbol: str) -> bool:
    code, market = symbol.split(".")
    return (market == "SH" and code.startswith(("600", "601", "603", "605"))) or (
        market == "SZ" and code.startswith(("000", "001", "002", "003"))
    )


def fetch_market_panel(
    client: TdxClient,
    start: str,
    end: str,
    cache_path: Path,
    batch_size: int = 10,
) -> MarketPanel:
    symbols = [symbol for symbol in client.get_stock_list() if is_main_board(symbol)]
    trading_dates = client.get_trading_dates(start, end)
    dates = np.array([item.isoformat() for item in trading_dates], dtype="U10")
    date_index = {value: index for index, value in enumerate(dates.tolist())}
    shape = (len(dates), len(symbols))
    arrays = {name: np.full(shape, np.nan, dtype=np.float64) for name in ("open", "high", "low", "close", "volume", "amount")}
    fields = ["Open", "High", "Low", "Close", "Volume", "Amount"]
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset : offset + batch_size]
        result = client._call(
            "get_market_data",
            {
                "field_list": fields,
                "stock_list": batch,
                "period": "1d",
                "start_time": start,
                "end_time": end,
                "count": -1,
                "dividend_type": "front",
                "fill_data": False,
            },
        )
        values = result.get("Value") or {}
        for column, symbol in enumerate(batch, start=offset):
            raw = values.get(symbol) or {}
            raw_dates = raw.get("Date") or []
            for row, raw_day in enumerate(raw_dates):
                day_text = str(raw_day)[:8]
                if len(day_text) != 8:
                    continue
                iso_day = f"{day_text[:4]}-{day_text[4:6]}-{day_text[6:8]}"
                target = date_index.get(iso_day)
                if target is None:
                    continue
                for field, name in zip(fields, arrays, strict=True):
                    series = raw.get(field) or []
                    if row < len(series):
                        try:
                            value = float(series[row])
                            arrays[name][target, column] = value * TDX_AMOUNT_UNIT if name == "amount" else value
                        except (TypeError, ValueError):
                            pass
        print(f"行情加载 {min(offset + batch_size, len(symbols))}/{len(symbols)}", file=sys.stderr)
    panel = MarketPanel(dates, np.array(symbols, dtype="U12"), **arrays)
    panel.save(cache_path)
    return panel


ScoreFunction = Callable[[MarketPanel, int], np.ndarray]


@dataclass(frozen=True)
class FactorSpec:
    name: str
    description: str
    min_history: int
    scorer: ScoreFunction
    rebalance_days: int = 20
    top_n: int = 5
    minimum_market_breadth: float = 0.45


def _return(panel: MarketPanel, index: int, window: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return panel.close[index] / panel.close[index - window] - 1.0


def _trend_mask(panel: MarketPanel, index: int, window: int = 120) -> np.ndarray:
    average = _nanmean(panel.close[index - window + 1 : index + 1], axis=0)
    return panel.close[index] > average


def _nanmean(values: np.ndarray, axis: int = 0) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(values, axis=axis)


def _nanstd(values: np.ndarray, axis: int = 0) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanstd(values, axis=axis)


def _masked(score: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.where(mask & np.isfinite(score), score, np.nan)


def factor_specs() -> tuple[FactorSpec, ...]:
    def momentum_20_60(panel: MarketPanel, index: int) -> np.ndarray:
        return _masked(_return(panel, index, 20) + _return(panel, index, 60), _trend_mask(panel, index))

    def momentum_120_ex5(panel: MarketPanel, index: int) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            score = panel.close[index - 5] / panel.close[index - 120] - 1.0
        return _masked(score, _trend_mask(panel, index))

    def breakout_120(panel: MarketPanel, index: int) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            previous_high = np.nanmax(panel.high[index - 120 : index], axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = panel.close[index] / previous_high
        return _masked(score, _return(panel, index, 60) > 0)

    def low_volatility_trend(panel: MarketPanel, index: int) -> np.ndarray:
        closes = panel.close[index - 60 : index + 1]
        returns = closes[1:] / closes[:-1] - 1.0
        volatility = _nanstd(returns, axis=0)
        return _masked(-volatility, _trend_mask(panel, index) & (_return(panel, index, 60) > 0))

    def volume_price_strength(panel: MarketPanel, index: int) -> np.ndarray:
        recent = _nanmean(panel.volume[index - 19 : index + 1], axis=0)
        baseline = _nanmean(panel.volume[index - 119 : index - 19], axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = _return(panel, index, 20) * np.log1p(recent / baseline)
        return _masked(score, _trend_mask(panel, index))

    def risk_adjusted_momentum(panel: MarketPanel, index: int) -> np.ndarray:
        closes = panel.close[index - 60 : index + 1]
        returns = closes[1:] / closes[:-1] - 1.0
        volatility = _nanstd(returns, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = _return(panel, index, 120) / volatility
        return _masked(score, _trend_mask(panel, index))

    return (
        FactorSpec("momentum_20_60", "20／60 日动量并要求站上 120 日均线", 121, momentum_20_60),
        FactorSpec("momentum_120_ex5", "跳过最近 5 日的 120 日中期动量", 121, momentum_120_ex5),
        FactorSpec("breakout_120", "接近 120 日新高且 60 日收益为正", 121, breakout_120),
        FactorSpec("low_volatility_trend", "上升趋势中的低波动股票", 121, low_volatility_trend),
        FactorSpec("volume_price_strength", "趋势中的 20 日量价强度", 121, volume_price_strength),
        FactorSpec("risk_adjusted_momentum", "120 日收益除以 60 日波动率", 121, risk_adjusted_momentum),
    )


@dataclass(frozen=True)
class Performance:
    strategy: str
    period: str
    start: str
    end: str
    annual_return: float
    max_drawdown: float
    sharpe: float
    calmar: float
    total_return: float
    turnover: float
    transaction_cost: float
    trade_count: int
    reconciled: bool


@dataclass(frozen=True)
class ExecutionAudit:
    signal_date: str
    execution_date: str
    symbol: str
    side: str


def select_symbols(panel: MarketPanel, spec: FactorSpec, signal_index: int, top_n: int | None = None) -> np.ndarray:
    if signal_index < spec.min_history:
        return np.array([], dtype=np.int64)
    score = spec.scorer(panel, signal_index).copy()
    average_amount = _nanmean(panel.amount[signal_index - 19 : signal_index + 1], axis=0)
    known = np.sum(np.isfinite(panel.close[signal_index - 119 : signal_index + 1]), axis=0) == 120
    trend = _trend_mask(panel, signal_index)
    eligible = known & np.isfinite(panel.close[signal_index]) & (panel.close[signal_index] > 0) & (average_amount >= MIN_AVERAGE_AMOUNT)
    if np.sum(eligible) == 0 or float(np.mean(trend[eligible])) < spec.minimum_market_breadth:
        return np.array([], dtype=np.int64)
    score[~eligible] = np.nan
    candidates = np.flatnonzero(np.isfinite(score))
    if not len(candidates):
        return candidates
    count = min(top_n or spec.top_n, len(candidates))
    chosen = candidates[np.argpartition(score[candidates], -count)[-count:]]
    return chosen[np.argsort(score[chosen])[::-1]]


def _fees(side: str, amount: float) -> float:
    schedule = FeeSchedule()
    commission = max(float(schedule.minimum_commission), amount * float(schedule.commission_rate))
    transfer = amount * float(schedule.transfer_fee_rate)
    stamp = amount * float(schedule.stamp_tax_rate) if side == "sell" else 0.0
    return commission + transfer + stamp


def backtest(
    panel: MarketPanel,
    spec: FactorSpec,
    start: str,
    end: str,
    initial_cash: float = INITIAL_CASH,
    top_n: int | None = None,
) -> tuple[Performance, list[float], list[ExecutionAudit]]:
    indices = np.flatnonzero((panel.dates >= start) & (panel.dates <= end))
    if len(indices) < 2:
        raise ValueError(f"insufficient data for {start} to {end}")
    cash = initial_cash
    shares: dict[int, int] = {}
    equity_curve: list[float] = []
    traded_amount = 0.0
    transaction_cost = 0.0
    trade_count = 0
    pending: tuple[np.ndarray, int] | None = None
    audit: list[ExecutionAudit] = []
    last_close = np.full(len(panel.symbols), np.nan, dtype=np.float64)
    for offset, index in enumerate(indices):
        opens = panel.open[index]
        previous_close = panel.close[index - 1] if index > 0 else np.full_like(opens, np.nan)
        one_price = np.isfinite(panel.high[index]) & np.isfinite(panel.low[index]) & (np.abs(panel.high[index] - panel.low[index]) < 1e-9)
        cannot_buy = one_price & np.isfinite(previous_close) & (opens >= previous_close * 1.095)
        cannot_sell = one_price & np.isfinite(previous_close) & (opens <= previous_close * 0.905)
        if pending is not None:
            pending_symbols, signal_index = pending
            target_set = set(pending_symbols.tolist())
            for column in list(shares):
                if column in target_set:
                    continue
                if not np.isfinite(opens[column]) or opens[column] <= 0 or cannot_sell[column]:
                    continue
                price = opens[column] * (1.0 - SLIPPAGE)
                amount = shares.pop(column) * price
                fee = _fees("sell", amount)
                cash += amount - fee
                traded_amount += amount
                transaction_cost += fee
                trade_count += 1
                audit.append(ExecutionAudit(str(panel.dates[signal_index]), str(panel.dates[index]), str(panel.symbols[column]), "SELL"))
            current_close = panel.close[index]
            last_close[np.isfinite(current_close)] = current_close[np.isfinite(current_close)]
            close_value = sum(quantity * last_close[column] for column, quantity in shares.items() if np.isfinite(last_close[column]))
            equity = cash + close_value
            target_value = min(equity * 0.90 / max(1, len(pending_symbols)), equity * MAX_POSITION_WEIGHT)
            for column in pending_symbols:
                if column in shares or not np.isfinite(opens[column]) or opens[column] <= 0 or cannot_buy[column]:
                    continue
                price = opens[column] * (1.0 + SLIPPAGE)
                quantity = int(target_value / price / 100) * 100
                while quantity >= 100:
                    amount = quantity * price
                    fee = _fees("buy", amount)
                    if cash >= amount + fee:
                        break
                    quantity -= 100
                if quantity < 100:
                    continue
                amount = quantity * price
                fee = _fees("buy", amount)
                cash -= amount + fee
                shares[int(column)] = quantity
                traded_amount += amount
                transaction_cost += fee
                trade_count += 1
                audit.append(ExecutionAudit(str(panel.dates[signal_index]), str(panel.dates[index]), str(panel.symbols[column]), "BUY"))
            pending = None
        current_close = panel.close[index]
        last_close[np.isfinite(current_close)] = current_close[np.isfinite(current_close)]
        close_value = sum(quantity * last_close[column] for column, quantity in shares.items() if np.isfinite(last_close[column]))
        equity_curve.append(cash + close_value)
        # 仅在收盘估值完成后生成信号，下一循环交易日开盘执行。
        if offset % spec.rebalance_days == spec.rebalance_days - 1 and index < indices[-1]:
            pending = (select_symbols(panel, spec, int(index), top_n), int(index))
    curve = np.asarray(equity_curve, dtype=np.float64)
    returns = curve[1:] / curve[:-1] - 1.0
    years = len(curve) / 242.0
    annual = float((curve[-1] / curve[0]) ** (1.0 / years) - 1.0) if years > 0 and curve[0] > 0 else 0.0
    peaks = np.maximum.accumulate(curve)
    drawdown = curve / peaks - 1.0
    maximum_drawdown = abs(float(np.nanmin(drawdown)))
    volatility = float(np.nanstd(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.nanmean(returns) / volatility * math.sqrt(242)) if volatility > 0 else 0.0
    calmar = annual / maximum_drawdown if maximum_drawdown > 0 else 0.0
    performance = Performance(
        strategy=spec.name,
        period="",
        start=start,
        end=end,
        annual_return=annual,
        max_drawdown=maximum_drawdown,
        sharpe=sharpe,
        calmar=calmar,
        total_return=float(curve[-1] / curve[0] - 1.0),
        turnover=traded_amount / max(initial_cash, 1.0),
        transaction_cost=transaction_cost,
        trade_count=trade_count,
        reconciled=bool(cash >= -0.01 and np.all(np.isfinite(curve)) and np.all(curve > 0)),
    )
    return performance, equity_curve, audit


def run_research(panel: MarketPanel) -> dict:
    periods = {
        "research": ("2021-01-01", "2024-12-31"),
        "validation": ("2025-01-01", "2025-12-31"),
        "out_of_sample": ("2026-01-01", "2026-12-31"),
    }
    optimized: list[FactorSpec] = []
    for base in factor_specs():
        best: tuple[float, FactorSpec] | None = None
        for top_n in (5, 10, 20):
            for rebalance_days in (10, 20, 40):
                for breadth in (0.30, 0.40, 0.50):
                    candidate = replace(
                        base,
                        top_n=top_n,
                        rebalance_days=rebalance_days,
                        minimum_market_breadth=breadth,
                    )
                    performance, _, _ = backtest(panel, candidate, *periods["research"])
                    score = performance.calmar + 0.25 * performance.sharpe
                    if best is None or score > best[0]:
                        best = (score, candidate)
        if best is None:
            raise RuntimeError(f"no research configuration for {base.name}")
        optimized.append(best[1])
    results: list[Performance] = []
    audits: dict[str, int] = {}
    for spec in optimized:
        for period, (start, end) in periods.items():
            performance, _, audit = backtest(panel, spec, start, end)
            violations = sum(item.signal_date >= item.execution_date for item in audit)
            if violations:
                raise RuntimeError(f"causality violation in {spec.name} {period}")
            audits[f"{spec.name}:{period}"] = violations
            results.append(Performance(**{**asdict(performance), "period": period}))
    validation = [item for item in results if item.period == "validation"]
    validation.sort(key=lambda item: (item.calmar, item.sharpe, item.annual_return), reverse=True)
    selected_names = [item.strategy for item in validation[:3]]
    selected = [
        {
            "strategy": spec.name,
            "description": spec.description,
            "top_n": spec.top_n,
            "rebalance_days": spec.rebalance_days,
            "minimum_market_breadth": spec.minimum_market_breadth,
        }
        for spec in optimized
        if spec.name in selected_names
    ]
    selected.sort(key=lambda item: selected_names.index(item["strategy"]))
    validation_by_name = {item.strategy: item for item in validation}
    for item in selected:
        performance = validation_by_name[item["strategy"]]
        item["validation_target_met"] = performance.annual_return >= 0.15 and performance.max_drawdown <= 0.15
        item["status"] = "provisional_paper_candidate"
    return {
        "methodology": {
            "initial_cash": INITIAL_CASH,
            "target_annual_return": 0.15,
            "target_max_drawdown": 0.15,
            "signal_execution": "T close signal, T+1 open execution",
            "rebalance": "every 20 trading days",
            "optimization_rule": "each factor configuration selected by research Calmar + 0.25 * Sharpe",
            "selection_rule": "top 3 frozen factors by validation Calmar, then Sharpe and annual return; OOS excluded from selection",
            "parameter_grid": {"top_n": [5, 10, 20], "rebalance_days": [10, 20, 40], "minimum_market_breadth": [0.30, 0.40, 0.50]},
            "slippage": SLIPPAGE,
            "causality_violations": audits,
            "known_limitations": [
                "current security list excludes previously delisted stocks and introduces survivorship bias",
                "historical ST status is unavailable, so 5 percent ST price limits cannot be reconstructed exactly",
                "daily bars approximate execution; 5-minute data is required for the next execution-quality validation",
            ],
        },
        "selected": selected,
        "results": [asdict(item) for item in results],
    }


def write_report(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
