"""Constants for Zagonel Smart Banho."""

from __future__ import annotations

import logging

DOMAIN = "zagonel_smartbanho"
LOGGER = logging.getLogger(__package__)

MANUFACTURER = "Zagonel"
MODEL = "Ducali"

API_BASE = "https://appsmartbanho.zagonel.com.br/api"
MQTT_HOST = "appsmartbanho.zagonel.com.br"
MQTT_PORT = 443
MQTT_PATH = "/mqtt"

TOPIC_FROM_DEVICE = "{device_id}_SA"
TOPIC_TO_DEVICE = "{device_id}_AS"

LIVE_POLL_SECONDS = 15
RUNNING_TIMEOUT = 90
MEASURE_FETCH_DELAYS = (20, 60, 180)
POLL_INTERVAL_MINUTES = 15

POWER_FACTOR_220V = 7500
POWER_FACTOR_127V = 5500
VOLTAGE_THRESHOLD_MV = 150000
RAW_POWER_SCALE = 65535

EVENT_SHOWER_STARTED = f"{DOMAIN}_banho_iniciado"
EVENT_SHOWER_FINISHED = f"{DOMAIN}_banho_finalizado"

CONTROL_MODES = {0: "manual", 1: "automatic"}
RGB_MODES = {0: "power", 1: "temperature", 2: "fixed"}
PARENTAL_MODES = {0: "off", 1: "sound", 2: "shutdown", 3: "sound_and_shutdown"}

CONF_RESIDENTS = "moradores"
CONF_DB_HOST = "db_host"
CONF_DB_PORT = "db_port"
CONF_DB_NAME = "db_name"
CONF_DB_USER = "db_user"
CONF_DB_PASSWORD = "db_password"
DEFAULT_DB_PORT = 3306
VISITOR = "Visitante"
UNIDENTIFIED = "Não identificado"

SERVICE_SET_RESIDENT = "definir_morador"

PLATFORMS =["binary_sensor", "button", "light", "number", "select", "sensor"]
