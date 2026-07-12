import type { ReviewBundle } from "./types";
import { AccountCard, AlertList, EquityChart } from "./components";

export function ReviewView({ bundle, reportMode = false }: { bundle: ReviewBundle; reportMode?: boolean }) {
  return <main className={reportMode ? "report-page" : "page"}>
    <header className="review-header">
      <div><div className="eyebrow">不可变复盘快照 · {bundle.trading_day}</div><h1>交易日复盘</h1></div>
      <div className="hash">Bundle<br /><code>{bundle.content_sha256.slice(0, 20)}…</code></div>
    </header>
    <section className="account-grid">{bundle.accounts.map((account) => <AccountCard account={account} key={account.account_id} />)}</section>
    <section className="panel"><div className="section-title"><h2>权益轨迹</h2><span>{bundle.strategy_set_id}</span></div><EquityChart bundle={bundle} /></section>
    <section className="two-column">
      <div className="panel"><h2>信号与执行</h2><div className="metric-row"><span>策略信号</span><b>{bundle.signals.length}</b></div><div className="metric-row"><span>风险决定</span><b>{bundle.risk_decisions.length}</b></div><div className="metric-row"><span>订单／成交</span><b>{bundle.orders.length}／{bundle.fills.length}</b></div></div>
      <div className="panel"><h2>告警</h2><AlertList alerts={bundle.alerts} /></div>
    </section>
    <section className="panel"><h2>已知限制</h2><ul className="limitations">{bundle.known_limitations.map((item) => <li key={item}>{item}</li>)}</ul></section>
    <footer>{bundle.disclaimer}　数据截止：{bundle.data_cutoff}</footer>
  </main>;
}
