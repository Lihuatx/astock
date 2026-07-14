from __future__ import annotations

import argparse
import json
import sys
import tempfile
import os
import subprocess
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from astock.config import Settings
from astock.data.tdx import TdxClient, TdxError
from astock.data.tdx_sim import JsonlErrorLog, TdxSimClient
from astock.data.tdx_transport import TdxSdkTransport
from astock.data.pytdx import PytdxMinuteClient, PytdxError
from astock.data.ths import ThsClient, ThsError
from astock.raw_store import JsonlRawStore
from astock.broker import AShareSimBroker
from astock.oms import OMS
from astock.replay import ReplayEngine
from astock.risk import RiskEngine
from astock.storage import Repository
from astock.strategy import MomentumTrendStrategy
from astock.research import MarketPanel, fetch_market_panel, research_signal_dates, run_research, write_markdown_report, write_report
from astock.data.tushare import FundamentalPanel, TushareProxyClient, build_fundamental_panel, update_valuation_date
from astock.paper import MultiStrategyPaperAccounts
from astock.aggressive_research import run_aggressive_research, write_aggressive_markdown
from astock.data.industry import IndustryPanel, build_industry_panel
from astock.industry_research import run_industry_research, write_industry_markdown
from astock.cgo_research import TurnoverPanel, build_turnover_panel, run_cgo_research, write_cgo_json, write_cgo_report
from astock.observability.repository import ObservabilityRepository
from astock.observability.runner import Runner
from astock.observability.snapshot import initialize_observation_set
from astock.observability.report import build_offline_report
from astock.dashboard.storage import DashboardStore
from astock.dashboard.backup import create_backup
from astock.intraday_review import load_intraday_bars, planned_orders, run_intraday_review, write_intraday_report
from astock.tdx_sim_execution import execute_tdx_sim_plan, review_tdx_sim_day


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env(args.env_file)


def _tdx_transport(settings: Settings) -> TdxSdkTransport | None:
    return TdxSdkTransport(settings.tdx_plugin_dir) if settings.tdx_plugin_dir else None


def _tdx_client(settings: Settings, raw_store: JsonlRawStore | None = None) -> TdxClient:
    return TdxClient(settings.tdx_base_url, raw_store, transport=_tdx_transport(settings))


def _paper_context(settings: Settings) -> tuple[ObservabilityRepository, str, Path]:
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    observability = ObservabilityRepository(settings.data_dir / "observability" / "observability.db")
    set_id, root = initialize_observation_set(
        observability,
        report_path,
        settings.data_dir / "paper",
        settings.initial_cash,
        Path.cwd(),
        datetime.now(ZoneInfo("Asia/Shanghai")),
    )
    return observability, set_id, root


def doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    raw_store = JsonlRawStore(settings.data_dir / "raw")
    result: dict[str, object] = {"tdx": {"ok": False}, "ths": {"configured": bool(settings.ths_api_key)}}
    try:
        result["tdx"] = _tdx_client(settings, raw_store).doctor()
    except TdxError as exc:
        result["tdx"] = {"ok": False, "error": str(exc)}
    if settings.ths_api_key:
        try:
            result["ths"] = {"configured": True, **ThsClient(settings.ths_base_url, settings.ths_api_key, raw_store).doctor()}
        except ThsError as exc:
            result["ths"] = {"configured": True, "ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if bool(result["tdx"].get("ok")) else 1  # type: ignore[union-attr]


def replay(args: argparse.Namespace) -> int:
    settings = _settings(args)
    bars = _tdx_client(settings, JsonlRawStore(settings.data_dir / "raw")).get_bars(
        args.symbol, start=args.start, end=args.end
    )
    curve = []
    fills = []
    if bars:
        with tempfile.TemporaryDirectory(prefix="astock-replay-") as folder:
            repository = Repository(Path(folder) / "replay.db")
            broker = AShareSimBroker(repository, settings.initial_cash)
            curve = ReplayEngine(
                broker, OMS(repository, broker), RiskEngine(), MomentumTrendStrategy(top_n=1)
            ).run({args.symbol: bars})
            fills = repository.load_fills()
            repository.close()
    summary = {
        "symbol": args.symbol,
        "bar_count": len(bars),
        "first_day": bars[0].trading_day.isoformat() if bars else None,
        "last_day": bars[-1].trading_day.isoformat() if bars else None,
        "fill_count": len(fills),
        "ending_equity": str(curve[-1].equity) if curve else None,
        "all_days_reconciled": bool(curve) and all(point.reconciled for point in curve),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if bars else 2


def research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    cache_path = settings.data_dir / "research" / "market_panel.npz"
    if cache_path.exists() and not args.refresh:
        panel = MarketPanel.load(cache_path)
    else:
        panel = fetch_market_panel(_tdx_client(settings), args.start, args.end, cache_path)
    result = run_research(panel)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    write_report(result, report_path)
    v3_data_path = settings.data_dir / "research" / "strategy_research_v3.json"
    write_report(result, v3_data_path)
    v3_document_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V3.md"
    write_markdown_report(result, v3_document_path)
    summary = {
        "symbols": len(panel.symbols),
        "trading_days": len(panel.dates),
        "selected": [item["strategy"] for item in result["selected"]],
        "report": str(report_path),
        "v3_report": str(v3_document_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def fundamental_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.tushare_base_token:
        raise ValueError("TUSHARE_BASE_TOKEN is required")
    market_path = settings.data_dir / "research" / "market_panel.npz"
    panel = MarketPanel.load(market_path)
    fundamental_path = settings.data_dir / "research" / "fundamental_panel.npz"
    if fundamental_path.exists() and not args.refresh:
        fundamentals = FundamentalPanel.load(fundamental_path)
    else:
        client = TushareProxyClient(
            settings.tushare_base_url,
            settings.tushare_base_token,
            settings.data_dir / "tushare" / "cache",
        )
        fundamentals = build_fundamental_panel(
            client, panel.dates, panel.symbols, research_signal_dates(panel), fundamental_path
        )
    result = run_research(panel, fundamentals)
    current_report = settings.data_dir / "reports" / "strategy_research.json"
    v4_data = settings.data_dir / "research" / "strategy_research_v4.json"
    v4_document = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V4.md"
    write_report(result, current_report)
    write_report(result, v4_data)
    write_markdown_report(result, v4_document)
    print(
        json.dumps(
            {
                "symbols": len(panel.symbols),
                "trading_days": len(panel.dates),
                "factors": result["methodology"]["factor_count"],
                "selected": [item["strategy"] for item in result["selected"]],
                "v4_report": str(v4_document),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def quality_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.tushare_base_token:
        raise ValueError("TUSHARE_BASE_TOKEN is required")
    panel = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    fundamental_path = settings.data_dir / "research" / "fundamental_panel.npz"
    client = TushareProxyClient(
        settings.tushare_base_url,
        settings.tushare_base_token,
        settings.data_dir / "tushare" / "cache",
    )
    fundamentals = build_fundamental_panel(
        client, panel.dates, panel.symbols, research_signal_dates(panel), fundamental_path
    )
    result = run_research(panel, fundamentals)
    result["methodology"]["version"] = "V7"
    result["methodology"]["research_theme"] = "cash-flow quality and working-capital efficiency"
    data_path = settings.data_dir / "research" / "strategy_research_v7_quality.json"
    document_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V7.md"
    write_report(result, data_path)
    write_markdown_report(result, document_path)
    print(json.dumps({"factors": result["methodology"]["factor_count"], "selected": [item["strategy"] for item in result["selected"]], "report": str(document_path)}, ensure_ascii=False, indent=2))
    return 0


def aggressive_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    panel = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    fundamental_path = settings.data_dir / "research" / "fundamental_panel.npz"
    fundamentals = FundamentalPanel.load(fundamental_path) if fundamental_path.exists() else None
    result = run_aggressive_research(panel, fundamentals)
    data_path = settings.data_dir / "research" / "strategy_research_v5_aggressive.json"
    document_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V5_AGGRESSIVE.md"
    write_report(result, data_path)
    write_aggressive_markdown(result, document_path)
    print(
        json.dumps(
            {
                "symbols": len(panel.symbols),
                "trading_days": len(panel.dates),
                "selected": [item["strategy"] for item in result["selected"]],
                "report": str(document_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def industry_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.tushare_base_token:
        raise ValueError("TUSHARE_BASE_TOKEN is required")
    panel = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    industry_path = settings.data_dir / "research" / "industry_panel.npz"
    if industry_path.exists() and not args.refresh:
        industries = IndustryPanel.load(industry_path)
    else:
        client = TushareProxyClient(
            settings.tushare_base_url,
            settings.tushare_base_token,
            settings.data_dir / "tushare" / "cache",
        )
        industries = build_industry_panel(client, panel.dates, panel.symbols, panel.close, industry_path)
    fundamental_path = settings.data_dir / "research" / "fundamental_panel.npz"
    fundamentals = FundamentalPanel.load(fundamental_path) if fundamental_path.exists() else None
    result = run_industry_research(panel, industries, fundamentals)
    data_path = settings.data_dir / "research" / "strategy_research_v6_industry.json"
    document_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V6_INDUSTRY.md"
    write_report(result, data_path)
    write_industry_markdown(result, document_path)
    print(
        json.dumps(
            {
                "industries": len(industries.industry_codes),
                "membership_coverage": result["methodology"]["membership_coverage_on_valid_stock_days"],
                "selected": [item["base_strategy"] for item in result["selected"]],
                "rotation": result["rotation"]["strategy"],
                "report": str(document_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cgo_research(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.tushare_base_token:
        raise ValueError("TUSHARE_BASE_TOKEN is required")
    market = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    turnover_path = settings.data_dir / "research" / "turnover_panel.npz"
    if turnover_path.exists() and not args.refresh:
        turnover = TurnoverPanel.load(turnover_path)
    else:
        client = TushareProxyClient(
            settings.tushare_base_url,
            settings.tushare_base_token,
            settings.data_dir / "tushare" / "cache",
        )
        turnover = build_turnover_panel(client, market, turnover_path)
    result = run_cgo_research(market, turnover)
    json_path = settings.data_dir / "research" / "strategy_research_v8_cgo.json"
    report_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V8_CGO.md"
    write_cgo_json(result, json_path)
    write_cgo_report(result, report_path)
    print(json.dumps({"selected": result["selected"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0


def paper_prepare(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    observability, set_id, root = _paper_context(settings)
    try:
        manager = MultiStrategyPaperAccounts(root, settings.initial_cash, observability, set_id)
        statuses = manager.prepare(report_path)
    finally:
        observability.close()
    print(json.dumps([status.__dict__ for status in statuses], ensure_ascii=False, indent=2))
    return 0


def paper_signals(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    market_path = settings.data_dir / "research" / "market_panel.npz"
    panel = MarketPanel.load(market_path)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    completed_end = now.date() if now.time() >= time(15, 10) else now.date() - timedelta(days=1)
    tdx_client = _tdx_client(settings, JsonlRawStore(settings.data_dir / "raw"))
    missing_dates = tdx_client.get_trading_dates(
        (date.fromisoformat(str(panel.dates[-1])) + timedelta(days=1)).strftime("%Y%m%d"),
        completed_end.strftime("%Y%m%d"),
    )
    inputs_refreshed = bool(missing_dates)
    if inputs_refreshed:
        panel = fetch_market_panel(
            tdx_client,
            str(panel.dates[0]).replace("-", ""),
            missing_dates[-1].strftime("%Y%m%d"),
            market_path,
            symbols=panel.symbols.tolist(),
        )
    fundamental_path = settings.data_dir / "research" / "fundamental_panel.npz"
    fundamentals = None
    if settings.tushare_base_token:
        client = TushareProxyClient(
            settings.tushare_base_url,
            settings.tushare_base_token,
            settings.data_dir / "tushare" / "cache",
        )
        if inputs_refreshed:
            fundamentals = build_fundamental_panel(
                client,
                panel.dates,
                panel.symbols,
                research_signal_dates(panel),
                fundamental_path,
            )
        elif fundamental_path.exists():
            fundamentals = FundamentalPanel.load(fundamental_path)
        if fundamentals is None:
            raise ValueError("fundamental panel is required for the current strategy set")
        fundamentals = update_valuation_date(client, fundamentals, str(panel.dates[-1]), fundamental_path)
    elif inputs_refreshed:
        raise ValueError("TUSHARE_BASE_TOKEN is required to refresh point-in-time fundamentals")
    elif fundamental_path.exists():
        fundamentals = FundamentalPanel.load(fundamental_path)
    observability, set_id, root = _paper_context(settings)
    try:
        target_path = root / "pending_signals.json"
        manager = MultiStrategyPaperAccounts(root, settings.initial_cash, observability, set_id)
        plan = manager.create_signal_plan(
            report_path,
            panel,
            target_path,
            fundamentals,
            schedule_root=manager.root,
        )
        signal_day = date.fromisoformat(plan["signal_date"])
        future_dates = tdx_client.get_trading_dates(
            (signal_day + timedelta(days=1)).strftime("%Y%m%d"),
            (signal_day + timedelta(days=14)).strftime("%Y%m%d"),
        )
        candidate = signal_day + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        plan["earliest_execution_date"] = (future_dates[0] if future_dates else candidate).isoformat()
        plan["inputs_refreshed"] = inputs_refreshed
        target_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        event_id = f"signal-plan:{set_id}:{plan['signal_date']}"
        event_payload = {
            "strategy_set_id": set_id,
            "signal_date": plan["signal_date"],
            "strategies": plan["strategies"],
        }
        existing_event = observability.event(event_id)
        if existing_event and existing_event["payload"] != event_payload:
            raise ValueError(f"signal plan {event_id!r} conflicts with its registered facts")
        if not existing_event:
            observability.append_event(
                "SIGNAL_PLAN",
                datetime.now(ZoneInfo("Asia/Shanghai")),
                event_payload,
                event_id=event_id,
            )
    finally:
        observability.close()
    print(json.dumps({
        "strategy_set_id": plan["strategy_set_id"],
        "signal_date": plan["signal_date"],
        "earliest_execution_date": plan["earliest_execution_date"],
        "strategies": [
            {"strategy": item["strategy"], "symbol_count": len(item["symbols"]), "symbols": item["symbols"]}
            for item in plan["strategies"]
        ],
        "skipped": plan["skipped"],
        "plan_path": str(target_path),
    }, ensure_ascii=False, indent=2))
    return 0


def paper_execute(args: argparse.Namespace) -> int:
    settings = _settings(args)
    if not settings.paper_execution_enabled:
        raise ValueError("paper execution is disabled; complete P4 execution acceptance before enabling it")
    observability, set_id, root = _paper_context(settings)
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        raw_store = JsonlRawStore(settings.data_dir / "raw")
        error_log = JsonlErrorLog(settings.data_dir / "logs")
        transport = _tdx_transport(settings)
        result = execute_tdx_sim_plan(
            root / "pending_signals.json",
            set_id,
            TdxClient(settings.tdx_base_url, raw_store, transport=transport),
            TdxSimClient(
                settings.tdx_base_url,
                settings.tdx_sim_account,
                settings.tdx_simulation_confirmed,
                raw_store,
                error_log,
                transport=transport,
            ),
            observability,
            error_log,
            now,
        )
    finally:
        observability.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def paper_review(args: argparse.Namespace) -> int:
    settings = _settings(args)
    observability, _, _ = _paper_context(settings)
    try:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        raw_store = JsonlRawStore(settings.data_dir / "raw")
        error_log = JsonlErrorLog(settings.data_dir / "logs")
        transport = _tdx_transport(settings)
        result = review_tdx_sim_day(
            TdxSimClient(
                settings.tdx_base_url,
                settings.tdx_sim_account,
                settings.tdx_simulation_confirmed,
                raw_store,
                error_log,
                transport=transport,
            ),
            observability,
            error_log,
            settings.data_dir / "review" / "tdx-sim",
            now,
        )
    finally:
        observability.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def intraday_review(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    panel = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    fundamentals = FundamentalPanel.load(settings.data_dir / "research" / "fundamental_panel.npz")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    orders, review_dates = planned_orders(panel, fundamentals, report, args.days)
    raw_store = JsonlRawStore(settings.data_dir / "raw")
    client = _tdx_client(settings, raw_store)
    bars = load_intraday_bars(
        client,
        (item.symbol for item in orders),
        review_dates,
        settings.data_dir / "research" / "intraday_5m",
        refresh=args.refresh,
        fallback_client=PytdxMinuteClient(raw_store),
    )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result = run_intraday_review(
        orders,
        review_dates,
        bars,
        [str(item["strategy"]) for item in report.get("selected") or []],
        report_path=report_path,
        git_sha=git_sha,
    )
    json_path = settings.data_dir / "reports" / "intraday_execution_review.json"
    markdown_path = settings.data_dir.parent / "docs" / "INTRADAY_EXECUTION_REVIEW_RESULT.md"
    write_intraday_report(result, json_path, markdown_path)
    print(
        json.dumps(
            {
                "all_passed": result["all_passed"],
                "passed_strategies": result["passed_strategies"],
                "failed_strategies": result["failed_strategies"],
                "planned_order_count": result["planned_order_count"],
                "data_start": result["data_start"],
                "data_end": result["data_end"],
                "report": str(markdown_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["all_passed"] else 1


def runner_command(args: argparse.Namespace) -> int:
    settings = _settings(args)
    runner = Runner(settings, Path.cwd(), args.env_file)
    if args.once:
        try:
            runner.tick()
        finally:
            runner.close()
    else:
        runner.run_forever()
    return 0


def dashboard_command(args: argparse.Namespace) -> int:
    if args.env_file:
        Settings.from_env(args.env_file)
    import uvicorn
    from astock.dashboard.app import create_app

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, workers=1)
    return 0


def dashboard_backup(args: argparse.Namespace) -> int:
    settings = _settings(args)
    server_root = Path(os.getenv("ASTOCK_SERVER_DATA_DIR", settings.data_dir / "server")).resolve()
    store = DashboardStore(server_root / "server.db", server_root / "bundles")
    try:
        create_backup(store, args.target)
    finally:
        store.close()
    print(json.dumps({"backup": str(args.target.resolve())}, ensure_ascii=False))
    return 0


def review_build(args: argparse.Namespace) -> int:
    target = args.output or args.bundle.with_suffix(".html")
    build_offline_report(args.bundle, args.assets, target)
    print(json.dumps({"report": str(target.resolve())}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="astock", description="A 股本机研究与模拟交易系统")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="检查本机行情源")
    doctor_parser.add_argument("--env-file", type=Path)
    doctor_parser.set_defaults(handler=doctor)
    replay_parser = subparsers.add_parser("replay", help="检查历史行情可回放范围")
    replay_parser.add_argument("--symbol", required=True)
    replay_parser.add_argument("--start", default="")
    replay_parser.add_argument("--end", default="")
    replay_parser.add_argument("--env-file", type=Path)
    replay_parser.set_defaults(handler=replay)
    research_parser = subparsers.add_parser("research", help="运行无未来函数的多策略研究")
    research_parser.add_argument("--start", default="20210101")
    research_parser.add_argument("--end", default="20260710")
    research_parser.add_argument("--refresh", action="store_true")
    research_parser.add_argument("--env-file", type=Path)
    research_parser.set_defaults(handler=research)
    fundamental_parser = subparsers.add_parser("research-fundamental", help="运行点时正确的技术面和基本面联合研究")
    fundamental_parser.add_argument("--refresh", action="store_true")
    fundamental_parser.add_argument("--env-file", type=Path)
    fundamental_parser.set_defaults(handler=fundamental_research)
    quality_parser = subparsers.add_parser("research-quality", help="运行 V7 现金流质量与营运效率研究")
    quality_parser.add_argument("--env-file", type=Path)
    quality_parser.set_defaults(handler=quality_research)
    aggressive_parser = subparsers.add_parser("research-aggressive", help="运行隔离的激进双窗口策略研究")
    aggressive_parser.add_argument("--env-file", type=Path)
    aggressive_parser.set_defaults(handler=aggressive_research)
    industry_parser = subparsers.add_parser("research-industry", help="运行申万一级行业中性与轮动研究")
    industry_parser.add_argument("--refresh", action="store_true")
    industry_parser.add_argument("--env-file", type=Path)
    industry_parser.set_defaults(handler=industry_research)
    cgo_parser = subparsers.add_parser("research-cgo", help="运行资本利得悬挂（CGO）独立因子研究")
    cgo_parser.add_argument("--refresh", action="store_true")
    cgo_parser.add_argument("--env-file", type=Path)
    cgo_parser.set_defaults(handler=cgo_research)
    paper_parser = subparsers.add_parser("paper-prepare", help="准备三个隔离策略账户和组合观察账户")
    paper_parser.add_argument("--env-file", type=Path)
    paper_parser.set_defaults(handler=paper_prepare)
    signal_parser = subparsers.add_parser("paper-signals", help="按最新收盘数据生成三个策略的下一交易日计划")
    signal_parser.add_argument("--env-file", type=Path)
    signal_parser.set_defaults(handler=paper_signals)
    execute_parser = subparsers.add_parser("paper-execute", help="向 TDX 模拟组合账户发送计划订单")
    execute_parser.add_argument("--env-file", type=Path)
    execute_parser.set_defaults(handler=paper_execute)
    review_paper_parser = subparsers.add_parser("paper-review", help="收盘后镜像并复盘 TDX 模拟账户事实")
    review_paper_parser.add_argument("--env-file", type=Path)
    review_paper_parser.set_defaults(handler=paper_review)
    intraday_parser = subparsers.add_parser("review-intraday", help="使用最近交易日的 5 分钟线复核开盘成交质量")
    intraday_parser.add_argument("--days", type=int, default=100)
    intraday_parser.add_argument("--refresh", action="store_true")
    intraday_parser.add_argument("--env-file", type=Path)
    intraday_parser.set_defaults(handler=intraday_review)
    runner_parser = subparsers.add_parser("runner", help="运行 P4 单实例观测与同步 runner")
    runner_parser.add_argument("--once", action="store_true")
    runner_parser.add_argument("--env-file", type=Path)
    runner_parser.set_defaults(handler=runner_command)
    dashboard_parser = subparsers.add_parser("dashboard", help="启动私有只读 Dashboard")
    dashboard_parser.add_argument("--port", type=int, default=18080)
    dashboard_parser.add_argument("--env-file", type=Path)
    dashboard_parser.set_defaults(handler=dashboard_command)
    backup_parser = subparsers.add_parser("dashboard-backup", help="备份 Dashboard 索引、Bundle 和 SHA256 清单")
    backup_parser.add_argument("--target", type=Path, required=True)
    backup_parser.add_argument("--env-file", type=Path)
    backup_parser.set_defaults(handler=dashboard_backup)
    review_parser = subparsers.add_parser("review-build", help="从不可变 ReviewBundle 生成离线 HTML")
    review_parser.add_argument("--bundle", type=Path, required=True)
    review_parser.add_argument("--assets", type=Path, default=Path("web/report-dist"))
    review_parser.add_argument("--output", type=Path)
    review_parser.add_argument("--env-file", type=Path)
    review_parser.set_defaults(handler=review_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (TdxError, ThsError, PytdxError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
