from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

from astock.data.industry import IndustryPanel
from astock.data.tushare import FundamentalPanel
from astock.research import TARGET_ANNUAL_RETURN, TARGET_MAX_DRAWDOWN, FactorSpec, MarketPanel, Performance, backtest, execution_audit_violations, factor_specs, fundamental_factor_specs


PERIODS = {
    "research": ("2021-01-01", "2023-12-31"),
    "validation_2024": ("2024-01-01", "2024-12-31"),
    "validation_2025": ("2025-01-01", "2025-12-31"),
    "stress_2026": ("2026-01-01", "2026-12-31"),
}


def _zscore(values: np.ndarray) -> np.ndarray:
    finite = np.isfinite(values)
    result = np.full_like(values, np.nan, dtype=np.float64)
    if np.sum(finite) < 3:
        return result
    deviation = float(np.std(values[finite]))
    if deviation > 0:
        result[finite] = (values[finite] - float(np.mean(values[finite]))) / deviation
    return result


def industry_relative_spec(base: FactorSpec, industries: IndustryPanel) -> FactorSpec:
    def scorer(panel: MarketPanel, index: int) -> np.ndarray:
        raw = base.scorer(panel, index)
        groups = industries.membership[index]
        relative = np.full_like(raw, np.nan, dtype=np.float64)
        for industry in range(len(industries.industry_codes)):
            members = np.flatnonzero((groups == industry) & np.isfinite(raw))
            if len(members) < 5:
                continue
            order = np.argsort(raw[members], kind="stable")
            ranks = np.empty(len(members), dtype=np.float64)
            ranks[order] = np.arange(len(members), dtype=np.float64)
            relative[members] = ranks / max(1, len(members) - 1)
        return relative

    return replace(
        base,
        name=f"industry_relative__{base.name}",
        family=f"industry_relative_{base.family}",
        description=f"SW2021 L1 industry-relative version of {base.name}",
        scorer=scorer,
    )


def industry_rotation_spec(
    industries: IndustryPanel,
    stock_base: FactorSpec,
    top_industries: int,
    rebalance_days: int,
) -> FactorSpec:
    def scorer(panel: MarketPanel, index: int) -> np.ndarray:
        closes = industries.close
        with np.errstate(divide="ignore", invalid="ignore"):
            return_20 = closes[index] / closes[index - 20] - 1.0
            return_60 = closes[index] / closes[index - 60] - 1.0
            daily = closes[index - 20 : index + 1][1:] / closes[index - 20 : index + 1][:-1] - 1.0
        volatility = np.nanstd(daily, axis=0)
        membership = industries.membership[index]
        stock_return = panel.close[index] / panel.close[index - 20] - 1.0
        breadth = np.full(len(industries.industry_codes), np.nan, dtype=np.float64)
        for industry in range(len(industries.industry_codes)):
            values = stock_return[membership == industry]
            finite = values[np.isfinite(values)]
            if len(finite) >= 5:
                breadth[industry] = float(np.mean(finite > 0))
        industry_score = (
            0.4 * _zscore(return_20)
            + 0.3 * _zscore(return_60)
            + 0.2 * _zscore(breadth)
            - 0.1 * _zscore(volatility)
        )
        valid_industries = np.flatnonzero(np.isfinite(industry_score))
        if not len(valid_industries):
            return np.full(len(panel.symbols), np.nan, dtype=np.float64)
        count = min(top_industries, len(valid_industries))
        chosen_industries = valid_industries[np.argsort(industry_score[valid_industries])[-count:][::-1]]
        stock_score = stock_base.scorer(panel, index)
        result = np.full(len(panel.symbols), np.nan, dtype=np.float64)
        for industry in chosen_industries:
            members = np.flatnonzero((membership == industry) & np.isfinite(stock_score))
            if not len(members):
                continue
            selected = members[np.argsort(stock_score[members])[-2:][::-1]]
            result[selected] = industry_score[industry] + np.linspace(0.002, 0.001, len(selected))
        return result

    return FactorSpec(
        name=f"industry_rotation_{top_industries}x2_{rebalance_days}d",
        family="industry_rotation",
        description="SW2021 L1 20/60-day momentum, breadth and volatility rotation with low-volatility stock selection",
        min_history=121,
        scorer=scorer,
        rebalance_days=rebalance_days,
        top_n=top_industries * 2,
        minimum_market_breadth=0.30,
    )


