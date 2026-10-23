"""Optional MQTT publishing of each sample (``mqtt.enabled`` in config.json; needs paho-mqtt)."""

from __future__ import annotations

import logging

from .config import SENSOR_ROLES, MqttConfig

log = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, cfg: MqttConfig):
        import paho.mqtt.client as mqtt  # imported lazily: optional dependency

        self.cfg = cfg
        try:  # paho-mqtt >= 2.0
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            self.client = mqtt.Client()
        if cfg.username:
            self.client.username_pw_set(cfg.username, cfg.password)
        self.client.connect_async(cfg.host, cfg.port, 60)
        self.client.loop_start()  # reconnects automatically in the background

    def publish(self, temps: dict, valve: int, mode: str) -> None:
        for role in SENSOR_ROLES:
            if temps.get(role) is not None:
                self.client.publish(f"{self.cfg.base_topic}/{role}", f"{temps[role]:.2f}")
        self.client.publish(f"{self.cfg.base_topic}/valve", str(valve))
        self.client.publish(f"{self.cfg.base_topic}/mode", mode)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
