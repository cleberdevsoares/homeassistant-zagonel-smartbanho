"""Config flow for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

import pymysql

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZagonelApi, ZagonelAuthError, ZagonelError
from .const import (
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USER,
    CONF_RESIDENTS,
    DEFAULT_DB_PORT,
    DOMAIN,
    LOGGER,
)
from .db import BanhoDB

SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


class ZagonelOptionsFlow(OptionsFlow):
    """Residents and the optional MariaDB/MySQL database."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.options}
        if user_input is not None:
            data = {k: v for k, v in user_input.items() if v not in (None, "")}
            if data.get(CONF_DB_HOST) and not data.get(CONF_DB_PASSWORD) and current.get(CONF_DB_PASSWORD):
                data[CONF_DB_PASSWORD] = current[CONF_DB_PASSWORD]
            if data.get(CONF_DB_HOST):
                db = BanhoDB(
                    data[CONF_DB_HOST],
                    int(data.get(CONF_DB_PORT) or DEFAULT_DB_PORT),
                    data.get(CONF_DB_NAME, ""),
                    data.get(CONF_DB_USER, ""),
                    data.get(CONF_DB_PASSWORD, ""),
                )
                try:
                    await self.hass.async_add_executor_job(db.setup)
                except pymysql.Error as err:
                    LOGGER.warning("Falha ao conectar no banco de banhos: %s", err)
                    errors["base"] = "db_cannot_connect"
            if not errors:
                return self.async_create_entry(data=data)
            current = {**current, **user_input}

        schema = vol.Schema(
            {
                vol.Optional(CONF_RESIDENTS, default=current.get(CONF_RESIDENTS, "")): str,
                vol.Optional(CONF_DB_HOST, default=current.get(CONF_DB_HOST, "")): str,
                vol.Optional(CONF_DB_PORT, default=int(current.get(CONF_DB_PORT, DEFAULT_DB_PORT))): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional(CONF_DB_NAME, default=current.get(CONF_DB_NAME, "")): str,
                vol.Optional(CONF_DB_USER, default=current.get(CONF_DB_USER, "")): str,
                vol.Optional(CONF_DB_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)


class ZagonelConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Smart Banho app account."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ZagonelOptionsFlow:
        return ZagonelOptionsFlow()

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
