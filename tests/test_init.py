"""Setup, statistics import, sensors, repairs and diagnostics."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dte_stats.const import CONF_LINK, DEFAULT_OPTIONS, DOMAIN, DTE_TZ, ISSUE_LINK
from custom_components.dte_stats.diagnostics import async_get_config_entry_diagnostics
from custom_components.dte_stats.tariff import PLANS, gas_price

from .conftest import CUSTOMER, DAYS, LINK, PREFIX, build_feed, wait_recorder

MANIFEST = Path(__file__).parent.parent / "custom_components" / "dte_stats" / "manifest.json"
NOW = "2026-10-31 09:00:00-04:00"  # Saturday morning; data runs through Friday Oct 30
IDS = [f"{DOMAIN}:{PREFIX}_{kind}_{what}" for kind in ("electric", "gas") for what in ("consumption", "cost")]


async def _setup(hass: HomeAssistant, **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, title="DTE Energy", unique_id=CUSTOMER, data={CONF_LINK: LINK}, options={**DEFAULT_OPTIONS, **options}
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await wait_recorder(hass)
    return entry


async def _last_sums(hass: HomeAssistant) -> dict[str, tuple[datetime, float]]:
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, datetime(2026, 9, 1, tzinfo=UTC), None, set(IDS), "hour", None, {"sum"}
    )
    return {k: (datetime.fromtimestamp(v[-1]["start"], UTC), v[-1]["sum"]) for k, v in rows.items()}


def _day_cost(plan: str, day: date, kwh_per_hour: float = 1.0) -> float:
    start = datetime(day.year, day.month, day.day, tzinfo=DTE_TZ).astimezone(UTC)
    end = (datetime(day.year, day.month, day.day, tzinfo=DTE_TZ) + timedelta(days=1)).astimezone(UTC)
    hours = int((end - start).total_seconds() // 3600)
    return sum(kwh_per_hour * PLANS[plan].price(start + timedelta(hours=h)) for h in range(hours))


async def test_setup_imports_statistics(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to(NOW)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    sums = await _last_sums(hass)
    assert set(sums) == set(IDS)
    last_hour = datetime(2026, 10, 31, 3, tzinfo=UTC)  # 11 pm EDT Oct 30
    assert sums[IDS[0]] == (last_hour, pytest.approx(DAYS * 24))
    assert sums[IDS[2]] == (datetime(2026, 10, 30, 4, tzinfo=UTC), pytest.approx(DAYS * 2.0))
    expected_cost = sum(_day_cost("D1.11", date(2026, 9, 21) + timedelta(days=n)) for n in range(DAYS))
    assert sums[IDS[1]][1] == pytest.approx(expected_cost, abs=0.01)
    assert entry.runtime_data.data.imported == {"electric": DAYS * 24, "gas": DAYS}


async def test_refresh_adds_only_new_hours(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to(NOW)
    entry = await _setup(hass)

    mock_dte.clear_requests()
    mock_dte.get(LINK, text=build_feed(end_day=date(2026, 10, 31), days=DAYS + 1))
    await entry.runtime_data.async_refresh()
    await wait_recorder(hass)
    assert entry.runtime_data.data.imported == {"electric": 24, "gas": 1}
    sums = await _last_sums(hass)
    assert sums[IDS[0]][1] == pytest.approx((DAYS + 1) * 24)  # sums continue, nothing doubled
    assert sums[IDS[2]][1] == pytest.approx((DAYS + 1) * 2.0)

    await entry.runtime_data.async_refresh()  # same file again: nothing new
    await wait_recorder(hass)
    assert entry.runtime_data.data.imported == {"electric": 0, "gas": 0}


async def test_usage_sensors(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to(NOW)
    hass.config.units = US_CUSTOMARY_SYSTEM  # metric would show gas in m3
    await _setup(hass)
    last_day = date(2026, 10, 30)

    state = hass.states.get("sensor.dte_energy_electricity_last_day")
    assert float(state.state) == 24.0
    assert state.attributes["date"] == "2026-10-30"
    assert float(hass.states.get("sensor.dte_energy_electricity_cost_last_day").state) == round(
        _day_cost("D1.11", last_day), 2
    )
    month = hass.states.get("sensor.dte_energy_electricity_this_month")
    assert float(month.state) == 720.0
    assert month.attributes["month"] == "2026-10"
    assert month.attributes["monthly_fixed_charges"] == 10.0

    assert float(hass.states.get("sensor.dte_energy_gas_last_day").state) == 2.0
    assert float(hass.states.get("sensor.dte_energy_gas_cost_last_day").state) == round(2 * gas_price(
        datetime(2026, 10, 30, 12, tzinfo=DTE_TZ)), 2)
    assert float(hass.states.get("sensor.dte_energy_gas_this_month").state) == 60.0

    # 30 days (Oct 1-30): 22 weekdays x 4 peak hours of D1.11 out of 720 hours
    assert float(hass.states.get("sensor.dte_energy_peak_share").state) == round(100 * 88 / 720, 1)
    cheapest = hass.states.get("sensor.dte_energy_cheapest_plan")
    costs = {
        key: round(sum(_day_cost(key, date(2026, 10, 1) + timedelta(days=n)) for n in range(30)), 2) for key in PLANS
    }
    assert cheapest.state == min(costs, key=lambda k: costs[k]).lower().replace(".", "_")
    assert cheapest.attributes["cost_d1_2"] == pytest.approx(costs["D1.2"], abs=0.01)
    assert cheapest.attributes["days"] == 30

    through = hass.states.get("sensor.dte_energy_data_through")
    assert through.state == "2026-10-31T04:00:00+00:00"
    assert through.attributes["gas_estimated_readings"] == 6


async def test_price_and_peak_entities(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to("2026-10-29 16:00:00-04:00")  # Thursday, inside D1.11's 3-7 pm peak
    await _setup(hass)
    assert hass.states.get("binary_sensor.dte_energy_peak_hours").state == "on"
    assert hass.states.get("sensor.dte_energy_price_period").state == "peak"
    price = hass.states.get("sensor.dte_energy_electricity_price")
    assert float(price.state) == pytest.approx((10.319 + 9.726 + 2.1283 + 0.9757) / 100, abs=1e-4)
    assert price.attributes["plan"] == "D1.11"
    assert f"{DOMAIN}:{PREFIX}_electric_cost" in price.attributes["statistic_ids"]
    assert hass.states.get("sensor.dte_energy_next_peak").state == "2026-10-30T19:00:00+00:00"  # Fri 3 pm EDT

    freezer.move_to("2026-10-29 19:00:01-04:00")
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.async_refresh()  # any update rewrites the states; the hourly tick does too
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.dte_energy_peak_hours").state == "off"


async def test_electric_only_file(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(LINK, text=build_feed(gas=False))
    await _setup(hass)
    assert hass.states.get("sensor.dte_energy_electricity_last_day") is not None
    assert hass.states.get("sensor.dte_energy_gas_last_day") is None


async def test_gas_only_file(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    freezer.move_to(NOW)
    aioclient_mock.get(LINK, text=build_feed(electric=False))
    await _setup(hass)
    assert hass.states.get("sensor.dte_energy_gas_last_day") is not None
    assert hass.states.get("binary_sensor.dte_energy_peak_hours") is None
    assert hass.states.get("sensor.dte_energy_electricity_price") is None


async def test_dead_link_raises_repair_and_recovers(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to(NOW)
    entry = await _setup(hass)
    issues = ir.async_get(hass)

    mock_dte.clear_requests()
    mock_dte.get(LINK, text="<html>This link has expired</html>")
    await entry.runtime_data.async_refresh()
    assert issues.async_get_issue(DOMAIN, ISSUE_LINK) is not None
    # last good data stays on screen
    assert float(hass.states.get("sensor.dte_energy_electricity_last_day").state) == 24.0

    mock_dte.clear_requests()
    mock_dte.get(LINK, text=build_feed())
    await entry.runtime_data.async_refresh()
    await wait_recorder(hass)
    assert issues.async_get_issue(DOMAIN, ISSUE_LINK) is None


async def test_setup_retries_when_link_fails(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(LINK, status=404)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LINK) is not None


async def test_unreachable_is_not_a_link_problem(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(LINK, status=502)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=CUSTOMER, data={CONF_LINK: LINK}, options=dict(DEFAULT_OPTIONS))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LINK) is None


async def test_device_card(hass: HomeAssistant, mock_dte, freezer) -> None:
    """The device page links to the project and shows the version, plan and rate date."""
    freezer.move_to(NOW)
    entry = await _setup(hass, electric_plan="d1_2")
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.configuration_url == "https://github.com/anthonysecco/dte-stats"
    assert device.sw_version == json.loads(MANIFEST.read_text())["version"]
    assert device.model == "Usage data link, plan D1.2, rates as of 2026-10-23"
    assert device.manufacturer == "DTE Energy (unofficial integration)"


async def test_diagnostics_hide_the_link(hass: HomeAssistant, mock_dte, freezer) -> None:
    freezer.move_to(NOW)
    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert LINK not in str(diag) and "00000000-0000-4000" not in str(diag)
    assert diag["data"][CONF_LINK] == "**REDACTED**"
    assert diag["series"]["electric"]["readings"] == DAYS * 24
    assert diag["series"]["gas"]["estimated_readings"] == 6
    assert diag["series"]["electric"]["statistic_ids"] == IDS[:2]
    assert diag["plan"] == "D1.11"
