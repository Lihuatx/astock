import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useParams } from "react-router-dom";
import { api } from "./api";
import { usePolling } from "./hooks";
import { EquityChart, Money } from "./components";
import { ReviewView } from "./ReviewView";
import type { Account, Alert, Overview, ResearchBundle, ResearchSummary, ReviewBundle } from "./types";

const nav = [
  ["/", "总览", "览"],
  ["/trade-plan", "交易计划", "计"],
  ["/account", "账户", "账"],
  ["/execution", "执行复盘", "复"],
  ["/research", "研究库", "研"],
  ["/system", "系统状态", "系"],
] as const;

const categoryNames: Record<string, string> = { STRATEGY: "策略", INDUSTRY: "行业", TOPIC: "专题" };
const statusNames: Record<string, string> = { PASS: "通过", REJECT: "拒绝", OBSERVE: "观察", READY: "就绪", PASSED: "通过", ATTENTION: "关注", UNAVAILABLE: "不可用" };

function Shell() {
  return <div className="app-shell">
    <aside className="sidebar">
      <NavLink className="brand" to="/"><span className="brand-mark">QL</span><span>Quant Ledger</span></NavLink>
      <div className="nav-group"><p className="nav-label">交易工作台</p><nav className="side-nav">{nav.map(([path, label, icon]) => <NavLink end={path === "/"} className="nav-link" to={path} key={path}><span className="nav-icon">{icon}</span>{label}</NavLink>)}</nav></div>
      <div className="sidebar-foot"><div className="system-mini"><span className="status-dot" /><strong>只读模拟盘</strong></div><small>TDX 事实源</small></div>
    </aside>
    <div className="page-main"><header className="mobile-header"><NavLink className="brand" to="/"><span className="brand-mark">QL</span><span>Quant Ledger</span></NavLink><span className="readonly-badge">只读</span></header><Routes>
      <Route path="/" element={<OverviewPage />} />
      <Route path="/trade-plan" element={<TradePlanPage />} />
      <Route path="/account" element={<AccountPage />} />
      <Route path="/accounts/:id" element={<AccountPage />} />
      <Route path="/execution" element={<ExecutionPage />} />
      <Route path="/research" element={<ResearchPage />} />
      <Route path="/system" element={<SystemPage />} />
      <Route path="/reviews/:id" element={<ReviewPage />} />
    </Routes></div>
    <nav className="mobile-nav">{nav.map(([path, label, icon]) => <NavLink end={path === "/"} to={path} key={path}><span>{icon}</span>{label.replace("交易", "").replace("执行", "").replace("状态", "")}</NavLink>)}</nav>
  </div>;
}

function Frame({ title, eyebrow, subtitle, actions, children }: { title: string; eyebrow: string; subtitle: string; actions?: React.ReactNode; children: React.ReactNode }) {
  return <main className="page-wrap"><header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1 className="page-title">{title}</h1><p className="page-subtitle">{subtitle}</p></div>{actions && <div className="header-actions">{actions}</div>}</header>{children}<footer className="page-footer">A 股模拟盘观察数据，不构成投资建议。</footer></main>;
}

function State({ error, text = "正在读取观测事实…" }: { error?: string | null; text?: string }) {
  return <div className={`state-card ${error ? "error" : ""}`}>{error ?? text}</div>;
}

function useOverview() {
  const loader = useCallback(() => api.overview(), []);
  return usePolling<Overview>(loader);
}

function Badge({ value }: { value: string }) {
  const tone = ["PASS", "PASSED", "READY", "ONLINE"].includes(value) ? "positive" : ["REJECT", "CRITICAL", "ERROR"].includes(value) ? "danger" : "warning";
  return <span className={`badge badge-${tone}`}>{statusNames[value] ?? value}</span>;
}

function Metric({ label, value, note, tone = "" }: { label: string; value: React.ReactNode; note?: string; tone?: string }) {
  return <article className="metric-card"><div className="metric-label">{label}</div><div className={`metric-value ${tone}`}>{value}</div>{note && <div className="metric-note">{note}</div>}</article>;
}

function total(accounts: Account[], field: keyof Pick<Account, "equity" | "cash" | "market_value" | "fees">) {
  return accounts.reduce((sum, item) => sum + Number(item[field] || 0), 0);
}

function downloadJson(name: string, value: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url);
}

