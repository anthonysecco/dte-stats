"""Base entities for DTE Energy."""

from __future__ import annotations

from datetime import datetime

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import DteCoordinator


class DteEntity(CoordinatorEntity[DteCoordinator]):
    """One entity on the "DTE Energy" service device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: DteCoordinator, description: EntityDescription) -> None:
        """Bind the description and device."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="DTE Energy",
            manufacturer="DTE Energy",
            model="Green Button usage data",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Usage arrives a day or two late anyway: keep showing the last good data after a failed poll."""
        return self.coordinator.data is not None


class TariffEntity(DteEntity):
    """Price and peak entities: they follow the clock, not the usage file."""

    @property
    def available(self) -> bool:
        """Prices come from the rate tables, so they are always available."""
        return True

    async def async_added_to_hass(self) -> None:
        """Update at the top of every hour, when a period can change."""
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_change(self.hass, self._on_hour, minute=0, second=1))

    @callback
    def _on_hour(self, _now: datetime) -> None:
        self.async_write_ha_state()
