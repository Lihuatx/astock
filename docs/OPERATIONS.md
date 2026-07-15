# P0～P4 操作说明

## 通达信准备

1. 启动支持「TQ策略」的通达信客户端并登录行情。
2. 确认 `127.0.0.1:17709` 已监听。
3. 在盘后数据下载中获取全 A 股和主要指数日线。
4. 不登录真实证券账户，不调用交易函数。

## 检查

```powershell
$env:PYTHONPATH='src'
python -m astock.cli doctor --env-file .env.demo
```

## 历史回放

```powershell
$env:PYTHONPATH='src'
python -m astock.cli replay --symbol 000001.SZ --start 20250101 --end 20260710 --env-file .env.demo
```

回放使用临时 SQLite 数据库，退出后自动清理；外部原始响应写入 `data/raw/`。运行数据目录均被 Git 忽略。

输出中的 `all_days_reconciled=true` 表示现金冻结、持仓批次、订单和成交数量在所有回放日均通过结构对账。

## 安全边界

- 当前禁止真实券商交易适配器。TDX 交易函数只允许由模拟交易适配器在已验证的模拟账户会话中调用。
- `.env.demo` 只在运行时加载，密钥不会进入输出、原始事件或 Git。
- P1 盘中行情新鲜度与断线恢复必须在交易时段另行执行硬验收。

## P4 本地观测与复盘

初始化当前研究报告对应的版本化观察集：

```powershell
$env:PYTHONPATH='src'
python -m astock.cli paper-prepare
```

该命令使用研究报告 SHA256 生成 `strategy_set_id`，在 `data/paper/sets/` 下创建新账户代次，并将原有账户登记为 legacy。不会移动或删除旧账户。

`paper-signals` 生成计划前必须把市场面板和点时基本面刷新到最近一个已经完整收盘的交易日，但不得重跑或替换冻结研究报告中的策略集合。TDX 模拟账户作为订单、成交、资金和持仓权威源，本地 SQLite 只保存发送 Outbox、事实镜像、错误日志和复盘差异。盘中行情质量、单笔接口错误、订单未知或账实差异只记录日志并继续处理其他模拟订单；每日收盘后统一复盘，不得用本地模型成交覆盖 TDX 事实。

生成信号后，runner 会在收盘阶段拉取 TDX 模拟账户事实、生成差异报告并保存账户快照、`ReviewBundle` 和 `LiveStatus`。自动模拟执行默认关闭；只有验证模拟账户类型、交易协议和重启幂等后，才允许设置 `ASTOCK_PAPER_EXECUTION_ENABLED=true`。5 分钟复核继续用于成交质量诊断，但不阻止前向模拟。

自动模拟委托只会在工作日连续竞价窗口 `09:35～11:25`、`13:05～14:55` 领取当天计划；午间、收盘后和非工作日不会发送。收盘后仍会执行 TDX 日终事实镜像和后验复盘。

TDX 模拟交易配置仅通过进程环境或本机 `.env.demo` 提供。新量化模拟客户端设置 `ASTOCK_TDX_PLUGIN_DIR` 指向其 `PYPlugins/user` 目录；`ASTOCK_TDX_SIMULATION_CONFIRMED=true` 表示当前登录会话已由 Yancey 确认为模拟账户；`ASTOCK_PAPER_EXECUTION_ENABLED=true` 启用 runner 发送订单。`ASTOCK_TDX_SIM_ACCOUNT` 可选，未配置时按官方协议使用当前登录账户。程序不得输出账号值。普通实盘账户下单返回的 `Value=1` 会被拒绝；只有模拟账户自动下单返回 `Value=2` 且存在 `Wtbh` 时才写为 `ACK`。未配置 SDK 目录时保留 `TDX_BASE_URL` HTTP 兼容路径。

集合竞价阶段 TDX 可能返回 `last=0`，但买一和卖一均为有效正价格；doctor 在此情况下按行情连接可用处理。runner 的同类任务每日最多尝试 6 次、失败后至少间隔 10 分钟，每次失败使用独立事件 ID，避免重试错误内容变化破坏不可变审计事件。

