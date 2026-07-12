from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from astock.data.tushare import TushareProxyClient, _safe_float
from astock.research import TARGET_ANNUAL_RETURN, TARGET_MAX_DRAWDOWN, FactorSpec, MarketPanel, Performance, backtest, execution_audit_violations


PERIODS = {
    "research": ("2021-01-01", "2023-12-31"),
    "validation_2024": ("2024-01-01", "2024-12-31"),
    "validation_2025": ("2025-01-01", "2025-12-31"),
    "stress_2026": ("2026-01-01", "2026-12-31"),
}


@dataclass(frozen=True)
class TurnoverPanel:
    dates: np.ndarray
    symbols: np.ndarray
    rate: np.ndarray

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, dates=self.dates, symbols=self.symbols, rate=self.rate)

    @classmethod
    def load(cls, path: Path) -> "TurnoverPanel":
        with np.load(path, allow_pickle=False) as data:
            return cls(data["dates"], data["symbols"], data["rate"])


def build_turnover_panel(
    client: TushareProxyClient,
    market: MarketPanel,
    cache_path: Path,
    batch_size: int = 5,
) -> TurnoverPanel:
    symbols = market.symbols.tolist()
    requests = [
        {
            "ts_code": ",".join(symbols[offset : offset + batch_size]),
            "start_date": str(market.dates[0]).replace("-", ""),
            "end_date": str(market.dates[-1]).replace("-", ""),
        }
        for offset in range(0, len(symbols), batch_size)
    ]
    rows = client.query_many(
        "daily_basic",
        requests,
        "ts_code,trade_date,turnover_rate",
    )
    rates = np.full((len(market.dates), len(market.symbols)), np.nan, dtype=np.float32)
    date_index = {str(value).replace("-", ""): index for index, value in enumerate(market.dates)}
    symbol_index = {str(value): index for index, value in enumerate(market.symbols)}
    for row in rows:
        row_index = date_index.get(str(row.get("trade_date") or ""))
        column = symbol_index.get(str(row.get("ts_code") or ""))
        value = _safe_float(row.get("turnover_rate"))
        if row_index is None or column is None or not np.isfinite(value):
            continue
        rates[row_index, column] = min(max(value / 100.0, 0.0), 1.0)
    panel = TurnoverPanel(market.dates.copy(), market.symbols.copy(), rates)
    panel.save(cache_path)
    return panel


def capital_gains_overhang(
    close: np.ndarray,
    turnover_rate: np.ndarray,
    index: int,
    window: int,
) -> np.ndarray:
    if index < window - 1:
        return np.full(close.shape[1], np.nan, dtype=np.float64)
    prices = close[index - window + 1 : index + 1]
    turnover = turnover_rate[index - window + 1 : index + 1]
    reference_sum = np.zeros(close.shape[1], dtype=np.float64)
    weight_sum = np.zeros(close.shape[1], dtype=np.float64)
    survival = np.ones(close.shape[1], dtype=np.float64)
    for row in range(window - 1, -1, -1):
        valid = np.isfinite(prices[row]) & np.isfinite(turnover[row])
        rate = np.where(valid, np.clip(turnover[row], 0.0, 1.0), 0.0)
        weight = rate * survival
        reference_sum += np.where(valid, prices[row] * weight, 0.0)
        weight_sum += np.where(valid, weight, 0.0)
        survival *= 1.0 - rate
    with np.errstate(divide="ignore", invalid="ignore"):
        reference_price = reference_sum / weight_sum
        cgo = (close[index] - reference_price) / close[index]
    coverage = np.mean(np.isfinite(prices) & np.isfinite(turnover), axis=0)
    return np.where((weight_sum > 0.5) & (coverage >= 0.80), cgo, np.nan)


def cgo_spec(turnover: TurnoverPanel, window: int) -> FactorSpec:
    def scorer(panel: MarketPanel, index: int) -> np.ndarray:
        return capital_gains_overhang(panel.close, turnover.rate, index, window)

    return FactorSpec(
        name="capital_gains_overhang",
        family="behavioral_finance",
        description=f"Grinblatt-Han capital gains overhang with {window}-day reference-price window",
        min_history=max(120, window - 1),
        scorer=scorer,
    )


