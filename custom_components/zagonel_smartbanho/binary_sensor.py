"""Binary sensors for Zagonel Smart Banho."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ZagonelConfigEntry
from .entity import ZagonelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ZagonelConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = []
    for shower in coordinator.showers.values():
        entities.append(ZagonelRunning(coordinator, shower, "running"))
        entities.append(ZagonelConnected(coordinator, shower, "connected"))
    async_add_entities(entities)


class ZagonelRunning(ZagonelEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool:
        return self.shower.running

    @property
    def extra_state_attributes(self) -> dict:
        return {"ultimo_status": self.shower.last_status.isoformat() if self.shower.last_status else None}


class ZagonelConnected(ZagonelEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool:
        return self.coordinator.mqtt_connected
