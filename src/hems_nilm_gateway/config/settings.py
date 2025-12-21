from __future__ import annotations

# Zweck: Zentrale Konfiguration des Gateways über Umgebungsvariablen

import os
from dataclasses import dataclass
from typing import List


def _getenv(key: str, default: str | None = None) -> str:
    # Hilfsfunktion: String aus Environment lesen (mit Default)
    v = os.getenv(key, default if default is not None else "")
    return v


def _getenv_bool(key: str, default: bool = False) -> bool:
    # Hilfsfunktion: Bool aus Environment lesen
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _getenv_int(key: str, default: int) -> int:
    # Hilfsfunktion: Int aus Environment lesen
    try:
        return int(_getenv(key, str(default)))
    except Exception:
        return default


def _getenv_float(key: str, default: float) -> float:
    # Hilfsfunktion: Float aus Environment lesen
    try:
        return float(_getenv(key, str(default)))
    except Exception:
        return default


def _getenv_list_int(key: str, default: List[int]) -> List[int]:
    # Hilfsfunktion: CSV-Liste "1,2,3" -> List[int]
    v = _getenv(key, "")
    if not v:
        return list(default)
    return [int(x.strip()) for x in v.split(",") if x.strip()]


def _getenv_list_str(key: str, default: List[str]) -> List[str]:
    # Hilfsfunktion: CSV-Liste "a,b,c" -> List[str]
    v = _getenv(key, "")
    if not v:
        return list(default)
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class MQTTSettings:
    # Konfiguration: MQTT-Verbindung + Home-Assistant-Discovery
    host: str
    port: int
    username: str | None
    password: str | None
    base_topic: str
    ha_discovery: bool
    ha_prefix: str
    retain: bool
    qos: int


@dataclass
class ModelSettings:
    # Konfiguration: Modellartefakte + Zielgeräte
    artifact_dir: str
    device_ids: List[int]
    device_names: List[str]


@dataclass
class StreamSettings:
    # Konfiguration: Windowing/Streaming (Online-Verarbeitung)
    window: int
    stride: int
    sample_rate_hz: float

    # Konfiguration: DEDDIAG-Replay (Offline/Playback)
    replay_speed: float
    use_deddiag_replay: bool

    deddiag_schema: str
    deddiag_mains_item_id: int
    deddiag_start: str
    deddiag_end: str
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    # Konfiguration: Shelly 3EM Live-Betrieb
    shelly_host: str
    shelly_port: int
    shelly_timeout_s: float


@dataclass
class RuntimeSettings:
    # Konfiguration: Laufzeitoptionen (Metriken, Schwellwerte, Glättung)
    publish_pi_metrics: bool
    pi_metrics_interval_s: int
    groundtruth_on_w: float
    ema_alpha: float


@dataclass
class Settings:
    # Teilkonfigurationen in ein Objekt
    mqtt: MQTTSettings
    model: ModelSettings
    stream: StreamSettings
    runtime: RuntimeSettings


def load_settings() -> Settings:
    # Einstiegspunkt: Settings aus Umgebungsvariablen zusammensetzen

    mqtt = MQTTSettings(
        host=_getenv("MQTT_HOST", "localhost"),
        port=_getenv_int("MQTT_PORT", 1883),
        username=_getenv("MQTT_USER", None) or None,
        password=_getenv("MQTT_PASS", None) or None,
        base_topic=_getenv("MQTT_BASE_TOPIC", "nilm"),
        ha_discovery=_getenv_bool("MQTT_HA_DISCOVERY", True),
        ha_prefix=_getenv("MQTT_HA_PREFIX", "homeassistant"),
        retain=_getenv_bool("MQTT_RETAIN", False),
        qos=_getenv_int("MQTT_QOS", 0),
    )

    model = ModelSettings(
        artifact_dir=_getenv("MODEL_ARTIFACT_DIR", "./artifacts/mgru/"),
        device_ids=_getenv_list_int("MODEL_DEVICE_IDS", []),
        device_names=_getenv_list_str("MODEL_DEVICE_NAMES", []),
    )

    stream = StreamSettings(
        window=_getenv_int("STREAM_WINDOW", 120),
        stride=_getenv_int("STREAM_STRIDE", 5),
        sample_rate_hz=_getenv_float("STREAM_SAMPLE_RATE_HZ", 1.0),
        replay_speed=_getenv_float("STREAM_REPLAY_SPEED", 1.0),
        use_deddiag_replay=_getenv_bool("STREAM_USE_DEDDIAG", True),
        deddiag_schema=_getenv("DEDDIAG_SCHEMA", "public"),
        deddiag_mains_item_id=_getenv_int("DEDDIAG_MAINS_ITEM_ID", 59),
        deddiag_start=_getenv("DEDDIAG_START", "2017-11-08T12:00:00"),
        deddiag_end=_getenv("DEDDIAG_END", "2017-11-23T12:00:00"),
        db_host=_getenv("DEDDIAG_DB_HOST", "127.0.0.1"),
        db_port=_getenv_int("DEDDIAG_DB_PORT", 5432),
        db_name=_getenv("DEDDIAG_DB_NAME", "postgres"),
        db_user=_getenv("DEDDIAG_DB_USER", "postgres"),
        db_password=_getenv("DEDDIAG_DB_PASSWORD", "password"),
        shelly_host=_getenv("SHELLY_HOST", "192.168.178.50"),
        shelly_port=_getenv_int("SHELLY_PORT", 80),
        shelly_timeout_s=_getenv_float("SHELLY_TIMEOUT_S", 3.0),
    )

    runtime = RuntimeSettings(
        publish_pi_metrics=_getenv_bool("PUBLISH_PI_METRICS", True),
        pi_metrics_interval_s=_getenv_int("PI_METRICS_INTERVAL_S", 5),
        groundtruth_on_w=_getenv_float("GROUNDTRUTH_ON_W", 15.0),
        ema_alpha=_getenv_float("EMA_ALPHA", 0.4),
    )

    # Ergebnis: Vollständiges Settings-Objekt für das Gateway
    return Settings(mqtt=mqtt, model=model, stream=stream, runtime=runtime)
