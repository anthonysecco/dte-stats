"""Sensors for DTE Stats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import ELECTRIC, GAS
from .coordinator import DteConfigEntry, DteCoordinator, DteData
from .entity import DteEntity, TariffEntity
from .statistics import statistic_ids
from .summary import SeriesSummary
from .tariff import ELECTRIC_FIXED_MONTHLY, GAS_FIXED_MONTHLY, PERIODS, PLANS, RATES_AS_OF, plan_slug

PARALLEL_UPDATES = 0
USD = "USD"
UNIT_PRICE = "USD/kWh"

StateType = str | float | datetime | None


@dataclass(frozen=True, kw_only=True)
class DteSensorDescription(SensorEntityDescription):
    """A sensor fed from the usage file."""

    kind: str = ELECTRIC
    value_fn: Callable[[DteData], StateType]
    attrs_fn: Callable[[DteData], dict[str, Any]] | None = None


def _summary(data: DteData, kind: str) -> SeriesSummary | None:
    return data.summaries.get(kind)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _day(kind: str, cost: bool) -> Callable[[DteData], StateType]:
    def value(data: DteData) -> StateType:
        s = _summary(data, kind)
        if s is None or s.last_day is None:
            return None
        return round(s.last_day_totals.cost if cost else s.last_day_totals.amount, 2 if cost else 3)

    return value


def _month(kind: str, cost: bool) -> Callable[[DteData], StateType]:
    def value(data: DteData) -> StateType:
        s = _summary(data, kind)
        if s is None or s.month is None:
            return None
        return round(s.month_totals.cost if cost else s.month_totals.amount, 2 if cost else 3)

    return value


def _day_attrs(kind: str) -> Callable[[DteData], dict[str, Any]]:
    return lambda data: {"date": _iso(s.last_day) if (s := _summary(data, kind)) else None}


def _month_attrs(kind: str) -> Callable[[DteData], dict[str, Any]]:
    fixed = ELECTRIC_FIXED_MONTHLY if kind == ELECTRIC else GAS_FIXED_MONTHLY

    def attrs(data: DteData) -> dict[str, Any]:
        s = _summary(data, kind)
        return {
            "month": s.month.strftime("%Y-%m") if s and s.month else None,
            "through": _iso(s.last_day) if s else None,
            "monthly_fixed_charges": fixed,
        }

    return attrs


def _usage(key: str, kind: str, fn: Callable[[DteData], StateType], attrs: Callable[[DteData], dict[str, Any]]):
    electric = kind == ELECTRIC
    return DteSensorDescription(
        key=key,
        translation_key=key,
        kind=kind,
        device_class=SensorDeviceClass.ENERGY if electric else SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR if electric else UnitOfVolume.CENTUM_CUBIC_FEET,
        suggested_display_precision=1,
        value_fn=fn,
        attrs_fn=attrs,
    )


def _cost(key: str, kind: str, fn: Callable[[DteData], StateType], attrs: Callable[[DteData], dict[str, Any]]):
    return DteSensorDescription(
        key=key,
        translation_key=key,
        kind=kind,
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement=USD,
        suggested_display_precision=2,
        value_fn=fn,
        attrs_fn=attrs,
    )


def _comparison_attrs(data: DteData) -> dict[str, Any]:
    c = data.comparison
    if c is None:
        return {}
    return {
        "from": c.start.isoformat(),
        "to": c.end.isoformat(),
        "days": c.days,
        **{f"cost_{plan_slug(key)}": cost for key, cost in c.costs.items()},
        "note": "Per-kWh charges only; the $10 monthly fixed charges are the same on every plan.",
    }


def _data_through_attrs(data: DteData) -> dict[str, Any]:
    attrs: dict[str, Any] = {"fetched": data.fetched.isoformat()}
    for kind, s in data.summaries.items():
        series = data.feed.series[kind]
        attrs[f"{kind}_first"] = series.first.isoformat() if series.first else None
        attrs[f"{kind}_through"] = s.data_through.isoformat() if s.data_through else None
        attrs[f"{kind}_readings"] = s.readings
        attrs[f"{kind}_estimated_readings"] = s.estimated
    return attrs


USAGE_SENSORS: tuple[DteSensorDescription, ...] = (
    _usage("electric_last_day", ELECTRIC, _day(ELECTRIC, False), _day_attrs(ELECTRIC)),
    _cost("electric_cost_last_day", ELECTRIC, _day(ELECTRIC, True), _day_attrs(ELECTRIC)),
    _usage("electric_month", ELECTRIC, _month(ELECTRIC, False), _month_attrs(ELECTRIC)),
    _cost("electric_cost_month", ELECTRIC, _month(ELECTRIC, True), _month_attrs(ELECTRIC)),
    DteSensorDescription(
        key="peak_share",
        translation_key="peak_share",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d: d.comparison.peak_share if d.comparison else None,
        attrs_fn=lambda d: {"days": d.comparison.days} if d.comparison else {},
    ),
    DteSensorDescription(
        key="cheapest_plan",
        translation_key="cheapest_plan",
        device_class=SensorDeviceClass.ENUM,
        options=[plan_slug(k) for k in PLANS],
        value_fn=lambda d: plan_slug(d.comparison.cheapest) if d.comparison else None,
        attrs_fn=_comparison_attrs,
    ),
    _usage("gas_last_day", GAS, _day(GAS, False), _day_attrs(GAS)),
    _cost("gas_cost_last_day", GAS, _day(GAS, True), _day_attrs(GAS)),
    _usage("gas_month", GAS, _month(GAS, False), _month_attrs(GAS)),
    _cost("gas_cost_month", GAS, _month(GAS, True), _month_attrs(GAS)),
    DteSensorDescription(
        key="data_through",
        translation_key="data_through",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: s.data_through if (s := d.summaries.get(ELECTRIC) or d.summaries.get(GAS)) else None,
        attrs_fn=_data_through_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors for the services the file has, plus the live price sensors."""
    coordinator = entry.runtime_data
    kinds = set(coordinator.data.feed.series)
    entities: list[SensorEntity] = [
        DteUsageSensor(coordinator, d) for d in USAGE_SENSORS if d.key == "data_through" or d.kind in kinds
    ]
    if ELECTRIC in kinds:
        entities += [ElectricPriceSensor(coordinator), PricePeriodSensor(coordinator), NextPeakSensor(coordinator)]
    async_add_entities(entities)


