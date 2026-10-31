"""Read DTE's Green Button (NAESB ESPI) usage file and fetch it from the shareable link.

The file is an Atom feed. Each usage point (electric or gas) has a meter reading, a reading type
(unit and power-of-ten multiplier) and many interval blocks, one per day:
- electric: hourly readings in Wh (multiplier 10^0)
- gas: daily readings in 10^-3 CCF

DTE's gas meter reading links to the electric reading type, so series are matched to their
reading type by the usage point's service kind (0 electricity, 1 gas) and the reading type's
commodity (1 electricity, 7 natural gas), not by those links.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import re
from xml.etree import ElementTree as ET

import aiohttp

from .const import ELECTRIC, FETCH_TIMEOUT, GAS

NS = {"a": "http://www.w3.org/2005/Atom", "e": "http://naesb.org/espi"}
SERVICE_KINDS = {"0": ELECTRIC, "1": GAS}
COMMODITIES = {"1": ELECTRIC, "7": GAS}
DEFAULT_MULTIPLIER = {ELECTRIC: 0, GAS: -3}
TO_UNIT = {ELECTRIC: 1 / 1000, GAS: 1.0}  # Wh -> kWh; gas is already CCF
# ESPI quality codes that are measured values: valid, raw, validated, verified, revenue quality.
# Others (7 edited, 8/9 estimated, 10 questionable, 11 derived, 12 projected...) count as estimated.
ESTIMATED_QUALITY_OK = {"0", "14", "17", "18", "19"}

_USAGE_POINT = re.compile(r"UsagePoint/([^/]+)")
_CUSTOMER = re.compile(r"RetailCustomer/([^/]+)")


class EspiError(Exception):
    """The response isn't a usable usage file."""


class DteLinkError(EspiError):
    """The link was refused or no longer returns usage data (likely expired or wrong)."""


class DteConnectionError(Exception):
    """DTE couldn't be reached; try again later."""


@dataclass(frozen=True, slots=True)
class Reading:
    """One interval: start (UTC), length in seconds, amount in kWh or CCF."""

    start: datetime
    seconds: int
    value: float
    estimated: bool = False


@dataclass(slots=True)
class Series:
    """All readings for one service, oldest first."""

    kind: str
    unit_multiplier: int
    readings: list[Reading] = field(default_factory=list)

    @property
    def first(self) -> datetime | None:
        """Start of the oldest reading."""
        return self.readings[0].start if self.readings else None

    @property
    def last_end(self) -> datetime | None:
        """End of the newest reading."""
        if not self.readings:
            return None
        last = self.readings[-1]
        return datetime.fromtimestamp(last.start.timestamp() + last.seconds, UTC)

    @property
    def estimated(self) -> int:
        """How many readings DTE flagged as estimated or edited."""
        return sum(1 for r in self.readings if r.estimated)


@dataclass(slots=True)
class UsageFeed:
    """The parsed file."""

    customer_id: str
    series: dict[str, Series]
    updated: datetime | None = None


def _text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def parse_feed(text: str) -> UsageFeed:
    """Parse the Atom/ESPI XML; raises DteLinkError when it isn't a usage file."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        raise DteLinkError(f"not XML: {err}") from err
    if root.tag != f"{{{NS['a']}}}feed":
        raise DteLinkError(f"not an Atom feed: {root.tag}")

    kinds: dict[str, str] = {}  # usage point id -> electric/gas
    multipliers: dict[str, int] = {}  # electric/gas -> power of ten
    blocks: list[tuple[str, list[ET.Element]]] = []
    customer_id = ""
    for entry in root.findall("a:entry", NS):
        link = entry.find("a:link[@rel='self']", NS)
        href = link.get("href", "") if link is not None else ""
        if not customer_id and (m := _CUSTOMER.search(href)):
            customer_id = m.group(1)
        content = entry.find("a:content", NS)
        if content is None:
            continue
        point = _USAGE_POINT.search(href)
        usage_point = content.find("e:UsagePoint", NS)
        if usage_point is not None and point:
            if kind := SERVICE_KINDS.get(_text(usage_point, "e:ServiceCategory/e:kind") or ""):
                kinds[point.group(1)] = kind
        reading_type = content.find("e:ReadingType", NS)
        if reading_type is not None and (kind := COMMODITIES.get(_text(reading_type, "e:commodity") or "")):
            multipliers[kind] = int(_text(reading_type, "e:powerOfTenMultiplier") or DEFAULT_MULTIPLIER[kind])
        interval_blocks = content.findall("e:IntervalBlock", NS)
        if interval_blocks and point:
            blocks.append((point.group(1), interval_blocks))

    series: dict[str, Series] = {}
    for point_id, elements in blocks:
        kind = kinds.get(point_id)
        if kind is None:
            continue
        power = multipliers.get(kind, DEFAULT_MULTIPLIER[kind])
        target = series.setdefault(kind, Series(kind, power))
        scale = (10**power) * TO_UNIT[kind]
        for block in elements:
            for reading in block.findall("e:IntervalReading", NS):
                value = _text(reading, "e:value")
                start = _text(reading, "e:timePeriod/e:start")
                seconds = _text(reading, "e:timePeriod/e:duration")
                if value is None or start is None or seconds is None:
                    continue  # DTE leaves days without a reading empty
                quality = _text(reading, "e:ReadingQuality/e:quality")
                target.readings.append(
                    Reading(
                        start=datetime.fromtimestamp(int(start), UTC),
                        seconds=int(seconds),
                        value=round(float(value) * scale, 6),
                        estimated=quality is not None and quality not in ESTIMATED_QUALITY_OK,
                    )
                )
    for item in series.values():
        unique = {r.start: r for r in item.readings}  # a repeated interval keeps its last value
        item.readings = [unique[k] for k in sorted(unique)]
    series = {k: v for k, v in series.items() if v.readings}
    if not series:
        raise DteLinkError("the file has no electric or gas readings")
    updated = _text(root, "a:updated")
    return UsageFeed(
        customer_id=customer_id.lower(),
        series=series,
        updated=datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None,
    )


class DteClient:
    """Downloads the usage file from the shareable link."""

    def __init__(self, session: aiohttp.ClientSession, link: str) -> None:
        """Bind the session and link."""
        self._session = session
        self._link = link.strip()

    async def fetch_text(self) -> str:
        """The raw XML; DteLinkError when DTE refuses the link, DteConnectionError when unreachable."""
        try:
            async with (
                asyncio.timeout(FETCH_TIMEOUT.total_seconds()),
                self._session.get(self._link, headers={"Accept": "application/xml, text/xml"}) as response,
            ):
                if response.status in (401, 403, 404, 410):
                    raise DteLinkError(f"HTTP {response.status}")
                if response.status != 200:
                    raise DteConnectionError(f"HTTP {response.status}")
                return await response.text()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise DteConnectionError(str(err) or type(err).__name__) from err

    async def fetch(self) -> UsageFeed:
        """Download and parse."""
        return parse_feed(await self.fetch_text())
