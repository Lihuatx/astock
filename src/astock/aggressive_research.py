from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from astock.data.tushare import FundamentalPanel
from astock.research import FactorSpec, MarketPanel, Performance, backtest, execution_audit_violations, factor_specs, fundamental_factor_specs


AGGRESSIVE_CASH = 30_000.0
MAX_POSITION_WEIGHT = 0.25
INVESTED_FRACTION = 0.90
BASE_SLIPPAGE = 0.002


def _run(panel: MarketPanel, spec: FactorSpec, start: str, end: str, slippage: float = BASE_SLIPPAGE):
    return backtest(
        panel,
        spec,
        start,
        end,
        initial_cash=AGGRESSIVE_CASH,
        slippage=slippage,
        max_position_weight=MAX_POSITION_WEIGHT,
        invested_fraction=INVESTED_FRACTION,
    )


def _monthly_statistics(dates: np.ndarray, curve: list[float], start: str, end: str) -> dict:
    period_dates = dates[(dates >= start) & (dates <= end)]
    values = np.asarray(curve, dtype=np.float64)
    months = np.asarray([str(item)[:7] for item in period_dates])
    returns: dict[str, float] = {}
    for month in np.unique(months):
        indices = np.flatnonzero(months == month)
        first = int(indices[0])
        base = values[first - 1] if first > 0 else values[first]
        returns[str(month)] = float(values[int(indices[-1])] / base - 1.0)
    monthly = np.asarray(list(returns.values()), dtype=np.float64)
    return {
        "returns": returns,
        "month_count": len(returns),
        "positive_month_ratio": float(np.mean(monthly > 0)) if len(monthly) else 0.0,
        "months_at_or_above_10pct": int(np.sum(monthly >= 0.10)),
        "best_month": float(np.max(monthly)) if len(monthly) else 0.0,
        "worst_month": float(np.min(monthly)) if len(monthly) else 0.0,
    }


