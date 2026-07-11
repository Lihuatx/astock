# 三策略研究报告 V2

> 本报告已被 `STRATEGY_RESEARCH_V3.md` 取代，仅保留为家族硬去重阶段的历史记录。

## 结论

V2 共评估 15 个因子、405 组研究期参数配置。最终三个策略仅用于前向模拟；2026 是压力测试，不是未观察样本。

| 策略 | 家族 | 冻结配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 达标 |
| --- | --- | --- | --- | --- | --- | --- |
| low_volatility_trend | volatility | 20 只／40 日／宽度 30% | 2.79%／4.53% | 5.18%／4.43% | -8.23%／8.44% | 否 |
| short_term_reversal | reversal | 10 只／20 日／宽度 40% | 11.51%／16.12% | 12.56%／18.31% | -26.23%／19.22% | 否 |
| volume_dry_up | volume | 20 只／40 日／宽度 40% | -8.56%／10.30% | 16.54%／10.47% | -19.97%／14.27% | 否 |

## 方法

- 2021～2023：参数研究；2024、2025：双验证；2026：只作压力测试。
- 参数选择同时考虑研究得分和相邻参数中位数，研究期成交少于 30 笔的配置不得入选。
- 最终排名要求两个验证期不能同时亏损，并优先选择不同策略家族。
- T 日收盘生成信号，T＋1 开盘后成交；未来函数审计违规数为 0。
- 初始资金 100000 元，计入佣金、印花税、过户费、10BP 单边滑点及一字板不可成交。

## 全部冻结因子表现

