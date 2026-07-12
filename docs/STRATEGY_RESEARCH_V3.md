# 三策略研究报告 V3

## 结论

V3 共评估 15 个因子、405 组研究期参数配置，并包含参数平坦度、相关性、成交置信度和成本敏感性。2026 只作压力测试，不参与候选选择。

| 策略 | 逻辑 | 冻结配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 置信度 | 达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| low_volatility_trend | volatility | 20 只／40 日／宽度 30% | 2.79%／4.53% | 5.18%／4.43% | -8.23%／8.44% | standard | 否 |
| bollinger_reversion | reversal | 5 只／40 日／宽度 30% | -9.25%／11.99% | 20.62%／9.82% | 5.84%／12.17% | standard | 否 |
| rsi_oversold_reversal | reversal | 10 只／10 日／宽度 30% | -7.82%／8.29% | 7.69%／9.01% | -10.37%／10.58% | standard | 否 |

## 方法

- 2021～2023：参数研究；2024、2025：双验证；2026：只作压力测试。
- 参数选择同时考虑研究得分和相邻参数中位数，研究期成交少于 30 笔的配置不得入选。
- 最终排名要求两个验证期不能同时亏损，并以验证期日收益相关性作软惩罚，不再按家族标签硬去重。
- T 日收盘生成信号，T＋1 开盘后成交；跨日因果与开盘字段可用性审计违规数为 0。
- 初始资金 100000 元，计入佣金、印花税、过户费和 10BP 单边滑点；开盘触及涨跌停时保守按不可成交处理。



## 全部冻结因子表现

