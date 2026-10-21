"""Refresh button for Zagonel Smart Banho."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .entity import ZagonelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(ZagonelRefresh(coordinator, shower, "refresh") for shower in coordinator.showers.values())


class ZagonelRefresh(ZagonelEntity, ButtonEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_press(self) -> None:
        self.coordinator.request_chars()
        await self.coordinator.async_request_refresh()