function OverviewPage() {
  const { data, error } = useOverview();
  if (!data) return <Frame title="运行总览" eyebrow="PRIVATE OBSERVER" subtitle="账户、计划、执行和系统事实的一页摘要。"><State error={error} /></Frame>;
  if (!data.bundle) return <Frame title="运行总览" eyebrow="数据日期 · 尚无快照" subtitle="先看账户和明日动作，再检查执行差异与运行异常。"><State text="尚未接收到 ReviewBundle。账户、计划和执行数据均不补造。" /><AlertSection alerts={data.alerts} /></Frame>;
  const bundle = data.bundle; const accounts = bundle.accounts; const plan = bundle.trade_plan; const review = bundle.execution_review; const live = data.live_status[0];
  return <Frame title="运行总览" eyebrow={`数据日期 · ${bundle?.trading_day ?? "尚无快照"}`} subtitle="先看账户和明日动作，再检查执行差异与运行异常。" actions={bundle && <button className="button" onClick={() => downloadJson(`${bundle.bundle_id}.json`, bundle)}>导出快照</button>}>
    <section className="metric-grid">
      <Metric label="观察账户权益" value={<><Money value={total(accounts, "equity")} /><small> 元</small></>} note={`${accounts.length} 个当前账户`} />
      <Metric label="可用现金" value={<><Money value={total(accounts, "cash")} /><small> 元</small></>} note="各策略账户合计" />
      <Metric label="明日计划标的" value={plan?.items.reduce((sum, item) => sum + item.symbol_count, 0) ?? "—"} note={plan?.execution_date ?? "尚无计划"} />
      <Metric label="执行复盘" value={review ? statusNames[review.status] ?? review.status : "—"} note={review?.captured_at ? formatTime(review.captured_at) : "尚无 TDX 日终事实"} tone={review?.status === "ATTENTION" ? "negative" : "positive"} />
    </section>
    <section className="section grid-main">
      <article className="card card-strong"><div className="card-header"><div><p className="plan-date">下一交易日 · {plan?.execution_date ?? "待生成"}</p><h2 className="plan-thesis">{plan?.status === "READY" ? (plan.items.length ? `计划覆盖 ${plan.items.length} 个策略。` : "当前计划为空仓观察，不创建委托。") : "尚未收到下一交易日计划。"}</h2></div>{plan && <Badge value={plan.status} />}</div>
        <div className="plan-list">{plan?.items.length ? plan.items.map((item) => <div className="plan-row" key={item.strategy}><div><strong>{item.strategy}</strong><p>{item.symbols.join("、") || "无标的"}</p></div><span className="num">{item.symbol_count} 只</span></div>) : <div className="empty">{plan?.skipped?.length ? `${plan.skipped.length} 个策略因调仓周期或选股条件跳过。` : "暂无计划事实。"}</div>}</div>
        <NavLink className="text-link" to="/trade-plan">查看完整计划 →</NavLink>
      </article>
      <aside className="card"><div className="card-header"><div><h2 className="card-title">运行准备度</h2><p className="card-note">只展示，不阻断模拟委托</p></div><Badge value={live?.runner.status ?? "OFFLINE"} /></div>
        <div className="detail-list"><Detail label="Runner" value={live?.runner.status ?? "未连接"} /><Detail label="自动模拟执行" value={live?.runner.paper_execution_enabled ? "已启用" : "关闭"} /><Detail label="同步积压" value={`${live?.sync.pending ?? 0} 项`} /><Detail label="活动告警" value={`${data.alerts.filter((item) => item.status !== "RESOLVED").length} 项`} /></div>
      </aside>
    </section>
    <section className="section"><div className="section-heading"><div><h2>账户快照</h2><p>TDX 与本地策略账户的最近已发布事实。</p></div></div>{accounts.length ? <div className="account-grid">{accounts.map((account) => <NavLink to={`/accounts/${encodeURIComponent(account.account_id)}`} className="account-card" key={account.account_id}><p className="eyebrow">{account.strategy}</p><h3><Money value={account.equity} /></h3><div className="account-meta"><span>现金 <b><Money value={account.cash} /></b></span><span>持仓 <b>{Object.keys(account.positions).length} 只</b></span></div><Badge value={account.reconciliation_ok ? "PASSED" : "ATTENTION"} /></NavLink>)}</div> : <State text="尚未收到任何账户快照。" />}</section>
    <AlertSection alerts={data.alerts} />
  </Frame>;
}