| 因子 | 家族 | 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | 成本 | 成交数 | 持仓覆盖 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| upside_downside_volatility | asymmetry | research | 0.49% | 9.61% | 0.10 | 0.05 | 4.4 | 276 | 32 | 27.3% |
| upside_downside_volatility | asymmetry | validation_2024 | 2.35% | 11.30% | 0.26 | 0.21 | 2.2 | 116 | 15 | 17.4% |
| upside_downside_volatility | asymmetry | validation_2025 | 15.38% | 14.01% | 0.88 | 1.10 | 7.5 | 407 | 44 | 67.1% |
| upside_downside_volatility | asymmetry | stress_2026 | 11.89% | 7.23% | 0.85 | 1.65 | 1.2 | 74 | 8 | 32.3% |
| accelerating_momentum | multi_cycle | research | 2.04% | 30.56% | 0.20 | 0.07 | 9.0 | 587 | 70 | 23.9% |
| accelerating_momentum | multi_cycle | validation_2024 | -21.98% | 34.91% | -1.12 | -0.63 | 4.0 | 241 | 31 | 25.6% |
| accelerating_momentum | multi_cycle | validation_2025 | -10.61% | 34.61% | -0.22 | -0.31 | 11.9 | 774 | 96 | 83.5% |
| accelerating_momentum | multi_cycle | stress_2026 | -25.95% | 17.30% | -1.79 | -1.50 | 2.2 | 143 | 18 | 32.3% |
| multi_timeframe_momentum | multi_cycle | research | 5.30% | 30.75% | 0.36 | 0.17 | 8.4 | 548 | 64 | 23.9% |
| multi_timeframe_momentum | multi_cycle | validation_2024 | -16.03% | 37.98% | -0.66 | -0.42 | 3.5 | 199 | 24 | 25.6% |
| multi_timeframe_momentum | multi_cycle | validation_2025 | -30.53% | 43.38% | -1.13 | -0.70 | 10.0 | 705 | 93 | 83.5% |
| multi_timeframe_momentum | multi_cycle | stress_2026 | -37.81% | 22.57% | -2.30 | -1.68 | 2.1 | 140 | 18 | 32.3% |
| **bollinger_reversion** | reversal | research | 4.53% | 19.51% | 0.35 | 0.23 | 12.7 | 791 | 95 | 65.9% |
| **bollinger_reversion** | reversal | validation_2024 | -9.25% | 11.99% | -1.10 | -0.77 | 3.3 | 192 | 25 | 33.9% |
| **bollinger_reversion** | reversal | validation_2025 | 20.62% | 9.82% | 1.44 | 2.10 | 8.7 | 478 | 54 | 83.5% |
| **bollinger_reversion** | reversal | stress_2026 | 5.84% | 12.17% | 0.46 | 0.48 | 3.1 | 181 | 20 | 64.5% |
| **rsi_oversold_reversal** | reversal | research | 3.14% | 10.45% | 0.36 | 0.30 | 30.2 | 2042 | 256 | 48.9% |
| **rsi_oversold_reversal** | reversal | validation_2024 | -7.82% | 8.29% | -1.66 | -0.94 | 3.9 | 238 | 32 | 29.8% |
| **rsi_oversold_reversal** | reversal | validation_2025 | 7.69% | 9.01% | 0.66 | 0.85 | 24.4 | 1828 | 240 | 79.4% |
| **rsi_oversold_reversal** | reversal | stress_2026 | -10.37% | 10.58% | -0.81 | -0.98 | 5.9 | 383 | 46 | 56.5% |
| short_term_reversal | reversal | research | 0.24% | 14.46% | 0.09 | 0.02 | 17.0 | 1423 | 196 | 34.1% |
| short_term_reversal | reversal | validation_2024 | 9.62% | 16.01% | 0.59 | 0.60 | 8.5 | 641 | 89 | 33.9% |
| short_term_reversal | reversal | validation_2025 | 14.24% | 18.53% | 0.67 | 0.77 | 20.5 | 1631 | 224 | 91.8% |
| short_term_reversal | reversal | stress_2026 | -26.23% | 19.22% | -1.84 | -1.36 | 4.5 | 403 | 58 | 48.4% |
| breakout_120 | trend | research | -1.84% | 16.96% | -0.04 | -0.11 | 4.8 | 305 | 36 | 27.3% |
| breakout_120 | trend | validation_2024 | -2.95% | 4.49% | -0.58 | -0.66 | 0.9 | 47 | 7 | 17.4% |
| breakout_120 | trend | validation_2025 | -3.72% | 16.55% | -0.07 | -0.22 | 4.6 | 268 | 33 | 67.1% |
| breakout_120 | trend | stress_2026 | -6.01% | 7.60% | -0.76 | -0.79 | 0.5 | 33 | 4 | 32.3% |
| momentum_120_ex5 | trend | research | 3.25% | 17.94% | 0.29 | 0.18 | 7.4 | 477 | 56 | 23.9% |
| momentum_120_ex5 | trend | validation_2024 | -6.80% | 30.90% | -0.22 | -0.22 | 2.8 | 151 | 19 | 25.6% |
| momentum_120_ex5 | trend | validation_2025 | -17.84% | 29.02% | -0.77 | -0.61 | 8.0 | 536 | 68 | 83.5% |
| momentum_120_ex5 | trend | stress_2026 | -14.87% | 17.08% | -0.83 | -0.87 | 1.9 | 128 | 16 | 32.3% |
| momentum_20_60 | trend | research | 16.04% | 23.40% | 0.87 | 0.69 | 9.6 | 591 | 64 | 23.9% |
| momentum_20_60 | trend | validation_2024 | -12.08% | 40.81% | -0.39 | -0.30 | 4.0 | 234 | 29 | 25.6% |
| momentum_20_60 | trend | validation_2025 | -21.52% | 41.54% | -0.62 | -0.52 | 9.5 | 653 | 85 | 83.5% |
| momentum_20_60 | trend | stress_2026 | -26.22% | 17.24% | -1.25 | -1.52 | 2.5 | 161 | 20 | 32.3% |
| risk_adjusted_momentum | trend | research | 0.97% | 8.48% | 0.15 | 0.11 | 7.1 | 1174 | 198 | 23.9% |
| risk_adjusted_momentum | trend | validation_2024 | -10.44% | 17.63% | -0.81 | -0.59 | 3.3 | 531 | 92 | 25.6% |
| risk_adjusted_momentum | trend | validation_2025 | -0.00% | 14.17% | 0.07 | -0.00 | 7.8 | 1261 | 214 | 83.5% |
| risk_adjusted_momentum | trend | stress_2026 | -10.49% | 7.96% | -1.84 | -1.32 | 1.0 | 176 | 30 | 32.3% |
| **low_volatility_trend** | volatility | research | 5.40% | 13.50% | 0.55 | 0.40 | 14.7 | 1992 | 326 | 72.7% |
| **low_volatility_trend** | volatility | validation_2024 | 2.79% | 4.53% | 0.49 | 0.62 | 3.2 | 458 | 79 | 33.9% |
| **low_volatility_trend** | volatility | validation_2025 | 5.18% | 4.43% | 0.67 | 1.17 | 6.2 | 905 | 152 | 83.5% |
| **low_volatility_trend** | volatility | stress_2026 | -8.23% | 8.44% | -0.79 | -0.98 | 2.7 | 420 | 70 | 64.5% |
| volatility_contraction | volatility | research | -0.17% | 15.91% | 0.04 | -0.01 | 7.0 | 418 | 51 | 38.7% |
| volatility_contraction | volatility | validation_2024 | -1.96% | 10.63% | -0.09 | -0.18 | 3.4 | 196 | 25 | 33.9% |
| volatility_contraction | volatility | validation_2025 | 9.99% | 7.63% | 0.69 | 1.31 | 8.6 | 480 | 55 | 83.5% |
| volatility_contraction | volatility | stress_2026 | -36.16% | 21.97% | -2.69 | -1.65 | 2.6 | 162 | 20 | 64.5% |
| volume_confirmed_breakout | volume | research | -11.90% | 28.64% | -1.01 | -0.42 | 6.9 | 1196 | 207 | 38.7% |
| volume_confirmed_breakout | volume | validation_2024 | -10.71% | 15.38% | -0.86 | -0.70 | 3.3 | 522 | 91 | 33.9% |
| volume_confirmed_breakout | volume | validation_2025 | -6.04% | 18.51% | -0.23 | -0.33 | 7.8 | 1250 | 213 | 83.5% |
| volume_confirmed_breakout | volume | stress_2026 | -17.52% | 15.37% | -1.15 | -1.14 | 2.8 | 440 | 74 | 64.5% |
| volume_dry_up | volume | research | 0.92% | 9.66% | 0.16 | 0.10 | 8.3 | 1236 | 208 | 38.7% |
| volume_dry_up | volume | validation_2024 | -8.56% | 10.30% | -1.37 | -0.83 | 2.5 | 351 | 61 | 33.9% |
| volume_dry_up | volume | validation_2025 | 16.54% | 10.47% | 1.18 | 1.58 | 9.8 | 1297 | 212 | 83.5% |
| volume_dry_up | volume | stress_2026 | -19.97% | 14.27% | -1.27 | -1.40 | 3.0 | 467 | 78 | 64.5% |
| volume_price_strength | volume | research | -4.58% | 35.84% | -0.19 | -0.13 | 8.9 | 900 | 134 | 23.9% |
| volume_price_strength | volume | validation_2024 | -13.58% | 36.04% | -0.52 | -0.38 | 5.0 | 406 | 59 | 25.6% |
| volume_price_strength | volume | validation_2025 | 1.87% | 25.39% | 0.21 | 0.07 | 13.9 | 1289 | 190 | 83.5% |
| volume_price_strength | volume | stress_2026 | -27.38% | 16.78% | -2.25 | -1.63 | 2.2 | 214 | 32 | 32.3% |

