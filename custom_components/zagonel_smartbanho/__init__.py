"""Zagonel Smart Banho integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import ZagonelApi
from .const import DOMAIN, PLATFORMS, SERVICE_SET_RESIDENT
from .coordinator import ZagonelCoordinator

type ZagonelConfigEntry = ConfigEntry[ZagonelCoordinator]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SET_RESIDENT_SCHEMA = vol.Schema(
    {
        vol.Optional("morador"): cv.string,
        vol.Optional("humor"): cv.string,
        vol.Optional("device_id"): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _set_resident(call: ServiceCall) -> None:
        resident = call.data.get("morador")
        mood = call.data.get("humor")
        if not resident and not mood:
            raise ServiceValidationError("Informe o morador e/ou o humor")
        shower_id = None
        if device_id := call.data.get("device_id"):
            device = dr.async_get(hass).async_get(device_id)
            if device is not None:
                shower_id = next((i for d, i in device.identifiers if d == DOMAIN), None)
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED
        ]
        if not entries:
            raise ServiceValidationError("Integração Zagonel Smart Banho não carregada")
        for entry in entries:
            coordinator: ZagonelCoordinator = entry.runtime_data
            if shower_id is None or shower_id in coordinator.showers:
                await coordinator.async_set_resident(shower_id, resident, mood)

    hass.services.async_register(DOMAIN, SERVICE_SET_RESIDENT, _set_resident, schema=SET_RESIDENT_SCHEMA)
    return True


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
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ZagonelConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ZagonelConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
