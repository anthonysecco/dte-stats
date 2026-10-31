"""Binary sensor for DTE Stats: is it peak time on the chosen plan?"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ELECTRIC
from .coordinator import DteConfigEntry, DteCoordinator
from .entity import TariffEntity
from .tariff import PEAK

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the peak sensor when the file has electric usage."""
    coordinator = entry.runtime_data
    if ELECTRIC in coordinator.data.feed.series:
        async_add_entities([PeakNowSensor(coordinator)])


class PeakNowSensor(TariffEntity, BinarySensorEntity):
    """On during the chosen plan's peak hours (weekdays; Michigan time)."""

    def __init__(self, coordinator: DteCoordinator) -> None:
        """Bind the description."""
        super().__init__(coordinator, BinarySensorEntityDescription(key="peak_now", translation_key="peak_now"))

    @property
    def is_on(self) -> bool:
        """True during peak hours."""
        return self.coordinator.plan.period(dt_util.utcnow()) == PEAK

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Plan and the next peak start."""
        plan = self.coordinator.plan
        nxt = plan.next_peak(dt_util.utcnow())
        return {"plan": plan.key, "next_peak": nxt.isoformat() if nxt else None}
