"""Sensors for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
import unicodedata

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .const import UNIDENTIFIED
from .coordinator import Shower
from .entity import ZagonelEntity


@dataclass(frozen=True, kw_only=True)
class ZagonelSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Shower], Any]
    last_reset_fn: Callable[[Shower], datetime | None] | None = None
    attrs_fn: Callable[[Shower], dict[str, Any]] | None = None


def _last(attr: str, digits: int | None = None) -> Callable[[Shower], Any]:
    def _value(shower: Shower) -> Any:
        if shower.last_measure is None:
            return None
        value = getattr(shower.last_measure, attr)
        return round(value, digits) if digits is not None else value

    return _value


def _total(period: str, attr: str, digits: int | None = None) -> Callable[[Shower], Any]:
    def _value(shower: Shower) -> Any:
        value = getattr(getattr(shower, period), attr)
        return round(value, digits) if digits is not None else value

    return _value


def _live_when_running(key: str) -> Callable[[Shower], Any]:
    def _value(shower: Shower) -> Any:
        if not shower.running:
            return 0.0
        value = shower.live(key)
        return None if value is None else round(value, 2)

    return _value


def _month_start(shower: Shower) -> datetime | None:
    return shower.month_start


TEMP = {
    "device_class": SensorDeviceClass.TEMPERATURE,
    "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
    "state_class": SensorStateClass.MEASUREMENT,
    "suggested_display_precision": 1,
}
WATER = {
    "device_class": SensorDeviceClass.WATER,
    "native_unit_of_measurement": UnitOfVolume.LITERS,
    "suggested_display_precision": 1,
}
ENERGY = {
    "device_class": SensorDeviceClass.ENERGY,
    "native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
    "suggested_display_precision": 3,
}
MONEY = {
    "device_class": SensorDeviceClass.MONETARY,
    "native_unit_of_measurement": "BRL",
    "suggested_display_precision": 2,
}
DURATION = {
    "device_class": SensorDeviceClass.DURATION,
    "native_unit_of_measurement": UnitOfTime.SECONDS,
    "suggested_unit_of_measurement": UnitOfTime.MINUTES,
}

SENSORS: tuple[ZagonelSensorDescription, ...] = (
    ZagonelSensorDescription(key="outlet_temperature", value_fn=lambda s: s.live("To"), **TEMP),
    ZagonelSensorDescription(key="inlet_temperature", value_fn=lambda s: s.live("Ti"), **TEMP),
    ZagonelSensorDescription(key="target_temperature", value_fn=lambda s: s.live("Ts"), **TEMP),
    ZagonelSensorDescription(
        key="flow",
        value_fn=_live_when_running("Fl"),
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    ZagonelSensorDescription(
        key="power",
        value_fn=lambda s: None if s.live_power_w is None else round(s.live_power_w),
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    ZagonelSensorDescription(
        key="voltage",
        value_fn=lambda s: s.live("Vi"),
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    ZagonelSensorDescription(
        key="wifi_signal",
        value_fn=lambda s: s.status.get("Wi"),
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    ZagonelSensorDescription(
        key="last_start",
        value_fn=_last("start"),
        device_class=SensorDeviceClass.TIMESTAMP,
        attrs_fn=lambda s: s.last_measure.as_event_data() if s.last_measure else {},
    ),
    ZagonelSensorDescription(key="last_duration", value_fn=_last("duration_s"), **DURATION),
    ZagonelSensorDescription(key="last_water", value_fn=_last("water_l", 2), **WATER),
    ZagonelSensorDescription(key="last_energy", value_fn=_last("energy_kwh", 4), **ENERGY),
    ZagonelSensorDescription(key="last_cost", value_fn=_last("cost", 2), **MONEY),
    ZagonelSensorDescription(
        key="last_temperature",
        value_fn=_last("temperature_c", 1),
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ZagonelSensorDescription(
        key="last_flow",
        value_fn=_last("flow_l_min", 2),
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
        native_unit_of_measurement=UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
    ),
    ZagonelSensorDescription(
        key="last_power",
        value_fn=_last("power_w", 0),
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    ZagonelSensorDescription(key="today_count", value_fn=_total("today", "count"), state_class=SensorStateClass.TOTAL_INCREASING),
    ZagonelSensorDescription(
        key="today_water", value_fn=_total("today", "water_l", 1), state_class=SensorStateClass.TOTAL_INCREASING, **WATER
    ),
    ZagonelSensorDescription(
        key="today_energy", value_fn=_total("today", "energy_kwh", 3), state_class=SensorStateClass.TOTAL_INCREASING, **ENERGY
    ),
    ZagonelSensorDescription(key="today_cost", value_fn=_total("today", "cost", 2), **MONEY),
    ZagonelSensorDescription(
        key="today_duration", value_fn=_total("today", "duration_s"), state_class=SensorStateClass.TOTAL_INCREASING, **DURATION
    ),
    ZagonelSensorDescription(key="month_count", value_fn=_total("month", "count")),
    ZagonelSensorDescription(
        key="month_water",
        value_fn=_total("month", "water_l", 1),
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_month_start,
        **WATER,
    ),
    ZagonelSensorDescription(
        key="month_energy",
        value_fn=_total("month", "energy_kwh", 3),
        state_class=SensorStateClass.TOTAL,
        last_reset_fn=_month_start,
        **ENERGY,
    ),
    ZagonelSensorDescription(key="month_cost", value_fn=_total("month", "cost", 2), **MONEY),
    ZagonelSensorDescription(key="month_duration", value_fn=_total("month", "duration_s"), **DURATION),
    ZagonelSensorDescription(
        key="firmware",
        value_fn=lambda s: s.chars.get("Fw_Version"),
        entity_category=EntityCategory.DIAGNOSTIC,
        attrs_fn=lambda s: {
            "hardware": s.chars.get("Hw_Version"),
            "compilacao": s.chars.get("Fw_Timestamp"),
            "hw_id": s.chars.get("Hw_Id"),
        },
    ),
    ZagonelSensorDescription(
        key="wifi_ssid",
        value_fn=lambda s: s.chars.get("Wifi_SSID"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        ZagonelSensor(coordinator, shower, description)
        for shower in coordinator.showers.values()
        for description in SENSORS
    ]
    for shower in coordinator.showers.values():
        entities.append(ZagonelSensor(coordinator, shower, LAST_RESIDENT))
        if coordinator.db is not None:
            for resident in [*coordinator.residents, UNIDENTIFIED]:
                entities.extend(
                    ZagonelResidentSensor(coordinator, shower, resident, description)
                    for description in RESIDENT_SENSORS
                )
    async_add_entities(entities)


LAST_RESIDENT = ZagonelSensorDescription(
    key="last_resident",
    value_fn=lambda s: s.last_resident or (UNIDENTIFIED if s.last_measure else None),
    attrs_fn=lambda s: {"humor": s.last_mood, "morador_pendente": s.pending_resident, "humor_pendente": s.pending_mood},
)


@dataclass(frozen=True, kw_only=True)
class ZagonelResidentDescription(SensorEntityDescription):
    metric: str
    scale: float = 1


RESIDENT_SENSORS: tuple[ZagonelResidentDescription, ...] = (
    ZagonelResidentDescription(key="resident_count", metric="count", state_class=SensorStateClass.TOTAL),
    ZagonelResidentDescription(key="resident_duration", metric="duration_s", **DURATION),
    ZagonelResidentDescription(key="resident_water", metric="water_l", **WATER),
    ZagonelResidentDescription(key="resident_energy", metric="energy_kwh", **ENERGY),
    ZagonelResidentDescription(key="resident_cost", metric="cost", **MONEY),
)


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).strip("_")


class ZagonelResidentSensor(ZagonelEntity, SensorEntity):
    """Monthly totals of one resident, read from the shower database."""

    entity_description: ZagonelResidentDescription

    def __init__(self, coordinator, shower: Shower, resident: str, description: ZagonelResidentDescription) -> None:
        super().__init__(coordinator, shower, f"{description.key}_{_slug(resident)}")
        self._attr_translation_key = description.key
        self._attr_translation_placeholders = {"morador": resident}
        self.entity_description = description
        self.resident = resident

    @property
    def native_value(self) -> float | int:
        value = self.shower.residents_month.get(self.resident, {}).get(self.entity_description.metric, 0)
        return round(value, 4) if isinstance(value, float) else value

    @property
    def last_reset(self) -> datetime | None:
        return self.shower.month_start if self.entity_description.state_class == SensorStateClass.TOTAL else None

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.db_ok


class ZagonelSensor(ZagonelEntity, SensorEntity):
    entity_description: ZagonelSensorDescription

    def __init__(self, coordinator, shower: Shower, description: ZagonelSensorDescription) -> None:
        super().__init__(coordinator, shower, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.shower)

    @property
    def last_reset(self) -> datetime | None:
        if self.entity_description.last_reset_fn is None:
            return None
        return self.entity_description.last_reset_fn(self.shower)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.shower)
