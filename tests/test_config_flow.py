"""Config, reconfigure and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dte_stats.const import CONF_LINK, CONF_PLAN, CONF_SCAN_HOURS, DEFAULT_OPTIONS, DOMAIN

from .conftest import CUSTOMER, LINK, OTHER_LINK, build_feed, wait_recorder


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result


async def test_user_flow(hass: HomeAssistant, mock_dte) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LINK: f"  {LINK} ", CONF_PLAN: "d1_2"}
    )
    await wait_recorder(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DTE Energy"
    assert result["data"] == {CONF_LINK: LINK}  # stored trimmed
    assert result["options"] == {**DEFAULT_OPTIONS, CONF_PLAN: "d1_2"}
    assert result["result"].unique_id == CUSTOMER
    assert hass.states.get("sensor.dte_energy_electricity_price").attributes["plan"] == "D1.2"


@pytest.mark.parametrize(
    ("link", "error"),
    [
        ("https://example.com/link/00000000-0000-4000-8000-000000000000", "invalid_link"),
        ("usagedata.dteenergy.com/link/00000000-0000-4000-8000-000000000000", "invalid_link"),
        ("https://usagedata.dteenergy.com/link/not-a-uuid", "invalid_link"),
    ],
)
async def test_bad_link_format(hass: HomeAssistant, link: str, error: str) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LINK: link, CONF_PLAN: "d1_11"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


@pytest.mark.parametrize(
    ("status", "text", "error"),
    [
        (404, "", "link_not_working"),
        (200, "<html>expired</html>", "link_not_working"),
        (503, "", "cannot_connect"),
    ],
)
async def test_link_check_errors(hass: HomeAssistant, aioclient_mock, status: int, text: str, error: str) -> None:
    aioclient_mock.get(LINK, status=status, text=text)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LINK: LINK, CONF_PLAN: "d1_11"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_same_account_twice(hass: HomeAssistant, mock_dte) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS)).add_to_hass(
        hass
    )
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LINK: LINK, CONF_PLAN: "d1_11"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_with_new_link(hass: HomeAssistant, mock_dte) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await wait_recorder(hass)

    mock_dte.get(OTHER_LINK, text=build_feed())  # a fresh link for the same account
    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LINK: OTHER_LINK})
    await wait_recorder(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_LINK] == OTHER_LINK


async def test_reconfigure_rejects_another_account(hass: HomeAssistant, mock_dte) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await wait_recorder(hass)

    mock_dte.get(OTHER_LINK, text=build_feed(customer="12345678-1234-5234-8234-123456789012"))
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LINK: OTHER_LINK})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "different_account"}
    assert entry.data[CONF_LINK] == LINK


async def test_options_flow(hass: HomeAssistant, mock_dte) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await wait_recorder(hass)
    assert entry.runtime_data.plan.key == "D1.11"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PLAN: "d1_13", CONF_SCAN_HOURS: 12}
    )
    await wait_recorder(hass)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_PLAN: "d1_13", CONF_SCAN_HOURS: 12}
    assert entry.runtime_data.plan.key == "D1.13"  # reloaded
    assert entry.runtime_data.update_interval.total_seconds() == 12 * 3600
