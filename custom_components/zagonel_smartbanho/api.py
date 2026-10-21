"""REST client and measure parsing for Zagonel Smart Banho."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .const import (
    API_BASE,
    POWER_FACTOR_127V,
    POWER_FACTOR_220V,
    RAW_POWER_SCALE,
    VOLTAGE_THRESHOLD_MV,
)


class ZagonelError(Exception):
    """Generic API error."""


class ZagonelAuthError(ZagonelError):
    """Invalid credentials."""


def raw_power_to_watts(raw_power: float, voltage_mv: float) -> float:
    factor = POWER_FACTOR_220V if voltage_mv > VOLTAGE_THRESHOLD_MV else POWER_FACTOR_127V
    return raw_power * factor / RAW_POWER_SCALE


@dataclass
class Measure:
    """One finished shower."""

    id: str
    start: datetime
    duration_s: int
    water_l: float
    flow_l_min: float
    temperature_c: float
    target_temperature_c: float
    inlet_temperature_c: float
    voltage_v: float
    power_w: float
    energy_kwh: float
    cost: float
    incomplete: bool

    def as_event_data(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "inicio": self.start.isoformat(),
            "duracao_s": self.duration_s,
            "agua_l": round(self.water_l, 1),
            "vazao_l_min": round(self.flow_l_min, 2),
            "temperatura_c": round(self.temperature_c, 1),
            "temperatura_alvo_c": round(self.target_temperature_c, 1),
            "temperatura_entrada_c": round(self.inlet_temperature_c, 1),
            "tensao_v": round(self.voltage_v, 1),
            "potencia_w": round(self.power_w),
            "energia_kwh": round(self.energy_kwh, 3),
            "custo": round(self.cost, 2),
            "incompleto": self.incomplete,
        }


def _num(raw: dict[str, Any], key: str) -> float:
    try:
        return float(raw.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_measure(raw: dict[str, Any], energy_price: float, water_price: float) -> Measure:
    duration = int(_num(raw, "Du"))
    voltage_mv = _num(raw, "Va")
    power_w = raw_power_to_watts(_num(raw, "Pa"), voltage_mv)
    energy_kwh = power_w / 1000 * duration / 3600
    water_l = _num(raw, "Ft") / 1000
    start_ms = int(_num(raw, "startTime") or _num(raw, "timestamp"))
    return Measure(
        id=str(raw.get("_id") or raw.get("id")),
        start=datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc),
        duration_s=duration,
        water_l=water_l,
        flow_l_min=_num(raw, "Fa") / 1000,
        temperature_c=_num(raw, "Ta") / 1000,
        target_temperature_c=_num(raw, "Tr") / 1000,
        inlet_temperature_c=_num(raw, "Ti") / 1000,
        voltage_v=voltage_mv / 1000,
        power_w=power_w,
        energy_kwh=energy_kwh,
        cost=energy_kwh * energy_price + water_l * water_price,
        incomplete=str(raw.get("Fd")) == "-1",
    )


class ZagonelApi:
    """Client for the Smart Banho cloud API."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self.user_id: str | None = None
        self.user_name: str | None = None
        self.energy_price: float = 0.0
        self.water_price: float = 0.0

    async def login(self) -> dict[str, Any]:
        try:
            async with self._session.post(
                f"{API_BASE}/users/login",
                json={"email": self._email, "password": self._password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (400, 401, 403, 404):
                    raise ZagonelAuthError(f"login recusado (HTTP {resp.status})")
                if resp.status != 200:
                    raise ZagonelError(f"login falhou (HTTP {resp.status})")
                data = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ZagonelError(f"falha de comunicação no login: {err}") from err

        if not data.get("token") or not data.get("userId"):
            raise ZagonelAuthError("resposta de login sem token")
        self._token = data["token"]
        self.user_id = data["userId"]
        self.user_name = data.get("userName")
        self.energy_price = float(data.get("energyPrice") or 0)
        self.water_price = float(data.get("waterPrice") or 0)
        return data

    async def _get(self, path: str) -> Any:
        if self._token is None:
            await self.login()
        for attempt in range(2):
            try:
                async with self._session.get(
                    f"{API_BASE}/{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status in (401, 403) and attempt == 0:
                        await self.login()
                        continue
                    if resp.status != 200:
                        raise ZagonelError(f"GET {path} falhou (HTTP {resp.status})")
                    return await resp.json(content_type=None)
            except aiohttp.ClientError as err:
                raise ZagonelError(f"falha de comunicação em {path}: {err}") from err
        raise ZagonelAuthError("token recusado após novo login")

    async def get_showers(self) -> list[dict[str, Any]]:
        data = await self._get(f"showers/user/{self.user_id}")
        return data.get("showers", [])

    async def get_measures_since(self, shower_id: str, since: datetime) -> list[Measure]:
        since_ms = int(since.timestamp() * 1000)
        data = await self._get(f"measures/shower/{shower_id}/{since_ms}")
        return [
            parse_measure(raw, self.energy_price, self.water_price)
            for raw in data.get("measures", [])
        ]
