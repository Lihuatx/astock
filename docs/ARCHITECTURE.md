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

## P4 观测与复盘目标架构

> 本节描述 P4 必须达到的目标架构，不表示当前实现已经通过验收。实际状态和审计阻塞以 `ROADMAP.md` 与 `docs/P4_AUDIT_2026-07-12.md` 为准。

```text
Account SQLite / Ledger ─> Observability DB ─> SnapshotBuilder
                                                   ├─> ReviewBundle
                                                   └─> LiveStatus

Windows runner ── outbound HTTPS over Tailscale ─> FastAPI
                                                      ├─> server.db / bundles
                                                      └─> React Dashboard
```

- Windows 本机仍是交易事实源，服务器是只读查询镜像。
- `strategy_set_id` 绑定规范化策略集合和研究报告哈希；`account_id` 固定包含策略集合、策略和账户代次。
- `run_id`、`account_id`、信号／计划 ID 和订单 ID 必须把策略、风险、订单、成交、费用和对账事件连成可审计链。
- 全局事件 ID 必须包含账户作用域；相同 ID、相同规范内容视为幂等，相同 ID、不同内容必须拒绝，禁止静默忽略。
- `ReviewBundle` 绑定 schema、策略集合、Git SHA、研究报告哈希、数据截止时间和来自持久化 RunRecord 的生成时间。所有业务字段参与内容哈希，同一输入重复生成必须得到相同规范 JSON 字节。
- `LiveStatus` 只保存正在变化的心跳、任务、数据源、同步和告警状态；每版状态拥有独立 `status_id` 和不可变本地 payload，服务器再按 `source_id` 派生最新视图。
- 本地同步 Outbox 以 Bundle ID 或 Status ID 唯一；断网期间不得覆盖尚未发送的版本，恢复后按版本幂等补传。
- 浏览器不得直接读取本机 SQLite、研究 JSON 或待执行信号文件。
- 服务器故障和同步失败不阻断本地任务；交易安全异常继续 fail closed。
- Dashboard 不提供任何交易控制能力。

## P4 服务与存储边界

- FastAPI 在 lifespan 内创建和关闭服务存储；SQLite 使用每操作独立连接或明确串行写锁，不共享无保护连接处理并发请求。
- `/healthz` 可匿名访问；Bundle／状态上传只接受独立 Bearer token；SPA、`/assets/*` 和所有浏览器查询 API 统一校验 Tailscale 用户允许列表。
- 服务器基于自身 `received_at` 计算新鲜度，正常同步目标小于 60 秒，超过 90 秒生成严重 `RUNNER_OFFLINE` 告警。
- 浏览器只展示 Bundle 和服务器状态，不重新计算权益、回撤、费用、成交或对账指标。
- 在线备份批次同时包含 SQLite backup、不可变 Bundle、版本信息和逐文件 SHA256 manifest；恢复必须在独立空目录重建可查询服务。
- 容器主机端只监听 `127.0.0.1:18080`，由 Tailscale Serve 提供私网 HTTPS；禁止 Funnel 和公网端口。

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
