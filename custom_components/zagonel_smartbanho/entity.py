"""Base entity for Zagonel Smart Banho."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import Shower, ZagonelCoordinator


class ZagonelEntity(CoordinatorEntity[ZagonelCoordinator]):
    """Entity bound to one shower."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ZagonelCoordinator, shower: Shower, key: str) -> None:
        super().__init__(coordinator)
        self.shower = shower
        self._attr_unique_id = f"{shower.device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, shower.device_id)},
            name=shower.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )


class ZagonelControlEntity(ZagonelEntity):
    """Entity that writes to the shower; only usable while it is off."""

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.can_send(self.shower) and bool(self.shower.chars)
