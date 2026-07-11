# 三策略研究报告 V4

## 结论

V4 共评估 20 个因子、540 组研究期参数配置，并包含参数平坦度、相关性、成交置信度和成本敏感性。2026 只作压力测试，不参与候选选择。

| 策略 | 逻辑 | 冻结配置 | 2024 年化／回撤 | 2025 年化／回撤 | 2026 压力年化／回撤 | 置信度 | 达标 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fundamental_value | fundamental_value | 5 只／40 日／宽度 40% | 12.58%／5.62% | 0.20%／16.58% | -6.75%／8.57% | low | 否 |
| low_volatility_trend | volatility | 20 只／40 日／宽度 30% | 2.79%／4.53% | 5.18%／4.43% | -8.23%／8.44% | standard | 否 |
| bollinger_reversion | reversal | 5 只／40 日／宽度 30% | -9.25%／11.99% | 20.62%／9.82% | 5.84%／12.17% | standard | 否 |

## 方法

- 2021～2023：参数研究；2024、2025：双验证；2026：只作压力测试。
- 参数选择同时考虑研究得分和相邻参数中位数，研究期成交少于 30 笔的配置不得入选。
- 最终排名要求两个验证期不能同时亏损，并以验证期日收益相关性作软惩罚，不再按家族标签硬去重。
- T 日收盘生成信号，T＋1 开盘后成交；未来函数审计违规数为 0。
- 初始资金 100000 元，计入佣金、印花税、过户费、10BP 单边滑点及一字板不可成交。
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
| pe_ttm | 7.6% |
| pb | 9.6% |
| dv_ttm | 6.7% |

## 全部冻结因子表现