def run_aggressive_research(panel: MarketPanel, fundamentals: FundamentalPanel | None = None) -> dict:
    periods = {
        "research": ("2021-01-01", "2023-12-31"),
        "validation_2024": ("2024-01-01", "2024-12-31"),
        "validation_2025": ("2025-01-01", "2025-12-31"),
        "stress_2026": ("2026-01-01", "2026-12-31"),
    }
    recent_start = str(panel.dates[max(0, len(panel.dates) - 363)])
    periods["recent_18m"] = (recent_start, str(panel.dates[-1]))
    specs = factor_specs() + (fundamental_factor_specs(fundamentals) if fundamentals is not None else ())
    optimized: list[FactorSpec] = []
    stability: dict[str, dict] = {}
    grids = ((3, 5), (2, 5, 10), (0.30, 0.40, 0.50))

    for base in specs:
        grid: dict[tuple[int, int, float], tuple[FactorSpec, Performance, float]] = {}
        for top_n in grids[0]:
            for rebalance_days in grids[1]:
                for breadth in grids[2]:
                    candidate = replace(
                        base,
                        top_n=top_n,
                        rebalance_days=rebalance_days,
                        minimum_market_breadth=breadth,
                    )
                    performance, _, _ = _run(panel, candidate, *periods["research"])
                    score = performance.calmar + 0.25 * performance.sharpe
                    grid[(top_n, rebalance_days, breadth)] = (candidate, performance, score)

        value_positions = (
            {value: index for index, value in enumerate(grids[0])},
            {value: index for index, value in enumerate(grids[1])},
            {value: index for index, value in enumerate(grids[2])},
        )
        robust: list[tuple[float, FactorSpec, dict]] = []
        for key, (candidate, performance, score) in grid.items():
            if performance.trade_count < 60:
                continue
            neighbors = [
                item[2]
                for other, item in grid.items()
                if sum(left != right for left, right in zip(key, other, strict=True)) == 1
                and sum(
                    abs(mapping[left] - mapping[right])
                    for mapping, left, right in zip(value_positions, key, other, strict=True)
                )
                == 1
            ]
            median = float(np.median(neighbors)) if neighbors else score
            details = {
                "research_score": score,
                "neighbor_median_score": median,
                "neighbor_score_std": float(np.std(neighbors)) if neighbors else 0.0,
                "positive_neighbor_ratio": float(np.mean(np.asarray(neighbors) > 0)) if neighbors else 0.0,
                "neighbor_count": len(neighbors),
            }
            robust.append((score + 0.25 * median, candidate, details))
        if not robust:
            continue
        robust.sort(key=lambda item: item[0], reverse=True)
        optimized.append(robust[0][1])
        stability[base.name] = {"robust_score": robust[0][0], **robust[0][2]}

    results: list[dict] = []
    curves: dict[tuple[str, str], np.ndarray] = {}
    monthly: dict[str, dict] = {}
    audits: dict[str, int] = {}
    for spec in optimized:
        for period, (start, end) in periods.items():
            performance, curve, audit = _run(panel, spec, start, end)
            violations = execution_audit_violations(audit)
            if violations:
                raise RuntimeError(f"causality violation in {spec.name} {period}")
            item = asdict(performance)
            item["period"] = period
            results.append(item)
            curves[(spec.name, period)] = np.asarray(curve, dtype=np.float64)
            audits[f"{spec.name}:{period}"] = violations
            if period == "recent_18m":
                monthly[spec.name] = _monthly_statistics(panel.dates, curve, start, end)

    lookup = {(item["strategy"], item["period"]): item for item in results}
    ranked: list[tuple[float, FactorSpec]] = []
    for spec in optimized:
        stable = stability[spec.name]
        if stable["research_score"] <= 0 or stable["positive_neighbor_ratio"] < 0.50:
            continue
        first = lookup[(spec.name, "validation_2024")]
        second = lookup[(spec.name, "validation_2025")]
        if first["annual_return"] < 0 and second["annual_return"] < 0:
            continue
        score = np.mean(
            [
                first["calmar"] + 0.25 * first["sharpe"],
                second["calmar"] + 0.25 * second["sharpe"],
            ]
        ) - 0.25 * max(first["max_drawdown"], second["max_drawdown"])
        ranked.append((float(score), spec))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected_specs = [item[1] for item in ranked[:3]]

    sensitivity: list[dict] = []
    for spec in selected_specs:
        for bps in (10, 20, 30):
            for period in ("validation_2024", "validation_2025", "recent_18m"):
                performance, _, _ = _run(panel, spec, *periods[period], slippage=bps / 10_000)
                sensitivity.append(
                    {
                        "strategy": spec.name,
                        "period": period,
                        "slippage_bps": bps,
                        "annual_return": performance.annual_return,
                        "max_drawdown": performance.max_drawdown,
                    }
                )

    selected = [
        {
            "strategy": spec.name,
            "family": spec.family,
            "top_n": spec.top_n,
            "rebalance_days": spec.rebalance_days,
            "minimum_market_breadth": spec.minimum_market_breadth,
            "stability": stability[spec.name],
            "recent_monthly": monthly[spec.name],
        }
        for spec in selected_specs
    ]
    return {
        "methodology": {
            "version": "V5_AGGRESSIVE",
            "factor_count": len(specs),
            "optimized_factor_count": len(optimized),
            "configuration_count": len(specs) * 18,
            "initial_cash": AGGRESSIVE_CASH,
            "max_position_weight": MAX_POSITION_WEIGHT,
            "target_annual_return_range": [0.25, 0.40],
            "target_max_drawdown": 0.25,
            "monthly_10pct_is_optimization_target": False,
            "parameter_grid": {"top_n": list(grids[0]), "rebalance_days": list(grids[1]), "minimum_market_breadth": list(grids[2])},
            "selection_periods": ["research", "validation_2024", "validation_2025"],
            "diagnostic_only_periods": ["stress_2026", "recent_18m"],
            "slippage": BASE_SLIPPAGE,
            "causality_violations": audits,
            "known_limitations": [
                "当前证券列表不含历史退市股票，存在幸存者偏差。",
                "缺少历史 ST 状态，无法精确重建 5% 涨跌停限制。",
                "日线回测不能复原盘中冲击成本和排队成交，结果必须经 5 分钟数据复核。",
                "2026 和最近 18 个月仅作诊断，不参与策略及参数选择。",
                "估值数据仅覆盖原 V4 信号日，短周期基本面价值策略可能因数据稀疏而低暴露。",
            ],
        },
        "selected": selected,
        "optimized": [
            {
                "strategy": spec.name,
                "family": spec.family,
                "top_n": spec.top_n,
                "rebalance_days": spec.rebalance_days,
                "minimum_market_breadth": spec.minimum_market_breadth,
                "stability": stability[spec.name],
            }
            for spec in optimized
        ],
        "results": results,
        "monthly": monthly,
        "slippage_sensitivity": sensitivity,
    }


