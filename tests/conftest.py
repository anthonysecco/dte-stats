"""Shared fixtures for DTE Energy tests.

The usage file is generated: same layout as DTE's Green Button export (including DTE's gas
meter reading that links to the electric reading type), made-up numbers, no real account.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant
import pytest

from custom_components.dte_stats.const import DTE_TZ

LINK = "https://usagedata.dteenergy.com/link/00000000-0000-4000-8000-000000000000"
OTHER_LINK = "https://usagedata.dteenergy.com/link/11111111-1111-4111-8111-111111111111"
CUSTOMER = "aaaaaaaa-bbbb-5ccc-8ddd-eeeeeeeeeeee"
PREFIX = "aaaaaaaa"
END_DAY = date(2026, 10, 30)  # a Friday; DST ends Nov 1, 2026
DAYS = 40

ELECTRIC_POINT = "e1e1e1e1-0000-5000-8000-000000000001"
GAS_POINT = "a9a9a9a9-0000-5000-8000-000000000002"


def _local_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), DTE_TZ).astimezone(UTC)


def _entry(self_href: str, title: str, content: str, related: str = "") -> str:
    return (
        f"<entry><id>urn:uuid:{abs(hash(self_href)) % 10**12:012d}</id>"
        f'<link href="{self_href}" rel="self"/>{related}<title>{title}</title>'
        f"<published>2026-10-31T18:45:14.516Z</published><updated>2026-10-31T18:45:14.516Z</updated>"
        f"<content>{content}</content></entry>"
    )


def _reading(start: int, seconds: int, value: int | None, quality: int | None = None) -> str:
    q = f"<ReadingQuality><quality>{quality}</quality></ReadingQuality>" if quality is not None else ""
    v = f"<value>{value}</value>" if value is not None else ""
    return f"<IntervalReading>{q}<timePeriod><duration>{seconds}</duration><start>{start}</start></timePeriod>{v}</IntervalReading>"


def build_feed(
    end_day: date = END_DAY,
    days: int = DAYS,
    electric: bool = True,
    gas: bool = True,
    customer: str = CUSTOMER,
    kwh: Callable[[datetime], float] = lambda _local: 1.0,
    ccf_per_day: float = 2.0,
) -> str:
    """A DTE-style Green Button feed covering `days` local days ending `end_day`."""
    base = f"RetailCustomer/{customer}/UsagePoint"
    entries = [
        _entry(
            "LocalTimeParameters/01",
            "DST For North America",
            '<LocalTimeParameters xmlns="http://naesb.org/espi"><dstEndRule>B40E2000</dstEndRule>'
            "<dstOffset>3600</dstOffset><dstStartRule>360E2000</dstStartRule><tzOffset>-18000</tzOffset>"
            "</LocalTimeParameters>",
        )
    ]
    first_day = end_day - timedelta(days=days - 1)
    if electric:
        entries.append(
            _entry(
                f"{base}/{ELECTRIC_POINT}",
                "Electric Data",
                '<UsagePoint xmlns="http://naesb.org/espi"><ServiceCategory><kind>0</kind></ServiceCategory></UsagePoint>',
            )
        )
        entries.append(
            _entry(
                f"{base}/{ELECTRIC_POINT}/MeterReading/01",
                "Electricity Consumption",
                '<MeterReading xmlns="http://naesb.org/espi"/>',
                '<link href="ReadingType/electric/KWH" rel="related"/>',
            )
        )
        entries.append(
            _entry(
                "ReadingType/electric/KWH",
                "Energy Delivered (kWh)",
                '<ReadingType xmlns="http://naesb.org/espi"><accumulationBehaviour>4</accumulationBehaviour>'
                "<commodity>1</commodity><currency>840</currency><dataQualifier>12</dataQualifier>"
                "<flowDirection>1</flowDirection><intervalLength>2678400</intervalLength><kind>12</kind>"
                "<powerOfTenMultiplier>0</powerOfTenMultiplier><uom>72</uom></ReadingType>",
            )
        )
        blocks = []
        for n in range(days):
            day = first_day + timedelta(days=n)
            start, end = _local_midnight(day), _local_midnight(day + timedelta(days=1))
            hours = int((end - start).total_seconds() // 3600)
            readings = "".join(
                _reading(
                    int((start + timedelta(hours=h)).timestamp()),
                    3600,
                    round(kwh((start + timedelta(hours=h)).astimezone(DTE_TZ)) * 1000),
                )
                for h in range(hours)
            )
            blocks.append(
                f'<IntervalBlock xmlns="http://naesb.org/espi"><interval><duration>{hours * 3600}</duration>'
                f"<start>{int(start.timestamp())}</start></interval>{readings}</IntervalBlock>"
            )
        entries.append(_entry(f"{base}/{ELECTRIC_POINT}/MeterReading/01/IntervalBlock/KWH", "Electric readings", "".join(blocks)))
    if gas:
        entries.append(
            _entry(
                f"{base}/{GAS_POINT}",
                "Gas Data",
                '<UsagePoint xmlns="http://naesb.org/espi"><ServiceCategory><kind>1</kind></ServiceCategory></UsagePoint>',
            )
        )
        entries.append(  # DTE links the gas meter reading to the electric reading type
            _entry(
                f"{base}/{GAS_POINT}/MeterReading/01",
                "Gas Consumption",
                '<MeterReading xmlns="http://naesb.org/espi"/>',
                '<link href="ReadingType/electric" rel="related"/>',
            )
        )
        entries.append(
            _entry(
                "ReadingType/gas",
                "Energy Delivered (CCF)",
                '<ReadingType xmlns="http://naesb.org/espi"><accumulationBehaviour>4</accumulationBehaviour>'
                "<commodity>7</commodity><currency>840</currency><dataQualifier>12</dataQualifier>"
                "<flowDirection>1</flowDirection><intervalLength>2678400</intervalLength><kind>58</kind>"
                "<powerOfTenMultiplier>-3</powerOfTenMultiplier><uom>119</uom></ReadingType>",
            )
        )
        blocks = []
        before = first_day - timedelta(days=1)  # DTE includes an empty reading for the day before
        start = _local_midnight(before)
        blocks.append(
            f'<IntervalBlock xmlns="http://naesb.org/espi"><interval><duration>86400</duration><start>{int(start.timestamp())}</start>'
            f"</interval>{_reading(int(start.timestamp()), 86400, None)}</IntervalBlock>"
        )
        for n in range(days):
            day = first_day + timedelta(days=n)
            start = _local_midnight(day)
            seconds = int((_local_midnight(day + timedelta(days=1)) - start).total_seconds())
            quality = 9 if n % 7 == 3 else None  # some days estimated by interpolation
            blocks.append(
                f'<IntervalBlock xmlns="http://naesb.org/espi"><interval><duration>{seconds}</duration>'
                f"<start>{int(start.timestamp())}</start></interval>"
                f"{_reading(int(start.timestamp()), seconds, round(ccf_per_day * 1000), quality)}</IntervalBlock>"
            )
        entries.append(_entry(f"{base}/{GAS_POINT}/MeterReading/01/IntervalBlock/CCF", "Gas readings", "".join(blocks)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<id>urn:uuid:{customer}</id><title>DTE Energy Usage Data</title><updated>2026-10-31T18:45:14.516Z</updated>"
        + "".join(entries)
        + "</feed>"
    )


@pytest.fixture(autouse=True)
def setup_environment(recorder_mock, enable_custom_integrations):
    """Recorder first (statistics), then custom_components/; both in every test."""
    return


@pytest.fixture
def feed_text() -> str:
    """The default generated feed: 40 days to Oct 30, 2026, electric 1 kWh/h, gas 2 CCF/day."""
    return build_feed()


@pytest.fixture
def mock_dte(aioclient_mock, feed_text):
    """The link answers with the generated feed."""
    aioclient_mock.get(LINK, text=feed_text)
    return aioclient_mock


async def wait_recorder(hass: HomeAssistant) -> None:
    """Let queued statistics imports finish."""
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()
    await hass.async_block_till_done()
