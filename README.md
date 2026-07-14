# astock

`astock` 是面向个人研究的 A 股模拟交易系统。通达信 TdxQuant 提供主行情和模拟账户交易，同花顺 Financial-API 用于盘后补充和交叉校验；TDX 模拟账户是前向订单、成交、资金和持仓的权威源，本地 SQLite 保存发送 Outbox、事实镜像和复盘证据。历史研究仍使用自建模拟 Broker。P4 正在增加不可变复盘快照、Windows runner 和私有只读 Dashboard。

## 当前范围

- P0：项目治理、架构和验收规范。
- P1：TDX／THS 数据适配、原始事件落地和数据质量检查。
- P2：现金账户、`T+1`、整手、费用、涨跌停、限价及部分成交。
- P3：20 日动量＋60 日趋势策略、独立风控、持久化 OMS、账本、对账和历史回放。
- P4：观测事实、`ReviewBundle`、运行状态、响应式 Dashboard、私网同步、CI、备份与驻留化。

禁止真实下单；前向交易只允许连接已明确确认的 TDX 模拟账户。不支持科创板、创业板、北交所、ST、新股特殊阶段、ETF、可转债、融资融券和集合竞价。

## 环境

- Windows 11
- Python 3.13
- 已启动并登录支持 TQ 的通达信金融终端
- 前向运行通过量化模拟客户端自带的 `PYPlugins/user/tqcenter.py` 本地 SDK 连接；旧版客户端仍可使用 `http://127.0.0.1:17709/` HTTP。

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
# 验收完成前，paper-execute 会因默认禁用而拒绝执行。
python -m astock.cli runner --once --env-file .env.demo

cd web
npm ci
npm test
npm run build
```

`doctor` 只报告配置项是否存在和接口能力，不输出密钥。详细运行与验收见 `docs/OPERATIONS.md` 和 `docs/ACCEPTANCE.md`。

`replay` 使用临时 SQLite 数据库执行策略、风控、OMS、模拟成交与逐日对账，不会触发真实交易，也不会改写正式账户数据。

P4 使用研究报告哈希隔离每一代观察账户，默认禁止自动模拟执行。私有 Dashboard 只展示服务器接收的 `ReviewBundle` 和 `LiveStatus`，不提供下单、撤单或策略修改能力。Bundle 规范见 `docs/REVIEW_BUNDLE.md`。

稳健策略研究结论见 `docs/STRATEGY_RESEARCH_V4.md`，隔离的激进研究结论见 `docs/STRATEGY_RESEARCH_V5_AGGRESSIVE.md`，申万一级行业中性与轮动研究见 `docs/STRATEGY_RESEARCH_V6_INDUSTRY.md`。三个稳健模拟策略使用完全隔离的 100000 元账户，另设一个 100000 元组合观察账户；V5／V6 均未新增合格模拟候选，所有结果都不是实盘策略。