function TradePlanPage() {
  const { data, error } = useOverview(); const [selected, setSelected] = useState<{ strategy?: string; symbols: string[]; symbol_count: number } | null>(null);
  const plan = data?.bundle?.trade_plan;
  return <Frame title="明日交易计划" eyebrow={`PLAN · ${plan?.execution_date ?? "待生成"}`} subtitle="策略在收盘后生成计划，最早下一交易日成交；页面不提供执行入口。" actions={plan && <button className="button" onClick={() => downloadJson(`trade-plan-${plan.execution_date ?? "latest"}.json`, plan)}>导出计划</button>}>
    {!data ? <State error={error} /> : !plan || plan.status === "UNAVAILABLE" ? <State text="尚未生成可发布的下一交易日计划。" /> : <>
      <section className="metric-grid metric-grid-3"><Metric label="执行日期" value={plan.execution_date ?? "—"} note={`信号日 ${plan.signal_date ?? "—"}`} /><Metric label="参与策略" value={plan.items.length} note={`${plan.skipped?.length ?? 0} 个跳过`} /><Metric label="候选标的" value={plan.items.reduce((sum, item) => sum + item.symbol_count, 0)} note="最终数量以 TDX 委托事实为准" /></section>
      <section className="section card"><div className="card-header"><div><h2 className="card-title">策略计划</h2><p className="card-note">{plan.rule ?? "T 日收盘信号，下一交易日执行"}</p></div><Badge value={plan.status} /></div>
        {plan.items.length ? <div className="plan-list">{plan.items.map((item) => <button className="plan-row plan-button" key={item.strategy} onClick={() => setSelected(item)}><div><strong>{item.strategy}</strong><p>{item.symbols.join("、") || "无标的"}</p></div><span className="num">{item.symbol_count} 只　›</span></button>)}</div> : <div className="empty big">当前计划为空。系统会保留空计划事实，不制造策略订单。</div>}
      </section>
      {!!plan.skipped?.length && <section className="section card"><h2 className="card-title">跳过原因</h2><div className="table-wrap"><table><thead><tr><th>策略</th><th>原因</th><th>最近信号日</th><th>调仓周期</th></tr></thead><tbody>{plan.skipped.map((item, index) => <tr key={`${item.strategy}-${index}`}><td>{String(item.strategy ?? "—")}</td><td>{String(item.reason ?? "—")}</td><td className="num">{String(item.last_signal_date ?? "—")}</td><td className="num">{item.rebalance_days ? `${item.rebalance_days} 日` : "—"}</td></tr>)}</tbody></table></div></section>}
    </>}
    {selected && <Drawer title={selected.strategy ?? "策略计划"} onClose={() => setSelected(null)}><p className="drawer-lead">候选标的 {selected.symbol_count} 只</p><div className="symbol-grid">{selected.symbols.map((symbol) => <code key={symbol}>{symbol}</code>)}</div><p className="muted">委托方向、数量和限价在交易日由 OMS／风控生成，并以 TDX 返回事实为准。</p></Drawer>}
  </Frame>;
}

function AccountPage() {
  const { id } = useParams(); const { data, error } = useOverview(); const [accountId, setAccountId] = useState(id ?? "");
  useEffect(() => { if (id) setAccountId(id); else if (!accountId && data?.bundle?.accounts[0]) setAccountId(data.bundle.accounts[0].account_id); }, [id, data, accountId]);
  if (!data) return <Frame title="账户总览" eyebrow="ACCOUNT FACTS" subtitle="资金、持仓、费用与对账事实。"><State error={error} /></Frame>;
  const accounts = data.bundle?.accounts ?? []; const account = accounts.find((item) => item.account_id === accountId) ?? accounts[0];
  return <Frame title="账户总览" eyebrow={`ACCOUNT · ${data.bundle?.trading_day ?? "尚无快照"}`} subtitle="账户数据来自不可变日终快照，不使用浏览器缓存补值。" actions={accounts.length > 1 && <select className="select" value={account?.account_id ?? ""} onChange={(event) => setAccountId(event.target.value)}>{accounts.map((item) => <option value={item.account_id} key={item.account_id}>{item.strategy}</option>)}</select>}>
    {!account ? <State text="尚未收到账户快照。" /> : <>
      <section className="metric-grid"><Metric label="账户权益" value={<Money value={account.equity} />} note="元" /><Metric label="可用现金" value={<Money value={account.cash} />} note={`冻结 ${Number(account.frozen_cash).toLocaleString("zh-CN")} 元`} /><Metric label="持仓市值" value={<Money value={account.market_value} />} note={`${Object.keys(account.positions).length} 只证券`} /><Metric label="累计费用" value={<Money value={account.fees} />} note={`回撤 ${(Number(account.drawdown) * 100).toFixed(2)}%`} /></section>
      <section className="section grid-main"><article className="card"><div className="card-header"><div><h2 className="card-title">权益轨迹</h2><p className="card-note">{account.strategy} · 第 {account.generation} 代</p></div><Badge value={account.reconciliation_ok ? "PASSED" : "ATTENTION"} /></div>{data.bundle && <EquityChart bundle={data.bundle} accountId={account.account_id} />}</article><aside className="card"><h2 className="card-title">账户身份</h2><div className="detail-list"><Detail label="账户 ID" value={account.account_id} /><Detail label="状态" value={account.status} /><Detail label="策略" value={account.strategy} /><Detail label="对账" value={account.reconciliation_ok ? "通过" : "存在差异"} /></div></aside></section>
      <section className="section card"><div className="card-header"><div><h2 className="card-title">当前持仓</h2><p className="card-note">当前快照仅发布证券代码与数量；价格和盈亏缺失时不推算。</p></div></div>{Object.keys(account.positions).length ? <div className="table-wrap"><table><thead><tr><th>证券代码</th><th>数量</th><th>来源</th></tr></thead><tbody>{Object.entries(account.positions).map(([symbol, quantity]) => <tr key={symbol}><td><code>{symbol}</code></td><td className="num">{quantity} 股</td><td>账户快照</td></tr>)}</tbody></table></div> : <div className="empty big">当前账户空仓。</div>}</section>
    </>}
  </Frame>;
}

