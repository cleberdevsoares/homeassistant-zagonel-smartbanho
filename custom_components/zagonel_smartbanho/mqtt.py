"""MQTT (WebSocket) client for Zagonel Smart Banho."""

from __future__ import annotations

from collections.abc import Callable
import json
import random
import ssl
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.core import HomeAssistant

from .const import LOGGER, MQTT_HOST, MQTT_PATH, MQTT_PORT, TOPIC_FROM_DEVICE, TOPIC_TO_DEVICE


class ZagonelMqtt:
    """Keeps one broker connection for all showers of an account."""

    def __init__(
        self,
        hass: HomeAssistant,
        user_id: str,
        device_ids: list[str],
        on_message: Callable[[str, dict[str, Any]], None],
        on_connection: Callable[[bool], None],
    ) -> None:
        self._hass = hass
        self._user_id = user_id
        self._device_ids = device_ids
        self._on_message = on_message
        self._on_connection = on_connection
        self._client: mqtt.Client | None = None
        self.connected = False

    def _build_client(self) -> mqtt.Client:
        client_id = f"APP_{random.randint(0, 99999)}"
        if hasattr(mqtt, "CallbackAPIVersion"):
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, transport="websockets"
            )
        else:
            client = mqtt.Client(client_id=client_id, transport="websockets")
        client.ws_set_options(path=MQTT_PATH)
        client.tls_set_context(ssl.create_default_context())
        client.reconnect_delay_set(min_delay=5, max_delay=120)
        client.on_connect = self._handle_connect
        client.on_disconnect = self._handle_disconnect
        client.on_message = self._handle_message
        return client

    async def async_start(self) -> None:
        def _start() -> None:
            self._client = self._build_client()
            self._client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
            self._client.loop_start()

        await self._hass.async_add_executor_job(_start)

    async def async_stop(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return

        def _stop() -> None:
            client.disconnect()
            client.loop_stop()

        await self._hass.async_add_executor_job(_stop)

    def _handle_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason: Any, *_: Any) -> None:
        if getattr(reason, "is_failure", reason != 0):
            LOGGER.warning("Conexão MQTT recusada: %s", reason)
            return
        for device_id in self._device_ids:
            client.subscribe(TOPIC_FROM_DEVICE.format(device_id=device_id), qos=0)
        self.connected = True
        self._hass.loop.call_soon_threadsafe(self._on_connection, True)
        self.request_chars()

    def _handle_disconnect(self, _client: mqtt.Client, _userdata: Any, *args: Any) -> None:
        self.connected = False
        self._hass.loop.call_soon_threadsafe(self._on_connection, False)

    def _handle_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        device_id = message.topic.removesuffix("_SA")
        if device_id not in self._device_ids:
            return
        try:
            data = json.loads(message.payload)
        except ValueError:
            LOGGER.warning("Mensagem MQTT inválida em %s: %r", message.topic, message.payload[:200])
            return
        if isinstance(data, dict):
            self._hass.loop.call_soon_threadsafe(self._on_message, device_id, data)

    def request_chars(self) -> None:
        if self._client is not None:
            self._client.publish(self._user_id, json.dumps({"command": "getChars"}))

    def send_command(self, device_id: str, command: str, value: Any) -> None:
        if self._client is None or not self.connected:
            raise ConnectionError("MQTT desconectado")
        info = self._client.publish(
            TOPIC_TO_DEVICE.format(device_id=device_id),
            json.dumps({"command": command, "value": value}),
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(mqtt.error_string(info.rc))
