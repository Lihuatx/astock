import { NavLink, Route, Routes, useParams } from "react-router-dom";
import { useCallback } from "react";
import { api } from "./api";
import { usePolling } from "./hooks";
import { AccountCard, AlertList, EquityChart, Money, StatusPill } from "./components";
import { ReviewView } from "./ReviewView";
import type { Overview, ReviewBundle } from "./types";

const nav = [
  ["/", "总览"], ["/orders", "订单"], ["/reviews", "复盘"], ["/health", "健康"], ["/alerts", "告警"],
];

function Shell() {
  return <div className="shell">
    <aside><div className="brand"><span>A</span><div><b>astock</b><small>PRIVATE OBSERVER</small></div></div><nav>{nav.map(([path, label]) => <NavLink end={path === "/"} to={path} key={path}>{label}</NavLink>)}</nav><div className="aside-note">模拟盘／观察集<br />不构成投资建议</div></aside>
    <div className="content"><Routes><Route path="/" element={<OverviewPage />} /><Route path="/accounts/:id" element={<AccountPage />} /><Route path="/strategies/:id" element={<StrategyPage />} /><Route path="/orders" element={<OrdersPage />} /><Route path="/reviews" element={<ReviewsPage />} /><Route path="/reviews/:id" element={<ReviewPage />} /><Route path="/health" element={<HealthPage />} /><Route path="/alerts" element={<AlertsPage />} /></Routes></div>
    <nav className="mobile-nav">{nav.slice(0, 5).map(([path, label]) => <NavLink end={path === "/"} to={path} key={path}>{label}</NavLink>)}</nav>
  </div>;
}

function Frame({ title, eyebrow, children }: { title: string; eyebrow: string; children: React.ReactNode }) {
  return <main className="page"><header className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1></div><span className="mode">只读</span></header>{children}</main>;
}

function Loading({ error }: { error?: string | null }) { return <div className="loading">{error ?? "正在读取观测事实…"}</div>; }

function OverviewPage() {
  const loader = useCallback(() => api.overview(), []);
  const { data, error } = usePolling<Overview>(loader);
  if (!data) return <Frame title="运行总览" eyebrow="PRIVATE OBSERVER"><Loading error={error} /></Frame>;
  const live = data.live_status[0];
  return <Frame title="运行总览" eyebrow={`数据日期 ${data.bundle?.trading_day ?? "尚无快照"}`}>
    <section className="hero-status"><div><span className="pulse" /><div><small>Windows runner</small><h2>{live?.runner.status ?? "未连接"}</h2></div></div><StatusPill ok={Boolean(live) && data.alerts.every((a) => a.severity !== "CRITICAL")}>{data.alerts.length ? `${data.alerts.length} 项告警` : "系统正常"}</StatusPill></section>
    {data.bundle ? <><section className="account-grid">{data.bundle.accounts.map((account) => <NavLink className="account-link" to={`/accounts/${encodeURIComponent(account.account_id)}`} key={account.account_id}><AccountCard account={account} /></NavLink>)}</section><section className="panel"><div className="section-title"><h2>组合权益</h2><span>30 秒刷新</span></div><EquityChart bundle={data.bundle} /></section></> : <div className="empty big">尚未接收到 ReviewBundle</div>}
    <section className="panel"><div className="section-title"><h2>当前告警</h2><span>仅站内展示</span></div><AlertList alerts={data.alerts.filter((item) => item.status !== "RESOLVED")} /></section>
  </Frame>;
}