function ExecutionPage() {
  const { data, error } = useOverview(); const historyLoader = useCallback(() => api.reviews(), []); const { data: history } = usePolling<Array<Record<string, string>>>(historyLoader, 300_000); const review = data?.bundle?.execution_review; const bundle = data?.bundle;
  return <Frame title="当日执行复盘" eyebrow={`EXECUTION · ${bundle?.trading_day ?? "待发布"}`} subtitle="对照本地发送记录与 TDX 日终委托事实，所有差异保留到复盘。" actions={review && <button className="button" onClick={() => downloadJson(`execution-${bundle?.trading_day}.json`, review)}>导出复盘</button>}>
    {!data ? <State error={error} /> : !review || review.status === "UNAVAILABLE" ? <State text={review?.message ?? "尚未收到当日 TDX 执行复盘。"} /> : <>
      <section className="metric-grid"><Metric label="本地计划订单" value={review.local_order_count ?? 0} note="Outbox 当日记录" /><Metric label="TDX 当日委托" value={review.tdx_order_count ?? 0} note="模拟账户权威事实" /><Metric label="未知订单" value={review.uncertain_orders?.length ?? 0} note="SENDING／UNKNOWN" tone={review.uncertain_orders?.length ? "negative" : "positive"} /><Metric label="复盘结论" value={statusNames[review.status] ?? review.status} note={review.captured_at ? formatTime(review.captured_at) : "—"} tone={review.ok ? "positive" : "negative"} /></section>
      <section className="section grid-main"><article className="card card-strong"><div className="card-header"><div><h2 className="card-title">差异检查</h2><p className="card-note">事实 ID：{review.fact_id}</p></div><Badge value={review.status} /></div><div className="review-list"><ReviewLine label="TDX 缺失已确认委托" values={review.missing_acknowledged_orders} /><ReviewLine label="状态不确定" values={review.uncertain_orders} /><ReviewLine label="发送错误" values={review.failed_orders} /><ReviewLine label="非本系统 TDX 委托" values={review.unmapped_tdx_orders} /></div></article><aside className="card"><h2 className="card-title">账户资产原始字段</h2><pre className="raw-block">{JSON.stringify(review.asset ?? {}, null, 2)}</pre></aside></section>
      <section className="section card"><h2 className="card-title">TDX 当日委托</h2>{review.orders?.length ? <pre className="raw-block">{JSON.stringify(review.orders, null, 2)}</pre> : <div className="empty big">当日无 TDX 委托。</div>}</section>
    </>}
    {!!history?.length && <section className="section"><div className="section-heading"><div><h2>历史复盘</h2><p>按交易日打开不可变 ReviewBundle。</p></div></div><div className="history-grid">{history.map((item) => <NavLink className="history-link" to={`/reviews/${encodeURIComponent(item.bundle_id)}`} key={item.bundle_id}><strong>{item.trading_day}</strong><code>{item.content_sha256?.slice(0, 12)}…</code><span>查看 →</span></NavLink>)}</div></section>}
  </Frame>;
}

