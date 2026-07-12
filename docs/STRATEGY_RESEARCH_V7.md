# 三策略研究报告 V7

## 结论

V7 共评估 26 个因子、702 组研究期参数配置，并包含参数平坦度、相关性、成交置信度和成本敏感性。2026 只作压力测试，不参与候选选择。

| 策略 | 逻辑 | 冻结配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 置信度 | 达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cash_conversion | cash_quality | 5 只／20 日／宽度 50% | 0.38%／11.09% | 41.62%／9.39% | -6.63%／8.56% | standard | 否 |
| cash_quality_value | fundamental_composite | 5 只／40 日／宽度 40% | 10.73%／4.87% | 7.83%／12.50% | -10.49%／11.53% | low | 否 |
| fundamental_value | fundamental_value | 5 只／40 日／宽度 40% | 12.58%／5.62% | 0.20%／16.58% | -6.75%／8.57% | low | 否 |

## 方法

- 2021～2023：参数研究；2024、2025：双验证；2026：只作压力测试。
- 参数选择同时考虑研究得分和相邻参数中位数，研究期成交少于 30 笔的配置不得入选。
- 最终排名要求两个验证期不能同时亏损，并以验证期日收益相关性作软惩罚，不再按家族标签硬去重。
- T 日收盘生成信号，T＋1 开盘后成交；跨日因果与开盘字段可用性审计违规数为 0。
- 初始资金 100000 元，计入佣金、印花税、过户费和 10BP 单边滑点；开盘触及涨跌停时保守按不可成交处理。
- 基本面数据仅在公告日后的下一交易日生效，每日估值不跨日回填。
- PE、PB、股息率只抓取 118 个实际信号日，因此全面板覆盖率约 7%～10% 是稀疏设计，不是接口缺失。

## 基本面数据覆盖率

| 字段 | 全面板覆盖率 |
| --- | ---: |
| roe | 98.1% |
| roic | 95.4% |
| grossprofit_margin | 95.2% |
| debt_to_assets | 98.5% |
| ocf_to_or | 98.4% |
| q_sales_yoy | 97.0% |
| q_netprofit_yoy | 97.1% |
| ocf_to_opincome | 73.6% |
| arturn_days | 94.9% |
| invturn_days | 94.4% |
| n_op_profit_of_ebt | 80.4% |
| pe_ttm | 7.5% |
| pb | 9.5% |
| dv_ttm | 6.6% |

## 全部冻结因子表现