| 因子 | 家族 | 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | 成本 | 成交数 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| accelerating_momentum | multi_cycle | research | 2.04% | 30.56% | 0.20 | 0.07 | 9.0 | 587 | 70 |
| accelerating_momentum | multi_cycle | validation_2024 | -22.30% | 35.18% | -1.16 | -0.63 | 4.0 | 240 | 31 |
| accelerating_momentum | multi_cycle | validation_2025 | -20.17% | 40.41% | -0.60 | -0.50 | 11.9 | 797 | 101 |
| accelerating_momentum | multi_cycle | stress_2026 | -30.53% | 18.76% | -1.98 | -1.63 | 2.4 | 158 | 20 |
| multi_timeframe_momentum | multi_cycle | research | 5.36% | 30.75% | 0.36 | 0.17 | 8.4 | 548 | 64 |
| multi_timeframe_momentum | multi_cycle | validation_2024 | -19.84% | 40.57% | -0.81 | -0.49 | 4.0 | 222 | 27 |
| multi_timeframe_momentum | multi_cycle | validation_2025 | -36.35% | 47.96% | -1.44 | -0.76 | 9.4 | 689 | 93 |
| multi_timeframe_momentum | multi_cycle | stress_2026 | -37.81% | 22.57% | -2.30 | -1.68 | 2.1 | 140 | 18 |
| bollinger_reversion | reversal | research | 4.53% | 19.51% | 0.35 | 0.23 | 12.7 | 791 | 95 |
| bollinger_reversion | reversal | validation_2024 | -9.25% | 11.99% | -1.10 | -0.77 | 3.3 | 192 | 25 |
| bollinger_reversion | reversal | validation_2025 | 20.62% | 9.82% | 1.44 | 2.10 | 8.7 | 478 | 54 |
| bollinger_reversion | reversal | stress_2026 | 5.84% | 12.17% | 0.46 | 0.48 | 3.1 | 181 | 20 |
| rsi_oversold_reversal | reversal | research | -1.93% | 20.99% | -0.05 | -0.09 | 52.3 | 3249 | 381 |
| rsi_oversold_reversal | reversal | validation_2024 | -23.47% | 27.90% | -1.29 | -0.84 | 12.9 | 882 | 113 |
| rsi_oversold_reversal | reversal | validation_2025 | 3.44% | 14.02% | 0.30 | 0.25 | 32.2 | 1925 | 221 |
| rsi_oversold_reversal | reversal | stress_2026 | -15.51% | 13.78% | -1.00 | -1.12 | 11.0 | 674 | 78 |
| **short_term_reversal** | reversal | research | 0.24% | 14.46% | 0.09 | 0.02 | 17.0 | 1423 | 196 |
| **short_term_reversal** | reversal | validation_2024 | 11.51% | 16.12% | 0.70 | 0.71 | 8.6 | 645 | 89 |
| **short_term_reversal** | reversal | validation_2025 | 12.56% | 18.31% | 0.62 | 0.69 | 20.3 | 1627 | 224 |
| **short_term_reversal** | reversal | stress_2026 | -26.23% | 19.22% | -1.84 | -1.36 | 4.5 | 403 | 58 |
| breakout_120 | trend | research | -1.84% | 16.96% | -0.04 | -0.11 | 4.8 | 305 | 36 |
| breakout_120 | trend | validation_2024 | -3.47% | 6.63% | -0.46 | -0.52 | 1.2 | 57 | 9 |
| breakout_120 | trend | validation_2025 | 5.15% | 21.81% | 0.32 | 0.24 | 5.8 | 341 | 41 |
| breakout_120 | trend | stress_2026 | -16.28% | 16.17% | -0.96 | -1.01 | 1.0 | 65 | 8 |
| momentum_120_ex5 | trend | research | 3.25% | 17.94% | 0.29 | 0.18 | 7.4 | 477 | 56 |
| momentum_120_ex5 | trend | validation_2024 | -6.81% | 30.90% | -0.22 | -0.22 | 2.8 | 151 | 19 |
| momentum_120_ex5 | trend | validation_2025 | -20.34% | 28.89% | -0.98 | -0.70 | 7.9 | 531 | 68 |
| momentum_120_ex5 | trend | stress_2026 | -14.87% | 17.08% | -0.83 | -0.87 | 1.9 | 128 | 16 |
| momentum_20_60 | trend | research | 16.10% | 23.40% | 0.87 | 0.69 | 9.6 | 592 | 64 |
| momentum_20_60 | trend | validation_2024 | -14.48% | 42.29% | -0.47 | -0.34 | 4.4 | 244 | 29 |
| momentum_20_60 | trend | validation_2025 | -29.14% | 48.84% | -0.94 | -0.60 | 9.1 | 663 | 89 |
| momentum_20_60 | trend | stress_2026 | -26.22% | 17.24% | -1.25 | -1.52 | 2.5 | 161 | 20 |
| risk_adjusted_momentum | trend | research | 1.10% | 8.91% | 0.16 | 0.12 | 7.1 | 1174 | 198 |
| risk_adjusted_momentum | trend | validation_2024 | -10.42% | 17.61% | -0.79 | -0.59 | 3.4 | 543 | 94 |
| risk_adjusted_momentum | trend | validation_2025 | -0.52% | 13.92% | 0.04 | -0.04 | 7.8 | 1260 | 214 |
| risk_adjusted_momentum | trend | stress_2026 | -10.49% | 7.96% | -1.84 | -1.32 | 1.0 | 176 | 30 |
| **low_volatility_trend** | volatility | research | 6.28% | 11.65% | 0.63 | 0.54 | 15.0 | 2001 | 326 |
| **low_volatility_trend** | volatility | validation_2024 | 2.79% | 4.53% | 0.49 | 0.62 | 3.2 | 458 | 79 |
| **low_volatility_trend** | volatility | validation_2025 | 5.18% | 4.43% | 0.67 | 1.17 | 6.2 | 905 | 152 |
| **low_volatility_trend** | volatility | stress_2026 | -8.23% | 8.44% | -0.79 | -0.98 | 2.7 | 420 | 70 |
| upside_downside_volatility | volatility | research | 0.37% | 12.35% | 0.09 | 0.03 | 4.9 | 309 | 36 |
| upside_downside_volatility | volatility | validation_2024 | 2.35% | 11.30% | 0.26 | 0.21 | 2.2 | 116 | 15 |
| upside_downside_volatility | volatility | validation_2025 | 15.21% | 14.79% | 0.87 | 1.03 | 7.6 | 412 | 45 |
| upside_downside_volatility | volatility | stress_2026 | 11.89% | 7.23% | 0.85 | 1.65 | 1.2 | 74 | 8 |
| volatility_contraction | volatility | research | -0.17% | 15.91% | 0.04 | -0.01 | 7.0 | 418 | 51 |
| volatility_contraction | volatility | validation_2024 | -1.96% | 10.63% | -0.09 | -0.18 | 3.4 | 196 | 25 |
| volatility_contraction | volatility | validation_2025 | 9.99% | 7.63% | 0.69 | 1.31 | 8.6 | 480 | 55 |
| volatility_contraction | volatility | stress_2026 | -36.16% | 21.97% | -2.69 | -1.65 | 2.6 | 162 | 20 |
| volume_confirmed_breakout | volume | research | -10.24% | 23.20% | -0.95 | -0.44 | 5.2 | 920 | 158 |
| volume_confirmed_breakout | volume | validation_2024 | -1.33% | 12.75% | -0.07 | -0.10 | 2.3 | 319 | 56 |
| volume_confirmed_breakout | volume | validation_2025 | -6.50% | 18.51% | -0.27 | -0.35 | 6.3 | 1035 | 178 |
| volume_confirmed_breakout | volume | stress_2026 | 2.17% | 12.19% | 0.23 | 0.18 | 1.6 | 242 | 40 |
| **volume_dry_up** | volume | research | 0.92% | 9.66% | 0.16 | 0.10 | 8.3 | 1236 | 208 |
| **volume_dry_up** | volume | validation_2024 | -8.56% | 10.30% | -1.37 | -0.83 | 2.5 | 351 | 61 |
| **volume_dry_up** | volume | validation_2025 | 16.54% | 10.47% | 1.18 | 1.58 | 9.8 | 1297 | 212 |
| **volume_dry_up** | volume | stress_2026 | -19.97% | 14.27% | -1.27 | -1.40 | 3.0 | 467 | 78 |
| volume_price_strength | volume | research | -4.58% | 35.84% | -0.19 | -0.13 | 8.9 | 900 | 134 |
| volume_price_strength | volume | validation_2024 | -15.24% | 37.50% | -0.57 | -0.41 | 5.2 | 416 | 60 |
| volume_price_strength | volume | validation_2025 | 6.81% | 27.24% | 0.37 | 0.25 | 14.0 | 1312 | 194 |
| volume_price_strength | volume | stress_2026 | -32.89% | 20.49% | -2.25 | -1.60 | 2.5 | 241 | 36 |

## 已知限制

- 当前证券列表不含历史退市股票，存在幸存者偏差。
- 缺少历史 ST 状态，无法精确重建 5% 涨跌停限制。
- 日线只能近似成交，下一阶段必须使用 5 分钟数据验证执行质量。
- 此前研究已经观察过 2026 市场状态，因此 2026 只能作为压力测试，不能称为未观察样本。