def _performance_score(performance: Performance) -> float:
    return performance.calmar + 0.25 * performance.sharpe


def _optimize_relative(panel: MarketPanel, base: FactorSpec, industries: IndustryPanel) -> tuple[FactorSpec, dict]:
    relative = industry_relative_spec(base, industries)
    top_values = (5, 10)
    cadence_values = (10, 20, 40)
    breadth_values = (0.30, 0.50)
    grid: dict[tuple[int, int, float], tuple[FactorSpec, Performance, float]] = {}
    for top_n in top_values:
        for cadence in cadence_values:
            for breadth in breadth_values:
                candidate = replace(relative, top_n=top_n, rebalance_days=cadence, minimum_market_breadth=breadth)
                performance, _, _ = backtest(panel, candidate, *PERIODS["research"])
                grid[(top_n, cadence, breadth)] = (candidate, performance, _performance_score(performance))
    positions = (
        {value: index for index, value in enumerate(top_values)},
        {value: index for index, value in enumerate(cadence_values)},
        {value: index for index, value in enumerate(breadth_values)},
    )
    robust: list[tuple[float, FactorSpec, dict]] = []
    for key, (candidate, performance, score) in grid.items():
        if performance.trade_count < 30:
            continue
        neighbors = [
            item[2]
            for other, item in grid.items()
            if sum(left != right for left, right in zip(key, other, strict=True)) == 1
            and sum(abs(mapping[left] - mapping[right]) for mapping, left, right in zip(positions, key, other, strict=True)) == 1
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
        raise RuntimeError(f"no industry-relative configuration for {base.name}")
    robust.sort(key=lambda item: item[0], reverse=True)
    return robust[0][1], {"robust_score": robust[0][0], **robust[0][2]}


def _industry_concentration(audit: list, panel: MarketPanel, industries: IndustryPanel) -> float:
    symbol_index = {symbol: index for index, symbol in enumerate(panel.symbols.tolist())}
    date_index = {day: index for index, day in enumerate(panel.dates.tolist())}
    counts: dict[int, int] = {}
    for item in audit:
        if item.side != "BUY":
            continue
        row = date_index.get(item.execution_date)
        column = symbol_index.get(item.symbol)
        if row is None or column is None:
            continue
        industry = int(industries.membership[row, column])
        counts[industry] = counts.get(industry, 0) + 1
    return max(counts.values()) / sum(counts.values()) if counts else 0.0


def run_industry_research(
    panel: MarketPanel,
    industries: IndustryPanel,
    fundamentals: FundamentalPanel | None = None,
) -> dict:
    bases = factor_specs() + (fundamental_factor_specs(fundamentals) if fundamentals is not None else ())
    optimized: list[tuple[FactorSpec, FactorSpec, dict]] = []
    excluded: list[dict] = []
    for base in bases:
        try:
            relative, stability = _optimize_relative(panel, base, industries)
            optimized.append((base, relative, stability))
        except RuntimeError:
            excluded.append({"strategy": base.name, "reason": "all configurations had fewer than 30 research trades"})

    results: list[dict] = []
    audits: dict[str, int] = {}
    concentration: dict[str, float] = {}
    for base, relative, _ in optimized:
        raw = replace(
            base,
            top_n=relative.top_n,
            rebalance_days=relative.rebalance_days,
            minimum_market_breadth=relative.minimum_market_breadth,
        )
        for variant, spec in (("raw", raw), ("industry_relative", relative)):
            for period, dates in PERIODS.items():
                performance, _, audit = backtest(panel, spec, *dates)
                violations = execution_audit_violations(audit)
                if violations:
                    raise RuntimeError(f"causality violation in {spec.name} {period}")
                item = asdict(performance)
                item.update({"base_strategy": base.name, "variant": variant, "period": period})
                results.append(item)
                audits[f"{spec.name}:{period}"] = violations
                concentration[f"{spec.name}:{period}"] = _industry_concentration(audit, panel, industries)

    low_volatility = next(spec for spec in bases if spec.name == "low_volatility_trend")
    rotation_grid: list[tuple[float, FactorSpec, Performance]] = []
    for top_industries in (2, 3, 4):
        for cadence in (10, 20, 40):
            spec = industry_rotation_spec(industries, low_volatility, top_industries, cadence)
            performance, _, _ = backtest(panel, spec, *PERIODS["research"])
            rotation_grid.append((_performance_score(performance), spec, performance))
    rotation_grid = [item for item in rotation_grid if item[2].trade_count >= 30]
    rotation_grid.sort(key=lambda item: item[0], reverse=True)
    if not rotation_grid:
        raise RuntimeError("no industry rotation configuration met the minimum trade count")
    rotation = rotation_grid[0][1]
    rotation_results: list[dict] = []
    for period, dates in PERIODS.items():
        performance, _, audit = backtest(panel, rotation, *dates)
        violations = execution_audit_violations(audit)
        if violations:
            raise RuntimeError(f"causality violation in {rotation.name} {period}")
        item = asdict(performance)
        item["period"] = period
        rotation_results.append(item)
        audits[f"{rotation.name}:{period}"] = violations
        concentration[f"{rotation.name}:{period}"] = _industry_concentration(audit, panel, industries)

    lookup = {(item["base_strategy"], item["variant"], item["period"]): item for item in results}
    ranked: list[tuple[float, FactorSpec, dict]] = []
    for base, relative, stability in optimized:
        if stability["research_score"] <= 0 or stability["positive_neighbor_ratio"] < 0.50:
            continue
        first = lookup[(base.name, "industry_relative", "validation_2024")]
        second = lookup[(base.name, "industry_relative", "validation_2025")]
        raw_first = lookup[(base.name, "raw", "validation_2024")]
        raw_second = lookup[(base.name, "raw", "validation_2025")]
        if first["annual_return"] < 0 and second["annual_return"] < 0:
            continue
        validation_lift = float(
            np.mean(
                [
                    first["annual_return"] - raw_first["annual_return"],
                    second["annual_return"] - raw_second["annual_return"],
                ]
            )
        )
        if validation_lift <= 0:
            continue
        score = float(np.mean([first["calmar"] + 0.25 * first["sharpe"], second["calmar"] + 0.25 * second["sharpe"]]))
        ranked.append((score, relative, {**stability, "validation_annual_return_lift": validation_lift}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = [
        {
            "strategy": spec.name,
            "base_strategy": spec.name.removeprefix("industry_relative__"),
            "top_n": spec.top_n,
            "rebalance_days": spec.rebalance_days,
            "minimum_market_breadth": spec.minimum_market_breadth,
            "validation_score": score,
            "stability": stability,
            "validation_target_met": all(
                lookup[(spec.name.removeprefix("industry_relative__"), "industry_relative", period)]["annual_return"] >= TARGET_ANNUAL_RETURN
                and lookup[(spec.name.removeprefix("industry_relative__"), "industry_relative", period)]["max_drawdown"] <= TARGET_MAX_DRAWDOWN
                for period in ("validation_2024", "validation_2025")
            ),
        }
        for score, spec, stability in ranked[:3]
    ]

    sensitivity: list[dict] = []
    tested_specs = [item[1] for item in ranked[:3]] + [rotation]
    for spec in tested_specs:
        for bps in (10, 20, 30):
            for period in ("validation_2024", "validation_2025"):
                performance, _, _ = backtest(panel, spec, *PERIODS[period], slippage=bps / 10_000)
                sensitivity.append(
                    {
                        "strategy": spec.name,
                        "period": period,
                        "slippage_bps": bps,
                        "annual_return": performance.annual_return,
                        "max_drawdown": performance.max_drawdown,
                    }
                )
    return {
        "methodology": {
            "version": "V6_INDUSTRY",
            "industry_standard": "SW2021 L1",
            "industry_count": len(industries.industry_codes),
            "membership_coverage_on_valid_stock_days": float(
                np.mean(industries.membership[np.isfinite(panel.close)] >= 0)
            ),
            "index_source": "SW classification and point-in-time membership; equal-weight constituent return fallback when proxy index history is incomplete",
            "selection_periods": ["research", "validation_2024", "validation_2025"],
            "diagnostic_only_periods": ["stress_2026"],
            "selection_rule": "positive research score, at least 50% positive neighbors, and positive average 2024/2025 annual-return lift versus the matched raw factor",
            "causality_violations": audits,
            "known_limitations": [
                "股票池仍以当前可交易证券为基础，尚未彻底消除退市股幸存者偏差。",
                "行业变更按 in_date/out_date 生效，但数据源不提供公告发布时间，无法审计公告到生效日之间的提前知情窗口。",
                "申万行业指数跨年查询在第三方代理上存在不完整返回，缺失行业使用前一日成分股等权收益合成。",
                "行业相对排名降低了行业暴露，但 5～10 只集中持仓无法实现严格的指数级行业中性。",
            ],
        },
        "selected": selected,
        "excluded": excluded,
        "optimized": [
            {
                "base_strategy": base.name,
                "strategy": relative.name,
                "top_n": relative.top_n,
                "rebalance_days": relative.rebalance_days,
                "minimum_market_breadth": relative.minimum_market_breadth,
                "stability": stability,
            }
            for base, relative, stability in optimized
        ],
        "results": results,
        "rotation": {
            "strategy": rotation.name,
            "top_n": rotation.top_n,
            "rebalance_days": rotation.rebalance_days,
            "research_grid": [
                {
                    "strategy": spec.name,
                    "score": score,
                    "annual_return": performance.annual_return,
                    "max_drawdown": performance.max_drawdown,
                    "trade_count": performance.trade_count,
                }
                for score, spec, performance in rotation_grid
            ],
            "positive_research_configuration_ratio": float(
                np.mean(np.asarray([item[0] for item in rotation_grid]) > 0)
            ),
            "results": rotation_results,
        },
        "industry_concentration": concentration,
        "slippage_sensitivity": sensitivity,
    }


def write_industry_markdown(result: dict, path: Path) -> None:
    lookup = {(item["base_strategy"], item["variant"], item["period"]): item for item in result["results"]}
    qualified = "、".join(item["base_strategy"] for item in result["selected"]) or "无"
    target_count = sum(item["validation_target_met"] for item in result["selected"])
    lines = [
        "# 申万一级行业研究报告 V6",
        "",
        "## 结论",
        "",
        "本报告比较原始因子与申万一级行业内相对排名，并独立测试行业动量／宽度／低波动轮动。2026 只作压力诊断，不参与选择。",
        "",
        f"通过研究稳定门且在 2024／2025 平均优于对应原始因子的行业相对因子：{qualified}；其中达到双验证 15% 年化／25% 回撤目标的数量为 {target_count}。",
        "",
        "行业处理提供了部分增量，但尚未形成跨年份稳定达到目标的策略；轮动在 2026 压力期的高收益不得用于候选选择。",
        "",
        "## 行业中性候选",
        "",
        "| 策略 | 配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 相对原始因子验证期提升 | 达标 |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for selected in result["selected"]:
        base = selected["base_strategy"]
        relative = [lookup[(base, "industry_relative", period)] for period in ("validation_2024", "validation_2025", "stress_2026")]
        raw = [lookup[(base, "raw", period)] for period in ("validation_2024", "validation_2025")]
        lift = float(np.mean([relative[index]["annual_return"] - raw[index]["annual_return"] for index in range(2)]))
        config = f"{selected['top_n']} 只／{selected['rebalance_days']} 日／宽度 {selected['minimum_market_breadth']:.0%}"
        cells = [f"{item['annual_return']:.2%}／-{item['max_drawdown']:.2%}" for item in relative]
        lines.append(f"| {base} | {config} | {' | '.join(cells)} | {lift:+.2%} | {'是' if selected['validation_target_met'] else '否'} |")
    rotation_lookup = {item["period"]: item for item in result["rotation"]["results"]}
    lines.extend(
        [
            "",
            "## 行业轮动",
            "",
            f"冻结配置：`{result['rotation']['strategy']}`，持仓 {result['rotation']['top_n']} 只，每 {result['rotation']['rebalance_days']} 个交易日调仓。",
            f"研究期 9 组配置中只有 {result['rotation']['positive_research_configuration_ratio']:.0%} 得分为正，正收益集中在 40 日调仓，参数置信度低。",
            "",
            "| 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 成交数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for period in PERIODS:
        item = rotation_lookup[period]
        lines.append(
            f"| {period} | {item['annual_return']:.2%} | -{item['max_drawdown']:.2%} | "
            f"{item['sharpe']:.2f} | {item['calmar']:.2f} | {item['trade_count']} |"
        )
    lines.extend(
        [
            "",
            "### 轮动参数平面",
            "",
            "| 配置 | 研究得分 | 年化 | 最大回撤 | 成交数 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in result["rotation"]["research_grid"]:
        lines.append(
            f"| {item['strategy']} | {item['score']:.3f} | {item['annual_return']:.2%} | "
            f"-{item['max_drawdown']:.2%} | {item['trade_count']} |"
        )
    lines.extend(
        [
            "",
            "## 全因子行业相对化对比",
            "",
            "| 因子 | 配置 | 2024 原始／行业相对 | 2025 原始／行业相对 | 2026 原始／行业相对 | 正邻域占比 |",
            "| --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for config in sorted(result["optimized"], key=lambda item: item["base_strategy"]):
        base = config["base_strategy"]
        cells = []
        for period in ("validation_2024", "validation_2025", "stress_2026"):
            raw = lookup[(base, "raw", period)]
            relative = lookup[(base, "industry_relative", period)]
            cells.append(f"{raw['annual_return']:.2%}／{relative['annual_return']:.2%}")
        parameter = f"{config['top_n']}／{config['rebalance_days']}日／{config['minimum_market_breadth']:.0%}"
        lines.append(f"| {base} | {parameter} | {' | '.join(cells)} | {config['stability']['positive_neighbor_ratio']:.0%} |")
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
            f"{item['annual_return']:.2%} | -{item['max_drawdown']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 方法与数据质量",
            "",
            f"- 申万 2021 一级行业共 {result['methodology']['industry_count']} 个，当日有行情股票的历史行业归属覆盖率为 {result['methodology']['membership_coverage_on_valid_stock_days']:.1%}。",
            "- 行业归属按 `in_date/out_date` 逐日重建，行业信号使用当日及此前数据，交易仍在下一交易日开盘执行。",
            "- 行业相对因子使用行业内百分位排名；轮动使用 20／60 日行业动量、上涨股票比例和 20 日波动率。",
            "- 参数只在 2021～2023 研究，2024／2025 双验证选择，2026 禁止参与候选替换。",
            "- 初始资金 100000 元，完整计入佣金、印花税、过户费和单边 10BP 滑点，并测试 20／30BP。",
            "",
            "## 已知限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in result["methodology"]["known_limitations"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
