# ReviewBundle v1

`ReviewBundle` 是交易事实的不可变发布快照，不替代账户 SQLite 和 Ledger。Dashboard、离线报告和后续公开内容只能消费 Bundle，不得自行重算交易指标。

## 身份与完整性

- `schema_version`：当前固定为 `1`。
- `strategy_set_id`：`set-` 加研究报告 SHA256 前 16 位。
- `content_sha256`：对排除 envelope 字段后的事实内容执行规范 JSON SHA256。
- `bundle_id`：`review-<trading_day>-<content_sha256 前 16 位>`。
- envelope 字段为 `schema_version`、`bundle_id`、`content_sha256`、`generated_at`。
- 同一 `bundle_id` 的不同内容必须拒绝；已有 Bundle 不得原地覆盖。

## 事实内容

- 数据血缘：交易日、Git SHA、行情截止时间、研究报告哈希和策略集合。
- 账户：账户代次、现金、冻结、持仓、权益、费用、回撤和对账状态。
- 决策链：信号、选股解释、风险决定、订单、成交、费用和对账事件。
- 展示：权益序列、健康状态、活动告警、已知限制和模拟盘声明。

`LiveStatus v1` 与 Bundle 分离，只保存 runner、数据源、任务、同步积压和当前告警。它可以更新，但不能修改历史 Bundle。