function ResearchPage() {
  const loader = useCallback(() => api.research(), []); const { data, error } = usePolling<ResearchSummary[]>(loader, 300_000); const [query, setQuery] = useState(""); const [category, setCategory] = useState("ALL"); const [selected, setSelected] = useState<ResearchBundle | null>(null); const [detailError, setDetailError] = useState("");
  const filtered = useMemo(() => (data ?? []).filter((item) => (category === "ALL" || item.category === category) && `${item.title}${item.summary}${item.conclusion}`.toLowerCase().includes(query.trim().toLowerCase())), [data, category, query]);
  const open = async (id: string) => { setDetailError(""); try { setSelected(await api.researchDetail(id)); } catch (reason) { setDetailError(reason instanceof Error ? reason.message : "报告读取失败"); } };
  return <Frame title="研究报告库" eyebrow="RESEARCH ARCHIVE" subtitle="策略、行业与专题证据的不可变版本库；展示既有结论，不重新计算指标。">
    <section className="filter-bar"><label className="search-field"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} type="search" placeholder="搜索标题、摘要或结论" /></label><div className="chips">{[["ALL", "全部"], ["STRATEGY", "策略"], ["INDUSTRY", "行业"], ["TOPIC", "专题"]].map(([value, label]) => <button className={`chip ${category === value ? "active" : ""}`} onClick={() => setCategory(value)} key={value}>{label}</button>)}</div></section>
    {!data ? <State error={error} /> : filtered.length ? <section className="research-grid">{filtered.map((report) => <button className="report-card" key={report.report_id} onClick={() => open(report.report_id)}><div className="report-top"><span className="report-category">{categoryNames[report.category]}</span><Badge value={report.status} /></div><h2>{report.title}</h2><p>{report.summary}</p><div className="report-conclusion">{report.conclusion}</div><footer><time>{report.data_cutoff}</time><code>{report.content_sha256.slice(0, 10)}…</code></footer></button>)}</section> : <State text="没有匹配的研究报告。" />}
    {detailError && <State error={detailError} />}
    {selected && <Drawer title={selected.title} onClose={() => setSelected(null)} wide><div className="report-meta"><Badge value={selected.status} /><span>{categoryNames[selected.category]}</span><span>数据截止 {selected.data_cutoff}</span></div><p className="drawer-lead">{selected.conclusion}</p><div className="detail-list"><Detail label="来源" value={selected.source_path} /><Detail label="Commit" value={selected.source_commit.slice(0, 16)} /><Detail label="内容哈希" value={selected.content_sha256.slice(0, 20)} /></div><MarkdownBody value={selected.body_markdown} /></Drawer>}
  </Frame>;
}

function SystemPage() {
  const { data, error } = useOverview(); const [showRaw, setShowRaw] = useState(false); const [filter, setFilter] = useState("ALL");
  if (!data) return <Frame title="系统运行状态" eyebrow="SYSTEM HEALTH" subtitle="Runner、数据源、任务和同步链路。"><State error={error} /></Frame>;
  const live = data.live_status[0]; const activity = data.bundle?.activity ?? []; const filtered = activity.filter((item) => filter === "ALL" || item.event_type.includes(filter));
  return <Frame title="系统运行状态" eyebrow={`最后状态 · ${live?.generated_at ? formatTime(live.generated_at) : "未连接"}`} subtitle="异常只展示和导出，不在 Dashboard 中修改人工状态。" actions={<><button className="button" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "收起原始状态" : "查看原始状态"}</button><button className="button button-primary" onClick={() => downloadJson("astock-diagnostics.json", data)}>导出诊断</button></>}>
    <section className="status-grid"><StatusCard title="Runner 心跳" value={live?.runner.status ?? "未连接"} note={live?.received_at ? formatTime(live.received_at) : "尚未接收"} status={live ? "ONLINE" : "CRITICAL"} /><StatusCard title="行情源" value={sourceSummary(live?.sources)} note="以最近健康检查为准" status={live ? "ONLINE" : "CRITICAL"} /><StatusCard title="同步积压" value={`${live?.sync.pending ?? 0} 项`} note="Outbox 待发送" status={live?.sync.pending ? "ATTENTION" : "PASS"} /><StatusCard title="活动告警" value={`${data.alerts.filter((item) => item.status !== "RESOLVED").length} 项`} note="服务器有效告警" status={data.alerts.some((item) => item.severity === "CRITICAL") ? "CRITICAL" : "PASS"} /></section>
    {showRaw && <section className="section card"><h2 className="card-title">原始 LiveStatus</h2><pre className="raw-block">{JSON.stringify(live ?? {}, null, 2)}</pre></section>}
    <AlertSection alerts={data.alerts} />
    <section className="section"><div className="section-heading"><div><h2>任务与结构化事件</h2><p>最近发布到 ReviewBundle 的事件时间线。</p></div><div className="chips">{["ALL", "TASK", "TDX", "ALERT"].map((value) => <button className={`chip ${filter === value ? "active" : ""}`} onClick={() => setFilter(value)} key={value}>{value === "ALL" ? "全部" : value}</button>)}</div></div><div className="card log-list">{filtered.length ? filtered.slice().reverse().map((item) => <div className="log-entry" key={item.event_id}><time>{formatTime(item.occurred_at)}</time><code>{item.event_type}</code><span>{eventSummary(item.payload)}</span></div>) : <div className="empty">尚无匹配事件。</div>}</div></section>
  </Frame>;
}