官方协议依据：

- [获取资金账户句柄](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h7k4k5tk6q64.html)
- [交易执行函数](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h7k5j4drr928.html)
- [查询账户委托信息](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h7k4rp481gt4.html)
- [查询账户资产信息](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h84fvcjulrnc.html)
- [查询账户持仓信息](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1h7k4iqb1grk4/mindoc-1h7k5ar9kc508.html)

5 分钟复核的固定数据范围、执行窗口、成交量参与率、数值门槛、失败分类和证据要求见 `docs/INTRADAY_EXECUTION_REVIEW.md`。复核必须先保存 TdxQuant 或 `pytdx` 原始响应，再生成可重复的结构化结果和 Markdown 报告；分钟数据缺失不得用日线静默填补。复核失败进入每日质量报告，不再阻止 TDX 模拟账户下单。

```powershell
python -m astock.cli review-intraday --days 100 --refresh --env-file .env.demo
```

命令退出码为 `0` 表示三个策略全部通过；退出码为 `1` 表示复核已完成但至少一个策略未通过；行情请求或输入错误返回 `2`。命令先读取 TdxQuant，本机历史不足时再通过 optional dependency `pytdx==1.72` 从通达信公开行情服务器分页补齐；不得改用日线补齐。`pytdx` 上游已归档，只允许用于历史复核，不得引入盘中 runner。

```powershell
python -m astock.cli runner --once
python -m astock.cli runner
```

从 Bundle 生成无需联网的单文件复盘报告：

```powershell
python -m astock.cli review-build --bundle data/review/bundles/YYYY-MM-DD/<bundle_id>.json
```

## P4 Dashboard 本地验证

```powershell
cd web
npm ci
npm test
npm run build
npm run build:report
cd ..
$env:ASTOCK_ALLOWED_TAILSCALE_USERS='local@example.com'
$env:ASTOCK_SYNC_TOKEN='local-test-token'
python -m astock.cli dashboard --port 18080
```

新发布的 `ReviewBundle v2` 包含下一交易日计划、当日执行复盘、结构化活动和研究索引。Runner 同时把仓库中已确认的策略、行业与专题 Markdown 生成独立 `ResearchBundle`；报告正文不会被大模型改写，内容变化才产生新版本。字段、路由和只读边界见 `docs/DASHBOARD.md`。

生产环境主机只允许监听 `127.0.0.1:18080`。本机 CLI 默认同样监听回环地址；Docker 镜像通过 `ASTOCK_DASHBOARD_HOST=0.0.0.0` 监听容器网络，再由 Compose 严格映射到宿主机回环地址。Tailscale Serve 提供私网 HTTPS。前端查询依赖 `Tailscale-User-Login` 允许列表；上传使用独立 Bearer token。不得启用 Funnel，也不得将 Dashboard 端口直接暴露到公网。

目标 Tailscale Serve 配置为转发到 `http://127.0.0.1:18080`。执行 Docker、Tailscale、服务器目录、端口或系统服务变更前，必须先说明风险并获得单独确认。

GitHub Actions 只允许执行 Python 测试、前端检查／构建和不推送的 Docker build。任何镜像发布、部署或 registry 登录 workflow 都不属于 P4 自动验收范围，未经确认不得运行。

## P4 备份

`dashboard-backup` 使用 SQLite online backup，不直接复制活动 WAL 文件：

```powershell
python -m astock.cli dashboard-backup --target backups/server-YYYYMMDD.db
```

P4 可恢复备份必须把 SQLite backup、不可变 Bundle、版本信息和逐文件 SHA256 manifest 绑定为同一批次，并在独立空目录完成真实恢复；只恢复数据库索引不算通过。

Docker、Tailscale、服务器目录和定时备份属于系统配置，必须逐步确认后才能在腾讯云服务器执行。

Windows 常驻化使用 `deploy/windows/install-runner.ps1` 注册单个开机任务，并依赖观测 SQLite lease 阻止重复 runner。该脚本会修改 Windows 计划任务，执行前必须单独确认。
