from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from astock.models import Quote


@dataclass(frozen=True)
class QualityResult:
    ok: bool
    reasons: tuple[str, ...]
    price_diff_pct: Decimal | None = None


def validate_quote(quote: Quote, now: datetime, max_age: timedelta = timedelta(seconds=90)) -> QualityResult:
    reasons: list[str] = []
    if quote.last <= 0 or quote.prev_close <= 0:
        reasons.append("invalid_price")
    if quote.volume < 0:
        reasons.append("invalid_volume")
    if quote.suspended:
        reasons.append("suspended")
    if quote.source_at and now - quote.source_at > max_age:
        reasons.append("stale_quote")
    return QualityResult(not reasons, tuple(reasons))


def compare_quotes(primary: Quote, secondary: Quote, max_diff_pct: Decimal = Decimal("0.5")) -> QualityResult:
    reasons: list[str] = []
    if primary.symbol != secondary.symbol:
        reasons.append("symbol_mismatch")
        return QualityResult(False, tuple(reasons))
    if secondary.last <= 0:
        return QualityResult(False, ("secondary_invalid_price",))
    diff = abs(primary.last - secondary.last) / secondary.last * Decimal("100")
    if diff > max_diff_pct:
        reasons.append("price_divergence")
    return QualityResult(not reasons, tuple(reasons), diff)

