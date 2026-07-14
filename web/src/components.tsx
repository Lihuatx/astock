import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { Account, Alert, ReviewBundle } from "./types";

echarts.use([LineChart, GridComponent, TooltipComponent, SVGRenderer]);

export function Money({ value }: { value: string | number }) {
  return <>{Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</>;
}

export function StatusPill({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return <span className={`pill ${ok ? "ok" : "bad"}`}>{ok ? "✓" : "!"} {children}</span>;
}

export function AlertList({ alerts }: { alerts: Alert[] }) {
  if (!alerts.length) return <div className="empty">当前没有活动告警</div>;
  return <div className="alert-list">{alerts.map((alert, index) => (
    <article className={`alert ${alert.severity.toLowerCase()}`} key={alert.alert_id ?? `${alert.code}-${index}`}>
      <strong>{alert.severity === "CRITICAL" ? "严重" : alert.severity === "WARNING" ? "警告" : "提示"}</strong>
      <div><b>{alert.code}</b><p>{alert.message}</p></div>
    </article>
  ))}</div>;
}

export function AccountCard({ account }: { account: Account }) {
  const change = Number(account.equity) - 100000;
  return <article className="account-card">
    <div className="eyebrow">{account.strategy}</div>
    <h3><Money value={account.equity} /></h3>
    <div className={change >= 0 ? "positive" : "negative"}>{change >= 0 ? "▲" : "▼"} <Money value={Math.abs(change)} /></div>
    <dl><div><dt>现金</dt><dd><Money value={account.cash} /></dd></div><div><dt>持仓</dt><dd>{Object.keys(account.positions).length} 只</dd></div></dl>
    <StatusPill ok={account.reconciliation_ok}>{account.reconciliation_ok ? "对账通过" : "对账异常"}</StatusPill>
  </article>;
}

export function EquityChart({ bundle, accountId }: { bundle: ReviewBundle; accountId?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim();
    const border = styles.getPropertyValue("--border").trim();
    const muted = styles.getPropertyValue("--muted").trim();
    const rows = bundle.equity_curve.filter((item) => !accountId || item.account_id === accountId);
    chart.setOption({
      grid: { left: 48, right: 16, top: 24, bottom: 38 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: rows.map((item) => item.trading_day), boundaryGap: false, axisLine: { lineStyle: { color: border } }, axisLabel: { color: muted } },
      yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: border } }, axisLabel: { color: muted } },
      series: [{ type: "line", data: rows.map((item) => Number(item.equity)), smooth: true, showSymbol: rows.length < 20, lineStyle: { color: accent, width: 2 }, areaStyle: { color: accent, opacity: .08 } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [bundle, accountId]);
  return <div className="chart" ref={ref} aria-label="账户权益曲线" />;
}
