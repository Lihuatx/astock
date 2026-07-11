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

## 设计原则

1. TDX 是盘中主源，THS 只校验，不自动切换后继续下单。
2. 策略输出目标和意图；风控、OMS、Broker 分层独立。
3. Outbox 先落库再送 Broker，`client_order_id` 全链路幂等。
4. 现金、冻结资金、持仓批次、可卖数量和费用分别记账。
5. 所有外部输入先保存原始 JSONL，再转换成领域对象。
6. 行情过期、订单未知或账实不符时 fail closed。

