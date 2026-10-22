"""State coordinator for Zagonel Smart Banho."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pymysql

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Measure, ZagonelApi, ZagonelAuthError, ZagonelError, raw_power_to_watts
from .const import (
    CONF_DB_HOST,
    CONF_DB_NAME,
    CONF_DB_PASSWORD,
    CONF_DB_PORT,
    CONF_DB_USER,
    CONF_RESIDENTS,
    DEFAULT_DB_PORT,
    DOMAIN,
    EVENT_SHOWER_FINISHED,
    EVENT_SHOWER_STARTED,
    IMPORT_BATCH,
    IMPORT_DELAY,
    LIVE_POLL_SECONDS,
    LOGGER,
    MEASURE_FETCH_DELAYS,
    POLL_INTERVAL_MINUTES,
    RUNNING_TIMEOUT,
    UNIDENTIFIED,
    VISITOR,
)
from .db import BanhoDB, measure_row
from .mqtt import ZagonelMqtt

STORAGE_VERSION = 1


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
    session_start: datetime | None = None
    awaiting_measure: bool = False
    pending_resident: str | None = None
    pending_mood: str | None = None
    last_resident: str | None = None
    last_mood: str | None = None
    residents_month: dict[str, dict[str, float]] = field(default_factory=dict)

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


def parse_residents(raw: str | None) -> list[str]:
    names = [n.strip() for n in (raw or "").split(",") if n.strip()]
    if names and not any(n.casefold() == VISITOR.casefold() for n in names):
        names.append(VISITOR)
    return names


class ZagonelCoordinator(DataUpdateCoordinator[dict[str, Shower]]):
    """Merges REST polling (history), MQTT push (live state) and the resident database."""

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
        self.residents = parse_residents(entry.options.get(CONF_RESIDENTS))
        self.db: BanhoDB | None = None
        self.db_ok = False
        self._queue: list[dict[str, Any]] = []
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}_fila")
        self._off_timers: dict[str, CALLBACK_TYPE] = {}
        self._fetch_timers: list[CALLBACK_TYPE] = []
        self._live_poll: CALLBACK_TYPE | None = None
        self.importing = False

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
        options = self.config_entry.options
        if options.get(CONF_DB_HOST):
            self.db = BanhoDB(
                options[CONF_DB_HOST],
                int(options.get(CONF_DB_PORT) or DEFAULT_DB_PORT),
                options[CONF_DB_NAME],
                options[CONF_DB_USER],
                options.get(CONF_DB_PASSWORD, ""),
            )
            self._queue = (await self._store.async_load()) or []
            try:
                await self.hass.async_add_executor_job(self.db.setup)
                self.db_ok = True
            except pymysql.Error as err:
                LOGGER.warning("Banco de banhos indisponível (%s); os banhos ficam na fila local", err)

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
                is_new = previous is not None and newest is not None and newest.id != previous.id and newest.start > previous.start
                if is_new:
                    self._claim_measure(shower, newest)
                if self.db is not None:
                    await self._async_store_measures(shower, measures)
                if is_new:
                    self.hass.bus.async_fire(
                        EVENT_SHOWER_FINISHED,
                        {
                            "device_id": shower.device_id,
                            "chuveiro": shower.name,
                            "morador": shower.last_resident or UNIDENTIFIED,
                            "humor": shower.last_mood,
                            **newest.as_event_data(),
                        },
                    )
        except ZagonelAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ZagonelError as err:
            raise UpdateFailed(str(err)) from err
        return self.showers

    @callback
    def _claim_measure(self, shower: Shower, measure: Measure) -> None:
        shower.last_resident = shower.pending_resident
        shower.last_mood = shower.pending_mood
        detected = shower.session_start if shower.awaiting_measure else None
        shower.awaiting_measure = False
        shower.pending_resident = None
        shower.pending_mood = None
        self._queue.append(
            measure_row(measure, shower.device_id, shower.name, shower.last_resident, shower.last_mood, detected)
        )
        self._save_queue()

    async def _async_store_measures(self, shower: Shower, measures: list[Measure]) -> None:
        assert self.db is not None
        rows = [measure_row(m, shower.device_id, shower.name) for m in measures]
        queue = list(self._queue)
        try:
            if not self.db_ok:
                await self.hass.async_add_executor_job(self.db.setup)
                self.db_ok = True
            for row in queue:
                await self.hass.async_add_executor_job(self.db.upsert_with_resident, row)
                self._queue.remove(row)
            await self.hass.async_add_executor_job(self.db.insert_ignore, rows)
            if shower.last_resident is None and shower.last_measure is not None:
                shower.last_resident, shower.last_mood = await self.hass.async_add_executor_job(
                    self.db.resident_of, shower.last_measure.id
                )
            if shower.month_start is not None:
                shower.residents_month = await self.hass.async_add_executor_job(
                    self.db.month_totals, shower.device_id, shower.month_start
                )
        except pymysql.Error as err:
            if self.db_ok:
                LOGGER.warning("Falha ao gravar no banco de banhos (%s); mantendo %d na fila", err, len(self._queue))
            self.db_ok = False
        self._save_queue()

    @callback
    def _save_queue(self) -> None:
        if self.db is not None:
            self._store.async_delay_save(lambda: self._queue, 1)

    def canonical_resident(self, name: str) -> str:
        wanted = name.strip().casefold()
        for resident in [*self.residents, UNIDENTIFIED]:
            if resident.casefold() == wanted:
                return resident
        raise ServiceValidationError(
            f"Morador '{name}' não está cadastrado. Cadastrados: {', '.join(self.residents)}"
        )

    async def async_set_resident_for(self, measure_id: str, resident: str, mood: str | None) -> None:
        resident = self.canonical_resident(resident)
        mood = mood.strip().lower() if mood else None
        if self.db is None:
            raise HomeAssistantError("O banco de banhos não está configurado nas opções da integração")
        try:
            changed = await self.hass.async_add_executor_job(self.db.set_resident, measure_id, resident, mood)
            for shower in self.showers.values():
                if shower.last_measure is not None and shower.last_measure.id == measure_id:
                    shower.last_resident = resident
                    shower.last_mood = mood or shower.last_mood
                if shower.month_start is not None:
                    shower.residents_month = await self.hass.async_add_executor_job(
                        self.db.month_totals, shower.device_id, shower.month_start
                    )
        except pymysql.Error as err:
            raise HomeAssistantError(f"Falha ao gravar no banco de banhos: {err}") from err
        if not changed:
            LOGGER.warning("Banho %s não encontrado no banco (ou já estava com %s)", measure_id, resident)
        self.async_update_listeners()

    async def async_set_resident(self, shower_id: str | None, resident: str | None, mood: str | None) -> None:
        resident = self.canonical_resident(resident) if resident else None
        mood = mood.strip().lower() if mood else None
        targets = [self.showers[shower_id]] if shower_id in self.showers else list(self.showers.values())
        for shower in targets:
            if shower.running or shower.awaiting_measure:
                shower.pending_resident = resident or shower.pending_resident
                shower.pending_mood = mood or shower.pending_mood
                continue
            if shower.last_measure is None:
                continue
            shower.last_resident = resident or shower.last_resident or UNIDENTIFIED
            shower.last_mood = mood or shower.last_mood
            if self.db is not None:
                try:
                    await self.hass.async_add_executor_job(
                        self.db.set_resident, shower.last_measure.id, shower.last_resident, shower.last_mood
                    )
                    if shower.month_start is not None:
                        shower.residents_month = await self.hass.async_add_executor_job(
                            self.db.month_totals, shower.device_id, shower.month_start
                        )
                except pymysql.Error as err:
                    raise HomeAssistantError(f"Falha ao gravar no banco de banhos: {err}") from err
        self.async_update_listeners()

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
            shower.session_start = dt_util.utcnow()
            shower.awaiting_measure = True
            shower.pending_resident = None
            shower.pending_mood = None
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

    @callback
    def start_history_import(self) -> None:
        if self.db is None:
            raise HomeAssistantError("Configure o banco de banhos nas opções da integração antes de importar o histórico")
        if self.importing:
            raise HomeAssistantError("A importação do histórico já está em andamento")
        self.importing = True
        self.config_entry.async_create_background_task(
            self.hass, self._async_import_history(), f"{DOMAIN}_importar_historico"
        )

    def _notify_import(self, message: str) -> None:
        persistent_notification.async_create(
            self.hass, message, title="Zagonel Smart Banho - histórico", notification_id=f"{DOMAIN}_importacao"
        )

    async def _async_import_history(self) -> None:
        assert self.db is not None
        imported = failed = 0
        try:
            for shower in self.showers.values():
                ids = await self.api.get_measure_ids(shower.device_id)
                known = await self.hass.async_add_executor_job(self.db.existing_ids, shower.device_id)
                missing = [i for i in ids if i not in known]
                self._notify_import(f"{shower.name}: {len(ids)} banhos na nuvem, {len(missing)} para importar. Isso pode levar alguns minutos.")
                batch: list[dict[str, Any]] = []
                for index, measure_id in enumerate(missing, 1):
                    try:
                        measure = await self.api.get_measure(measure_id)
                    except ZagonelError as err:
                        failed += 1
                        LOGGER.debug("Banho %s não importado: %s", measure_id, err)
                        measure = None
                    if measure is not None:
                        batch.append(measure_row(measure, shower.device_id, shower.name))
                    if len(batch) >= IMPORT_BATCH or (index == len(missing) and batch):
                        imported += await self.hass.async_add_executor_job(self.db.insert_ignore, batch)
                        batch = []
                    if index % 250 == 0:
                        self._notify_import(f"{shower.name}: {index} de {len(missing)} banhos processados...")
                    await asyncio.sleep(IMPORT_DELAY)
                if shower.month_start is not None:
                    shower.residents_month = await self.hass.async_add_executor_job(
                        self.db.month_totals, shower.device_id, shower.month_start
                    )
            message = f"Importação concluída: {imported} banhos antigos gravados no banco."
            if failed:
                message += f" {failed} não puderam ser lidos da nuvem; rode a importação de novo para tentar outra vez."
            self._notify_import(message)
        except (ZagonelError, pymysql.Error) as err:
            LOGGER.warning("Importação do histórico interrompida: %s", err)
            self._notify_import(f"Importação interrompida ({err}). {imported} banhos foram gravados; rode de novo para continuar.")
        finally:
            self.importing = False
            self.async_update_listeners()

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
