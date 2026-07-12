# 架构

```text
TdxMarketData ──┐
                ├─> Normalized Market Events ─> StrategyCore
ThsReference ───┘                                ↓
                                             RiskEngine
                                                 ↓
                                         Persistent OMS/Outbox
                                                 ↓
                                         AShareSimBroker
                                                 ↓
                                        Ledger/Reconciliation
```

## P4 观测与复盘

```text
Account SQLite / Ledger ─> Observability DB ─> SnapshotBuilder
                                                   ├─> ReviewBundle
                                                   └─> LiveStatus

Windows runner ── outbound HTTPS over Tailscale ─> FastAPI
                                                      ├─> server.db / bundles
                                                      └─> React Dashboard
```

- Windows 本机仍是交易事实源，服务器是只读查询镜像。
- `ReviewBundle` 绑定 schema、策略集合、Git SHA、研究报告哈希和数据截止时间，生成后不得原地修改。
- `LiveStatus` 只保存正在变化的心跳、任务、数据源、同步和告警状态。
- 浏览器不得直接读取本机 SQLite、研究 JSON 或待执行信号文件。
- 服务器故障和同步失败不阻断本地任务；交易安全异常继续 fail closed。
- Dashboard 不提供任何交易控制能力。

## 设计原则

1. TDX 是盘中主源，THS 只校验，不自动切换后继续下单。
2. 策略输出目标和意图；风控、OMS、Broker 分层独立。
3. Outbox 先落库再送 Broker，`client_order_id` 全链路幂等。
4. 现金、冻结资金、持仓批次、可卖数量和费用分别记账。
5. 所有外部输入先保存原始 JSONL，再转换成领域对象。
6. 行情过期、订单未知或账实不符时 fail closed。
7. 研究框架使用滚动窗口计算横截面因子，T 日收盘生成目标，T＋1 开盘执行。
8. 多策略账户完全隔离，策略比较不共享现金、订单、持仓或成交状态。
9. 当前观察集使用研究报告哈希生成 `strategy_set_id`，历史账户登记为 legacy，不移动或覆盖。
10. 生产服务只监听本机回环地址，由 Tailscale Serve 提供私网 HTTPS 和用户身份头。
