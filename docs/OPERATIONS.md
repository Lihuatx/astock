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

- 当前没有真实券商交易适配器，也不调用 TDX 交易函数。
- `.env.demo` 只在运行时加载，密钥不会进入输出、原始事件或 Git。
- P1 盘中行情新鲜度与断线恢复必须在交易时段另行执行硬验收。

## P4 本地观测与复盘

初始化当前研究报告对应的版本化观察集：

```powershell
$env:PYTHONPATH='src'
python -m astock.cli paper-prepare
```

该命令使用研究报告 SHA256 生成 `strategy_set_id`，在 `data/paper/sets/` 下创建新账户代次，并将原有账户登记为 legacy。不会移动或删除旧账户。

生成信号后，runner 会在收盘阶段保存账户快照、`ReviewBundle` 和 `LiveStatus`。自动模拟执行默认关闭；只有设置 `ASTOCK_PAPER_EXECUTION_ENABLED=true` 才会运行执行任务，该配置在完成 5 分钟成交复核和首次调仓验收前禁止启用。

5 分钟复核与首次调仓的固定数据范围、执行窗口、成交量参与率、数值门槛、失败分类和证据要求见 `docs/INTRADAY_EXECUTION_REVIEW.md`。复核必须先保存原始 TDX 响应，再生成可重复的结构化结果和 Markdown 报告；分钟数据缺失不得用日线静默填补。首次调仓期间继续保持自动执行关闭，只允许人工运行和逐步核对。

```powershell
python -m astock.cli review-intraday --days 100 --refresh --env-file .env.demo
```

命令退出码为 `0` 表示三个策略全部通过；退出码为 `1` 表示复核已完成但至少一个策略未通过；行情请求或输入错误返回 `2`。TDX 本机缺少历史分钟线时，先在通达信客户端下载对应盘后数据，再使用 `--refresh` 重跑；不得改用日线补齐。

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

生产环境主机只允许监听 `127.0.0.1:18080`，容器内部端口可以独立设置，由 Tailscale Serve 提供私网 HTTPS。前端查询依赖 `Tailscale-User-Login` 允许列表；上传使用独立 Bearer token。不得启用 Funnel，也不得将 Dashboard 端口直接暴露到公网。

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