| 因子 | 家族 | 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | 成本 | 成交数 | 持仓覆盖 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| upside_downside_volatility | asymmetry | research | 0.49% | 9.61% | 0.10 | 0.05 | 4.4 | 276 | 32 | 27.3% |
| upside_downside_volatility | asymmetry | validation_2024 | 2.35% | 11.30% | 0.26 | 0.21 | 2.2 | 116 | 15 | 17.4% |
| upside_downside_volatility | asymmetry | validation_2025 | 15.38% | 14.01% | 0.88 | 1.10 | 7.5 | 407 | 44 | 67.1% |
| upside_downside_volatility | asymmetry | stress_2026 | 11.89% | 7.23% | 0.85 | 1.65 | 1.2 | 74 | 8 | 32.3% |
| **cash_conversion** | cash_quality | research | 5.68% | 10.09% | 0.63 | 0.56 | 10.0 | 596 | 66 | 23.9% |
| **cash_conversion** | cash_quality | validation_2024 | 0.38% | 11.09% | 0.10 | 0.03 | 5.0 | 278 | 33 | 25.6% |
| **cash_conversion** | cash_quality | validation_2025 | 41.62% | 9.39% | 2.18 | 4.43 | 14.7 | 801 | 85 | 83.5% |
| **cash_conversion** | cash_quality | stress_2026 | -6.63% | 8.56% | -0.60 | -0.78 | 2.6 | 158 | 18 | 32.3% |
| non_operating_independence | cash_quality_diagnostic | research | -2.33% | 17.32% | -0.10 | -0.13 | 13.1 | 1130 | 162 | 65.9% |
| non_operating_independence | cash_quality_diagnostic | validation_2024 | -11.10% | 15.17% | -1.03 | -0.73 | 2.6 | 231 | 36 | 33.9% |
| non_operating_independence | cash_quality_diagnostic | validation_2025 | 16.98% | 10.93% | 1.20 | 1.55 | 8.2 | 665 | 94 | 83.5% |
| non_operating_independence | cash_quality_diagnostic | stress_2026 | -23.27% | 12.90% | -2.09 | -1.80 | 2.5 | 242 | 36 | 64.5% |
| **cash_quality_value** | fundamental_composite | research | 4.58% | 10.99% | 0.52 | 0.42 | 5.5 | 299 | 35 | 38.7% |
| **cash_quality_value** | fundamental_composite | validation_2024 | 10.73% | 4.87% | 1.33 | 2.20 | 2.3 | 117 | 15 | 33.9% |
| **cash_quality_value** | fundamental_composite | validation_2025 | 7.83% | 12.50% | 0.69 | 0.63 | 4.2 | 227 | 27 | 83.5% |
| **cash_quality_value** | fundamental_composite | stress_2026 | -10.49% | 11.53% | -0.94 | -0.91 | 2.9 | 173 | 20 | 64.5% |
| fundamental_quality_growth | fundamental_composite | research | -7.70% | 21.45% | -0.86 | -0.36 | 3.8 | 663 | 116 | 65.9% |
| fundamental_quality_growth | fundamental_composite | validation_2024 | -3.22% | 6.03% | -0.49 | -0.53 | 1.1 | 177 | 32 | 33.9% |
| fundamental_quality_growth | fundamental_composite | validation_2025 | 22.71% | 5.86% | 2.14 | 3.88 | 3.6 | 505 | 85 | 83.5% |
| fundamental_quality_growth | fundamental_composite | stress_2026 | -20.27% | 12.43% | -2.27 | -1.63 | 1.6 | 264 | 45 | 67.7% |
| fundamental_quality_value | fundamental_composite | research | -0.25% | 13.96% | 0.03 | -0.02 | 5.1 | 788 | 134 | 65.9% |
| fundamental_quality_value | fundamental_composite | validation_2024 | 4.83% | 4.40% | 0.82 | 1.10 | 1.9 | 276 | 48 | 33.9% |
| fundamental_quality_value | fundamental_composite | validation_2025 | 12.99% | 6.93% | 1.33 | 1.87 | 4.0 | 545 | 92 | 83.5% |
| fundamental_quality_value | fundamental_composite | stress_2026 | -10.28% | 10.62% | -1.03 | -0.97 | 2.3 | 348 | 58 | 64.5% |
| fundamental_growth | fundamental_growth | research | -3.48% | 17.12% | -0.25 | -0.20 | 7.3 | 1197 | 205 | 65.9% |
| fundamental_growth | fundamental_growth | validation_2024 | -5.22% | 8.63% | -0.49 | -0.60 | 2.0 | 314 | 56 | 33.9% |
| fundamental_growth | fundamental_growth | validation_2025 | 21.42% | 7.93% | 1.53 | 2.70 | 5.1 | 684 | 114 | 83.5% |
| fundamental_growth | fundamental_growth | stress_2026 | -11.14% | 8.72% | -0.75 | -1.28 | 2.3 | 352 | 59 | 67.7% |
| fundamental_quality | fundamental_quality | research | -3.72% | 10.97% | -0.45 | -0.34 | 2.4 | 397 | 69 | 65.9% |
| fundamental_quality | fundamental_quality | validation_2024 | -5.81% | 6.53% | -1.35 | -0.89 | 1.0 | 155 | 28 | 33.9% |
| fundamental_quality | fundamental_quality | validation_2025 | 9.22% | 3.53% | 1.20 | 2.61 | 2.2 | 329 | 57 | 83.5% |
| fundamental_quality | fundamental_quality | stress_2026 | -14.99% | 10.33% | -1.88 | -1.45 | 1.4 | 228 | 39 | 67.7% |
| **fundamental_value** | fundamental_value | research | 6.61% | 9.98% | 0.75 | 0.66 | 5.9 | 321 | 37 | 38.7% |
| **fundamental_value** | fundamental_value | validation_2024 | 12.58% | 5.62% | 1.58 | 2.24 | 2.6 | 135 | 17 | 33.9% |
| **fundamental_value** | fundamental_value | validation_2025 | 0.20% | 16.58% | 0.08 | 0.01 | 2.3 | 117 | 15 | 83.5% |
| **fundamental_value** | fundamental_value | stress_2026 | -6.75% | 8.57% | -0.73 | -0.79 | 1.7 | 104 | 12 | 64.5% |
| accelerating_momentum | multi_cycle | research | 2.04% | 30.56% | 0.20 | 0.07 | 9.0 | 587 | 70 | 23.9% |
| accelerating_momentum | multi_cycle | validation_2024 | -21.98% | 34.91% | -1.12 | -0.63 | 4.0 | 241 | 31 | 25.6% |
| accelerating_momentum | multi_cycle | validation_2025 | -10.61% | 34.61% | -0.22 | -0.31 | 11.9 | 774 | 96 | 83.5% |
| accelerating_momentum | multi_cycle | stress_2026 | -25.95% | 17.30% | -1.79 | -1.50 | 2.2 | 143 | 18 | 32.3% |
| multi_timeframe_momentum | multi_cycle | research | 5.30% | 30.75% | 0.36 | 0.17 | 8.4 | 548 | 64 | 23.9% |
| multi_timeframe_momentum | multi_cycle | validation_2024 | -16.03% | 37.98% | -0.66 | -0.42 | 3.5 | 199 | 24 | 25.6% |
| multi_timeframe_momentum | multi_cycle | validation_2025 | -30.53% | 43.38% | -1.13 | -0.70 | 10.0 | 705 | 93 | 83.5% |
| multi_timeframe_momentum | multi_cycle | stress_2026 | -37.81% | 22.57% | -2.30 | -1.68 | 2.1 | 140 | 18 | 32.3% |
| bollinger_reversion | reversal | research | 4.53% | 19.51% | 0.35 | 0.23 | 12.7 | 791 | 95 | 65.9% |
| bollinger_reversion | reversal | validation_2024 | -9.25% | 11.99% | -1.10 | -0.77 | 3.3 | 192 | 25 | 33.9% |
| bollinger_reversion | reversal | validation_2025 | 20.62% | 9.82% | 1.44 | 2.10 | 8.7 | 478 | 54 | 83.5% |
| bollinger_reversion | reversal | stress_2026 | 5.84% | 12.17% | 0.46 | 0.48 | 3.1 | 181 | 20 | 64.5% |
| rsi_oversold_reversal | reversal | research | 3.14% | 10.45% | 0.36 | 0.30 | 30.2 | 2042 | 256 | 48.9% |
| rsi_oversold_reversal | reversal | validation_2024 | -7.82% | 8.29% | -1.66 | -0.94 | 3.9 | 238 | 32 | 29.8% |
| rsi_oversold_reversal | reversal | validation_2025 | 7.69% | 9.01% | 0.66 | 0.85 | 24.4 | 1828 | 240 | 79.4% |
| rsi_oversold_reversal | reversal | stress_2026 | -10.37% | 10.58% | -0.81 | -0.98 | 5.9 | 383 | 46 | 56.5% |
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
| low_volatility_trend | volatility | research | 5.40% | 13.50% | 0.55 | 0.40 | 14.7 | 1992 | 326 | 72.7% |
| low_volatility_trend | volatility | validation_2024 | 2.79% | 4.53% | 0.49 | 0.62 | 3.2 | 458 | 79 | 33.9% |
| low_volatility_trend | volatility | validation_2025 | 5.18% | 4.43% | 0.67 | 1.17 | 6.2 | 905 | 152 | 83.5% |
| low_volatility_trend | volatility | stress_2026 | -8.23% | 8.44% | -0.79 | -0.98 | 2.7 | 420 | 70 | 64.5% |
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
| inventory_efficiency | working_capital | research | 0.90% | 14.03% | 0.14 | 0.06 | 39.7 | 3491 | 496 | 67.6% |
| inventory_efficiency | working_capital | validation_2024 | -13.70% | 18.98% | -0.65 | -0.72 | 13.8 | 1229 | 178 | 50.4% |
| inventory_efficiency | working_capital | validation_2025 | 10.07% | 11.39% | 0.76 | 0.88 | 25.9 | 2112 | 292 | 91.8% |
| inventory_efficiency | working_capital | stress_2026 | -26.59% | 16.85% | -2.03 | -1.58 | 9.9 | 874 | 124 | 64.5% |
| receivable_efficiency | working_capital | research | 0.66% | 13.76% | 0.11 | 0.05 | 6.4 | 951 | 160 | 65.9% |
| receivable_efficiency | working_capital | validation_2024 | -10.21% | 12.59% | -1.05 | -0.81 | 2.0 | 302 | 53 | 33.9% |
| receivable_efficiency | working_capital | validation_2025 | 23.97% | 7.85% | 1.70 | 3.05 | 4.0 | 531 | 89 | 83.5% |
| receivable_efficiency | working_capital | stress_2026 | -18.76% | 13.31% | -1.95 | -1.41 | 1.6 | 258 | 44 | 64.5% |
| working_capital_efficiency | working_capital | research | -2.66% | 17.16% | -0.16 | -0.16 | 4.7 | 748 | 129 | 72.7% |
| working_capital_efficiency | working_capital | validation_2024 | -6.70% | 10.59% | -0.69 | -0.63 | 1.8 | 275 | 49 | 33.9% |
| working_capital_efficiency | working_capital | validation_2025 | 27.56% | 8.08% | 2.01 | 3.41 | 3.0 | 403 | 68 | 83.5% |
| working_capital_efficiency | working_capital | stress_2026 | -28.68% | 22.39% | -2.69 | -1.28 | 1.9 | 315 | 54 | 64.5% |

