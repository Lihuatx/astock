# P0～P3 操作说明

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
