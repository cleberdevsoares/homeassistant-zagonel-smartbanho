"""Number entities (presets, parental limit, volume) for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberDeviceClass, NumberEntityDescription, NumberMode, NumberEntity
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .entity import ZagonelControlEntity


@dataclass(frozen=True, kw_only=True)
class ZagonelNumberDescription(NumberEntityDescription):
    field: str
    to_device: Callable[[float], int]
    from_device: Callable[[int], float]


def _preset(index: int) -> ZagonelNumberDescription:
    return ZagonelNumberDescription(
        key=f"preset_{index}",
        field=f"Preset_{index}",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=0,
        native_max_value=50,
        native_step=0.5,
        mode=NumberMode.BOX,
        to_device=lambda v: int(round(v * 1000)),
        from_device=lambda v: v / 1000,
    )


NUMBERS: tuple[ZagonelNumberDescription, ...] = (
    *(_preset(i) for i in range(1, 5)),
    ZagonelNumberDescription(
        key="parental_limit",
        field="Parental_Limit",
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        native_min_value=1,
        native_max_value=60,
        native_step=1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        to_device=lambda v: int(v * 60),
        from_device=lambda v: v / 60,
    ),
    ZagonelNumberDescription(
        key="buzzer_volume",
        field="Buzzer_Volume",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=0,
        native_max_value=100,
        native_step=10,
        entity_category=EntityCategory.CONFIG,
        to_device=int,
        from_device=float,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZagonelNumber(coordinator, shower, description)
        for shower in coordinator.showers.values()
        for description in NUMBERS
    )


class ZagonelNumber(ZagonelControlEntity, NumberEntity):
    entity_description: ZagonelNumberDescription

    def __init__(self, coordinator, shower, description: ZagonelNumberDescription) -> None:
        super().__init__(coordinator, shower, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        raw = self.shower.chars.get(self.entity_description.field)
        return None if raw is None else self.entity_description.from_device(raw)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_send(
            self.shower, self.entity_description.field, self.entity_description.to_device(value)
        )
