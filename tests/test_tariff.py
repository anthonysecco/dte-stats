"""Prices and periods from the rate books (cents/kWh values from the October 2026 rate books)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.dte_stats.const import DTE_TZ
from custom_components.dte_stats.tariff import (
    OFF_PEAK,
    PEAK,
    PLANS,
    PLANS_BY_SLUG,
    SUPER_OFF_PEAK,
    gas_price,
    plan_slug,
)


def local(*args: int) -> datetime:
    return datetime(*args, tzinfo=DTE_TZ)


@pytest.mark.parametrize(
    ("plan", "when", "period", "cents"),
    [
        # D1.2: peak weekdays 11 am-7 pm; summer June-October
        ("D1.2", local(2026, 1, 14, 12), PEAK, 13.687 + 9.726 + 2.0501 + 0.9643),
        ("D1.2", local(2026, 1, 17, 12), OFF_PEAK, 5.241 + 9.726 + 2.0501 + 0.9643),  # Saturday
        ("D1.2", local(2026, 10, 29, 18), PEAK, 16.203 + 9.726 + 2.0501 + 0.9643),  # October is summer
        ("D1.2", local(2026, 10, 29, 19), OFF_PEAK, 5.456 + 9.726 + 2.0501 + 0.9643),
        # D1.11: peak weekdays 3-7 pm; summer June-September
        ("D1.11", local(2026, 7, 15, 16), PEAK, 14.407 + 9.726 + 2.1283 + 0.9757),
        ("D1.11", local(2026, 10, 29, 16), PEAK, 10.319 + 9.726 + 2.1283 + 0.9757),
        ("D1.11", local(2026, 10, 29, 12), OFF_PEAK, 8.709 + 9.726 + 2.1283 + 0.9757),
        # D1.13: super off-peak 1-7 am every day, with its own distribution charges
        ("D1.13", local(2026, 1, 17, 3), SUPER_OFF_PEAK, 6.852 + 4.892 + 2.1283 + 0.9757),
        ("D1.13", local(2026, 7, 15, 16), PEAK, 15.991 + 19.568 + 2.1283 + 0.9757),
        ("D1.13", local(2026, 1, 14, 12), OFF_PEAK, 8.214 + 7.338 + 2.1283 + 0.9757),
    ],
)
async def test_electric_prices(plan: str, when: datetime, period: str, cents: float) -> None:
    p = PLANS[plan]
    assert p.period(when) == period
    assert p.price(when) == pytest.approx(cents / 100, abs=1e-6)


async def test_period_uses_michigan_time() -> None:
    """11:00 EDT is 15:00 UTC."""
    assert PLANS["D1.2"].period(datetime(2026, 10, 29, 15, tzinfo=UTC)) == PEAK
    assert PLANS["D1.2"].period(datetime(2026, 10, 29, 14, 59, tzinfo=UTC)) == OFF_PEAK


async def test_next_peak() -> None:
    plan = PLANS["D1.2"]
    assert plan.next_peak(local(2026, 10, 30, 20)) == local(2026, 11, 2, 11)  # Friday evening -> Monday
    assert plan.next_peak(local(2026, 10, 29, 12)) == local(2026, 10, 30, 11)  # during a peak -> the next one


async def test_export_credit() -> None:
    assert PLANS["D1.2"].export_credit(local(2026, 1, 17, 12)) == pytest.approx((5.241 + 1.877) / 100)
    assert PLANS["D1.2"].export_credit(local(2026, 1, 14, 12)) == pytest.approx((13.687 + 1.877) / 100)


@pytest.mark.parametrize(
    ("when", "per_ccf"),
    [
        (local(2026, 10, 15, 12), 0.50791 + 0.360 + 0.050),  # new distribution charge from Oct 1, 2026
        (local(2026, 9, 15, 12), 0.44616 + 0.392 + 0.050),
        (local(2025, 1, 15, 12), 0.44616 + 0.377 + 0.035),
        (local(2027, 3, 15, 12), 0.50791 + 0.360 + 0.050),  # past the table: latest known factor
        (local(2024, 6, 15, 12), 0.44616 + 0.377 + 0.035),  # before the table: earliest
    ],
)
async def test_gas_price(when: datetime, per_ccf: float) -> None:
    assert gas_price(when) == pytest.approx(per_ccf, abs=1e-6)


async def test_slugs() -> None:
    assert plan_slug("D1.11") == "d1_11"
    assert set(PLANS_BY_SLUG) == {"d1_11", "d1_2", "d1_13"}
    assert PLANS_BY_SLUG["d1_2"] is PLANS["D1.2"]