## 参数平坦度

| 因子 | 研究得分 | 邻域中位数 | 邻域标准差 | 正邻域占比 |
| --- | ---: | ---: | ---: | ---: |
| accelerating_momentum | 0.117 | -0.327 | 0.177 | 0% |
| bollinger_reversion | 0.320 | 0.112 | 0.360 | 67% |
| breakout_120 | -0.119 | -0.372 | 0.084 | 0% |
| low_volatility_trend | 0.539 | 0.288 | 0.269 | 67% |
| momentum_120_ex5 | 0.253 | -0.167 | 0.203 | 25% |
| momentum_20_60 | 0.903 | 0.265 | 0.323 | 100% |
| multi_timeframe_momentum | 0.262 | 0.070 | 0.364 | 50% |
| risk_adjusted_momentum | 0.153 | -0.506 | 0.186 | 0% |
| rsi_oversold_reversal | 0.389 | 0.160 | 0.402 | 75% |
| short_term_reversal | 0.038 | -0.263 | 0.132 | 0% |
| upside_downside_volatility | 0.075 | -0.309 | 0.157 | 0% |
| volatility_contraction | -0.002 | -0.367 | 0.106 | 0% |
| volume_confirmed_breakout | -0.668 | -0.703 | 0.037 | 0% |
| volume_dry_up | 0.134 | -0.312 | 0.231 | 0% |
| volume_price_strength | -0.176 | -0.292 | 0.170 | 0% |