## 参数平坦度

| 因子 | 研究得分 | 邻域中位数 | 邻域标准差 | 正邻域占比 |
| --- | ---: | ---: | ---: | ---: |
| accelerating_momentum | 0.117 | -0.327 | 0.177 | 0% |
| bollinger_reversion | 0.320 | 0.112 | 0.360 | 67% |
| breakout_120 | -0.119 | -0.372 | 0.084 | 0% |
| cash_conversion | 0.719 | 0.087 | 0.350 | 50% |
| cash_quality_value | 0.548 | 0.408 | 0.164 | 100% |
| fundamental_growth | -0.265 | -0.398 | 0.134 | 0% |
| fundamental_quality | -0.451 | -0.652 | 0.054 | 0% |
| fundamental_quality_growth | -0.574 | -0.729 | 0.036 | 0% |
| fundamental_quality_value | -0.012 | -0.110 | 0.102 | 0% |
| fundamental_value | 0.849 | 0.508 | 0.203 | 100% |
| inventory_efficiency | 0.098 | -0.226 | 0.120 | 0% |
| low_volatility_trend | 0.539 | 0.288 | 0.269 | 67% |
| momentum_120_ex5 | 0.253 | -0.167 | 0.203 | 25% |
| momentum_20_60 | 0.903 | 0.265 | 0.323 | 100% |
| multi_timeframe_momentum | 0.262 | 0.070 | 0.364 | 50% |
| non_operating_independence | -0.159 | -0.428 | 0.129 | 0% |
| receivable_efficiency | 0.077 | -0.255 | 0.309 | 33% |
| risk_adjusted_momentum | 0.153 | -0.506 | 0.186 | 0% |
| rsi_oversold_reversal | 0.389 | 0.160 | 0.402 | 75% |
| short_term_reversal | 0.038 | -0.263 | 0.132 | 0% |
| upside_downside_volatility | 0.075 | -0.309 | 0.157 | 0% |
| volatility_contraction | -0.002 | -0.367 | 0.106 | 0% |
| volume_confirmed_breakout | -0.668 | -0.703 | 0.037 | 0% |
| volume_dry_up | 0.134 | -0.312 | 0.231 | 0% |
| volume_price_strength | -0.176 | -0.292 | 0.170 | 0% |
| working_capital_efficiency | -0.194 | -0.414 | 0.136 | 0% |

