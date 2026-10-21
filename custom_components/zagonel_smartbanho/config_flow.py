"""Config flow for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZagonelApi, ZagonelAuthError, ZagonelError
from .const import DOMAIN, LOGGER

SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


class ZagonelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Smart Banho app account."""

    VERSION = 1

    async def _validate(self, email: str, password: str) -> tuple[dict[str, Any] | None, str | None]:
        api = ZagonelApi(async_get_clientsession(self.hass), email, password)
        try:
            data = await api.login()
        except ZagonelAuthError:
            return None, "invalid_auth"
        except ZagonelError as err:
            LOGGER.warning("Falha ao validar conta Zagonel: %s", err)
            return None, "cannot_connect"
        if not data.get("showers"):
            return None, "no_showers"
        return data, None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data, error = await self._validate(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(data["userId"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=data.get("userName") or user_input[CONF_EMAIL], data=user_input
                )
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data, error = await self._validate(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(data["userId"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )
