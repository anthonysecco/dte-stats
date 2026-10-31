"""Diagnostics for DTE Energy: coverage and settings, never the link or the readings."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_LINK
from .coordinator import DteConfigEntry
from .statistics import statistic_ids
from .tariff import RATES_AS_OF

TO_REDACT = {CONF_LINK}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: DteConfigEntry) -> dict[str, Any]:
    """Settings, what the file covers, statistic ids and the last error."""
    coordinator = entry.runtime_data
    data = coordinator.data
    series: dict[str, Any] = {}
    if data is not None:
        for kind, s in data.feed.series.items():
            summary = data.summaries.get(kind)
            ids = statistic_ids(coordinator.prefix, kind)
            series[kind] = {
                "readings": len(s.readings),
                "estimated_readings": s.estimated,
                "first": s.first.isoformat() if s.first else None,
                "through": s.last_end.isoformat() if s.last_end else None,
                "interval_seconds": sorted({r.seconds for r in s.readings}),
                "power_of_ten": s.unit_multiplier,
                "last_complete_day": summary.last_day.isoformat() if summary and summary.last_day else None,
                "statistic_ids": [ids.consumption, ids.cost],
                "imported_last_refresh": data.imported.get(kind, 0),
            }
    return {
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "plan": coordinator.plan.key,
        "rates_as_of": RATES_AS_OF.isoformat(),
        "last_update_success": coordinator.last_update_success,
        "last_error": coordinator.last_error,
        "fetched": data.fetched.isoformat() if data else None,
        "feed_updated": data.feed.updated.isoformat() if data and data.feed.updated else None,
        "series": series,
        "comparison": None
        if data is None or data.comparison is None
        else {
            "from": data.comparison.start.isoformat(),
            "to": data.comparison.end.isoformat(),
            "costs": data.comparison.costs,
            "peak_share": data.comparison.peak_share,
        },
    }