## 候选相关性

- `cash_conversion` 与 `cash_quality_value`：0.257。
- `cash_conversion` 与 `fundamental_value`：0.200。
- `cash_quality_value` 与 `fundamental_value`：0.885。

## 滑点敏感性

| 策略 | 区间 | 单边滑点 | 年化 | 最大回撤 |
| --- | --- | ---: | ---: | ---: |
| cash_conversion | validation_2024 | 10BP | 0.38% | 11.09% |
| cash_conversion | validation_2025 | 10BP | 41.62% | 9.39% |
| cash_conversion | validation_2024 | 20BP | -0.14% | 11.17% |
| cash_conversion | validation_2025 | 20BP | 40.14% | 9.50% |
| cash_conversion | validation_2024 | 30BP | -0.61% | 11.33% |
| cash_conversion | validation_2025 | 30BP | 38.23% | 9.65% |
| cash_quality_value | validation_2024 | 10BP | 10.73% | 4.87% |
| cash_quality_value | validation_2025 | 10BP | 7.83% | 12.50% |
| cash_quality_value | validation_2024 | 20BP | 10.49% | 4.82% |
| cash_quality_value | validation_2025 | 20BP | 7.39% | 12.50% |
| cash_quality_value | validation_2024 | 30BP | 10.26% | 4.82% |
| cash_quality_value | validation_2025 | 30BP | 6.97% | 12.55% |
| fundamental_value | validation_2024 | 10BP | 12.58% | 5.62% |
| fundamental_value | validation_2025 | 10BP | 0.20% | 16.58% |
| fundamental_value | validation_2024 | 20BP | 12.25% | 5.63% |
| fundamental_value | validation_2025 | 20BP | -0.02% | 16.50% |
| fundamental_value | validation_2024 | 30BP | 11.91% | 5.55% |
| fundamental_value | validation_2025 | 30BP | -0.25% | 16.57% |

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
- Tushare 数据来自第三方代理，存在服务中断、延迟、token 撤销和协议变化风险。
- 当前股票池仍以现有证券列表为基础，基本面接入尚未消除退市股幸存者偏差。
