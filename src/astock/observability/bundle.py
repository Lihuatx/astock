from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


REVIEW_SCHEMA_VERSION = 2
LIVE_STATUS_SCHEMA_VERSION = 1


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def strategy_set_id(report_path: Path) -> str:
    return f"set-{sha256_file(report_path)[:16]}"


def review_bundle_content_hash(facts: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(facts))


def build_review_bundle(
    *,
    trading_day: str,
    generated_at: datetime,
    git_sha: str,
    data_cutoff: str,
    report_sha256: str,
    strategy_set_id: str,
    strategy_set: dict[str, Any],
    accounts: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    risk_decisions: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    health: dict[str, Any],
    alerts: list[dict[str, Any]],
    known_limitations: list[str],
    trade_plan: dict[str, Any] | None = None,
    execution_review: dict[str, Any] | None = None,
    activity: list[dict[str, Any]] | None = None,
    research_index: list[str] | None = None,
) -> dict[str, Any]:
    facts = {
        "trading_day": trading_day,
        "generated_at": generated_at.isoformat(),
        "git_sha": git_sha,
        "data_cutoff": data_cutoff,
        "report_sha256": report_sha256,
        "strategy_set_id": strategy_set_id,
        "strategy_set": strategy_set,
        "accounts": accounts,
        "signals": signals,
        "risk_decisions": risk_decisions,
        "orders": orders,
        "fills": fills,
        "equity_curve": equity_curve,
        "reconciliation": reconciliation,
        "health": health,
        "alerts": alerts,
        "known_limitations": known_limitations,
        "trade_plan": trade_plan or {"status": "UNAVAILABLE", "items": []},
        "execution_review": execution_review or {"status": "UNAVAILABLE"},
        "activity": activity or [],
        "research_index": research_index or [],
        "disclaimer": "A股模拟盘观察数据，不构成投资建议。",
    }
    content_hash = review_bundle_content_hash(facts)
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "bundle_id": f"review-{trading_day}-{content_hash[:16]}",
        "content_sha256": content_hash,
        **facts,
    }


def validate_review_bundle(bundle: dict[str, Any]) -> None:
    if bundle.get("schema_version") not in {1, REVIEW_SCHEMA_VERSION}:
        raise ValueError("unsupported review bundle schema")
    facts = {
        key: value
        for key, value in bundle.items()
        if key not in {"schema_version", "bundle_id", "content_sha256"}
    }
    actual = review_bundle_content_hash(facts)
    if actual != bundle.get("content_sha256"):
        raise ValueError("review bundle content hash mismatch")
    expected_id = f"review-{bundle['trading_day']}-{actual[:16]}"
    if expected_id != bundle.get("bundle_id"):
        raise ValueError("review bundle id mismatch")


def write_review_bundle(bundle: dict[str, Any], root: Path) -> Path:
    validate_review_bundle(bundle)
    target = root / bundle["trading_day"] / f"{bundle['bundle_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(bundle)
    if target.exists():
        existing_bytes = target.read_bytes()
        existing = json.loads(existing_bytes)
        validate_review_bundle(existing)
        if existing_bytes != encoded:
            raise ValueError("immutable review bundle already exists with different content")
        return target
    target.write_bytes(encoded)
    return target


def build_live_status(
    *,
    source_id: str,
    generated_at: datetime,
    runner: dict[str, Any],
    sources: dict[str, Any],
    jobs: dict[str, Any],
    sync: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> dict[str, Any]:
    facts = {
        "schema_version": LIVE_STATUS_SCHEMA_VERSION,
        "source_id": source_id,
        "generated_at": generated_at.isoformat(),
        "runner": runner,
        "sources": sources,
        "jobs": jobs,
        "sync": sync,
        "alerts": alerts,
    }
    return {"status_id": f"status-{sha256_bytes(canonical_json(facts))[:24]}", **facts}


def validate_live_status(status: dict[str, Any]) -> None:
    if status.get("schema_version") != LIVE_STATUS_SCHEMA_VERSION:
        raise ValueError("unsupported live status schema")
    facts = {key: value for key, value in status.items() if key != "status_id"}
    expected = f"status-{sha256_bytes(canonical_json(facts))[:24]}"
    if status.get("status_id") != expected:
        raise ValueError("live status id mismatch")