function AccountPage() {
  const { id = "" } = useParams();
  const loader = useCallback(() => api.overview(), []);
  const { data, error } = usePolling(loader);
  const account = data?.bundle?.accounts.find((item) => item.account_id === id);
  if (!data || !account) return <Frame title="账户" eyebrow="ACCOUNT"><Loading error={error ?? (data ? "账户不存在" : null)} /></Frame>;
  return <Frame title={account.strategy} eyebrow={`${account.status} · 第 ${account.generation} 代账户`}><section className="account-grid"><AccountCard account={account} /><article className="panel metric-panel"><div><small>累计费用</small><h2><Money value={account.fees} /></h2></div><div><small>冻结资金</small><h2><Money value={account.frozen_cash} /></h2></div></article></section><section className="panel"><h2>权益与回撤</h2><EquityChart bundle={data.bundle as ReviewBundle} accountId={id} /></section><section className="panel"><h2>当前持仓</h2>{Object.entries(account.positions).length ? <table><tbody>{Object.entries(account.positions).map(([symbol, quantity]) => <tr key={symbol}><td>{symbol}</td><td>{quantity} 股</td></tr>)}</tbody></table> : <div className="empty">当前空仓</div>}</section></Frame>;
}

function StrategyPage() {
  const { id = "" } = useParams(); const loader = useCallback(() => api.overview(), []); const { data, error } = usePolling(loader);
  const selected = data?.bundle?.strategy_set.selected?.find((item) => item.strategy === id);
  return <Frame title={id || "策略"} eyebrow={data?.bundle?.strategy_set_id ?? "STRATEGY SET"}>{selected ? <pre className="json-card">{JSON.stringify(selected, null, 2)}</pre> : <Loading error={error ?? "策略配置不存在"} />}</Frame>;
}

function OrdersPage() {
  const loader = useCallback(() => api.overview(), []); const { data, error } = usePolling(loader);
  const bundle = data?.bundle;
  return <Frame title="订单与成交" eyebrow="SIGNAL → RISK → ORDER → FILL">{!bundle ? <Loading error={error} /> : <section className="panel"><div className="metric-row"><span>信号</span><b>{bundle.signals.length}</b></div><div className="metric-row"><span>风险决定</span><b>{bundle.risk_decisions.length}</b></div><div className="metric-row"><span>订单</span><b>{bundle.orders.length}</b></div><div className="metric-row"><span>成交</span><b>{bundle.fills.length}</b></div>{bundle.orders.length ? <pre className="json-card">{JSON.stringify(bundle.orders, null, 2)}</pre> : <div className="empty">尚无订单，当前账户仅用于执行链观察</div>}</section>}</Frame>;
}

function ReviewsPage() {
  const loader = useCallback(() => api.reviews(), []); const { data, error } = usePolling(loader);
  return <Frame title="交易日复盘" eyebrow="IMMUTABLE REVIEW BUNDLES">{!data ? <Loading error={error} /> : <section className="review-list">{data.map((item) => <NavLink to={`/reviews/${item.bundle_id}`} key={item.bundle_id}><b>{item.trading_day}</b><span>{item.strategy_set_id}</span><code>{item.content_sha256.slice(0, 12)}…</code></NavLink>)}</section>}</Frame>;
}

function ReviewPage() { const { id = "" } = useParams(); const loader = useCallback(() => api.review(id), [id]); const { data, error } = usePolling(loader, 300_000); return data ? <ReviewView bundle={data} /> : <Frame title="交易日复盘" eyebrow="REVIEW"><Loading error={error} /></Frame>; }

function HealthPage() { const loader = useCallback(() => api.health(), []); const { data, error } = usePolling(loader); return <Frame title="系统健康" eyebrow="RUNNER · SOURCES · SYNC">{!data ? <Loading error={error} /> : <><section className="panel"><h2>数据源与 runner</h2><pre className="json-card">{JSON.stringify(data.sources, null, 2)}</pre></section><AlertList alerts={data.alerts} /></>}</Frame>; }
function AlertsPage() { const loader = useCallback(() => api.alerts(), []); const { data, error } = usePolling(loader); return <Frame title="告警中心" eyebrow="ACTIVE / RESOLVED">{data ? <AlertList alerts={data} /> : <Loading error={error} />}</Frame>; }

export default Shell;
