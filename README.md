# astock

`astock` 是面向个人研究的 A 股模拟交易系统。通达信 TdxQuant 提供主行情，同花顺 Financial-API 用于盘后补充和交叉校验；系统内部自建 A 股账户、风控、OMS、账本和模拟 Broker，后续可替换为 MiniQMT 执行适配器。

## 当前范围

- P0：项目治理、架构和验收规范。
- P1：TDX／THS 数据适配、原始事件落地和数据质量检查。
- P2：现金账户、`T+1`、整手、费用、涨跌停、限价及部分成交。
- P3：20 日动量＋60 日趋势策略、独立风控、持久化 OMS、账本、对账和历史回放。

不支持真实下单、科创板、创业板、北交所、ST、新股特殊阶段、ETF、可转债、融资融券和集合竞价。

## 环境

- Windows 11
- Python 3.13
- 已启动并登录支持 TQ 的通达信金融终端
- 本地 TQ HTTP：`http://127.0.0.1:17709/`

## 快速验证

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m astock.cli doctor --env-file .env.demo
python -m astock.cli replay --symbol 000001.SZ --start 20250101 --end 20260710 --env-file .env.demo
python -m astock.cli research --env-file .env.demo
python -m astock.cli research-fundamental --env-file .env.demo
python -m astock.cli paper-prepare --env-file .env.demo
python -m astock.cli paper-signals --env-file .env.demo
# 仅在下一交易日、TDX 日历确认后执行：
python -m astock.cli paper-execute --env-file .env.demo
```

`doctor` 只报告配置项是否存在和接口能力，不输出密钥。详细运行与验收见 `docs/OPERATIONS.md` 和 `docs/ACCEPTANCE.md`。

`replay` 使用临时 SQLite 数据库执行策略、风控、OMS、模拟成交与逐日对账，不会触发真实交易，也不会改写正式账户数据。

最新策略研究结论见 `docs/STRATEGY_RESEARCH_V4.md`。三个模拟策略使用完全隔离的 100000 元账户，另设一个 100000 元组合观察账户；它们目前都是待前向淘汰的候选，不是实盘策略。
