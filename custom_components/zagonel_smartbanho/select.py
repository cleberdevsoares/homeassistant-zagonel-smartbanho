"""Select entities (control, LED and parental modes) for Zagonel Smart Banho."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .const import CONTROL_MODES, PARENTAL_MODES, RGB_MODES
from .entity import ZagonelControlEntity


@dataclass(frozen=True, kw_only=True)
class ZagonelSelectDescription(SelectEntityDescription):
    field: str
    values: dict[int, str]


SELECTS: tuple[ZagonelSelectDescription, ...] = (
    ZagonelSelectDescription(key="control_mode", field="Control_Mode", values=CONTROL_MODES),
    ZagonelSelectDescription(
        key="led_mode", field="Rgb_Mode", values=RGB_MODES, entity_category=EntityCategory.CONFIG
    ),
    ZagonelSelectDescription(
        key="parental_mode", field="Parental_Mode", values=PARENTAL_MODES, entity_category=EntityCategory.CONFIG
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ZagonelSelect(coordinator, shower, description)
        for shower in coordinator.showers.values()
        for description in SELECTS
    )


class ZagonelSelect(ZagonelControlEntity, SelectEntity):
    entity_description: ZagonelSelectDescription

    def __init__(self, coordinator, shower, description: ZagonelSelectDescription) -> None:
        super().__init__(coordinator, shower, description.key)
        self.entity_description = description
        self._attr_options = list(description.values.values())

    @property
    def current_option(self) -> str | None:
        return self.entity_description.values.get(self.shower.chars.get(self.entity_description.field))

    async def async_select_option(self, option: str) -> None:
        value = next(k for k, v in self.entity_description.values.items() if v == option)
        await self.coordinator.async_send(self.shower, self.entity_description.field, value)
