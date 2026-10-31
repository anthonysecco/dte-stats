"""Constants for DTE Energy."""

from __future__ import annotations

from datetime import timedelta
import logging
import re
from zoneinfo import ZoneInfo

DOMAIN = "dte_stats"
LOGGER = logging.getLogger(__package__)
ATTRIBUTION = "Usage from DTE's Green Button data link; prices from the DTE rate books"

# DTE bills and sets time-of-day periods on Michigan local time.
DTE_TZ = ZoneInfo("America/Detroit")

# The shareable usage link from the DTE account (Usage -> Usage History -> share).
LINK_RE = re.compile(r"^https://usagedata\.dteenergy\.com/link/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/?$")
LINK_PREFIX = "https://usagedata.dteenergy.com/link/"
PROJECT_URL = "https://github.com/anthonysecco/dte-stats"

CONF_LINK = "link"
CONF_PLAN = "electric_plan"
CONF_SCAN_HOURS = "update_hours"

DEFAULT_PLAN = "d1_11"  # plan slugs: d1_11, d1_2, d1_13
DEFAULT_SCAN_HOURS = 6
MIN_SCAN_HOURS = 1
MAX_SCAN_HOURS = 24
DEFAULT_OPTIONS = {CONF_PLAN: DEFAULT_PLAN, CONF_SCAN_HOURS: DEFAULT_SCAN_HOURS}

ELECTRIC = "electric"
GAS = "gas"

COMPARE_DAYS = 30  # plan comparison and peak share look back this many days of data
FETCH_TIMEOUT = timedelta(seconds=90)  # the file is a few MB

ISSUE_LINK = "link_not_working"


def scan_interval(hours: float) -> timedelta:
    """Polling interval, clamped to the allowed range."""
    return timedelta(hours=min(MAX_SCAN_HOURS, max(MIN_SCAN_HOURS, float(hours))))