function ReviewPage() { const { id = "" } = useParams(); const loader = useCallback(() => api.review(id), [id]); const { data, error } = usePolling<ReviewBundle>(loader, 300_000); return data ? <ReviewView bundle={data} /> : <Frame title="交易日复盘" eyebrow="IMMUTABLE REVIEW" subtitle="读取指定复盘快照。"><State error={error} /></Frame>; }

function Detail({ label, value }: { label: string; value: React.ReactNode }) { return <div className="detail-row"><span>{label}</span><strong>{value}</strong></div>; }
function ReviewLine({ label, values = [] }: { label: string; values?: string[] }) { return <div className="review-item"><span className={`review-bar ${values.length ? "warn" : "good"}`} /><div><h3>{label}</h3><p>{values.length ? values.join("、") : "无差异"}</p></div><span className="num">{values.length}</span></div>; }
function StatusCard({ title, value, note, status }: { title: string; value: string; note: string; status: string }) { return <article className="card status-card"><div className="status-card-head"><h3>{title}</h3><Badge value={status} /></div><div className="status-value">{value}</div><p className="status-meta">{note}</p></article>; }
function AlertSection({ alerts }: { alerts: Alert[] }) { return <section className="section"><div className="section-heading"><div><h2>异常与提醒</h2><p>异常不会阻断其他模拟订单，收盘后统一复盘。</p></div></div><div className="card alert-list">{alerts.length ? alerts.map((alert, index) => <div className="alert-row" key={alert.alert_id ?? `${alert.code}-${index}`}><Badge value={alert.severity} /><div><strong>{alert.code}</strong><p>{alert.message}</p></div><time>{alert.last_seen_at ? formatTime(alert.last_seen_at) : "—"}</time></div>) : <div className="empty">当前没有活动告警。</div>}</div></section>; }
function Drawer({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) { useEffect(() => { const close = (event: KeyboardEvent) => event.key === "Escape" && onClose(); document.addEventListener("keydown", close); return () => document.removeEventListener("keydown", close); }, [onClose]); return <div className="drawer-overlay open" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><aside className={`drawer ${wide ? "drawer-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}><div className="drawer-header"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭">×</button></div><div className="drawer-body">{children}</div></aside></div>; }
function MarkdownBody({ value }: { value: string }) { return <div className="markdown-body">{value.split(/\r?\n/).map((line, index) => line.startsWith("### ") ? <h4 key={index}>{line.slice(4)}</h4> : line.startsWith("## ") ? <h3 key={index}>{line.slice(3)}</h3> : line.startsWith("# ") ? <h2 key={index}>{line.slice(2)}</h2> : line.startsWith("- ") ? <p className="markdown-list" key={index}>• {line.slice(2)}</p> : line ? <p key={index}>{line}</p> : <br key={index} />)}</div>; }

function formatTime(value: string) { try { return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); } catch { return value; } }
function eventSummary(payload: Record<string, unknown>) { return String(payload.message ?? payload.code ?? payload.reason ?? payload.status ?? "已记录结构化事实"); }
function sourceSummary(sources?: Record<string, Record<string, unknown>>) { if (!sources) return "未知"; const tdx = sources.tdx; if (tdx && "ok" in tdx) return tdx.ok ? "TDX 正常" : "TDX 异常"; return Object.keys(sources).length ? "已有状态" : "无状态"; }

export default Shell;
