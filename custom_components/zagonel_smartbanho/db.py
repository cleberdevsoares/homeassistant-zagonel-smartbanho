"""MariaDB/MySQL storage of showers with the resident who took them."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pymysql

from .api import Measure
from .const import UNIDENTIFIED

SCHEMA = """
CREATE TABLE IF NOT EXISTS banhos (
    id VARCHAR(32) NOT NULL PRIMARY KEY,
    chuveiro_id VARCHAR(32) NOT NULL,
    chuveiro VARCHAR(100) NOT NULL,
    inicio DATETIME NULL,
    inicio_nuvem DATETIME NOT NULL,
    duracao_s INT NOT NULL,
    agua_l DECIMAL(8,2) NOT NULL,
    vazao_l_min DECIMAL(6,2) NOT NULL,
    energia_kwh DECIMAL(9,4) NOT NULL,
    potencia_w INT NOT NULL,
    custo DECIMAL(8,2) NOT NULL,
    temperatura_c DECIMAL(4,1) NOT NULL,
    temperatura_alvo_c DECIMAL(4,1) NOT NULL,
    temperatura_entrada_c DECIMAL(4,1) NOT NULL,
    tensao_v DECIMAL(5,1) NOT NULL,
    incompleto TINYINT(1) NOT NULL DEFAULT 0,
    morador VARCHAR(50) NOT NULL DEFAULT 'Não identificado',
    humor VARCHAR(20) NULL,
    registrado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_morador (morador),
    KEY idx_inicio_nuvem (inicio_nuvem),
    KEY idx_chuveiro (chuveiro_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

def _utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def measure_row(
    measure: Measure,
    shower_id: str,
    shower_name: str,
    morador: str | None = None,
    humor: str | None = None,
    detected_start: datetime | None = None,
) -> dict[str, Any]:
    return {
        "id": measure.id,
        "chuveiro_id": shower_id,
        "chuveiro": shower_name,
        "inicio": _utc_naive(detected_start),
        "inicio_nuvem": _utc_naive(measure.start),
        "duracao_s": measure.duration_s,
        "agua_l": round(measure.water_l, 2),
        "vazao_l_min": round(measure.flow_l_min, 2),
        "energia_kwh": round(measure.energy_kwh, 4),
        "potencia_w": round(measure.power_w),
        "custo": round(measure.cost, 2),
        "temperatura_c": round(measure.temperature_c, 1),
        "temperatura_alvo_c": round(measure.target_temperature_c, 1),
        "temperatura_entrada_c": round(measure.inlet_temperature_c, 1),
        "tensao_v": round(measure.voltage_v, 1),
        "incompleto": int(measure.incomplete),
        "morador": morador or UNIDENTIFIED,
        "humor": humor or None,
    }


class BanhoDB:
    """Thin synchronous wrapper; every method runs in the executor."""

    def __init__(self, host: str, port: int, database: str, user: str, password: str) -> None:
        self._params = {
            "host": host,
            "port": port,
            "database": database,
            "user": user,
            "password": password,
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 20,
            "write_timeout": 20,
            "autocommit": True,
        }

    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(**self._params)

    def setup(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(SCHEMA)

    def insert_ignore(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        cols = list(rows[0])
        sql = (
            f"INSERT IGNORE INTO banhos ({', '.join(cols)}) "
            f"VALUES ({', '.join(['%s'] * len(cols))})"
        )
        with self._connect() as conn, conn.cursor() as cur:
            return cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])

    def upsert_with_resident(self, row: dict[str, Any]) -> None:
        cols = list(row)
        sql = (
            f"INSERT INTO banhos ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            "ON DUPLICATE KEY UPDATE morador = VALUES(morador), humor = VALUES(humor), "
            "inicio = COALESCE(VALUES(inicio), inicio)"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))

    def set_resident(self, measure_id: str, morador: str, humor: str | None) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            return cur.execute(
                "UPDATE banhos SET morador = %s, humor = COALESCE(%s, humor) WHERE id = %s",
                (morador, humor or None, measure_id),
            )

    def month_totals(self, shower_id: str, month_start: datetime) -> dict[str, dict[str, float]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT morador, COUNT(*), SUM(duracao_s), SUM(agua_l), SUM(energia_kwh), SUM(custo) "
                "FROM banhos WHERE chuveiro_id = %s AND inicio_nuvem >= %s GROUP BY morador",
                (shower_id, _utc_naive(month_start)),
            )
            return {
                morador: {
                    "count": int(count),
                    "duration_s": int(duration or 0),
                    "water_l": float(water or 0),
                    "energy_kwh": float(energy or 0),
                    "cost": float(cost or 0),
                }
                for morador, count, duration, water, energy, cost in cur.fetchall()
            }