def write_aggressive_markdown(result: dict, path: Path) -> None:
    lookup = {(item["strategy"], item["period"]): item for item in result["results"]}
    recent_ranked = sorted(
        result["optimized"],
        key=lambda item: lookup[(item["strategy"], "recent_18m")]["annual_return"],
        reverse=True,
    )
    lines = [
        "# 激进策略研究报告 V5",
        "",
        "## 结论",
        "",
        "本报告使用 30000 元隔离实验资金。月收益 10% 只统计命中次数，不参与任何参数优化。",
        "",
        "**结论：没有策略同时通过长历史稳定门、最近 18 个月有效交易和激进收益观察线，因此本轮不新增模拟盘候选。**",
        "",
        "`fundamental_value` 是历史规则唯一幸存者，但最近 18 个月因短周期估值数据稀疏而没有交易，不能视为有效的近期回测。`fundamental_quality_growth` 最近 18 个月表现最好，但研究期亏损且正邻域占比为 0%，只能作为被稳定门拒绝的诊断项。",
        "",
        "| 策略 | 配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 最近 18 月年化／回撤 | 10% 月份 |",
        "| --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for selected in result["selected"]:
        name = selected["strategy"]
        config = f"{selected['top_n']} 只／{selected['rebalance_days']} 日／宽度 {selected['minimum_market_breadth']:.0%}"
        values = [lookup[(name, period)] for period in ("validation_2024", "validation_2025", "stress_2026", "recent_18m")]
        cells = [f"{item['annual_return']:.2%}／-{item['max_drawdown']:.2%}" for item in values]
        lines.append(f"| {name} | {config} | {' | '.join(cells)} | {selected['recent_monthly']['months_at_or_above_10pct']} |")
    lines.extend(
        [
            "",
            "## 近期高收益诊断项（未入选）",
            "",
            "| 策略 | 研究期年化／回撤 | 研究得分 | 正邻域占比 | 最近 18 月年化／回撤 | 10% 月份 | 判定 |",
            "| --- | --- | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for item in recent_ranked[:3]:
        name = item["strategy"]
        research = lookup[(name, "research")]
        recent = lookup[(name, "recent_18m")]
        stable = item["stability"]
        passed = stable["research_score"] > 0 and stable["positive_neighbor_ratio"] >= 0.50
        lines.append(
            f"| {name} | {research['annual_return']:.2%}／-{research['max_drawdown']:.2%} | "
            f"{stable['research_score']:.3f} | {stable['positive_neighbor_ratio']:.0%} | "
            f"{recent['annual_return']:.2%}／-{recent['max_drawdown']:.2%} | "
            f"{result['monthly'][name]['months_at_or_above_10pct']} | {'通过稳定门' if passed else '拒绝'} |"
        )
    lines.extend(
        [
            "",
            "## 方法",
            "",
            "- 2021～2023 研究参数，2024／2025 双验证选择；2026 与最近 18 个月仅作诊断。",
            "- 参数网格为 3／5 只持仓、2／5／10 日调仓、30%／40%／50% 市场宽度。",
            "- 单票不超过 25%，不使用杠杆；T 日收盘信号、T＋1 开盘成交。",
            "- 基准使用单边 20BP 滑点，并另测 10／20／30BP。",
            "- 研究期至少 60 笔成交，并要求研究得分为正、相邻参数正收益比例不低于 50%。",
            "",
            "## 全部冻结因子",
            "",
            "| 因子 | 配置 | 2024 年化 | 2025 年化 | 2026 压力年化 | 最近 18 月年化 | 最近回撤 | 最好月 | 最差月 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    selected_names = {item["strategy"] for item in result["selected"]}
    for item in sorted(result["optimized"], key=lambda value: value["strategy"]):
        name = item["strategy"]
        display = f"**{name}**" if name in selected_names else name
        config = f"{item['top_n']}／{item['rebalance_days']}日／{item['minimum_market_breadth']:.0%}"
        recent = result["monthly"][name]
        lines.append(
            f"| {display} | {config} | {lookup[(name, 'validation_2024')]['annual_return']:.2%} | "
            f"{lookup[(name, 'validation_2025')]['annual_return']:.2%} | {lookup[(name, 'stress_2026')]['annual_return']:.2%} | "
            f"{lookup[(name, 'recent_18m')]['annual_return']:.2%} | -{lookup[(name, 'recent_18m')]['max_drawdown']:.2%} | "
            f"{recent['best_month']:.2%} | {recent['worst_month']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 参数稳定性",
            "",
            "| 因子 | 研究得分 | 邻域中位数 | 邻域标准差 | 正邻域占比 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in sorted(result["optimized"], key=lambda value: value["strategy"]):
        stable = item["stability"]
        lines.append(
            f"| {item['strategy']} | {stable['research_score']:.3f} | {stable['neighbor_median_score']:.3f} | "
            f"{stable['neighbor_score_std']:.3f} | {stable['positive_neighbor_ratio']:.0%} |"
        )
    lines.extend(
        [
            "",
            "## 历史幸存者滑点敏感性",
            "",
            "| 策略 | 区间 | 单边滑点 | 年化 | 最大回撤 |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for item in result["slippage_sensitivity"]:
        lines.append(
            f"| {item['strategy']} | {item['period']} | {item['slippage_bps']}BP | "
            f"{item['annual_return']:.2%} | -{item['max_drawdown']:.2%} |"
        )
    lines.extend(["", "## 已知限制", ""])
    lines.extend(f"- {item}" for item in result["methodology"]["known_limitations"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
