"""Parsing DTE's Green Button file and downloading it."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.dte_stats.espi import DteClient, DteConnectionError, DteLinkError, parse_feed

from .conftest import CUSTOMER, DAYS, LINK, build_feed


async def test_parse_both_services() -> None:
    feed = parse_feed(build_feed())
    assert feed.customer_id == CUSTOMER
    assert set(feed.series) == {"electric", "gas"}

    electric = feed.series["electric"]
    assert len(electric.readings) == DAYS * 24  # no clock change in Sep 21 - Oct 30, 2026
    assert electric.readings[0].value == 1.0  # 1000 Wh -> 1 kWh
    assert electric.readings[0].seconds == 3600
    assert electric.first == datetime(2026, 9, 21, 4, tzinfo=UTC)  # local midnight, EDT
    assert electric.last_end == datetime(2026, 10, 31, 4, tzinfo=UTC)
    assert electric.estimated == 0

    gas = feed.series["gas"]
    assert gas.unit_multiplier == -3  # matched by commodity, not DTE's gas -> electric link
    assert len(gas.readings) == DAYS  # the empty day-before reading is skipped
    assert gas.readings[0].value == 2.0  # 2000 x 10^-3 CCF
    assert gas.estimated == 6  # quality 9 = estimated by interpolation


async def test_parse_electric_only_and_dst() -> None:
    feed = parse_feed(build_feed(end_day=datetime(2026, 11, 2).date(), days=3, gas=False))
    assert set(feed.series) == {"electric"}
    assert len(feed.series["electric"].readings) == 24 + 25 + 24  # Nov 1 has 25 hours


async def test_duplicates_keep_last() -> None:
    text = build_feed(days=1, gas=False)
    first_block = text.index("<IntervalReading>")
    doubled = text.replace("</IntervalBlock>", text[first_block : text.index("</IntervalReading>") + 18] + "</IntervalBlock>", 1)
    assert len(parse_feed(doubled).series["electric"].readings) == 24


@pytest.mark.parametrize(
    "text",
    [
        "<html><body>This link has expired</body></html>",
        "not xml at all",
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>empty</title></feed>',
    ],
)
async def test_not_a_usage_file(text: str) -> None:
    with pytest.raises(DteLinkError):
        parse_feed(text)


async def test_client_statuses(hass: HomeAssistant, aioclient_mock) -> None:
    client = DteClient(async_get_clientsession(hass), f" {LINK} ")
    aioclient_mock.get(LINK, text=build_feed(days=2))
    feed = await client.fetch()
    assert len(feed.series["electric"].readings) == 48

    aioclient_mock.clear_requests()
    aioclient_mock.get(LINK, status=404)
    with pytest.raises(DteLinkError):
        await client.fetch()

    aioclient_mock.clear_requests()
    aioclient_mock.get(LINK, status=503)
    with pytest.raises(DteConnectionError):
        await client.fetch()

    aioclient_mock.clear_requests()
    aioclient_mock.get(LINK, exc=TimeoutError())
    with pytest.raises(DteConnectionError):
        await client.fetch()
