"""Polling coordinator: download the usage file, import new hours into statistics, summarize."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LINK,
    CONF_PLAN,
    CONF_SCAN_HOURS,
    DEFAULT_OPTIONS,
    DOMAIN,
    ELECTRIC,
    ISSUE_LINK,
    LOGGER,
    scan_interval,
)
from .espi import DteClient, DteConnectionError, DteLinkError, UsageFeed, parse_feed
from .statistics import async_import
from .summary import PlanComparison, SeriesSummary, compare_plans, price_for, summarize
from .tariff import PLANS_BY_SLUG, ElectricPlan

type DteConfigEntry = ConfigEntry[DteCoordinator]


@dataclass(slots=True)
class DteData:
    """Everything the entities read."""

    feed: UsageFeed
    summaries: dict[str, SeriesSummary]
    comparison: PlanComparison | None
    fetched: datetime
    imported: dict[str, int] = field(default_factory=dict)


class DteCoordinator(DataUpdateCoordinator[DteData]):
    """Fetches the usage link every few hours."""

    config_entry: DteConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DteConfigEntry) -> None:
        """Read the options."""
        options = {**DEFAULT_OPTIONS, **entry.options}
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=scan_interval(options[CONF_SCAN_HOURS]),
        )
        self.plan: ElectricPlan = PLANS_BY_SLUG.get(options[CONF_PLAN], PLANS_BY_SLUG[DEFAULT_OPTIONS[CONF_PLAN]])
        self.client = DteClient(async_get_clientsession(hass), entry.data[CONF_LINK])
        self.prefix = (entry.unique_id or entry.entry_id).replace("-", "")[:8].lower()
        self.last_error: str | None = None

    async def _async_update_data(self) -> DteData:
        try:
            text = await self.client.fetch_text()
            feed = await self.hass.async_add_executor_job(parse_feed, text)
        except DteLinkError as err:
            self.last_error = f"link: {err}"
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                ISSUE_LINK,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_LINK,
            )
            raise UpdateFailed(f"DTE did not return usage data for the link ({err})") from err
        except DteConnectionError as err:
            self.last_error = f"connection: {err}"
            raise UpdateFailed(f"Could not reach DTE: {err}") from err
        ir.async_delete_issue(self.hass, DOMAIN, ISSUE_LINK)
        self.last_error = None

        imported: dict[str, int] = {}
        for kind, series in feed.series.items():
            imported[kind] = await async_import(self.hass, self.prefix, series, price_for(kind, self.plan))
        summaries, comparison = await self.hass.async_add_executor_job(_summarize, feed, self.plan)
        return DteData(feed, summaries, comparison, dt_util.utcnow(), imported)


def _summarize(feed: UsageFeed, plan: ElectricPlan) -> tuple[dict[str, SeriesSummary], PlanComparison | None]:
    """Per-service summaries and the plan comparison (off the event loop: ~10k readings)."""
    summaries = {kind: summarize(series, price_for(kind, plan)) for kind, series in feed.series.items()}
    comparison = compare_plans(feed.series[ELECTRIC], plan) if ELECTRIC in feed.series else None
    return summaries, comparison