| 因子 | 家族 | 区间 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | 成本 | 成交数 | 持仓覆盖 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| upside_downside_volatility | asymmetry | research | 0.37% | 12.35% | 0.09 | 0.03 | 4.9 | 309 | 36 | 27.3% |
| upside_downside_volatility | asymmetry | validation_2024 | 2.35% | 11.30% | 0.26 | 0.21 | 2.2 | 116 | 15 | 17.4% |
| upside_downside_volatility | asymmetry | validation_2025 | 15.21% | 14.79% | 0.87 | 1.03 | 7.6 | 412 | 45 | 67.1% |
| upside_downside_volatility | asymmetry | stress_2026 | 11.89% | 7.23% | 0.85 | 1.65 | 1.2 | 74 | 8 | 32.3% |
| fundamental_quality_growth | fundamental_composite | research | -7.70% | 21.45% | -0.86 | -0.36 | 3.8 | 663 | 116 | 65.9% |
| fundamental_quality_growth | fundamental_composite | validation_2024 | -3.22% | 6.03% | -0.49 | -0.53 | 1.1 | 177 | 32 | 33.9% |
| fundamental_quality_growth | fundamental_composite | validation_2025 | 22.07% | 5.86% | 2.08 | 3.77 | 3.6 | 505 | 85 | 83.5% |
| fundamental_quality_growth | fundamental_composite | stress_2026 | -20.96% | 12.43% | -2.36 | -1.69 | 1.6 | 270 | 46 | 64.5% |
| fundamental_quality_value | fundamental_composite | research | -0.25% | 13.96% | 0.03 | -0.02 | 5.1 | 788 | 134 | 65.9% |
| fundamental_quality_value | fundamental_composite | validation_2024 | 4.83% | 4.40% | 0.82 | 1.10 | 1.9 | 276 | 48 | 33.9% |
| fundamental_quality_value | fundamental_composite | validation_2025 | 12.99% | 6.93% | 1.33 | 1.87 | 4.0 | 545 | 92 | 83.5% |
| fundamental_quality_value | fundamental_composite | stress_2026 | -10.28% | 10.62% | -1.03 | -0.97 | 2.3 | 348 | 58 | 64.5% |
| fundamental_growth | fundamental_growth | research | -3.48% | 17.12% | -0.25 | -0.20 | 7.3 | 1197 | 205 | 65.9% |
| fundamental_growth | fundamental_growth | validation_2024 | -5.22% | 8.63% | -0.49 | -0.60 | 2.0 | 314 | 56 | 33.9% |
| fundamental_growth | fundamental_growth | validation_2025 | 21.65% | 7.96% | 1.54 | 2.72 | 5.2 | 684 | 114 | 83.5% |
| fundamental_growth | fundamental_growth | stress_2026 | -11.87% | 8.72% | -0.81 | -1.36 | 2.3 | 359 | 60 | 64.5% |
| fundamental_quality | fundamental_quality | research | -3.72% | 10.97% | -0.45 | -0.34 | 2.4 | 397 | 69 | 65.9% |
| fundamental_quality | fundamental_quality | validation_2024 | -5.81% | 6.53% | -1.35 | -0.89 | 1.0 | 155 | 28 | 33.9% |
| fundamental_quality | fundamental_quality | validation_2025 | 9.22% | 3.53% | 1.20 | 2.61 | 2.2 | 329 | 57 | 83.5% |
| fundamental_quality | fundamental_quality | stress_2026 | -15.71% | 10.33% | -1.98 | -1.52 | 1.4 | 234 | 40 | 64.5% |
| **fundamental_value** | fundamental_value | research | 6.61% | 9.98% | 0.75 | 0.66 | 5.9 | 321 | 37 | 38.7% |
| **fundamental_value** | fundamental_value | validation_2024 | 12.58% | 5.62% | 1.58 | 2.24 | 2.6 | 135 | 17 | 33.9% |
| **fundamental_value** | fundamental_value | validation_2025 | 0.20% | 16.58% | 0.08 | 0.01 | 2.3 | 117 | 15 | 83.5% |
| **fundamental_value** | fundamental_value | stress_2026 | -6.75% | 8.57% | -0.73 | -0.79 | 1.7 | 104 | 12 | 64.5% |
| accelerating_momentum | multi_cycle | research | 2.04% | 30.56% | 0.20 | 0.07 | 9.0 | 587 | 70 | 23.9% |
| accelerating_momentum | multi_cycle | validation_2024 | -22.30% | 35.18% | -1.16 | -0.63 | 4.0 | 240 | 31 | 25.6% |
| accelerating_momentum | multi_cycle | validation_2025 | -20.17% | 40.41% | -0.60 | -0.50 | 11.9 | 797 | 101 | 83.5% |
| accelerating_momentum | multi_cycle | stress_2026 | -30.53% | 18.76% | -1.98 | -1.63 | 2.4 | 158 | 20 | 32.3% |
| multi_timeframe_momentum | multi_cycle | research | 5.36% | 30.75% | 0.36 | 0.17 | 8.4 | 548 | 64 | 23.9% |
| multi_timeframe_momentum | multi_cycle | validation_2024 | -19.84% | 40.57% | -0.81 | -0.49 | 4.0 | 222 | 27 | 25.6% |
| multi_timeframe_momentum | multi_cycle | validation_2025 | -36.35% | 47.96% | -1.44 | -0.76 | 9.4 | 689 | 93 | 83.5% |
| multi_timeframe_momentum | multi_cycle | stress_2026 | -37.81% | 22.57% | -2.30 | -1.68 | 2.1 | 140 | 18 | 32.3% |
| **bollinger_reversion** | reversal | research | 4.53% | 19.51% | 0.35 | 0.23 | 12.7 | 791 | 95 | 65.9% |
| **bollinger_reversion** | reversal | validation_2024 | -9.25% | 11.99% | -1.10 | -0.77 | 3.3 | 192 | 25 | 33.9% |
| **bollinger_reversion** | reversal | validation_2025 | 20.62% | 9.82% | 1.44 | 2.10 | 8.7 | 478 | 54 | 83.5% |
| **bollinger_reversion** | reversal | stress_2026 | 5.84% | 12.17% | 0.46 | 0.48 | 3.1 | 181 | 20 | 64.5% |
| rsi_oversold_reversal | reversal | research | 3.14% | 10.45% | 0.36 | 0.30 | 30.2 | 2042 | 256 | 48.9% |
| rsi_oversold_reversal | reversal | validation_2024 | -7.82% | 8.29% | -1.66 | -0.94 | 3.9 | 238 | 32 | 29.8% |
| rsi_oversold_reversal | reversal | validation_2025 | 7.69% | 9.01% | 0.66 | 0.85 | 24.4 | 1828 | 240 | 79.4% |
| rsi_oversold_reversal | reversal | stress_2026 | -10.60% | 10.61% | -0.84 | -1.00 | 5.9 | 382 | 46 | 56.5% |
| short_term_reversal | reversal | research | 0.24% | 14.46% | 0.09 | 0.02 | 17.0 | 1423 | 196 | 34.1% |
| short_term_reversal | reversal | validation_2024 | 11.51% | 16.12% | 0.70 | 0.71 | 8.6 | 645 | 89 | 33.9% |
| short_term_reversal | reversal | validation_2025 | 12.56% | 18.31% | 0.62 | 0.69 | 20.3 | 1627 | 224 | 91.8% |
| short_term_reversal | reversal | stress_2026 | -26.23% | 19.22% | -1.84 | -1.36 | 4.5 | 403 | 58 | 48.4% |
| breakout_120 | trend | research | -1.84% | 16.96% | -0.04 | -0.11 | 4.8 | 305 | 36 | 27.3% |
| breakout_120 | trend | validation_2024 | -3.47% | 6.63% | -0.46 | -0.52 | 1.2 | 57 | 9 | 17.4% |
| breakout_120 | trend | validation_2025 | 5.15% | 21.81% | 0.32 | 0.24 | 5.8 | 341 | 41 | 67.1% |
| breakout_120 | trend | stress_2026 | -16.28% | 16.17% | -0.96 | -1.01 | 1.0 | 65 | 8 | 32.3% |
| momentum_120_ex5 | trend | research | 3.25% | 17.94% | 0.29 | 0.18 | 7.4 | 477 | 56 | 23.9% |
| momentum_120_ex5 | trend | validation_2024 | -6.81% | 30.90% | -0.22 | -0.22 | 2.8 | 151 | 19 | 25.6% |
| momentum_120_ex5 | trend | validation_2025 | -20.34% | 28.89% | -0.98 | -0.70 | 7.9 | 531 | 68 | 83.5% |
| momentum_120_ex5 | trend | stress_2026 | -14.87% | 17.08% | -0.83 | -0.87 | 1.9 | 128 | 16 | 32.3% |
| momentum_20_60 | trend | research | 16.10% | 23.40% | 0.87 | 0.69 | 9.6 | 592 | 64 | 23.9% |
| momentum_20_60 | trend | validation_2024 | -14.48% | 42.29% | -0.47 | -0.34 | 4.4 | 244 | 29 | 25.6% |
| momentum_20_60 | trend | validation_2025 | -29.14% | 48.84% | -0.94 | -0.60 | 9.1 | 663 | 89 | 83.5% |
| momentum_20_60 | trend | stress_2026 | -26.22% | 17.24% | -1.25 | -1.52 | 2.5 | 161 | 20 | 32.3% |
| risk_adjusted_momentum | trend | research | 1.10% | 8.91% | 0.16 | 0.12 | 7.1 | 1174 | 198 | 23.9% |
| risk_adjusted_momentum | trend | validation_2024 | -10.42% | 17.61% | -0.79 | -0.59 | 3.4 | 543 | 94 | 25.6% |
| risk_adjusted_momentum | trend | validation_2025 | -0.52% | 13.92% | 0.04 | -0.04 | 7.8 | 1260 | 214 | 83.5% |
| risk_adjusted_momentum | trend | stress_2026 | -10.49% | 7.96% | -1.84 | -1.32 | 1.0 | 176 | 30 | 32.3% |
| **low_volatility_trend** | volatility | research | 6.28% | 11.65% | 0.63 | 0.54 | 15.0 | 2001 | 326 | 65.9% |
| **low_volatility_trend** | volatility | validation_2024 | 2.79% | 4.53% | 0.49 | 0.62 | 3.2 | 458 | 79 | 33.9% |
| **low_volatility_trend** | volatility | validation_2025 | 5.18% | 4.43% | 0.67 | 1.17 | 6.2 | 905 | 152 | 83.5% |
| **low_volatility_trend** | volatility | stress_2026 | -8.23% | 8.44% | -0.79 | -0.98 | 2.7 | 420 | 70 | 64.5% |
| volatility_contraction | volatility | research | -0.17% | 15.91% | 0.04 | -0.01 | 7.0 | 418 | 51 | 38.7% |
| volatility_contraction | volatility | validation_2024 | -1.96% | 10.63% | -0.09 | -0.18 | 3.4 | 196 | 25 | 33.9% |
| volatility_contraction | volatility | validation_2025 | 9.99% | 7.63% | 0.69 | 1.31 | 8.6 | 480 | 55 | 83.5% |
| volatility_contraction | volatility | stress_2026 | -36.16% | 21.97% | -2.69 | -1.65 | 2.6 | 162 | 20 | 64.5% |
| volume_confirmed_breakout | volume | research | -10.24% | 23.20% | -0.95 | -0.44 | 5.2 | 920 | 158 | 27.3% |
| volume_confirmed_breakout | volume | validation_2024 | -1.33% | 12.75% | -0.07 | -0.10 | 2.3 | 319 | 56 | 17.4% |
| volume_confirmed_breakout | volume | validation_2025 | -6.50% | 18.51% | -0.27 | -0.35 | 6.3 | 1035 | 178 | 67.1% |
| volume_confirmed_breakout | volume | stress_2026 | 2.17% | 12.19% | 0.23 | 0.18 | 1.6 | 242 | 40 | 32.3% |
| volume_dry_up | volume | research | 0.92% | 9.66% | 0.16 | 0.10 | 8.3 | 1236 | 208 | 38.7% |
| volume_dry_up | volume | validation_2024 | -8.56% | 10.30% | -1.37 | -0.83 | 2.5 | 351 | 61 | 33.9% |
| volume_dry_up | volume | validation_2025 | 16.54% | 10.47% | 1.18 | 1.58 | 9.8 | 1297 | 212 | 83.5% |
| volume_dry_up | volume | stress_2026 | -19.97% | 14.27% | -1.27 | -1.40 | 3.0 | 467 | 78 | 64.5% |
| volume_price_strength | volume | research | -4.58% | 35.84% | -0.19 | -0.13 | 8.9 | 900 | 134 | 23.9% |
| volume_price_strength | volume | validation_2024 | -15.24% | 37.50% | -0.57 | -0.41 | 5.2 | 416 | 60 | 25.6% |
| volume_price_strength | volume | validation_2025 | 6.81% | 27.24% | 0.37 | 0.25 | 14.0 | 1312 | 194 | 83.5% |
| volume_price_strength | volume | stress_2026 | -32.89% | 20.49% | -2.25 | -1.60 | 2.5 | 241 | 36 | 32.3% |

