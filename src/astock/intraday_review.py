from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np

from astock.data.tdx import TdxClient
from astock.data.tushare import FundamentalPanel
from astock.models import Bar
from astock.observability.bundle import sha256_file
from astock.research import MarketPanel, backtest, factor_specs, fundamental_factor_specs


SHANGHAI = ZoneInfo("Asia/Shanghai")
LIMIT_SLIPPAGE = Decimal("0.002")
PARTICIPATION_RATE = Decimal("0.10")
EXPECTED_BARS_PER_DAY = 48


@dataclass(frozen=True)
class ReviewOrder:
    strategy: str
    signal_date: str
    execution_date: str
    symbol: str
    side: str
    quantity: int
    daily_modeled_price: str

    @property
    def reference_open(self) -> Decimal:
        price = Decimal(self.daily_modeled_price)
        divisor = Decimal("1") + LIMIT_SLIPPAGE if self.side == "BUY" else Decimal("1") - LIMIT_SLIPPAGE
        return price / divisor

    @property
    def limit_price(self) -> Decimal:
        return Decimal(self.daily_modeled_price)


def planned_orders(
    panel: MarketPanel,
    fundamentals: FundamentalPanel,
    report: dict,
    review_days: int,
) -> tuple[list[ReviewOrder], list[str]]:
    if review_days <= 0 or review_days > len(panel.dates):
        raise ValueError("review_days must fit inside the market panel")
    review_dates = panel.dates[-review_days:].tolist()
    review_set = set(review_dates)
    specs = {item.name: item for item in factor_specs() + fundamental_factor_specs(fundamentals)}
    orders: list[ReviewOrder] = []
    for selected in report.get("selected") or []:
        name = str(selected["strategy"])
        spec = replace(
            specs[name],
            top_n=int(selected["top_n"]),
            rebalance_days=int(selected["rebalance_days"]),
            minimum_market_breadth=float(selected["minimum_market_breadth"]),
        )
        _, _, audit = backtest(
            panel,
            spec,
            str(panel.dates[0]),
            str(panel.dates[-1]),
            slippage=float(LIMIT_SLIPPAGE),
        )
        orders.extend(
            ReviewOrder(
                strategy=name,
                signal_date=item.signal_date,
                execution_date=item.execution_date,
                symbol=item.symbol,
                side=item.side,
                quantity=item.quantity,
                daily_modeled_price=str(item.price),
            )
            for item in audit
            if item.execution_date in review_set
        )
    orders.sort(key=lambda item: (item.execution_date, item.symbol, item.strategy, item.side))
    return orders, review_dates


def _bar_to_dict(bar: Bar) -> dict:
    return {
        "symbol": bar.symbol,
        "trading_day": bar.trading_day.isoformat(),
        "timestamp": bar.timestamp.isoformat() if bar.timestamp else None,
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": bar.volume,
        "amount": str(bar.amount),
    }


def _bar_from_dict(value: dict) -> Bar:
    return Bar(
        symbol=str(value["symbol"]),
        trading_day=date.fromisoformat(value["trading_day"]),
        timestamp=datetime.fromisoformat(value["timestamp"]) if value.get("timestamp") else None,
        open=Decimal(value["open"]),
        high=Decimal(value["high"]),
        low=Decimal(value["low"]),
        close=Decimal(value["close"]),
        volume=int(value["volume"]),
        amount=Decimal(value["amount"]),
        source="tdx",
    )


