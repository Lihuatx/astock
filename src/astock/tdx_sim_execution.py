from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any

from astock.data.tdx import TdxClient
from astock.data.tdx_sim import JsonlErrorLog, TdxSimClient
from astock.models import Side
from astock.observability.repository import ObservabilityRepository
from astock.paper import PAPER_SLIPPAGE, _rebalance_intents


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _positions(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        symbol = str(row.get("Code") or "")
        if symbol:
            result[symbol] = int(_decimal(row.get("TotalVol")))
    return result


def execute_tdx_sim_plan(
    plan_path: Path,
    strategy_set_id: str,
    market_client: TdxClient,
    sim_client: TdxSimClient,
    repository: ObservabilityRepository,
    error_log: JsonlErrorLog,
    executed_at: datetime,
) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        error_log.append("paper_execute", exc, executed_at, {"plan_path": str(plan_path)})
        return {"enqueued": 0, "acknowledged": 0, "errors": 1, "unknown": 0, "reason": str(exc)}
    if plan.get("strategy_set_id") != strategy_set_id:
        error = ValueError("pending signal plan does not match the current strategy set")
        error_log.append("paper_execute", error, executed_at, {"plan_path": str(plan_path)})
        return {"enqueued": 0, "acknowledged": 0, "errors": 1, "unknown": 0, "reason": "strategy_set_mismatch"}

    try:
        account = sim_client.snapshot()
    except Exception as exc:
        return {"enqueued": 0, "acknowledged": 0, "errors": 1, "unknown": 0, "reason": str(exc)}

    selected = sorted({symbol for item in plan.get("strategies", []) for symbol in item.get("symbols", [])})
    current_positions = _positions(account.positions)
    symbols = sorted(set(selected) | set(current_positions))
    quotes = {}
    for symbol in symbols:
        try:
            quotes[symbol] = market_client.get_snapshot(symbol)
        except Exception as exc:
            error_log.append("get_market_snapshot", exc, executed_at, {"symbol": symbol})
    prices = {symbol: quote.last for symbol, quote in quotes.items() if quote.last > 0}
    selected = [symbol for symbol in selected if symbol in prices]
    current_positions = {symbol: quantity for symbol, quantity in current_positions.items() if symbol in prices}
    equity = _decimal(account.asset.get("Asset") or account.asset.get("Balance"))
    intents = _rebalance_intents(
        "combined_observer", selected, current_positions, prices, equity, executed_at
    )
    enqueued = 0
    enqueue_errors = 0
    for intent in intents:
        try:
            quote = quotes[intent.symbol]
            raw_limit_price = (
                quote.ask_price * (Decimal("1") + PAPER_SLIPPAGE)
                if intent.side is Side.BUY
                else quote.bid_price * (Decimal("1") - PAPER_SLIPPAGE)
            )
            limit_price = raw_limit_price.quantize(
                Decimal("0.01"),
                rounding=ROUND_CEILING if intent.side is Side.BUY else ROUND_FLOOR,
            )
            scoped = replace(
                intent,
                client_order_id=f"{strategy_set_id}:{intent.client_order_id}",
                limit_price=limit_price,
            )
            repository.enqueue_tdx_sim_order({
                "client_order_id": scoped.client_order_id,
                "strategy_set_id": strategy_set_id,
                "strategy": "combined_observer",
                "signal_date": plan["signal_date"],
                "symbol": scoped.symbol,
                "side": scoped.side.value,
                "quantity": scoped.quantity,
                "limit_price": str(scoped.limit_price),
                "created_at": scoped.created_at.isoformat(),
            })
            enqueued += 1
        except Exception as exc:
            enqueue_errors += 1
            error_log.append("enqueue_tdx_sim_order", exc, executed_at, {"symbol": intent.symbol})

    acknowledged = 0
    errors = 0
    unknown = 0
    claimed = repository.claim_tdx_sim_orders(
        executed_at,
        strategy_set_id=strategy_set_id,
        signal_date=plan["signal_date"],
    )
    for item in claimed:
        try:
            response = sim_client.submit_limit_order(
                item["symbol"], Side(item["side"]), item["quantity"], Decimal(item["limit_price"])
            )
            repository.finish_tdx_sim_order(
                item["client_order_id"], "ACK", datetime.now(executed_at.tzinfo),
                tdx_order_id=str(response["Wtbh"]), response=response,
            )
            repository.append_event(
                "TDX_SIM_ORDER_ACK",
                datetime.now(executed_at.tzinfo),
                {"client_order_id": item["client_order_id"], "tdx_order_id": str(response["Wtbh"])},
                event_id=f"tdx-sim-order:{item['client_order_id']}",
            )
            acknowledged += 1
        except Exception as exc:
            status = "UNKNOWN" if "request failed" in str(exc).lower() else "ERROR"
            repository.finish_tdx_sim_order(
                item["client_order_id"], status, datetime.now(executed_at.tzinfo), error=str(exc)
            )
            repository.append_event(
                "TDX_SIM_ORDER_ERROR",
                datetime.now(executed_at.tzinfo),
                {"client_order_id": item["client_order_id"], "status": status, "error": str(exc)},
                event_id=f"tdx-sim-order-error:{item['client_order_id']}",
            )
            if status == "UNKNOWN":
                unknown += 1
            else:
                errors += 1
    return {
        "enqueued": enqueued,
        "claimed": len(claimed),
        "acknowledged": acknowledged,
        "errors": errors + enqueue_errors,
        "unknown": unknown,
        "selected_symbols": selected,
    }


def review_tdx_sim_day(
    sim_client: TdxSimClient,
    repository: ObservabilityRepository,
    error_log: JsonlErrorLog,
    review_root: Path,
    reviewed_at: datetime,
) -> dict[str, Any]:
    try:
        snapshot = sim_client.snapshot()
    except Exception as exc:
        error_log.append("daily_review", exc, reviewed_at)
        return {"saved": False, "ok": False, "error": str(exc)}

    trading_day = reviewed_at.date().isoformat()
    local_orders = [
        item for item in repository.tdx_sim_orders() if str(item["created_at"]).startswith(trading_day)
    ]
    remote_by_id = {
        str(item.get("Wtbh")): item for item in snapshot.orders if str(item.get("Wtbh") or "")
    }
    missing_ack = [
        item["client_order_id"] for item in local_orders
        if item["status"] == "ACK" and str(item.get("tdx_order_id") or "") not in remote_by_id
    ]
    uncertain = [item["client_order_id"] for item in local_orders if item["status"] in {"SENDING", "UNKNOWN"}]
    errors = [item["client_order_id"] for item in local_orders if item["status"] == "ERROR"]
    mapped = {str(item.get("tdx_order_id") or "") for item in local_orders}
    external = sorted(order_id for order_id in remote_by_id if order_id not in mapped)
    review = {
        "ok": not missing_ack and not uncertain,
        "missing_acknowledged_orders": missing_ack,
        "uncertain_orders": uncertain,
        "failed_orders": errors,
        "unmapped_tdx_orders": external,
        "local_order_count": len(local_orders),
        "tdx_order_count": len(snapshot.orders),
    }
    fact = {
        "trading_day": trading_day,
        "captured_at": reviewed_at.isoformat(),
        "asset": snapshot.asset,
        "positions": snapshot.positions,
        "orders": snapshot.orders,
        "review": review,
    }
    try:
        fact_id = repository.save_tdx_sim_daily_fact(fact)
        combined_accounts = [
            item for item in repository.accounts("CURRENT") if item["strategy"] == "combined_observer"
        ]
        if combined_accounts:
            account = combined_accounts[0]
            cash = _decimal(snapshot.asset.get("Cash"))
            balance = _decimal(snapshot.asset.get("Balance"), str(cash))
            market_value = _decimal(snapshot.asset.get("MarketValue"))
            equity = _decimal(snapshot.asset.get("Asset"), str(cash + market_value))
            previous = repository.snapshots(account["account_id"])
            peak = max([_decimal(item["equity"]) for item in previous] + [equity])
            repository.save_snapshot({
                "snapshot_id": f"{fact_id}:combined_observer",
                "account_id": account["account_id"],
                "trading_day": reviewed_at.date().isoformat(),
                "captured_at": reviewed_at.isoformat(),
                "cash": cash,
                "frozen_cash": max(Decimal("0"), balance - cash),
                "market_value": market_value,
                "equity": equity,
                "fees": Decimal("0"),
                "drawdown": equity / peak - Decimal("1") if peak else Decimal("0"),
                "positions": _positions(snapshot.positions),
                "reconciliation_ok": review["ok"],
            })
        target_dir = review_root / reviewed_at.date().isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{fact_id.replace(':', '-')}.json"
        encoded = json.dumps({"fact_id": fact_id, **fact}, ensure_ascii=False, indent=2)
        if target.exists() and target.read_text(encoding="utf-8") != encoded:
            raise ValueError("immutable TDX simulation review file already exists with different content")
        target.write_text(encoded, encoding="utf-8")
        repository.append_event(
            "TDX_SIM_DAILY_REVIEW",
            reviewed_at,
            {"fact_id": fact_id, **review},
            event_id=fact_id,
        )
        return {"saved": True, "fact_id": fact_id, **review, "path": str(target)}
    except Exception as exc:
        error_log.append("daily_review_save", exc, reviewed_at)
        return {"saved": False, "ok": False, "error": str(exc), **review}
