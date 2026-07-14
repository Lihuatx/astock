from __future__ import annotations

import json
import subprocess
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from astock.broker import AShareSimBroker
from astock.observability.bundle import build_review_bundle, sha256_file, strategy_set_id, write_review_bundle
from astock.observability.repository import ObservabilityRepository
from astock.storage import Repository


def current_git_sha(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def initialize_observation_set(
    repository: ObservabilityRepository,
    report_path: Path,
    paper_root: Path,
    initial_cash: Decimal,
    workspace: Path,
    created_at: datetime,
) -> tuple[str, Path]:
    paper_root.mkdir(parents=True, exist_ok=True)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    set_id = strategy_set_id(report_path)
    report_hash = sha256_file(report_path)
    set_payload = {"selected": report.get("selected", []), "methodology": report.get("methodology", {})}
    existing_set = repository.strategy_set(set_id)
    if existing_set:
        if existing_set["report_sha256"] != report_hash or existing_set["payload"] != set_payload:
            raise ValueError(f"strategy set {set_id!r} conflicts with its registered facts")
    else:
        repository.register_strategy_set(
            set_id,
            report_hash,
            current_git_sha(workspace),
            set_payload,
            created_at,
        )
    repository.activate_strategy_set(set_id)
    current_root = paper_root / "sets" / set_id
    selected = [item["strategy"] if isinstance(item, dict) else str(item) for item in report.get("selected", [])]
    for strategy in [*selected, "combined_observer"]:
        account_id = f"{set_id}:{strategy}:g1"
        db_path = current_root / strategy / "account.db"
        existing_account = repository.account(account_id)
        expected = (set_id, strategy, 1, str(db_path), str(initial_cash))
        actual = None if existing_account is None else (
            existing_account["strategy_set_id"], existing_account["strategy"], existing_account["generation"],
            existing_account["db_path"], existing_account["initial_cash"],
        )
        if existing_account and actual != expected:
            raise ValueError(f"account {account_id!r} conflicts with its registered facts")
        if not existing_account:
            repository.register_account(
                account_id, strategy, 1, db_path, initial_cash, created_at, set_id, "CURRENT"
            )
    for folder in sorted(path for path in paper_root.iterdir() if path.is_dir() and path.name != "sets"):
        db_path = folder / "account.db"
        if db_path.exists():
            account_id = f"legacy:{folder.name}:g1"
            existing_account = repository.account(account_id)
            expected = (None, folder.name, 1, str(db_path), str(initial_cash))
            actual = None if existing_account is None else (
                existing_account["strategy_set_id"], existing_account["strategy"], existing_account["generation"],
                existing_account["db_path"], existing_account["initial_cash"],
            )
            if existing_account and actual != expected:
                raise ValueError(f"account {account_id!r} conflicts with its registered facts")
            if not existing_account:
                repository.register_account(
                    account_id, folder.name, 1, db_path, initial_cash, created_at, None, "LEGACY"
                )
    legacy_plan = paper_root / "pending_signals.json"
    if legacy_plan.exists():
        payload = json.loads(legacy_plan.read_text(encoding="utf-8"))
        if payload.get("strategy_set_id") != set_id:
            event_id = f"stale-plan:{sha256_file(legacy_plan)[:16]}:{set_id}"
            if repository.event(event_id) is None:
                repository.append_event(
                    "STALE_SIGNAL_PLAN",
                    created_at,
                    {
                        "code": "STALE_SIGNAL_PLAN",
                        "severity": "WARNING",
                        "message": "旧待执行信号与当前观察集不一致，已禁止执行",
                        "status": "ACTIVE",
                        "expected_strategy_set_id": set_id,
                        "actual_strategy_set_id": payload.get("strategy_set_id"),
                        "legacy_plan_path": str(legacy_plan),
                    },
                    event_id=event_id,
                )
    return set_id, current_root


def capture_account_snapshot(
    observability: ObservabilityRepository,
    account: dict[str, Any],
    trading_day: date,
    captured_at: datetime,
    prices: dict[str, Decimal],
) -> dict[str, Any]:
    repository = Repository(Path(account["db_path"]))
    broker = AShareSimBroker(repository, Decimal(account["initial_cash"]))
    state = broker.snapshot(trading_day)
    market_value = sum(Decimal(quantity) * prices.get(symbol, Decimal("0")) for symbol, quantity in state.positions.items())
    equity = state.cash + market_value
    fees = sum(fill.total_fee for fill in repository.load_fills())
    previous = observability.snapshots(account["account_id"])
    peak = max([Decimal(item["equity"]) for item in previous] + [equity])
    drawdown = (equity / peak - Decimal("1")) if peak else Decimal("0")
    reconciliation = broker.reconcile(trading_day)
    snapshot = {
        "snapshot_id": uuid.uuid4().hex,
        "account_id": account["account_id"],
        "strategy": account["strategy"],
        "trading_day": trading_day.isoformat(),
        "captured_at": captured_at.isoformat(),
        "cash": state.cash,
        "frozen_cash": state.frozen_cash,
        "market_value": market_value,
        "equity": equity,
        "fees": fees,
        "drawdown": drawdown,
        "positions": state.positions,
        "reconciliation_ok": reconciliation.ok,
        "reconciliation_reasons": list(reconciliation.reasons),
    }
    observability.save_snapshot(snapshot)
    repository.close()
    return snapshot


def create_review_bundle_from_repository(
    observability: ObservabilityRepository,
    report_path: Path,
    workspace: Path,
    bundle_root: Path,
    trading_day: date,
    generated_at: datetime,
    data_cutoff: str,
    health: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Path]:
    set_id = strategy_set_id(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    accounts = observability.accounts("CURRENT")
    snapshots = observability.snapshots()
    events = observability.events()
    account_payload = []
    equity_curve = []
    for account in accounts:
        account_snapshots = [item for item in snapshots if item["account_id"] == account["account_id"]]
        latest = account_snapshots[-1] if account_snapshots else None
        account_payload.append(
            {
                "account_id": account["account_id"],
                "strategy": account["strategy"],
                "generation": account["generation"],
                "status": account["status"],
                "cash": latest["cash"] if latest else account["initial_cash"],
                "frozen_cash": latest["frozen_cash"] if latest else "0",
                "market_value": latest["market_value"] if latest else "0",
                "equity": latest["equity"] if latest else account["initial_cash"],
                "fees": latest["fees"] if latest else "0",
                "drawdown": latest["drawdown"] if latest else "0",
                "positions": latest["positions"] if latest else {},
                "reconciliation_ok": latest["reconciliation_ok"] if latest else True,
            }
        )
        equity_curve.extend(
            {
                "account_id": account["account_id"],
                "trading_day": item["trading_day"],
                "equity": item["equity"],
                "drawdown": item["drawdown"],
            }
            for item in account_snapshots
        )
    event_payload = lambda kind: [item for item in events if item["event_type"] == kind]
    signals = []
    signal_path = report_path.parent.parent / "paper" / "sets" / set_id / "pending_signals.json"
    if signal_path.exists():
        plan = json.loads(signal_path.read_text(encoding="utf-8"))
        signals = plan.get("strategies", [])
    bundle = build_review_bundle(
        trading_day=trading_day.isoformat(),
        generated_at=generated_at,
        git_sha=current_git_sha(workspace),
        data_cutoff=data_cutoff,
        report_sha256=sha256_file(report_path),
        strategy_set_id=set_id,
        strategy_set={"selected": report.get("selected", []), "methodology": report.get("methodology", {})},
        accounts=account_payload,
        signals=signals,
        risk_decisions=event_payload("RISK_DECISION"),
        orders=event_payload("ORDER"),
        fills=event_payload("FILL"),
        equity_curve=equity_curve,
        reconciliation=event_payload("RECONCILIATION"),
        health=health or {},
        alerts=[item for item in events if item["event_type"].endswith("ALERT") or item["event_type"] == "STALE_SIGNAL_PLAN"],
        known_limitations=list(report.get("methodology", {}).get("known_limitations", [])),
    )
    return bundle, write_review_bundle(bundle, bundle_root)
