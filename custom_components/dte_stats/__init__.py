"""DTE Stats: DTE Energy usage, costs and time-of-day prices from the Green Button data link."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_LINK
from .coordinator import DteConfigEntry, DteCoordinator

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: DteConfigEntry) -> bool:
    """Set up DTE Stats from a config entry."""
    coordinator = DteCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DteConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: DteConfigEntry) -> None:
    """Clear the link issue when the entry is deleted (imported statistics stay in the database)."""
    ir.async_delete_issue(hass, DOMAIN, ISSUE_LINK)
