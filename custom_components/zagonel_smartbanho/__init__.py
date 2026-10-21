"""Zagonel Smart Banho integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZagonelApi
from .const import PLATFORMS
from .coordinator import ZagonelCoordinator

type ZagonelConfigEntry = ConfigEntry[ZagonelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZagonelConfigEntry) -> bool:
    api = ZagonelApi(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = ZagonelCoordinator(hass, entry, api)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_start_push()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZagonelConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
