from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from astock.config import Settings
from astock.data.tdx import TdxClient, TdxError
from astock.data.ths import ThsClient, ThsError
from astock.raw_store import JsonlRawStore
from astock.broker import AShareSimBroker
from astock.oms import OMS
from astock.replay import ReplayEngine
from astock.risk import RiskEngine
from astock.storage import Repository
from astock.strategy import MomentumTrendStrategy
from astock.research import MarketPanel, fetch_market_panel, run_research, write_markdown_report, write_report
from astock.paper import MultiStrategyPaperAccounts


def _settings(args: argparse.Namespace) -> Settings:
    return Settings.from_env(args.env_file)


def doctor(args: argparse.Namespace) -> int:
    settings = _settings(args)
    raw_store = JsonlRawStore(settings.data_dir / "raw")
    result: dict[str, object] = {"tdx": {"ok": False}, "ths": {"configured": bool(settings.ths_api_key)}}
    try:
        result["tdx"] = TdxClient(settings.tdx_base_url, raw_store).doctor()
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
    bars = TdxClient(settings.tdx_base_url, JsonlRawStore(settings.data_dir / "raw")).get_bars(
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
        panel = fetch_market_panel(TdxClient(settings.tdx_base_url), args.start, args.end, cache_path)
    result = run_research(panel)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    write_report(result, report_path)
    v2_data_path = settings.data_dir / "research" / "strategy_research_v2.json"
    write_report(result, v2_data_path)
    v2_document_path = settings.data_dir.parent / "docs" / "STRATEGY_RESEARCH_V2.md"
    write_markdown_report(result, v2_document_path)
    summary = {
        "symbols": len(panel.symbols),
        "trading_days": len(panel.dates),
        "selected": [item["strategy"] for item in result["selected"]],
        "report": str(report_path),
        "v2_report": str(v2_document_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def paper_prepare(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    manager = MultiStrategyPaperAccounts(settings.data_dir / "paper", settings.initial_cash)
    statuses = manager.prepare(report_path)
    print(json.dumps([status.__dict__ for status in statuses], ensure_ascii=False, indent=2))
    return 0


def paper_signals(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report_path = settings.data_dir / "reports" / "strategy_research.json"
    panel = MarketPanel.load(settings.data_dir / "research" / "market_panel.npz")
    target_path = settings.data_dir / "paper" / "pending_signals.json"
    plan = MultiStrategyPaperAccounts.create_signal_plan(report_path, panel, target_path)
    signal_day = date.fromisoformat(plan["signal_date"])
    future_dates = TdxClient(settings.tdx_base_url).get_trading_dates(
        (signal_day + timedelta(days=1)).strftime("%Y%m%d"),
        (signal_day + timedelta(days=14)).strftime("%Y%m%d"),
    )
    plan["earliest_execution_date"] = future_dates[0].isoformat() if future_dates else None
    target_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def paper_execute(args: argparse.Namespace) -> int:
    settings = _settings(args)
    manager = MultiStrategyPaperAccounts(settings.data_dir / "paper", settings.initial_cash)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    results = manager.execute_plan(
        settings.data_dir / "paper" / "pending_signals.json",
        TdxClient(settings.tdx_base_url),
        now.date(),
        now,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
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
    paper_parser = subparsers.add_parser("paper-prepare", help="准备三个隔离策略账户和组合观察账户")
    paper_parser.add_argument("--env-file", type=Path)
    paper_parser.set_defaults(handler=paper_prepare)
    signal_parser = subparsers.add_parser("paper-signals", help="按最新收盘数据生成三个策略的下一交易日计划")
    signal_parser.add_argument("--env-file", type=Path)
    signal_parser.set_defaults(handler=paper_signals)
    execute_parser = subparsers.add_parser("paper-execute", help="在下一交易日执行三个隔离账户的模拟计划")
    execute_parser.add_argument("--env-file", type=Path)
    execute_parser.set_defaults(handler=paper_execute)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (TdxError, ThsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
