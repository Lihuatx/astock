export type Alert = {
  alert_id?: string;
  code: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  message: string;
  status?: string;
  first_seen_at?: string;
  last_seen_at?: string;
};

export type Account = {
  account_id: string;
  strategy: string;
  generation: number;
  status: string;
  cash: string;
  frozen_cash: string;
  market_value: string;
  equity: string;
  fees: string;
  drawdown: string;
  positions: Record<string, number>;
  reconciliation_ok: boolean;
};

export type ReviewBundle = {
  schema_version: number;
  bundle_id: string;
  content_sha256: string;
  generated_at: string;
  trading_day: string;
  data_cutoff: string;
  strategy_set_id: string;
  strategy_set: { selected?: Array<Record<string, unknown>>; methodology?: Record<string, unknown> };
  accounts: Account[];
  signals: Array<Record<string, unknown>>;
  risk_decisions: Array<Record<string, unknown>>;
  orders: Array<Record<string, unknown>>;
  fills: Array<Record<string, unknown>>;
  equity_curve: Array<{ account_id: string; trading_day: string; equity: string; drawdown: string }>;
  reconciliation: Array<Record<string, unknown>>;
  health: Record<string, unknown>;
  alerts: Alert[];
  known_limitations: string[];
  trade_plan?: TradePlan;
  execution_review?: ExecutionReview;
  activity?: Activity[];
  research_index?: string[];
  disclaimer: string;
};

export type TradePlanItem = {
  strategy?: string;
  symbols: string[];
  symbol_count: number;
  selection_audit?: Record<string, unknown>;
};

export type TradePlan = {
  status: string;
  signal_date?: string | null;
  execution_date?: string | null;
  generated_at?: string | null;
  rule?: string | null;
  items: TradePlanItem[];
  skipped?: Array<Record<string, unknown>>;
};

export type ExecutionReview = {
  status: string;
  message?: string;
  fact_id?: string;
  captured_at?: string;
  ok?: boolean;
  local_order_count?: number;
  tdx_order_count?: number;
  missing_acknowledged_orders?: string[];
  uncertain_orders?: string[];
  failed_orders?: string[];
  unmapped_tdx_orders?: string[];
  asset?: Record<string, unknown>;
  positions?: Array<Record<string, unknown>>;
  orders?: Array<Record<string, unknown>>;
};

export type Activity = {
  event_id: string;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type ResearchSummary = {
  report_id: string;
  category: "STRATEGY" | "INDUSTRY" | "TOPIC";
  title: string;
  summary: string;
  conclusion: string;
  status: string;
  content_sha256: string;
  source_commit: string;
  data_cutoff: string;
  published_at: string;
};

export type ResearchBundle = ResearchSummary & {
  schema_version: 1;
  source_path: string;
  body_markdown: string;
  disclaimer: string;
};

export type LiveStatus = {
  source_id: string;
  generated_at: string;
  received_at?: string;
  runner: { status?: string; paper_execution_enabled?: boolean };
  sources: Record<string, Record<string, unknown>>;
  jobs: Record<string, Record<string, unknown>>;
  sync: { pending?: number };
  alerts: Alert[];
};

export type Overview = {
  bundle: ReviewBundle | null;
  live_status: LiveStatus[];
  alerts: Alert[];
  research: ResearchSummary[];
};
