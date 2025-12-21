from __future__ import annotations

# Zweck: CLI-Einstiegspunkt für den Gateway-Runtime-Betrieb (Quelle -> Preprocessing -> Modell -> MQTT)

import argparse

from hems_nilm_gateway.config.settings import load_settings
from hems_nilm_gateway.gateway.io_adapters.meter_adapter import (
    DeddiagReplayMeter,
    ShellyPro3EmMeter,
)
from hems_nilm_gateway.gateway.io_adapters.homeassistant_publisher import MqttPublisher
from hems_nilm_gateway.gateway.nilm.model_manager import build_mgru_engine
from hems_nilm_gateway.gateway.preprocessing.preprocessor import Preprocessor
from hems_nilm_gateway.gateway.controller import GatewayController


def main() -> None:
    # CLI-Argumente
    ap = argparse.ArgumentParser(description="NILM Gateway Runtime")
    ap.add_argument(
        "--artifacts",
        help="Pfad zu Artefakt-Ordner (model.pt, normalizer.json, kpis.json)",
        default=None,
    )
    args = ap.parse_args()

    # Settings aus Environment laden (siehe config/settings.py)
    cfg = load_settings()
    if args.artifacts:
        cfg.model.artifact_dir = args.artifacts

    # Engine: Modell laden + Normalizer bereitstellen
    engine = build_mgru_engine(
        artifact_dir=cfg.model.artifact_dir,
        device_ids=cfg.model.device_ids,
    )
    mean, std = engine.normalizer

    # Preprocessor: Feature-Fenster erzeugen
    pre = Preprocessor(
        window=cfg.stream.window,
        stride=cfg.stream.stride,
        mean=mean,
        std=std,
    )

    # Datenquelle wählen: Replay (DEDDDIAG) oder Live-Betrieb (Shelly 3EM)
    if cfg.stream.use_deddiag_replay:
        print("[INFO] Source: DEDDIAG Postgres-Replay.")
        db_cfg = dict(
            host=cfg.stream.db_host,
            port=cfg.stream.db_port,
            dbname=cfg.stream.db_name,
            user=cfg.stream.db_user,
            password=cfg.stream.db_password,
        )
        source = DeddiagReplayMeter(
            db_cfg=db_cfg,
            schema=cfg.stream.deddiag_schema,
            mains_item_id=cfg.stream.deddiag_mains_item_id,
            start=cfg.stream.deddiag_start,
            end=cfg.stream.deddiag_end,
            sample_rate_hz=cfg.stream.sample_rate_hz,
            speed=cfg.stream.replay_speed,
            truth_device_ids=cfg.model.device_ids,
        )
    else:
        print(
            f"[INFO] Source: Shelly 3EM Live-Messung "
            f"({cfg.stream.shelly_host}:{cfg.stream.shelly_port})."
        )
        source = ShellyPro3EmMeter(
            host=cfg.stream.shelly_host,
            port=cfg.stream.shelly_port,
            sample_rate_hz=cfg.stream.sample_rate_hz,
            timeout_s=cfg.stream.shelly_timeout_s,
        )

    # Publisher: MQTT-Ausgabe
    pub = MqttPublisher(
        host=cfg.mqtt.host,
        port=cfg.mqtt.port,
        username=cfg.mqtt.username,
        password=cfg.mqtt.password,
        base_topic=cfg.mqtt.base_topic,
        ha_discovery=cfg.mqtt.ha_discovery,
        ha_prefix=cfg.mqtt.ha_prefix,
        retain=cfg.mqtt.retain,  # jetzt wirksam
        qos=cfg.mqtt.qos,
        device_ids=cfg.model.device_ids,
        device_names=cfg.model.device_names,
        publish_pi_metrics=cfg.runtime.publish_pi_metrics,
    )

    # Controller Loop + Metriken
    ctrl = GatewayController(
        source=source,
        engine=engine,
        preprocessor=pre,
        publisher=pub,
        host_metrics_interval_s=cfg.runtime.pi_metrics_interval_s,
        groundtruth_on_w=cfg.runtime.groundtruth_on_w,
        ema_alpha=cfg.runtime.ema_alpha,
    )
    ctrl.run_forever()


if __name__ == "__main__":
    main()
