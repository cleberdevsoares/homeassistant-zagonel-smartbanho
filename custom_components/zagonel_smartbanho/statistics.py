"""Hourly totals of the showers in the Home Assistant long-term statistics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .api import Measure
from .const import DOMAIN

STORAGE_VERSION = 1

METRICS = (
    ("agua", "água", UnitOfVolume.LITERS, VolumeConverter.UNIT_CLASS),
    ("energia", "energia", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    ("custo", "custo", None, None),
)


def statistic_id(device_id: str, key: str) -> str:
    return f"{DOMAIN}:{device_id.lower()}_{key}"


class BanhoStatistics:
    """Keeps every shower bucketed by hour and mirrors the running sums into the recorder."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}_estatisticas")
        self._data: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        self._data = (await self._store.async_load()) or {}

    def known_ids(self, device_id: str) -> set[str]:
        return set(self._data.get(device_id, {}).get("ids", []))

    def add(self, device_id: str, measures: list[Measure]) -> datetime | None:
        shower = self._data.setdefault(device_id, {"ids": [], "horas": {}})
        known = set(shower["ids"])
        earliest: datetime | None = None
        for measure in measures:
            if measure.id in known:
                continue
            known.add(measure.id)
            shower["ids"].append(measure.id)
            hour = measure.start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
            bucket = shower["horas"].setdefault(hour.isoformat(), [0.0, 0.0, 0.0])
            bucket[0] += measure.water_l
            bucket[1] += measure.energy_kwh
            bucket[2] += measure.cost
            earliest = hour if earliest is None or hour < earliest else earliest
        if earliest is not None:
            self._store.async_delay_save(lambda: self._data, 5)
        return earliest

    def publish(self, device_id: str, shower_name: str, since: datetime) -> None:
        hours = sorted(self._data.get(device_id, {}).get("horas", {}).items())
        sums = [0.0, 0.0, 0.0]
        rows: list[list[StatisticData]] = [[], [], []]
        for iso, values in hours:
            start = datetime.fromisoformat(iso)
            for index, value in enumerate(values):
                sums[index] += value
                if start >= since:
                    rows[index].append(StatisticData(start=start, state=value, sum=round(sums[index], 4)))
        currency = self.hass.config.currency
        for index, (key, label, unit, unit_class) in enumerate(METRICS):
            if not rows[index]:
                continue
            metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{shower_name} {label} dos banhos",
                source=DOMAIN,
                statistic_id=statistic_id(device_id, key),
                unit_class=unit_class,
                unit_of_measurement=unit if key != "custo" else currency,
            )
            async_add_external_statistics(self.hass, metadata, rows[index])
