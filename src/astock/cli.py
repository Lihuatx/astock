from __future__ import annotations

import argparse
import json
import sys
import tempfile
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