def _score(performance: Performance) -> float:
    return performance.calmar + 0.25 * performance.sharpe


def run_cgo_research(market: MarketPanel, turnover: TurnoverPanel) -> dict:
    if not np.array_equal(market.dates, turnover.dates) or not np.array_equal(market.symbols, turnover.symbols):
        raise ValueError("turnover panel is not aligned with market panel")
    grid: list[dict] = []
    candidates: list[tuple[float, FactorSpec, int]] = []
    for window in (126, 252):
        base = cgo_spec(turnover, window)
        for top_n in (5, 10, 20):
            for rebalance_days in (10, 20, 40):
                spec = replace(base, top_n=top_n, rebalance_days=rebalance_days, minimum_market_breadth=0.30)
                performance, _, audit = backtest(market, spec, *PERIODS["research"])
                if execution_audit_violations(audit):
                    raise RuntimeError("CGO causality violation")
                score = _score(performance)
                grid.append({
                    "window": window,
                    "top_n": top_n,
                    "rebalance_days": rebalance_days,
                    "score": score,
                    "performance": asdict(performance),
                })
                if performance.trade_count >= 30:
                    candidates.append((score, spec, window))
    if not candidates:
        raise RuntimeError("no CGO configuration met the minimum trade count")
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, selected, selected_window = candidates[0]
    selected_key = (selected_window, selected.top_n, selected.rebalance_days)
    grid_scores = {
        (item["window"], item["top_n"], item["rebalance_days"]): item["score"]
        for item in grid
    }
    value_positions = (
        {126: 0, 252: 1},
        {5: 0, 10: 1, 20: 2},
        {10: 0, 20: 1, 40: 2},
    )
    neighbor_scores = [
        score
        for key, score in grid_scores.items()
        if sum(left != right for left, right in zip(selected_key, key, strict=True)) == 1
        and sum(
            abs(mapping[left] - mapping[right])
            for mapping, left, right in zip(value_positions, selected_key, key, strict=True)
        ) == 1
    ]
    stability = {
        "research_score": grid_scores[selected_key],
        "neighbor_median_score": float(np.median(neighbor_scores)),
        "neighbor_score_std": float(np.std(neighbor_scores)),
        "positive_neighbor_ratio": float(np.mean(np.asarray(neighbor_scores) > 0)),
        "neighbor_count": len(neighbor_scores),
    }
    results: list[dict] = []
    causality_violations = 0
    for period, dates in PERIODS.items():
        performance, _, audit = backtest(market, selected, *dates)
        causality_violations += execution_audit_violations(audit)
        results.append({**asdict(performance), "period": period})
    sensitivity: list[dict] = []
    for basis_points in (10, 20, 30):
        for period in ("validation_2024", "validation_2025"):
            performance, _, _ = backtest(
                market,
                selected,
                *PERIODS[period],
                slippage=basis_points / 10_000,
            )
            sensitivity.append({
                "period": period,
                "slippage_bps": basis_points,
                "annual_return": performance.annual_return,
                "max_drawdown": performance.max_drawdown,
                "trade_count": performance.trade_count,
            })
    lookup = {item["period"]: item for item in results}
    validation_target_met = all(
        lookup[period]["annual_return"] >= TARGET_ANNUAL_RETURN
        and lookup[period]["max_drawdown"] <= TARGET_MAX_DRAWDOWN
        for period in ("validation_2024", "validation_2025")
    )
    stability_target_met = stability["research_score"] > 0 and stability["positive_neighbor_ratio"] >= 0.50
    return {
        "methodology": {
            "version": "V8-CGO",
            "formula": "CGO=(close-reference_price)/close; reference price uses turnover survival weights",
            "parameter_selection_period": "2021-2023",
            "validation_periods": ["2024", "2025"],
            "diagnostic_only_period": "2026",
            "signal_execution": "T close signal, T+1 open execution",
            "slippage": 0.001,
            "target_annual_return": TARGET_ANNUAL_RETURN,
            "target_max_drawdown": TARGET_MAX_DRAWDOWN,
            "turnover_coverage": float(np.mean(np.isfinite(turnover.rate))),
            "causality_violations": causality_violations,
            "selection_rule": "best research score, then require at least 50% positive adjacent configurations; 2024/2025 must both meet return and drawdown targets",
            "known_limitations": [
                "行情从 2021 年开始，252 日窗口在约 2022 年后才完整有效。",
                "当前股票列表不含历史退市股票，存在幸存者偏差。",
                "换手率来自 Tushare 第三方代理，行情价格来自 TDX，存在跨源口径风险。",
                "2026 仅作压力测试，禁止参与参数选择。",
            ],
        },
        "selected": {
            "window": selected_window,
            "top_n": selected.top_n,
            "rebalance_days": selected.rebalance_days,
            "minimum_market_breadth": selected.minimum_market_breadth,
            "stability": stability,
            "stability_target_met": stability_target_met,
            "validation_target_met": validation_target_met,
            "status": "research_observation" if stability_target_met and validation_target_met else "rejected",
        },
        "research_grid": grid,
        "results": results,
        "slippage_sensitivity": sensitivity,
    }


