from __future__ import annotations

# Zweck: MQTT-Publisher für NILM-Ergebnisse und Home-Assistant-Discovery

import json
import socket
from typing import List, Dict, Any

import paho.mqtt.client as mqtt

from hems_nilm_gateway.gateway.io_adapters.interfaces import ISignalPublisher
from hems_nilm_gateway.core.domain import NILMResult


class MqttPublisher(ISignalPublisher):
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        base_topic: str,
        ha_discovery: bool,
        ha_prefix: str,
        retain: bool,
        qos: int,
        device_ids: List[int],
        device_names: List[str],
        publish_pi_metrics: bool = True,
        discover_confidence_sensor: bool = True,
        clear_retained_on_start: bool = True,
    ):
        # MQTT-Client
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        # Topic-/Discovery-Konfiguration
        self.base_topic = base_topic.strip("/")
        self.ha_discovery = bool(ha_discovery)
        self.ha_prefix = ha_prefix.strip("/")
        self.retain = bool(retain)
        self.qos = int(qos)

        # Optional: Systemmetriken + "Konfidenz"-Sensor
        self.publish_pi_metrics_enabled = bool(publish_pi_metrics)
        self.discover_confidence_sensor = bool(discover_confidence_sensor)

        self.clear_retained_on_start = bool(clear_retained_on_start)

        # Geräte-Metadaten (ID -> Anzeigename)
        self.devinfo = [
            (str(d), (device_names[i] if i < len(device_names) else f"Device {d}"))
            for i, d in enumerate(device_ids)
        ]

        # Hostname als Node-ID (HA unique_id)
        self._discovered = False
        self._node_id = socket.gethostname() or "nilm-gw"

        # Availability-Topic + Last Will (offline bei Verbindungsabbruch)
        self.availability_topic = f"{self.base_topic}/availability"
        self.client.will_set(
            self.availability_topic,
            payload="offline",
            qos=self.qos,
            retain=True,
        )

        # Authentifizierung + Broker-Verbindung
        if username:
            self.client.username_pw_set(username=username, password=password or "")
        self.client.connect(host, port, 60)
        self.client.loop_start()

    # ---------- Helper ----------
    def _pub(
        self,
        topic: str,
        payload: str,
        qos: int | None = None,
        retain: bool | None = None,
    ) -> None:
        # Publish-Wrapper (QoS/Retain)
        q = self.qos if qos is None else int(qos)
        r = self.retain if retain is None else bool(retain)
        self.client.publish(topic, payload, qos=q, retain=r)

    def _disc_sensor(
        self,
        uniq_suffix: str,
        name: str,
        state_topic: str,
        unit: str | None = None,
        device_class: str | None = None,
        icon: str | None = None,
        state_class: str = "measurement",
    ) -> None:
        # Home-Assistant: MQTT Discovery für Sensoren
        if not self.ha_discovery:
            return
        cfg_topic = f"{self.ha_prefix}/sensor/{self._node_id}_{uniq_suffix}/config"
        payload: Dict[str, Any] = {
            "name": name,
            "unique_id": f"{self._node_id}_{uniq_suffix}",
            "state_topic": state_topic,
            "state_class": state_class,
            "availability": [
                {
                    "topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "device": {
                "identifiers": [self._node_id],
                "name": "NILM",
                "manufacturer": "hems-nilm-gateway",
                "model": "Raspberry Pi",
            },
        }
        if unit:
            payload["unit_of_measurement"] = unit
        if device_class:
            payload["device_class"] = device_class
        if icon:
            payload["icon"] = icon

        # Discovery-Configs müssen retained sein
        self._pub(cfg_topic, json.dumps(payload), qos=self.qos, retain=True)

    def _disc_binary(
        self,
        uniq_suffix: str,
        name: str,
        state_topic: str,
        payload_on: str = "ON",
        payload_off: str = "OFF",
        icon: str | None = None,
    ) -> None:
        # Home-Assistant: MQTT Discovery für Binary-Sensoren (ON/OFF)
        if not self.ha_discovery:
            return
        cfg_topic = f"{self.ha_prefix}/binary_sensor/{self._node_id}_{uniq_suffix}/config"
        payload: Dict[str, Any] = {
            "name": name,
            "unique_id": f"{self._node_id}_{uniq_suffix}",
            "state_topic": state_topic,
            "payload_on": payload_on,
            "payload_off": payload_off,
            "availability": [
                {
                    "topic": self.availability_topic,
                    "payload_available": "online",
                    "payload_not_available": "offline",
                }
            ],
            "device": {
                "identifiers": [self._node_id],
                "name": "NILM",
                "manufacturer": "hems-nilm-gateway",
                "model": "M-GRU NILM",
            },
        }
        if icon:
            payload["icon"] = icon

        # Discovery-Configs müssen retained sein
        self._pub(cfg_topic, json.dumps(payload), qos=self.qos, retain=True)

    def _disc_delete_legacy(self, component: str, legacy_uniq: str) -> None:
        # Alte Discovery-Entities entfernen
        if not self.ha_discovery:
            return
        topic = f"{self.ha_prefix}/{component}/{legacy_uniq}/config"
        self._pub(topic, "", qos=self.qos, retain=True)

    def _clear_retained(self) -> None:
        # Retained Topics leeren
        if not self.clear_retained_on_start:
            return

        self._pub(f"{self.base_topic}/mains/power_W", "", qos=self.qos, retain=True)
        for dev_id, _ in self.devinfo:
            self._pub(f"{self.base_topic}/{dev_id}/state", "", qos=self.qos, retain=True)
            self._pub(f"{self.base_topic}/{dev_id}/confidence", "", qos=self.qos, retain=True)
            self._pub(f"{self.base_topic}/{dev_id}/truth/state", "", qos=self.qos, retain=True)
            self._pub(f"{self.base_topic}/{dev_id}/truth/power_W", "", qos=self.qos, retain=True)

    # ---------- Discovery ----------
    def startup(self) -> None:
        # Initialisierung: Availability + HA-Discovery Entities anlegen
        if self._discovered:
            return

        # Gateway als online markieren (retained)
        self._pub(self.availability_topic, "online", qos=self.qos, retain=True)

        # Entity-IDs entfernen
        for dev_id, _ in self.devinfo:
            legacy = f"{self._node_id}_nilm_{dev_id}"
            self._disc_delete_legacy("binary_sensor", legacy)

        self._clear_retained()

        # Mains (Summenleistung)
        self._disc_sensor(
            uniq_suffix="nilm_mains_power_w",
            name="Mains Power",
            state_topic=f"{self.base_topic}/mains/power_W",
            unit="W",
            device_class="power",
            icon="mdi:flash",
        )

        # Pro Gerät: Prediction + Truth + Truth-Power (+ optional Konfidenz des Modells)
        for dev_id, dev_name in self.devinfo:
            self._disc_binary(
                uniq_suffix=f"nilm_{dev_id}_pred_state",
                name=f"{dev_name} Predicted",
                state_topic=f"{self.base_topic}/{dev_id}/state",
                icon="mdi:power-plug",
            )
            self._disc_binary(
                uniq_suffix=f"nilm_{dev_id}_truth_state",
                name=f"{dev_name} Truth",
                state_topic=f"{self.base_topic}/{dev_id}/truth/state",
                icon="mdi:check-circle-outline",
            )
            self._disc_sensor(
                uniq_suffix=f"nilm_{dev_id}_truth_power_w",
                name=f"{dev_name} Power (Truth)",
                state_topic=f"{self.base_topic}/{dev_id}/truth/power_W",
                unit="W",
                device_class="power",
                icon="mdi:flash",
            )
            if self.discover_confidence_sensor:
                self._disc_sensor(
                    uniq_suffix=f"nilm_{dev_id}_pred_conf",
                    name=f"{dev_name} Confidence",
                    state_topic=f"{self.base_topic}/{dev_id}/confidence",
                    icon="mdi:chart-bell-curve",
                )

        # Host-/Gateway-Metriken
        self._disc_sensor(
            "host_cpu_percent",
            "CPU",
            f"{self.base_topic}/host/cpu_percent",
            "%",
            None,
            "mdi:cpu-64-bit",
        )
        self._disc_sensor(
            "host_mem_percent",
            "RAM",
            f"{self.base_topic}/host/mem_percent",
            "%",
            None,
            "mdi:memory",
        )
        self._disc_sensor(
            "host_mem_used_mb",
            "RAM Used",
            f"{self.base_topic}/host/mem_used_mb",
            "MB",
            None,
            "mdi:memory",
        )
        self._disc_sensor(
            "host_temp_c",
            "CPU Temp",
            f"{self.base_topic}/host/temp_c",
            "°C",
            "temperature",
            "mdi:thermometer",
        )
        self._disc_sensor(
            "host_uptime_s",
            "Uptime",
            f"{self.base_topic}/host/uptime_s",
            "s",
            "duration",
            "mdi:clock-outline",
        )
        self._disc_sensor(
            "host_latency_ms",
            "Latency",
            f"{self.base_topic}/host/latency_ms",
            "ms",
            None,
            "mdi:timer-outline",
        )

        self._discovered = True

    # ---------- Publish ----------
    def publish(self, result: NILMResult) -> None:
        # Ergebnis: vorhergesagter Zustand + Konfidenz publizieren
        state_topic = f"{self.base_topic}/{result.device_id}/state"
        payload = "ON" if int(result.state) == 1 else "OFF"
        self._pub(state_topic, payload)

        conf_topic = f"{self.base_topic}/{result.device_id}/confidence"
        self._pub(conf_topic, str(float(result.confidence)))

    def publish_timeseries(
        self,
        mains_w: float,
        actual_power_w: Dict[int, float],
        actual_state: Dict[int, int],
    ) -> None:
        # Wahren Zustände Timeseries (für Evaluierung/Visualisierung im HEMS)
        self._pub(
            f"{self.base_topic}/mains/power_W",
            str(float(mains_w)),
        )
        for did, p in (actual_power_w or {}).items():
            self._pub(
                f"{self.base_topic}/{did}/truth/power_W",
                str(float(p)),
            )
        for did, s in (actual_state or {}).items():
            self._pub(
                f"{self.base_topic}/{did}/truth/state",
                "ON" if int(s) == 1 else "OFF",
            )

    def publish_host_metrics(self, metrics: Dict[str, Any]) -> None:
        # Gateway-Metriken publizieren
        if not self.publish_pi_metrics_enabled:
            return
        for k in ("cpu_percent", "mem_percent", "mem_used_mb", "temp_c", "uptime_s"):
            if k in metrics:
                self._pub(
                    f"{self.base_topic}/host/{k}",
                    str(metrics[k]),
                )

    def publish_latency(self, latency_ms: float) -> None:
        # End-to-End Latenz publizieren (ms)
        if not self.publish_pi_metrics_enabled:
            return
        topic = f"{self.base_topic}/host/latency_ms"
        self._pub(topic, f"{float(latency_ms):.3f}")

    def close(self) -> None:
        # Offline signalisieren + MQTT trennen
        try:
            self._pub(self.availability_topic, "offline", qos=self.qos, retain=True)
        except Exception:
            pass
        try:
            self.client.loop_stop()
        finally:
            try:
                self.client.disconnect()
            except Exception:
                pass
