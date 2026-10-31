"""Import DTE's readings into Home Assistant's long-term statistics.

DTE publishes usage a day or two late, so readings go in as external statistics at the hour
they happened (the pattern Home Assistant's own utility integrations use). Each refresh adds
only the hours after the last imported one and continues the running sums.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics, get_last_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import DOMAIN, ELECTRIC, GAS, LOGGER
from .espi import Reading, Series

UNITS = {ELECTRIC: UnitOfEnergy.KILO_WATT_HOUR, GAS: UnitOfVolume.CENTUM_CUBIC_FEET}
UNIT_CLASSES = {ELECTRIC: EnergyConverter.UNIT_CLASS, GAS: VolumeConverter.UNIT_CLASS}


@dataclass(frozen=True, slots=True)
class StatisticIds:
    """The two statistics kept for one service."""

    consumption: str
    cost: str


def statistic_ids(prefix: str, kind: str) -> StatisticIds:
    """E.g. dte_stats:1a2b3c4d_electric_consumption."""
    return StatisticIds(f"{DOMAIN}:{prefix}_{kind}_consumption", f"{DOMAIN}:{prefix}_{kind}_cost")


def _metadata(statistic_id: str, name: str, kind: str | None) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=UNIT_CLASSES[kind] if kind else None,
        unit_of_measurement=UNITS[kind] if kind else None,
    )


async def _last(hass: HomeAssistant, statistic_id: str) -> tuple[float, float] | None:
    """(start timestamp, sum) of the newest imported hour, if any."""
    found = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    if not found or statistic_id not in found:
        return None
    row = found[statistic_id][0]
    return float(row["start"]), float(row.get("sum") or 0.0)


async def async_import(
    hass: HomeAssistant, prefix: str, series: Series, price: Callable[[datetime], float]
) -> int:
    """Add readings newer than what's stored; returns how many hours were added."""
    ids = statistic_ids(prefix, series.kind)
    usage_last = await _last(hass, ids.consumption)
    cost_last = await _last(hass, ids.cost)
    after = usage_last[0] if usage_last else float("-inf")
    usage_sum = usage_last[1] if usage_last else 0.0
    cost_sum = cost_last[1] if cost_last else 0.0

    new: list[Reading] = [r for r in series.readings if r.start.timestamp() > after]
    if not new:
        return 0
    usage_rows: list[StatisticData] = []
    cost_rows: list[StatisticData] = []
    for reading in new:
        cost = reading.value * price(reading.start)
        usage_sum += reading.value
        cost_sum += cost
        usage_rows.append(StatisticData(start=reading.start, state=reading.value, sum=usage_sum))
        cost_rows.append(StatisticData(start=reading.start, state=cost, sum=cost_sum))
    usage_meta = _metadata(ids.consumption, f"DTE {series.kind} consumption", series.kind)
    async_add_external_statistics(hass, usage_meta, usage_rows)
    async_add_external_statistics(hass, _metadata(ids.cost, f"DTE {series.kind} cost", None), cost_rows)
    LOGGER.debug("Imported %s %s readings from %s", len(new), series.kind, new[0].start.isoformat())
    return len(new)