## 参数平坦度

| 因子 | 研究得分 | 邻域中位数 | 邻域标准差 | 正邻域占比 |
| --- | ---: | ---: | ---: | ---: |
| accelerating_momentum | 0.117 | -0.345 | 0.187 | 0% |
| bollinger_reversion | 0.320 | 0.112 | 0.360 | 67% |
| breakout_120 | -0.119 | -0.423 | 0.179 | 0% |
| fundamental_growth | -0.265 | -0.373 | 0.139 | 0% |
| fundamental_quality | -0.451 | -0.652 | 0.054 | 0% |
| fundamental_quality_growth | -0.574 | -0.728 | 0.036 | 0% |
| fundamental_quality_value | -0.012 | -0.088 | 0.112 | 0% |
| fundamental_value | 0.849 | 0.508 | 0.202 | 100% |
| low_volatility_trend | 0.697 | 0.287 | 0.269 | 67% |
| momentum_120_ex5 | 0.253 | -0.154 | 0.199 | 25% |
| momentum_20_60 | 0.906 | 0.180 | 0.349 | 100% |
| multi_timeframe_momentum | 0.264 | 0.024 | 0.380 | 50% |
| risk_adjusted_momentum | 0.164 | -0.525 | 0.193 | 0% |
| rsi_oversold_reversal | 0.389 | 0.160 | 0.402 | 75% |
| short_term_reversal | 0.038 | -0.263 | 0.137 | 0% |
| upside_downside_volatility | 0.052 | -0.207 | 0.122 | 0% |
| volatility_contraction | -0.002 | -0.367 | 0.106 | 0% |
| volume_confirmed_breakout | -0.679 | -0.717 | 0.044 | 0% |
| volume_dry_up | 0.134 | -0.312 | 0.231 | 0% |
| volume_price_strength | -0.176 | -0.292 | 0.176 | 0% |

