"""LED color light for Zagonel Smart Banho."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_RGB_COLOR, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .entity import ZagonelControlEntity

FIXED_COLOR_MODE = 2


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZagonelLed(coordinator, shower, "led") for shower in coordinator.showers.values())


class ZagonelLed(ZagonelControlEntity, LightEntity):
    """LED color. Turning it on with a color switches the LED to fixed-color mode."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}

    @property
    def is_on(self) -> bool:
        return True

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        color = str(self.shower.chars.get("Rgb_Color") or "").lstrip("#")
        if len(color) != 6:
            return None
        try:
            return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb = kwargs.get(ATTR_RGB_COLOR)
        if rgb is None:
            return
        await self.coordinator.async_send(self.shower, "Rgb_Color", "#{:02X}{:02X}{:02X}".format(*rgb))
        if self.shower.chars.get("Rgb_Mode") != FIXED_COLOR_MODE:
            await self.coordinator.async_send(self.shower, "Rgb_Mode", FIXED_COLOR_MODE)

    async def async_turn_off(self, **kwargs: Any) -> None:
        raise HomeAssistantError("O LED do chuveiro não pode ser desligado; mude o modo do LED")