def write_cgo_report(result: dict, path: Path) -> None:
    lookup = {item["period"]: item for item in result["results"]}
    selected = result["selected"]
    first = lookup["validation_2024"]
    second = lookup["validation_2025"]
    if selected["status"] == "rejected":
        conclusion = (
            f"CGO 独立做多因子被拒绝：研究期年化 {lookup['research']['annual_return']:.2%}、最大回撤 "
            f"{lookup['research']['max_drawdown']:.2%}，2024／2025 年化分别为 {first['annual_return']:.2%}／"
            f"{second['annual_return']:.2%}；相邻参数正得分占比仅 {selected['stability']['positive_neighbor_ratio']:.0%}。"
        )
    else:
        conclusion = "CGO 通过研究稳定门和双验证目标，可保留为研究观察。"
    lines = [
        "# CGO 独立因子研究（V8）",
        "",
        "## 结论",
        "",
        conclusion,
        "",
        "## 冻结配置",
        "",
        f"- 参考成本窗口：{selected['window']} 个交易日。",
        f"- 持仓数：{selected['top_n']}；调仓周期：{selected['rebalance_days']} 个交易日。",
        "- 2021～2023 只用于参数研究；2024／2025 双验证；2026 只作压力测试。",
        "- 收盘生成信号，下一交易日开盘成交；基准单边滑点 10BP。",
        f"- 参数相邻正得分占比：{selected['stability']['positive_neighbor_ratio']:.0%}；状态：{selected['status']}。",
        "",
        "## 分段结果",
        "",
        "| 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 成交数 | 持仓覆盖 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    labels = {"research": "2021～2023", "validation_2024": "2024", "validation_2025": "2025", "stress_2026": "2026 压力"}
    for period in ("research", "validation_2024", "validation_2025", "stress_2026"):
        item = lookup[period]
        lines.append(
            f"| {labels[period]} | {item['annual_return']:.2%} | -{item['max_drawdown']:.2%} | "
            f"{item['sharpe']:.2f} | {item['calmar']:.2f} | {item['trade_count']} | {item['exposure_rate']:.1%} |"
        )
    lines.extend(["", "## 成本敏感性", "", "| 区间 | 单边滑点 | 年化 | 最大回撤 | 成交数 |", "|---|---:|---:|---:|---:|"])
    for item in result["slippage_sensitivity"]:
        lines.append(
            f"| {labels[item['period']]} | {item['slippage_bps']}BP | {item['annual_return']:.2%} | "
            f"-{item['max_drawdown']:.2%} | {item['trade_count']} |"
        )
    lines.extend(["", "## 限制", ""] + [f"- {item}" for item in result["methodology"]["known_limitations"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_cgo_json(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