class DteUsageSensor(DteEntity, SensorEntity):
    """A value computed from the usage file."""

    entity_description: DteSensorDescription

    @property
    def native_value(self) -> StateType:
        """Current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Dates, plan costs and data coverage."""
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data) if fn else None


class ElectricPriceSensor(TariffEntity, SensorEntity):
    """What a kWh costs right now on the chosen plan; usable as the Energy dashboard price."""

    _attr_native_unit_of_measurement = UNIT_PRICE
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: DteCoordinator) -> None:
        """Bind the description."""
        super().__init__(coordinator, SensorEntityDescription(key="electric_price", translation_key="electric_price"))

    @property
    def native_value(self) -> float:
        """USD per kWh, before tax and fixed charges."""
        return self.coordinator.plan.price(dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Plan, period, season and the solar export credit."""
        plan, now = self.coordinator.plan, dt_util.utcnow()
        return {
            "plan": plan.key,
            "period": plan.period(now),
            "season": plan.season(now),
            "solar_export_credit": plan.export_credit(now),
            "rates_as_of": RATES_AS_OF.isoformat(),
            "statistic_ids": [i for k in self.coordinator.data.feed.series for i in _ids(self.coordinator, k)]
            if self.coordinator.data
            else [],
        }


def _ids(coordinator: DteCoordinator, kind: str) -> tuple[str, str]:
    ids = statistic_ids(coordinator.prefix, kind)
    return ids.consumption, ids.cost


class PricePeriodSensor(TariffEntity, SensorEntity):
    """Peak, off-peak or super off-peak right now."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: DteCoordinator) -> None:
        """Bind the description."""
        super().__init__(coordinator, SensorEntityDescription(key="price_period", translation_key="price_period"))
        self._attr_options = list(PERIODS)

    @property
    def native_value(self) -> str:
        """The current period."""
        return self.coordinator.plan.period(dt_util.utcnow())


class NextPeakSensor(TariffEntity, SensorEntity):
    """When the next peak period starts."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: DteCoordinator) -> None:
        """Bind the description."""
        super().__init__(coordinator, SensorEntityDescription(key="next_peak", translation_key="next_peak"))

    @property
    def native_value(self) -> datetime | None:
        """Start of the next peak."""
        return self.coordinator.plan.next_peak(dt_util.utcnow())
