# ReviewBundle v1／v2

`ReviewBundle` 是交易事实的不可变发布快照，不替代账户 SQLite 和 Ledger。Dashboard、离线报告和后续公开内容只能消费 Bundle，不得自行重算交易指标。

## 身份与完整性

- `schema_version`：新发布包为 `2`；验证器和 Dashboard 必须继续接受既有 `1`。
- `strategy_set_id`：`set-` 加研究报告 SHA256 前 16 位。
- `generated_at`：取生成该 Bundle 的已持久化 RunRecord 完成时间，不得在重建时读取新的墙钟时间。
- `content_sha256`：对包含 `generated_at` 的全部业务事实执行规范 JSON SHA256；只排除由哈希派生的 `bundle_id` 和 `content_sha256`。
- `bundle_id`：`review-<trading_day>-<content_sha256 前 16 位>`。
- 同一持久化输入重复生成必须得到完全相同的 UTF-8 规范 JSON 字节、`content_sha256` 和 `bundle_id`。
- 同一 `bundle_id` 的不同字节必须拒绝；已有 Bundle 不得原地覆盖。

## 事实内容

- 数据血缘：交易日、Git SHA、行情截止时间、研究报告哈希和策略集合。
- v2 展示事实：`trade_plan` 保存下一交易日、计划项和取消条件；`execution_review` 保存 TDX 事实版本、计划／发送／确认／成交数量与差异；`activity` 保存结构化任务和错误时间线；`research_index` 保存关联 ResearchBundle ID。

## ResearchBundle v1

`ResearchBundle` 与每日 Bundle 分离，避免把长报告正文复制进每个交易日快照。字段包括 `report_id`、`category`、`title`、`summary`、`conclusion`、`status`、`source_path`、`source_commit`、`data_cutoff`、`published_at`、`body_markdown` 和 `content_sha256`。内容哈希和 ID 校验通过后才允许写入、同步和索引。
- 账户：账户代次、现金、冻结、持仓、权益、费用、回撤和对账状态。
- 决策链：信号、选股解释、风险决定、订单、成交、费用和对账事件。
- 展示：权益序列、健康状态、活动告警、已知限制和模拟盘声明。

`LiveStatus v1` 与 Bundle 分离，只保存 runner、数据源、任务、同步积压和当前告警。每版状态必须包含独立 `status_id`、`source_id` 和生成序号／时间，保存为不可变本地 payload；服务器按 `source_id` 派生最新视图，但不能让新状态覆盖尚未同步的旧版本，也不能修改历史 Bundle。