## 候选相关性

- `fundamental_value` 与 `low_volatility_trend`：0.678。
- `bollinger_reversion` 与 `fundamental_value`：0.118。
- `bollinger_reversion` 与 `low_volatility_trend`：0.434。

## 滑点敏感性

| 策略 | 区间 | 单边滑点 | 年化 | 最大回撤 |
| --- | --- | ---: | ---: | ---: |
| fundamental_value | validation_2024 | 10BP | 12.58% | 5.62% |
| fundamental_value | validation_2025 | 10BP | 0.20% | 16.58% |
| fundamental_value | validation_2024 | 20BP | 12.25% | 5.63% |
| fundamental_value | validation_2025 | 20BP | -0.00% | 16.49% |
| fundamental_value | validation_2024 | 30BP | 11.91% | 5.55% |
| fundamental_value | validation_2025 | 30BP | -0.22% | 16.55% |
| low_volatility_trend | validation_2024 | 10BP | 2.79% | 4.53% |
| low_volatility_trend | validation_2025 | 10BP | 5.18% | 4.43% |
| low_volatility_trend | validation_2024 | 20BP | 2.47% | 4.53% |
| low_volatility_trend | validation_2025 | 20BP | 4.38% | 4.43% |
| low_volatility_trend | validation_2024 | 30BP | 2.17% | 4.50% |
| low_volatility_trend | validation_2025 | 30BP | 3.76% | 4.43% |
| bollinger_reversion | validation_2024 | 10BP | -9.25% | 11.99% |
| bollinger_reversion | validation_2025 | 10BP | 20.62% | 9.82% |
| bollinger_reversion | validation_2024 | 20BP | -9.59% | 12.15% |
| bollinger_reversion | validation_2025 | 20BP | 19.78% | 9.82% |
| bollinger_reversion | validation_2024 | 30BP | -9.92% | 12.30% |
| bollinger_reversion | validation_2025 | 30BP | 18.86% | 9.83% |

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