def load_intraday_bars(
    client: TdxClient,
    symbols: Iterable[str],
    review_dates: list[str],
    cache_dir: Path,
    *,
    refresh: bool,
) -> dict[str, list[Bar]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    start = review_dates[0].replace("-", "")
    end = review_dates[-1].replace("-", "")
    result: dict[str, list[Bar]] = {}
    for symbol in sorted(set(symbols)):
        target = cache_dir / f"{symbol}.json"
        if target.exists() and not refresh:
            payload = json.loads(target.read_text(encoding="utf-8"))
            if payload.get("start") == start and payload.get("end") == end:
                result[symbol] = [_bar_from_dict(item) for item in payload["bars"]]
                continue
        bars = client.get_bars(symbol, period="5m", start=start, end=end, count_=-1)
        target.write_text(
            json.dumps(
                {"symbol": symbol, "period": "5m", "start": start, "end": end, "bars": [_bar_to_dict(item) for item in bars]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        result[symbol] = bars
    return result


def _valid_session_bar(bar: Bar) -> bool:
    if bar.timestamp is None or bar.volume < 0:
        return False
    value = bar.timestamp.timetz().replace(tzinfo=None)
    return time(9, 35) <= value <= time(11, 30) or time(13, 5) <= value <= time(15, 0)


def _percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "p90": None, "p95": None, "maximum": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "median": float(np.percentile(array, 50)),
        "p90": float(np.percentile(array, 90)),
        "p95": float(np.percentile(array, 95)),
        "maximum": float(np.max(array)),
    }


def _match_window(
    orders: list[ReviewOrder],
    bars_by_symbol: dict[str, list[Bar]],
    window_minutes: int,
) -> list[dict]:
    cutoff_bars = window_minutes // 5
    used: dict[tuple[str, str, str], int] = {}
    details: list[dict] = []
    for order in orders:
        day_bars = sorted(
            (
                bar for bar in bars_by_symbol.get(order.symbol, [])
                if bar.trading_day.isoformat() == order.execution_date
                and bar.timestamp is not None
                and time(9, 35) <= bar.timestamp.timetz().replace(tzinfo=None) <= time(10, 0)
            ),
            key=lambda item: item.timestamp,
        )[:cutoff_bars]
        remaining = order.quantity
        fills: list[tuple[int, Decimal]] = []
        touched = False
        had_capacity = False
        for bar in day_bars:
            key = (order.symbol, order.execution_date, bar.timestamp.isoformat())
            total_capacity = int(
                (Decimal(bar.volume) * PARTICIPATION_RATE / Decimal(100)).to_integral_value(rounding=ROUND_FLOOR)
            ) * 100
            available = max(0, total_capacity - used.get(key, 0))
            if available > 0:
                had_capacity = True
            if order.side == "BUY":
                can_fill = bar.low <= order.limit_price
                price = min(bar.open, order.limit_price) if can_fill else order.limit_price
            else:
                can_fill = bar.high >= order.limit_price
                price = max(bar.open, order.limit_price) if can_fill else order.limit_price
            if not can_fill:
                continue
            touched = True
            quantity = min(remaining, available)
            quantity = quantity // 100 * 100
            if quantity <= 0:
                continue
            fills.append((quantity, price))
            used[key] = used.get(key, 0) + quantity
            remaining -= quantity
            if remaining == 0:
                break
        filled = order.quantity - remaining
        fill_price = (
            sum(Decimal(quantity) * price for quantity, price in fills) / Decimal(filled)
            if filled else None
        )
        adverse_bps = None
        if fill_price is not None:
            adverse = (
                fill_price / order.reference_open - Decimal("1")
                if order.side == "BUY"
                else Decimal("1") - fill_price / order.reference_open
            )
            adverse_bps = float(adverse * Decimal(10_000))
        if not day_bars:
            reason = "missing_data"
        elif filled == order.quantity:
            reason = "filled"
        elif filled > 0:
            reason = "partial_volume"
        elif touched and not had_capacity:
            reason = "volume_insufficient"
        elif not touched:
            reason = "limit_not_touched"
        else:
            reason = "volume_insufficient"
        details.append(
            {
                **asdict(order),
                "reference_open": str(order.reference_open),
                "limit_price": str(order.limit_price),
                "filled_quantity": filled,
                "fill_price": str(fill_price) if fill_price is not None else None,
                "adverse_slippage_bps": adverse_bps,
                "result": reason,
            }
        )
    return details


def _coverage(symbols: set[str], review_dates: list[str], bars_by_symbol: dict[str, list[Bar]]) -> dict:
    expected = len(symbols) * len(review_dates) * EXPECTED_BARS_PER_DAY
    allowed_dates = set(review_dates)
    actual_keys = {
        (bar.symbol, bar.trading_day.isoformat(), bar.timestamp.isoformat())
        for symbol in symbols
        for bar in bars_by_symbol.get(symbol, [])
        if bar.trading_day.isoformat() in allowed_dates and _valid_session_bar(bar)
    }
    actual = len(actual_keys)
    return {
        "symbols": len(symbols),
        "trading_days": len(review_dates),
        "expected_bars": expected,
        "actual_bars": actual,
        "ratio": actual / expected if expected else 0.0,
    }


def _strategy_metrics(
    strategy: str,
    details: list[dict],
    coverage: dict,
) -> dict:
    rows = [item for item in details if item["strategy"] == strategy]
    planned_quantity = sum(item["quantity"] for item in rows)
    filled_quantity = sum(item["filled_quantity"] for item in rows)
    planned_amount = sum(float(Decimal(item["reference_open"]) * item["quantity"]) for item in rows)
    filled_amount = sum(float(Decimal(item["reference_open"]) * item["filled_quantity"]) for item in rows)
    by_side = {
        side: _percentiles(
            [float(item["adverse_slippage_bps"]) for item in rows if item["side"] == side and item["adverse_slippage_bps"] is not None]
        )
        for side in ("BUY", "SELL")
    }
    complete = sum(item["filled_quantity"] == item["quantity"] for item in rows)
    reasons: dict[str, int] = {}
    for item in rows:
        reasons[item["result"]] = reasons.get(item["result"], 0) + 1
    order_fill_rate = complete / len(rows) if rows else 0.0
    amount_fill_rate = filled_amount / planned_amount if planned_amount else 0.0
    evidence_by_side = {side: by_side[side]["p95"] is not None for side in ("BUY", "SELL")}
    passed = bool(
        rows
        and coverage["ratio"] >= 0.99
        and amount_fill_rate >= 0.95
        and order_fill_rate >= 0.90
        and all(evidence_by_side.values())
        and all(float(by_side[side]["p95"]) <= 20.0 for side in ("BUY", "SELL"))
    )
    return {
        "strategy": strategy,
        "planned_orders": len(rows),
        "complete_orders": complete,
        "partial_orders": sum(0 < item["filled_quantity"] < item["quantity"] for item in rows),
        "unfilled_orders": sum(item["filled_quantity"] == 0 for item in rows),
        "quantity_fill_rate": filled_quantity / planned_quantity if planned_quantity else 0.0,
        "amount_fill_rate": amount_fill_rate,
        "complete_order_rate": order_fill_rate,
        "slippage_bps": by_side,
        "direction_evidence": evidence_by_side,
        "reasons": reasons,
        "coverage": coverage,
        "passed": passed,
    }


def run_intraday_review(
    orders: list[ReviewOrder],
    review_dates: list[str],
    bars_by_symbol: dict[str, list[Bar]],
    strategy_names: list[str],
    *,
    report_path: Path,
    git_sha: str,
    generated_at: datetime | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(SHANGHAI)
    windows: dict[str, dict] = {}
    for minutes in (5, 15, 30):
        details = _match_window(orders, bars_by_symbol, minutes)
        metrics = []
        for strategy in strategy_names:
            symbols = {item.symbol for item in orders if item.strategy == strategy}
            metrics.append(_strategy_metrics(strategy, details, _coverage(symbols, review_dates, bars_by_symbol)))
        windows[str(minutes)] = {"strategies": metrics, "details": details if minutes == 30 else []}
    main_metrics = windows["30"]["strategies"]
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "git_sha": git_sha,
        "report_sha256": sha256_file(report_path),
        "data_start": review_dates[0],
        "data_end": review_dates[-1],
        "trading_days": len(review_dates),
        "period": "5m",
        "execution_window_minutes": 30,
        "participation_rate": float(PARTICIPATION_RATE),
        "limit_slippage_bps": 20,
        "thresholds": {"coverage": 0.99, "amount_fill_rate": 0.95, "complete_order_rate": 0.90, "p95_slippage_bps": 20},
        "planned_order_count": len(orders),
        "windows": windows,
        "passed_strategies": [item["strategy"] for item in main_metrics if item["passed"]],
        "failed_strategies": [item["strategy"] for item in main_metrics if not item["passed"]],
        "all_passed": bool(main_metrics) and all(item["passed"] for item in main_metrics),
    }


def write_intraday_report(result: dict, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 100 天 5 分钟成交复核",
        "",
        f"- 数据区间：{result['data_start']}～{result['data_end']}，{result['trading_days']} 个交易日。",
        f"- 计划订单：{result['planned_order_count']}；主窗口：开盘后 {result['execution_window_minutes']} 分钟。",
        f"- 参与率：{result['participation_rate']:.0%}；限价滑点：单边 {result['limit_slippage_bps']}BP。",
        f"- 总结论：{'通过' if result['all_passed'] else '不通过'}。",
        "",
        "## 主窗口结果",
        "",
        "| 策略 | 数据覆盖 | 订单 | 完整／部分／未成 | 金额成交率 | 完整订单率 | 买入 P95 | 卖出 P95 | 结论 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in result["windows"]["30"]["strategies"]:
        buy = item["slippage_bps"]["BUY"]["p95"]
        sell = item["slippage_bps"]["SELL"]["p95"]
        buy_text = f"{buy:.2f}BP" if buy is not None else "证据不足"
        sell_text = f"{sell:.2f}BP" if sell is not None else "证据不足"
        lines.append(
            f"| {item['strategy']} | {item['coverage']['ratio']:.2%} | {item['planned_orders']} | "
            f"{item['complete_orders']}／{item['partial_orders']}／{item['unfilled_orders']} | "
            f"{item['amount_fill_rate']:.2%} | {item['complete_order_rate']:.2%} | "
            f"{buy_text} | {sell_text} | {'通过' if item['passed'] else '不通过'} |"
        )
    lines.extend(["", "## 执行窗口对比", "", "| 窗口 | 策略 | 金额成交率 | 完整订单率 |", "| ---: | --- | ---: | ---: |"])
    for minutes in (5, 15, 30):
        for item in result["windows"][str(minutes)]["strategies"]:
            lines.append(f"| {minutes} 分钟 | {item['strategy']} | {item['amount_fill_rate']:.2%} | {item['complete_order_rate']:.2%} |")
    lines.extend(
        [
            "",
            "## 证据说明",
            "",
            f"- 输入报告 SHA256：`{result['report_sha256']}`。",
            f"- 代码 commit：`{result['git_sha']}`。",
            f"- 生成时间：{result['generated_at']}。",
            "- 缺失分钟线不推定成交；任一方向没有成交时，该方向标记为证据不足。",
        ]
    )
    lines.extend(["", "## 不可成交原因", ""])
    for item in result["windows"]["30"]["strategies"]:
        reasons = "、".join(f"{key}={value}" for key, value in sorted(item["reasons"].items())) or "无计划订单"
        lines.append(f"- `{item['strategy']}`：{reasons}。")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
