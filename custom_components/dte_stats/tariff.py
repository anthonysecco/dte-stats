"""DTE residential prices from the rate books, per kWh or per CCF of use.

Electric (DTE Electric Rate Book, base rates effective Mar 5, 2026, case U-21860; PSCR 1.877 c/kWh
billed from Apr 2026; surcharges as of Sep 2026). Each plan's price for a kWh =
power supply (capacity + non-capacity) + distribution + power-supply surcharges (incl. PSCR)
+ delivery surcharges. Fixed monthly charges ($8.50 service + $1.50 LIEAF) are not per-kWh and
are reported separately. Prices before sales tax.

Gas (DTE Gas Rate Book, Rate A): distribution per CCF + the monthly Gas Cost Recovery factor
+ the GCR reservation charge. The $15.40 monthly customer charge is reported separately.

Prices change with each rate case and monthly gas factor; update the tables and release.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from .const import DTE_TZ

type PriceTable = dict[tuple[str, str], float]

PEAK = "peak"
OFF_PEAK = "off_peak"
SUPER_OFF_PEAK = "super_off_peak"
PERIODS = (PEAK, OFF_PEAK, SUPER_OFF_PEAK)
SUMMER = "summer"
WINTER = "winter"

PSCR_CENTS = 1.877  # Power Supply Cost Recovery factor billed from Apr 2026, c/kWh
ELECTRIC_FIXED_MONTHLY = 10.00  # service charge + LIEAF, USD
GAS_FIXED_MONTHLY = 15.40  # Rate A customer charge, USD
RATES_AS_OF = date(2026, 10, 23)  # rate book update the electric and gas tables come from


@dataclass(frozen=True, slots=True)
class ElectricPlan:
    """A time-of-use plan. Prices are cents per kWh."""

    key: str
    name: str
    peak_start: int  # local hour, weekdays only
    peak_end: int
    summer_months: frozenset[int]
    supply: PriceTable  # (season, period) -> capacity + non-capacity energy
    distribution: PriceTable
    supply_surcharges: float  # PSCR, securitization (C8.5)
    delivery_surcharges: float  # nuclear, EWR, securitization, IRM (C9.8)
    super_off_start: int | None = None  # every day, if the plan has a super off-peak window
    super_off_end: int | None = None

    def season(self, when: datetime) -> str:
        """Summer or winter pricing for this moment."""
        return SUMMER if when.astimezone(DTE_TZ).month in self.summer_months else WINTER

    def period(self, when: datetime) -> str:
        """Peak, off-peak or super off-peak for this moment (Michigan local time)."""
        local = when.astimezone(DTE_TZ)
        if (
            self.super_off_start is not None
            and self.super_off_end is not None
            and self.super_off_start <= local.hour < self.super_off_end
        ):
            return SUPER_OFF_PEAK
        if local.weekday() < 5 and self.peak_start <= local.hour < self.peak_end:
            return PEAK
        return OFF_PEAK

    def price(self, when: datetime) -> float:
        """USD per kWh used at this moment, before tax and fixed charges."""
        key = (self.season(when), self.period(when))
        cents = self.supply[key] + self.distribution[key] + self.supply_surcharges + self.delivery_surcharges
        return round(cents / 100, 6)

    def export_credit(self, when: datetime) -> float:
        """USD per kWh credited for solar sent to DTE under Rider 18 (power supply + PSCR)."""
        return round((self.supply[(self.season(when), self.period(when))] + PSCR_CENTS) / 100, 6)

    def next_peak(self, after: datetime) -> datetime | None:
        """Start of the next peak period after this moment, within the next 8 days."""
        hour = after.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        for step in range(1, 24 * 8):
            moment = hour + timedelta(hours=step)
            if self.period(moment) == PEAK and self.period(moment - timedelta(hours=1)) != PEAK:
                return moment.astimezone(DTE_TZ)
        return None


def _flat(value: float) -> PriceTable:
    return {(s, p): value for s in (SUMMER, WINTER) for p in PERIODS}


def _supply(summer_peak: float, summer_off: float, winter_peak: float, winter_off: float) -> PriceTable:
    prices: PriceTable = {(SUMMER, PEAK): summer_peak, (SUMMER, OFF_PEAK): summer_off}
    prices |= {(WINTER, PEAK): winter_peak, (WINTER, OFF_PEAK): winter_off}
    prices[(SUMMER, SUPER_OFF_PEAK)] = summer_off
    prices[(WINTER, SUPER_OFF_PEAK)] = winter_off
    return prices


PLANS: dict[str, ElectricPlan] = {
    "D1.11": ElectricPlan(
        key="D1.11",
        name="Standard time of day (D1.11)",
        peak_start=15,
        peak_end=19,
        summer_months=frozenset(range(6, 10)),  # June-September
        supply=_supply(5.360 + 9.047, 3.240 + 5.469, 3.839 + 6.480, 3.240 + 5.469),
        distribution=_flat(9.726),
        supply_surcharges=2.1283,
        delivery_surcharges=0.9757,
    ),
    "D1.2": ElectricPlan(
        key="D1.2",
        name="Time of day 11 a.m.-7 p.m. (D1.2)",
        peak_start=11,
        peak_end=19,
        summer_months=frozenset(range(6, 11)),  # June-October
        supply=_supply(4.677 + 11.526, 1.575 + 3.881, 3.951 + 9.736, 1.513 + 3.728),
        distribution=_flat(9.726),
        supply_surcharges=2.0501,
        delivery_surcharges=0.9643,
    ),
    "D1.13": ElectricPlan(
        key="D1.13",
        name="Overnight savers (D1.13)",
        peak_start=15,
        peak_end=19,
        summer_months=frozenset(range(6, 10)),
        supply={
            (SUMMER, PEAK): 5.949 + 10.042,
            (SUMMER, OFF_PEAK): 4.012 + 6.772,
            (SUMMER, SUPER_OFF_PEAK): 2.549 + 4.303,
            (WINTER, PEAK): 3.450 + 5.824,
            (WINTER, OFF_PEAK): 3.056 + 5.158,
            (WINTER, SUPER_OFF_PEAK): 2.549 + 4.303,
        },
        distribution={
            (SUMMER, PEAK): 19.568,
            (SUMMER, OFF_PEAK): 14.676,
            (SUMMER, SUPER_OFF_PEAK): 4.892,
            (WINTER, PEAK): 9.784,
            (WINTER, OFF_PEAK): 7.338,
            (WINTER, SUPER_OFF_PEAK): 4.892,
        },
        supply_surcharges=2.1283,
        delivery_surcharges=0.9757,
        super_off_start=1,
        super_off_end=7,
    ),
}


def plan_slug(key: str) -> str:
    """D1.11 -> d1_11 (option values and entity states)."""
    return key.lower().replace(".", "_")


PLANS_BY_SLUG: dict[str, ElectricPlan] = {plan_slug(key): plan for key, plan in PLANS.items()}

# Gas Rate A. Distribution per CCF by effective date (Jan 2025 bill example; U-21973 from Oct 1, 2026).
GAS_DISTRIBUTION: tuple[tuple[date, float], ...] = (
    (date(2025, 1, 1), 0.44616),
    (date(2026, 10, 1), 0.50791),
)
# Gas Cost Recovery factor actually billed, USD per CCF, by billing month (Sheet D-3.00).
GAS_GCR: dict[tuple[int, int], float] = {
    (2025, 1): 0.377, (2025, 2): 0.377, (2025, 3): 0.377, (2025, 4): 0.411, (2025, 5): 0.408,
    (2025, 6): 0.404, (2025, 7): 0.404, (2025, 8): 0.398, (2025, 9): 0.384, (2025, 10): 0.363,
    (2025, 11): 0.387, (2025, 12): 0.375, (2026, 1): 0.394, (2026, 2): 0.365, (2026, 3): 0.391,
    (2026, 4): 0.329, (2026, 5): 0.329, (2026, 6): 0.392, (2026, 7): 0.392, (2026, 8): 0.392,
    (2026, 9): 0.392, (2026, 10): 0.360, (2026, 11): 0.360,
}  # fmt: skip
# GCR reservation charge billed to sales customers, USD per CCF, from the given month on.
GAS_RESERVATION: tuple[tuple[date, float], ...] = (
    (date(2025, 1, 1), 0.035),
    (date(2025, 4, 1), 0.036),
    (date(2026, 4, 1), 0.050),
)


def _effective(table: tuple[tuple[date, float], ...], day: date) -> float:
    value = table[0][1]
    for start, amount in table:
        if day >= start:
            value = amount
    return value


def gas_price(when: datetime) -> float:
    """USD per CCF used on this day, before tax and the monthly customer charge."""
    day = when.astimezone(DTE_TZ).date()
    month = (day.year, day.month)
    if month in GAS_GCR:
        gcr = GAS_GCR[month]
    else:  # outside the table: the nearest known month
        known = sorted(GAS_GCR)
        gcr = GAS_GCR[known[0]] if month < known[0] else GAS_GCR[known[-1]]
    return round(_effective(GAS_DISTRIBUTION, day) + gcr + _effective(GAS_RESERVATION, day), 6)
