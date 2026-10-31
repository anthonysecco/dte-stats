"""Usage and cost summaries for the sensors, computed from the readings in the file."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .const import COMPARE_DAYS, DTE_TZ, ELECTRIC
from .espi import Series
from .tariff import PEAK, PLANS, ElectricPlan, gas_price


@dataclass(slots=True)
class Totals:
    """Amount (kWh or CCF) and cost (USD) over some span."""

    amount: float = 0.0
    cost: float = 0.0


@dataclass(slots=True)
class SeriesSummary:
    """What the sensors show for one service."""

    data_through: datetime | None = None
    last_day: date | None = None
    last_day_totals: Totals = field(default_factory=Totals)
    month: date | None = None  # first day of the month of last_day
    month_totals: Totals = field(default_factory=Totals)
    readings: int = 0
    estimated: int = 0


@dataclass(slots=True)
class PlanComparison:
    """Electric cost of the last COMPARE_DAYS days of use on each plan (per-kWh charges only)."""

    days: int
    start: date
    end: date
    costs: dict[str, float]
    peak_share: float  # % of kWh in the chosen plan's peak hours

    @property
    def cheapest(self) -> str:
        """Key of the cheapest plan."""
        return min(self.costs, key=lambda k: self.costs[k])


def _complete_days(series: Series) -> list[date]:
    """Local days the file fully covers (electric: 23+ hourly readings; gas: one daily reading)."""
    counts: dict[date, float] = defaultdict(float)
    for reading in series.readings:
        counts[reading.start.astimezone(DTE_TZ).date()] += reading.seconds / 3600
    return sorted(d for d, hours in counts.items() if hours >= 23)


def summarize(series: Series, price: Callable[[datetime], float]) -> SeriesSummary:
    """Last complete day and its month to date, priced with the given function."""
    result = SeriesSummary(data_through=series.last_end, readings=len(series.readings), estimated=series.estimated)
    days = _complete_days(series)
    if not days:
        return result
    result.last_day = days[-1]
    result.month = result.last_day.replace(day=1)
    for reading in series.readings:
        day = reading.start.astimezone(DTE_TZ).date()
        if result.month <= day <= result.last_day:
            cost = reading.value * price(reading.start)
            result.month_totals.amount += reading.value
            result.month_totals.cost += cost
            if day == result.last_day:
                result.last_day_totals.amount += reading.value
                result.last_day_totals.cost += cost
    return result


def compare_plans(series: Series, chosen: ElectricPlan) -> PlanComparison | None:
    """Cost of the last COMPARE_DAYS complete days on every plan, and the chosen plan's peak share."""
    if series.kind != ELECTRIC:
        return None
    days = _complete_days(series)
    if not days:
        return None
    end = days[-1]
    start = max(days[0], end - timedelta(days=COMPARE_DAYS - 1))
    window = [r for r in series.readings if start <= r.start.astimezone(DTE_TZ).date() <= end]
    costs = {key: round(sum(r.value * plan.price(r.start) for r in window), 2) for key, plan in PLANS.items()}
    total = sum(r.value for r in window)
    peak = sum(r.value for r in window if chosen.period(r.start) == PEAK)
    return PlanComparison(
        days=(end - start).days + 1,
        start=start,
        end=end,
        costs=costs,
        peak_share=round(100 * peak / total, 1) if total else 0.0,
    )


def price_for(kind: str, plan: ElectricPlan) -> Callable[[datetime], float]:
    """The per-unit price function for a service."""
    return plan.price if kind == ELECTRIC else gas_price
