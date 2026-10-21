"""State coordinator for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Measure, ZagonelApi, ZagonelAuthError, ZagonelError, raw_power_to_watts
from .const import (
    DOMAIN,
    EVENT_SHOWER_FINISHED,
    EVENT_SHOWER_STARTED,
    LIVE_POLL_SECONDS,
    LOGGER,
    MEASURE_FETCH_DELAYS,
    POLL_INTERVAL_MINUTES,
    RUNNING_TIMEOUT,
)
from .mqtt import ZagonelMqtt


@dataclass
class Totals:
    count: int = 0
    water_l: float = 0.0
    energy_kwh: float = 0.0
    cost: float = 0.0
    duration_s: int = 0

    @classmethod
    def from_measures(cls, measures: list[Measure]) -> Totals:
        return cls(
            count=len(measures),
            water_l=sum(m.water_l for m in measures),
            energy_kwh=sum(m.energy_kwh for m in measures),
            cost=sum(m.cost for m in measures),
            duration_s=sum(m.duration_s for m in measures),
        )


@dataclass
class Shower:
    device_id: str
    name: str
    mac: str | None = None
    chars: dict[str, Any] = field(default_factory=dict)
    status: dict[str, Any] = field(default_factory=dict)
    running: bool = False
    last_status: datetime | None = None
    last_measure: Measure | None = None
    today: Totals = field(default_factory=Totals)
    month: Totals = field(default_factory=Totals)
    month_start: datetime | None = None

    def live(self, key: str, scale: float = 1000) -> float | None:
        value = self.status.get(key)
        return None if value is None else value / scale

    @property
    def live_power_w(self) -> float | None:
        if not self.running:
            return 0.0
        if self.status.get("Pw") is None:
            return None
        return raw_power_to_watts(self.status["Pw"], self.status.get("Vi") or 0)


class ZagonelCoordinator(DataUpdateCoordinator[dict[str, Shower]]):
    """Merges REST polling (history) and MQTT push (live state)."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ZagonelApi) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=POLL_INTERVAL_MINUTES),
        )
        self.api = api
        self.mqtt: ZagonelMqtt | None = None
        self.mqtt_connected = False
        self.showers: dict[str, Shower] = {}
        self._off_timers: dict[str, CALLBACK_TYPE] = {}
        self._fetch_timers: list[CALLBACK_TYPE] = []
        self._live_poll: CALLBACK_TYPE | None = None

    async def async_setup(self) -> None:
        try:
            await self.api.login()
            raw_showers = await self.api.get_showers()
        except ZagonelAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        for raw in raw_showers:
            device_id = raw.get("_id") or raw.get("id")
            self.showers[device_id] = Shower(
                device_id=device_id,
                name=raw.get("showerName") or "Chuveiro",
                mac=raw.get("MAC"),
            )
        self.mqtt = ZagonelMqtt(
            self.hass,
            self.api.user_id,
            list(self.showers),
            self._handle_mqtt_message,
            self._handle_mqtt_connection,
        )

    async def async_start_push(self) -> None:
        if self.mqtt is not None:
            await self.mqtt.async_start()
            self._live_poll = async_track_time_interval(
                self.hass, self._poll_live_status, timedelta(seconds=LIVE_POLL_SECONDS)
            )

    @callback
    def _poll_live_status(self, _now: datetime) -> None:
        if self.mqtt is not None and self.mqtt_connected:
            self.mqtt.request_chars()

    async def async_shutdown(self) -> None:
        if self._live_poll is not None:
            self._live_poll()
            self._live_poll = None
        for cancel in [*self._off_timers.values(), *self._fetch_timers]:
            cancel()
        self._off_timers.clear()
        self._fetch_timers.clear()
        if self.mqtt is not None:
            await self.mqtt.async_stop()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, Shower]:
        now = dt_util.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            for shower in self.showers.values():
                measures = await self.api.get_measures_since(shower.device_id, month_start)
                if len(measures) >= 250:
                    LOGGER.warning("Mais de 250 banhos no mês em %s; total do mês pode ficar incompleto", shower.name)
                newest = max(measures, key=lambda m: m.start, default=None)
                previous = shower.last_measure
                if newest is not None:
                    shower.last_measure = newest
                elif previous is None:
                    recent = await self.api.get_measures_since(shower.device_id, month_start - timedelta(days=62))
                    shower.last_measure = max(recent, key=lambda m: m.start, default=None)
                shower.month = Totals.from_measures(measures)
                shower.today = Totals.from_measures([m for m in measures if m.start >= day_start])
                shower.month_start = month_start
                if previous is not None and newest is not None and newest.id != previous.id and newest.start > previous.start:
                    self.hass.bus.async_fire(
                        EVENT_SHOWER_FINISHED,
                        {"device_id": shower.device_id, "chuveiro": shower.name, **newest.as_event_data()},
                    )
        except ZagonelAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ZagonelError as err:
            raise UpdateFailed(str(err)) from err
        return self.showers

    @callback
    def _handle_mqtt_connection(self, connected: bool) -> None:
        self.mqtt_connected = connected
        self.async_update_listeners()

    @callback
    def _handle_mqtt_message(self, device_id: str, data: dict[str, Any]) -> None:
        shower = self.showers.get(device_id)
        if shower is None:
            return
        kind = data.get("Type")
        if kind == "Chars":
            shower.chars.update({k: v for k, v in data.items() if k != "Type"})
        elif kind == "Status":
            shower.status = data
            shower.last_status = dt_util.utcnow()
            self._mark_running(shower, data.get("St") == "RUN")
        else:
            return
        self.async_update_listeners()

    @callback
    def _mark_running(self, shower: Shower, running: bool) -> None:
        if cancel := self._off_timers.pop(shower.device_id, None):
            cancel()
        if running and not shower.running:
            shower.running = True
            self.hass.bus.async_fire(
                EVENT_SHOWER_STARTED,
                {
                    "device_id": shower.device_id,
                    "chuveiro": shower.name,
                    "temperatura_alvo_c": shower.live("Ts"),
                },
            )
        if not running:
            self._set_stopped(shower)
            return
        self._off_timers[shower.device_id] = async_call_later(
            self.hass, RUNNING_TIMEOUT, self._timeout_callback(shower)
        )

    def _timeout_callback(self, shower: Shower) -> Callable[[datetime], None]:
        @callback
        def _expired(_now: datetime) -> None:
            self._off_timers.pop(shower.device_id, None)
            self._set_stopped(shower)
            self.async_update_listeners()

        return _expired

    @callback
    def _set_stopped(self, shower: Shower) -> None:
        if not shower.running:
            return
        shower.running = False
        for cancel in self._fetch_timers:
            cancel()
        self._fetch_timers.clear()
        for delay in MEASURE_FETCH_DELAYS:
            self._fetch_timers.append(async_call_later(self.hass, delay, self._scheduled_refresh))

    @callback
    def _scheduled_refresh(self, _now: datetime) -> None:
        self.hass.async_create_task(self.async_request_refresh())

    def can_send(self, shower: Shower) -> bool:
        return self.mqtt is not None and self.mqtt_connected and not shower.running

    async def async_send(self, shower: Shower, command: str, value: Any) -> None:
        if shower.running:
            raise HomeAssistantError("O chuveiro só aceita alterações quando está desligado")
        if self.mqtt is None or not self.mqtt_connected:
            raise HomeAssistantError("Sem conexão com o servidor da Zagonel")
        try:
            self.mqtt.send_command(shower.device_id, command, value)
        except ConnectionError as err:
            raise HomeAssistantError(f"Falha ao enviar comando: {err}") from err

    def request_chars(self) -> None:
        if self.mqtt is not None:
            self.mqtt.request_chars()
