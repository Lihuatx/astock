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
from astock.data.tushare import FundamentalPanel
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
    family: str
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


def _nanmedian(values: np.ndarray, axis: int = 0) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(values, axis=axis)


def _wilder_rsi(closes: np.ndarray, period: int = 14) -> np.ndarray:
    changes = np.diff(closes, axis=0)
    gains = np.where(changes > 0, changes, 0.0)
    losses = np.where(changes < 0, -changes, 0.0)
    average_gain = _nanmean(gains[:period], axis=0)
    average_loss = _nanmean(losses[:period], axis=0)
    for row in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[row]) / period
        average_loss = (average_loss * (period - 1) + losses[row]) / period
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100.0 - 100.0 / (1.0 + average_gain / average_loss)
    valid = np.all(np.isfinite(closes), axis=0)
    return np.where(valid, rsi, np.nan)


def _volume_dry_up_scorer(range_threshold: float) -> ScoreFunction:
    def scorer(panel: MarketPanel, index: int) -> np.ndarray:
        volume = panel.volume[index - 4 : index + 1]
        average_volume = _nanmean(volume, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            volume_cv = _nanstd(volume, axis=0) / average_volume
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            range_width = (
                np.nanmax(panel.high[index - 19 : index + 1], axis=0)
                - np.nanmin(panel.low[index - 19 : index + 1], axis=0)
            ) / panel.close[index]
        return _masked(-volume_cv, (range_width < range_threshold) & _trend_mask(panel, index))

    return scorer


def _masked(score: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return np.where(mask & np.isfinite(score), score, np.nan)


def _cross_sectional_zscore(values: np.ndarray) -> np.ndarray:
    finite = np.isfinite(values)
    if np.sum(finite) < 20:
        return np.full_like(values, np.nan, dtype=np.float64)
    lower, upper = np.nanpercentile(values[finite], [1, 99])
    clipped = np.clip(values, lower, upper)
    deviation = np.nanstd(clipped)
    return (clipped - np.nanmean(clipped)) / deviation if deviation > 0 else np.full_like(values, np.nan)


def _combine_scores(components: list[np.ndarray], minimum_present: int) -> np.ndarray:
    stacked = np.stack(components)
    present = np.sum(np.isfinite(stacked), axis=0)
    return np.where(present >= minimum_present, np.nansum(stacked, axis=0), np.nan)


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

    def short_term_reversal(panel: MarketPanel, index: int) -> np.ndarray:
        score = -(_return(panel, index, 5) + _return(panel, index, 10))
        return _masked(score, _trend_mask(panel, index))

    def bollinger_reversion(panel: MarketPanel, index: int) -> np.ndarray:
        window = panel.close[index - 19 : index + 1]
        average = _nanmean(window, axis=0)
        deviation = _nanstd(window, axis=0)
        lower = average - 2.0 * deviation
        upper = average + 2.0 * deviation
        returns = panel.close[index - 80 : index + 1][1:] / panel.close[index - 80 : index + 1][:-1] - 1.0
        rolling_vol = np.stack([_nanstd(returns[offset : offset + 20], axis=0) for offset in range(61)])
        expanding = rolling_vol[-1] > _nanmedian(rolling_vol[:-1], axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = -(panel.close[index] - lower) / (upper - lower)
        return _masked(score, expanding & _trend_mask(panel, index))

    def rsi_oversold_reversal(panel: MarketPanel, index: int) -> np.ndarray:
        rsi = _wilder_rsi(panel.close[index - 120 : index + 1])
        return _masked(-rsi, (rsi < 35.0) & _trend_mask(panel, index))

    def volatility_contraction(panel: MarketPanel, index: int) -> np.ndarray:
        closes = panel.close[index - 120 : index + 1]
        returns = closes[1:] / closes[:-1] - 1.0
        short_vol = _nanstd(returns[-20:], axis=0)
        long_vol = _nanstd(returns, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = -(short_vol / long_vol)
        return _masked(score, _trend_mask(panel, index))

    def upside_downside_volatility(panel: MarketPanel, index: int) -> np.ndarray:
        closes = panel.close[index - 60 : index + 1]
        returns = closes[1:] / closes[:-1] - 1.0
        up_count = np.sum(returns > 0, axis=0)
        down_count = np.sum(returns < 0, axis=0)
        upside = _nanstd(np.where(returns > 0, returns, np.nan), axis=0)
        downside = _nanstd(np.where(returns < 0, -returns, np.nan), axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = upside / downside
        return _masked(score, (up_count >= 10) & (down_count >= 10) & _trend_mask(panel, index))

    def multi_timeframe_momentum(panel: MarketPanel, index: int) -> np.ndarray:
        returns = [_return(panel, index, window) for window in (10, 20, 60, 120)]
        score = 0.4 * returns[0] + 0.3 * returns[1] + 0.2 * returns[2] + 0.1 * returns[3]
        positive = np.logical_and.reduce([item > 0 for item in returns])
        return _masked(score, positive)

    def accelerating_momentum(panel: MarketPanel, index: int) -> np.ndarray:
        recent = _return(panel, index, 20)
        with np.errstate(divide="ignore", invalid="ignore"):
            previous = panel.close[index - 20] / panel.close[index - 40] - 1.0
        return _masked(recent - previous, (recent > 0) & _trend_mask(panel, index))

    def volume_confirmed_breakout(panel: MarketPanel, index: int) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            previous_high = np.nanmax(panel.high[index - 120 : index], axis=0)
        recent_volume = _nanmean(panel.volume[index - 4 : index + 1], axis=0)
        baseline_volume = _nanmean(panel.volume[index - 59 : index + 1], axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            score = panel.close[index] / previous_high * np.log1p(recent_volume / baseline_volume)
        return _masked(score, _return(panel, index, 60) > 0)

    return (
        FactorSpec("momentum_20_60", "trend", "20/60-day momentum above the 120-day average", 121, momentum_20_60),
        FactorSpec("momentum_120_ex5", "trend", "120-day momentum excluding the latest 5 days", 121, momentum_120_ex5),
        FactorSpec("breakout_120", "trend", "120-day breakout with positive 60-day return", 121, breakout_120),
        FactorSpec("low_volatility_trend", "volatility", "low volatility within an established uptrend", 121, low_volatility_trend),
        FactorSpec("volume_price_strength", "volume", "20-day price and volume strength", 121, volume_price_strength),
        FactorSpec("risk_adjusted_momentum", "trend", "120-day return divided by 60-day volatility", 121, risk_adjusted_momentum),
        FactorSpec("short_term_reversal", "reversal", "5/10-day reversal with trend filter", 121, short_term_reversal),
        FactorSpec("bollinger_reversion", "reversal", "lower Bollinger-band reversion during volatility expansion", 121, bollinger_reversion),
        FactorSpec("rsi_oversold_reversal", "reversal", "Wilder RSI oversold reversal within an uptrend", 121, rsi_oversold_reversal),
        FactorSpec("volatility_contraction", "volatility", "20/120-day volatility contraction within an uptrend", 121, volatility_contraction),
        FactorSpec("upside_downside_volatility", "asymmetry", "upside-to-downside volatility ratio", 121, upside_downside_volatility),
        FactorSpec("multi_timeframe_momentum", "multi_cycle", "10/20/60/120-day momentum agreement", 121, multi_timeframe_momentum),
        FactorSpec("accelerating_momentum", "multi_cycle", "recent 20-day momentum acceleration", 121, accelerating_momentum),
        FactorSpec("volume_confirmed_breakout", "volume", "120-day breakout confirmed by 5-day volume", 121, volume_confirmed_breakout),
        FactorSpec("volume_dry_up", "volume", "volume dry-up during narrow trend consolidation", 121, _volume_dry_up_scorer(0.12)),
    )


def fundamental_factor_specs(panel: FundamentalPanel) -> tuple[FactorSpec, ...]:
    def value(panel_: MarketPanel, index: int) -> np.ndarray:
        pe = panel.pe_ttm[index]
        pb = panel.pb[index]
        dividend = panel.dv_ttm[index]
        earnings_yield = np.where(pe > 0, 1.0 / pe, np.nan)
        book_yield = np.where(pb > 0, 1.0 / pb, np.nan)
        return _combine_scores(
            [
                _cross_sectional_zscore(earnings_yield),
                _cross_sectional_zscore(book_yield),
                0.5 * _cross_sectional_zscore(dividend),
            ],
            2,
        )

    def quality(panel_: MarketPanel, index: int) -> np.ndarray:
        return _combine_scores(
            [
                _cross_sectional_zscore(panel.roe[index]),
                _cross_sectional_zscore(panel.roic[index]),
                _cross_sectional_zscore(panel.grossprofit_margin[index]),
                _cross_sectional_zscore(panel.ocf_to_or[index]),
                -_cross_sectional_zscore(panel.debt_to_assets[index]),
            ],
            3,
        )

    def growth(panel_: MarketPanel, index: int) -> np.ndarray:
        return _combine_scores(
            [_cross_sectional_zscore(panel.q_sales_yoy[index]), _cross_sectional_zscore(panel.q_netprofit_yoy[index])], 2
        )

    def quality_value(panel_: MarketPanel, index: int) -> np.ndarray:
        return _combine_scores([quality(panel_, index), value(panel_, index)], 2)

    def quality_growth(panel_: MarketPanel, index: int) -> np.ndarray:
        return _combine_scores([quality(panel_, index), growth(panel_, index)], 2)

    return (
        FactorSpec("fundamental_value", "fundamental_value", "point-in-time earnings, book and dividend yield", 121, value),
        FactorSpec("fundamental_quality", "fundamental_quality", "point-in-time profitability, cash quality and leverage", 121, quality),
        FactorSpec("fundamental_growth", "fundamental_growth", "point-in-time quarterly sales and profit growth", 121, growth),
        FactorSpec("fundamental_quality_value", "fundamental_composite", "quality plus value composite", 121, quality_value),
        FactorSpec("fundamental_quality_growth", "fundamental_composite", "quality plus growth composite", 121, quality_growth),
    )


def research_signal_dates(panel: MarketPanel) -> list[str]:
    periods = (
        ("2021-01-01", "2023-12-31"),
        ("2024-01-01", "2024-12-31"),
        ("2025-01-01", "2025-12-31"),
        ("2026-01-01", "2026-12-31"),
    )
    selected: set[str] = set()
    for start, end in periods:
        indices = np.flatnonzero((panel.dates >= start) & (panel.dates <= end))
        for cadence in (10, 20, 40):
            selected.update(str(panel.dates[index]) for offset, index in enumerate(indices) if offset % cadence == cadence - 1)
    return sorted(selected)


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
    exposure_rate: float
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
    slippage: float = SLIPPAGE,
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
    invested_days = 0
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
                price = opens[column] * (1.0 - slippage)
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
                price = opens[column] * (1.0 + slippage)
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
        if shares:
            invested_days += 1
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
        exposure_rate=invested_days / len(indices),
        reconciled=bool(cash >= -0.01 and np.all(np.isfinite(curve)) and np.all(curve > 0)),
    )
    return performance, equity_curve, audit


def run_research(panel: MarketPanel, fundamentals: FundamentalPanel | None = None) -> dict:
    periods = {
        "research": ("2021-01-01", "2023-12-31"),
        "validation_2024": ("2024-01-01", "2024-12-31"),
        "validation_2025": ("2025-01-01", "2025-12-31"),
        "stress_2026": ("2026-01-01", "2026-12-31"),
    }
    specs = factor_specs() + (fundamental_factor_specs(fundamentals) if fundamentals is not None else ())
    optimized: list[FactorSpec] = []
    stability: dict[str, dict] = {}
    for base in specs:
        grid: dict[tuple[int, int, float], tuple[FactorSpec, Performance, float]] = {}
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
                    grid[(top_n, rebalance_days, breadth)] = (candidate, performance, score)
        robust: list[tuple[float, FactorSpec, dict]] = []
        value_positions = ({5: 0, 10: 1, 20: 2}, {10: 0, 20: 1, 40: 2}, {0.30: 0, 0.40: 1, 0.50: 2})
        for key, (candidate, performance, score) in grid.items():
            if performance.trade_count < 30:
                continue
            neighbor_scores = [
                item[2]
                for other_key, item in grid.items()
                if sum(left != right for left, right in zip(key, other_key, strict=True)) == 1
                and sum(
                    abs(mapping[left] - mapping[right])
                    for mapping, left, right in zip(value_positions, key, other_key, strict=True)
                ) == 1
            ]
            neighbor_median = float(np.median(neighbor_scores)) if neighbor_scores else score
            details = {
                "research_score": score,
                "neighbor_median_score": neighbor_median,
                "neighbor_score_std": float(np.std(neighbor_scores)) if neighbor_scores else 0.0,
                "positive_neighbor_ratio": float(np.mean(np.asarray(neighbor_scores) > 0)) if neighbor_scores else 0.0,
                "neighbor_count": len(neighbor_scores),
            }
            robust.append((score + 0.25 * neighbor_median, candidate, details))
        if not robust:
            raise RuntimeError(f"no research configuration for {base.name}")
        robust.sort(key=lambda item: item[0], reverse=True)
        optimized.append(robust[0][1])
        stability[base.name] = {"robust_score": robust[0][0], **robust[0][2]}
    results: list[Performance] = []
    audits: dict[str, int] = {}
    curves: dict[tuple[str, str], np.ndarray] = {}
    for spec in optimized:
        for period, (start, end) in periods.items():
            performance, curve, audit = backtest(panel, spec, start, end)
            violations = sum(item.signal_date >= item.execution_date for item in audit)
            if violations:
                raise RuntimeError(f"causality violation in {spec.name} {period}")
            audits[f"{spec.name}:{period}"] = violations
            results.append(Performance(**{**asdict(performance), "period": period}))
            curves[(spec.name, period)] = np.asarray(curve, dtype=np.float64)
    result_lookup = {(item.strategy, item.period): item for item in results}
    ranked: list[tuple[float, FactorSpec]] = []
    for spec in optimized:
        if stability[spec.name]["research_score"] <= 0:
            continue
        if stability[spec.name]["positive_neighbor_ratio"] < 0.50:
            continue
        first = result_lookup[(spec.name, "validation_2024")]
        second = result_lookup[(spec.name, "validation_2025")]
        if first.annual_return < 0 and second.annual_return < 0:
            continue
        if first.trade_count + second.trade_count < 20:
            continue
        score = np.mean([first.calmar + 0.25 * first.sharpe, second.calmar + 0.25 * second.sharpe])
        score -= 0.25 * max(first.max_drawdown, second.max_drawdown)
        ranked.append((float(score), spec))
    ranked.sort(key=lambda item: item[0], reverse=True)
    validation_returns = {
        spec.name: np.concatenate(
            [
                curves[(spec.name, period)][1:] / curves[(spec.name, period)][:-1] - 1.0
                for period in ("validation_2024", "validation_2025")
            ]
        )
        for _, spec in ranked
    }
    correlations: dict[str, dict[str, float]] = {spec.name: {} for _, spec in ranked}
    for _, left in ranked:
        for _, right in ranked:
            correlation = float(np.corrcoef(validation_returns[left.name], validation_returns[right.name])[0, 1])
            correlations[left.name][right.name] = correlation if np.isfinite(correlation) else 1.0
    selected_specs: list[FactorSpec] = []
    remaining = {spec.name: (score, spec) for score, spec in ranked}
    while remaining and len(selected_specs) < 3:
        adjusted: list[tuple[float, FactorSpec]] = []
        for base_score, spec in remaining.values():
            maximum_correlation = max(
                (abs(correlations[spec.name][selected.name]) for selected in selected_specs), default=0.0
            )
            adjusted.append((base_score - 0.15 * maximum_correlation, spec))
        adjusted.sort(key=lambda item: item[0], reverse=True)
        chosen = adjusted[0][1]
        selected_specs.append(chosen)
        remaining.pop(chosen.name)
    if len(selected_specs) < 3:
        raise RuntimeError("fewer than three strategies passed dual-validation eligibility")
    selected_names = [spec.name for spec in selected_specs]
    selected = [
        {
            "strategy": spec.name,
            "family": spec.family,
            "description": spec.description,
            "top_n": spec.top_n,
            "rebalance_days": spec.rebalance_days,
            "minimum_market_breadth": spec.minimum_market_breadth,
        }
        for spec in optimized
        if spec.name in selected_names
    ]
    selected.sort(key=lambda item: selected_names.index(item["strategy"]))
    for item in selected:
        first = result_lookup[(item["strategy"], "validation_2024")]
        second = result_lookup[(item["strategy"], "validation_2025")]
        item["stability"] = stability[item["strategy"]]
        item["validation_target_met"] = all(
            performance.annual_return >= 0.15 and performance.max_drawdown <= 0.15
            for performance in (first, second)
        )
        item["status"] = "provisional_paper_candidate"
        item["confidence"] = (
            "low"
            if min(first.trade_count, second.trade_count) < 20
            or min(first.exposure_rate, second.exposure_rate) < 0.15
            or item["stability"]["positive_neighbor_ratio"] < 0.50
            else "standard"
        )
        item["validation_trade_counts"] = [first.trade_count, second.trade_count]
        item["validation_exposure_rates"] = [first.exposure_rate, second.exposure_rate]
    slippage_sensitivity: list[dict] = []
    for spec in selected_specs:
        for basis_points in (10, 20, 30):
            for period in ("validation_2024", "validation_2025"):
                performance, _, _ = backtest(
                    panel, spec, *periods[period], slippage=basis_points / 10_000
                )
                slippage_sensitivity.append(
                    {
                        "strategy": spec.name,
                        "period": period,
                        "slippage_bps": basis_points,
                        "annual_return": performance.annual_return,
                        "max_drawdown": performance.max_drawdown,
                        "trade_count": performance.trade_count,
                    }
                )
    volume_spec = next(spec for spec in optimized if spec.name == "volume_dry_up")
    volume_range_sensitivity: list[dict] = []
    for threshold in (0.08, 0.10, 0.12, 0.15):
        candidate = replace(volume_spec, scorer=_volume_dry_up_scorer(threshold))
        for period in ("validation_2024", "validation_2025"):
            performance, _, _ = backtest(panel, candidate, *periods[period])
            volume_range_sensitivity.append(
                {
                    "range_threshold": threshold,
                    "period": period,
                    "annual_return": performance.annual_return,
                    "max_drawdown": performance.max_drawdown,
                    "trade_count": performance.trade_count,
                }
            )
    return {
        "methodology": {
            "factor_count": len(specs),
            "configuration_count": len(specs) * 27,
            "initial_cash": INITIAL_CASH,
            "target_annual_return": 0.15,
            "target_max_drawdown": 0.15,
            "signal_execution": "T close signal, T+1 open execution",
            "rebalance": "optimized from 10, 20, or 40 trading days",
            "optimization_rule": "research score plus 0.25 times median neighboring-parameter score; minimum 30 research trades",
            "selection_rule": "positive research score and at least 50 percent positive neighbors, then 2024/2025 composite score with drawdown and correlation penalties",
            "parameter_grid": {"top_n": [5, 10, 20], "rebalance_days": [10, 20, 40], "minimum_market_breadth": [0.30, 0.40, 0.50]},
            "slippage": SLIPPAGE,
            "causality_violations": audits,
            "fundamental_coverage": (
                {
                    name: float(np.mean(np.isfinite(getattr(fundamentals, name))))
                    for name in (
                        "roe",
                        "roic",
                        "grossprofit_margin",
                        "debt_to_assets",
                        "ocf_to_or",
                        "q_sales_yoy",
                        "q_netprofit_yoy",
                        "pe_ttm",
                        "pb",
                        "dv_ttm",
                    )
                }
                if fundamentals is not None
                else None
            ),
            "known_limitations": [
                "当前证券列表不含历史退市股票，存在幸存者偏差。",
                "缺少历史 ST 状态，无法精确重建 5% 涨跌停限制。",
                "日线只能近似成交，下一阶段必须使用 5 分钟数据验证执行质量。",
                "此前研究已经观察过 2026 市场状态，因此 2026 只能作为压力测试，不能称为未观察样本。",
                *(
                    [
                        "Tushare 数据来自第三方代理，存在服务中断、延迟、token 撤销和协议变化风险。",
                        "当前股票池仍以现有证券列表为基础，基本面接入尚未消除退市股幸存者偏差。",
                    ]
                    if fundamentals is not None
                    else []
                ),
            ],
        },
        "selected": selected,
        "validation_correlations": correlations,
        "slippage_sensitivity": slippage_sensitivity,
        "volume_range_sensitivity": volume_range_sensitivity,
        "optimized": [
            {
                "strategy": spec.name,
                "family": spec.family,
                "description": spec.description,
                "top_n": spec.top_n,
                "rebalance_days": spec.rebalance_days,
                "minimum_market_breadth": spec.minimum_market_breadth,
                "stability": stability[spec.name],
            }
            for spec in optimized
        ],
        "results": [asdict(item) for item in results],
    }


def write_report(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(result: dict, path: Path) -> None:
    selected_names = {item["strategy"] for item in result["selected"]}
    result_lookup = {(item["strategy"], item["period"]): item for item in result["results"]}
    periods = ("research", "validation_2024", "validation_2025", "stress_2026")
    factor_count = result["methodology"]["factor_count"]
    configuration_count = result["methodology"]["configuration_count"]
    version = "V4" if factor_count > 15 else "V3"
    lines = [
        f"# 三策略研究报告 {version}",
        "",
        "## 结论",
        "",
        f"{version} 共评估 {factor_count} 个因子、{configuration_count} 组研究期参数配置，并包含参数平坦度、相关性、成交置信度和成本敏感性。2026 只作压力测试，不参与候选选择。",
        "",
        "| 策略 | 逻辑 | 冻结配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 置信度 | 达标 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for selected in result["selected"]:
        name = selected["strategy"]
        first = result_lookup[(name, "validation_2024")]
        second = result_lookup[(name, "validation_2025")]
        stress = result_lookup[(name, "stress_2026")]
        config = f"{selected['top_n']} 只／{selected['rebalance_days']} 日／宽度 {selected['minimum_market_breadth']:.0%}"
        lines.append(
            f"| {name} | {selected['family']} | {config} | {first['annual_return']:.2%}／{first['max_drawdown']:.2%} | "
            f"{second['annual_return']:.2%}／{second['max_drawdown']:.2%} | {stress['annual_return']:.2%}／{stress['max_drawdown']:.2%} | {selected['confidence']} | "
            f"{'是' if selected['validation_target_met'] else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            "- 2021～2023：参数研究；2024、2025：双验证；2026：只作压力测试。",
            "- 参数选择同时考虑研究得分和相邻参数中位数，研究期成交少于 30 笔的配置不得入选。",
            "- 最终排名要求两个验证期不能同时亏损，并以验证期日收益相关性作软惩罚，不再按家族标签硬去重。",
            "- T 日收盘生成信号，T＋1 开盘后成交；未来函数审计违规数为 0。",
            "- 初始资金 100000 元，计入佣金、印花税、过户费、10BP 单边滑点及一字板不可成交。",
            "- 基本面数据仅在公告日后的下一交易日生效，每日估值不跨日回填。" if factor_count > 15 else "",
            "- PE、PB、股息率只抓取 118 个实际信号日，因此全面板覆盖率约 7%～10% 是稀疏设计，不是接口缺失。" if factor_count > 15 else "",
        ]
    )
    if factor_count > 15:
        lines.extend(["", "## 基本面数据覆盖率", "", "| 字段 | 全面板覆盖率 |", "| --- | ---: |"])
        for name, coverage in result["methodology"]["fundamental_coverage"].items():
            lines.append(f"| {name} | {coverage:.1%} |")
    lines.extend(
        [
            "",
            "## 全部冻结因子表现",
            "",
            "| 因子 | 家族 | 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | 成本 | 成交数 | 持仓覆盖 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for config in sorted(result["optimized"], key=lambda item: (item["family"], item["strategy"])):
        name = config["strategy"]
        display = f"**{name}**" if name in selected_names else name
        for period in periods:
            item = result_lookup[(name, period)]
            lines.append(
                f"| {display} | {config['family']} | {period} | {item['annual_return']:.2%} | {item['max_drawdown']:.2%} | "
                f"{item['sharpe']:.2f} | {item['calmar']:.2f} | {item['turnover']:.1f} | {item['transaction_cost']:.0f} | {item['trade_count']} | {item['exposure_rate']:.1%} |"
            )
    lines.extend(
        [
            "",
            "## 参数平坦度",
            "",
            "| 因子 | 研究得分 | 邻域中位数 | 邻域标准差 | 正邻域占比 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for config in sorted(result["optimized"], key=lambda item: item["strategy"]):
        item = config["stability"]
        lines.append(
            f"| {config['strategy']} | {item['research_score']:.3f} | {item['neighbor_median_score']:.3f} | "
            f"{item['neighbor_score_std']:.3f} | {item['positive_neighbor_ratio']:.0%} |"
        )
    lines.extend(["", "## 候选相关性", ""])
    for left in result["selected"]:
        for right in result["selected"]:
            if left["strategy"] < right["strategy"]:
                correlation = result["validation_correlations"][left["strategy"]][right["strategy"]]
                lines.append(f"- `{left['strategy']}` 与 `{right['strategy']}`：{correlation:.3f}。")
    lines.extend(
        [
            "",
            "## 滑点敏感性",
            "",
            "| 策略 | 区间 | 单边滑点 | 年化 | 最大回撤 |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for item in result["slippage_sensitivity"]:
        lines.append(
            f"| {item['strategy']} | {item['period']} | {item['slippage_bps']}BP | "
            f"{item['annual_return']:.2%} | {item['max_drawdown']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 缩量整理阈值敏感性",
            "",
            "| 整理宽度 | 区间 | 年化 | 最大回撤 | 成交数 |",
            "| ---: | --- | ---: | ---: | ---: |",
        ]
    )
    for item in result["volume_range_sensitivity"]:
        lines.append(
            f"| {item['range_threshold']:.0%} | {item['period']} | {item['annual_return']:.2%} | "
            f"{item['max_drawdown']:.2%} | {item['trade_count']} |"
        )
    lines.extend(["", "## 已知限制", ""])
    lines.extend(f"- {item}" for item in result["methodology"]["known_limitations"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
