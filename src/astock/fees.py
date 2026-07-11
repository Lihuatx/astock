from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from astock.models import Side


CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeBreakdown:
    commission: Decimal
    stamp_tax: Decimal
    transfer_fee: Decimal

    @property
    def total(self) -> Decimal:
        return self.commission + self.stamp_tax + self.transfer_fee


@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: Decimal = Decimal("0.00025")
    minimum_commission: Decimal = Decimal("5")
    stamp_tax_rate: Decimal = Decimal("0.0005")
    transfer_fee_rate: Decimal = Decimal("0.00001")

    def calculate(
        self,
        side: Side,
        fill_amount: Decimal,
        cumulative_amount: Decimal,
        commission_already_charged: Decimal,
    ) -> FeeBreakdown:
        commission_due = max(self.minimum_commission, money(cumulative_amount * self.commission_rate))
        commission = max(Decimal("0"), commission_due - commission_already_charged)
        stamp_tax = money(fill_amount * self.stamp_tax_rate) if side is Side.SELL else Decimal("0")
        transfer_fee = money(fill_amount * self.transfer_fee_rate)
        return FeeBreakdown(money(commission), stamp_tax, transfer_fee)