## 候选相关性

- `low_volatility_trend` 与 `rsi_oversold_reversal`：0.190。
- `bollinger_reversion` 与 `low_volatility_trend`：0.434。
- `bollinger_reversion` 与 `rsi_oversold_reversal`：0.328。

## 滑点敏感性

| 策略 | 区间 | 单边滑点 | 年化 | 最大回撤 |
| --- | --- | ---: | ---: | ---: |
| low_volatility_trend | validation_2024 | 10BP | 2.79% | 4.53% |
| low_volatility_trend | validation_2025 | 10BP | 5.18% | 4.43% |
| low_volatility_trend | validation_2024 | 20BP | 2.47% | 4.53% |
| low_volatility_trend | validation_2025 | 20BP | 4.42% | 4.43% |
| low_volatility_trend | validation_2024 | 30BP | 2.17% | 4.50% |
| low_volatility_trend | validation_2025 | 30BP | 3.80% | 4.43% |
| bollinger_reversion | validation_2024 | 10BP | -9.25% | 11.99% |
| bollinger_reversion | validation_2025 | 10BP | 20.62% | 9.82% |
| bollinger_reversion | validation_2024 | 20BP | -9.59% | 12.15% |
| bollinger_reversion | validation_2025 | 20BP | 19.78% | 9.82% |
| bollinger_reversion | validation_2024 | 30BP | -9.92% | 12.30% |
| bollinger_reversion | validation_2025 | 30BP | 18.86% | 9.83% |
| rsi_oversold_reversal | validation_2024 | 10BP | -7.82% | 8.29% |
| rsi_oversold_reversal | validation_2025 | 10BP | 7.69% | 9.01% |
| rsi_oversold_reversal | validation_2024 | 20BP | -8.21% | 8.65% |
| rsi_oversold_reversal | validation_2025 | 20BP | 5.16% | 9.26% |
| rsi_oversold_reversal | validation_2024 | 30BP | -8.35% | 8.77% |
| rsi_oversold_reversal | validation_2025 | 30BP | 2.69% | 9.51% |

## 缩量整理阈值敏感性

| 整理宽度 | 区间 | 年化 | 最大回撤 | 成交数 |
| ---: | --- | ---: | ---: | ---: |
| 8% | validation_2024 | -3.65% | 8.07% | 58 |
| 8% | validation_2025 | 17.76% | 10.86% | 187 |
| 10% | validation_2024 | -5.01% | 8.21% | 57 |
| 10% | validation_2025 | 19.57% | 10.15% | 210 |
| 12% | validation_2024 | -8.56% | 10.30% | 61 |
| 12% | validation_2025 | 16.54% | 10.47% | 212 |
| 15% | validation_2024 | -3.40% | 9.36% | 84 |
| 15% | validation_2025 | 14.56% | 9.48% | 214 |

## 已知限制

- 当前证券列表不含历史退市股票，存在幸存者偏差。
- 缺少历史 ST 状态，无法精确重建 5% 涨跌停限制。
- 日线只能近似成交，下一阶段必须使用 5 分钟数据验证执行质量。
- 此前研究已经观察过 2026 市场状态，因此 2026 只能作为压力测试，不能称为未观察样本。
