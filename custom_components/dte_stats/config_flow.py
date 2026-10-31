"""Config, reconfigure and options flows for DTE Stats."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    CONF_LINK,
    CONF_PLAN,
    CONF_SCAN_HOURS,
    DEFAULT_OPTIONS,
    DOMAIN,
    LINK_PREFIX,
    LINK_RE,
    LOGGER,
    MAX_SCAN_HOURS,
    MIN_SCAN_HOURS,
)
from .coordinator import DteConfigEntry
from .espi import DteClient, DteConnectionError, DteLinkError, UsageFeed, parse_feed
from .tariff import PLANS_BY_SLUG

LINK_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
PLAN_SELECTOR = SelectSelector(
    SelectSelectorConfig(options=list(PLANS_BY_SLUG), mode=SelectSelectorMode.LIST, translation_key=CONF_PLAN)
)
HOURS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=MIN_SCAN_HOURS, max=MAX_SCAN_HOURS, step=1, unit_of_measurement="h", mode=NumberSelectorMode.BOX
    )
)


async def _check_link(flow: ConfigFlow | OptionsFlowWithReload, link: str) -> tuple[UsageFeed | None, str | None]:
    """Download the file once; returns the feed or an error code."""
    if not LINK_RE.match(link):
        return None, "invalid_link"
    try:
        text = await DteClient(async_get_clientsession(flow.hass), link).fetch_text()
        parsed = await flow.hass.async_add_executor_job(parse_feed, text)
    except DteLinkError as err:
        LOGGER.warning("DTE did not return usage data for the link: %s", err)
        return None, "link_not_working"
    except DteConnectionError as err:
        LOGGER.warning("Could not reach DTE: %s", err)
        return None, "cannot_connect"
    return parsed, None


class DteStatsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a DTE account from its usage link."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the link and the electric plan."""
        errors: dict[str, str] = {}
        if user_input is not None:
            link = str(user_input[CONF_LINK]).strip()
            feed, error = await _check_link(self, link)
            if feed is not None:
                await self.async_set_unique_id(feed.customer_id or link.rsplit("/", 1)[-1].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="DTE Energy",
                    data={CONF_LINK: link},
                    options={**DEFAULT_OPTIONS, CONF_PLAN: user_input[CONF_PLAN]},
                )
            errors["base"] = error or "unknown"
        schema = vol.Schema(
            {
                vol.Required(CONF_LINK): LINK_SELECTOR,
                vol.Required(CONF_PLAN, default=(user_input or {}).get(CONF_PLAN, DEFAULT_OPTIONS[CONF_PLAN])): (
                    PLAN_SELECTOR
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors, description_placeholders={"link_prefix": LINK_PREFIX}
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Paste a new link (DTE links can stop working)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            link = str(user_input[CONF_LINK]).strip()
            feed, error = await _check_link(self, link)
            if feed is not None:
                if entry.unique_id and feed.customer_id and feed.customer_id != entry.unique_id:
                    errors["base"] = "different_account"
                else:
                    return self.async_update_reload_and_abort(entry, data_updates={CONF_LINK: link})
            else:
                errors["base"] = error or "unknown"
        schema = vol.Schema({vol.Required(CONF_LINK): LINK_SELECTOR})
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: DteConfigEntry) -> DteStatsOptionsFlow:
        """Plan and polling interval."""
        return DteStatsOptionsFlow()


class DteStatsOptionsFlow(OptionsFlowWithReload):
    """Edit the options; the entry reloads on save."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show or save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**DEFAULT_OPTIONS, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_PLAN, default=current[CONF_PLAN]): PLAN_SELECTOR,
                vol.Required(CONF_SCAN_HOURS, default=current[CONF_SCAN_HOURS]): HOURS_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
