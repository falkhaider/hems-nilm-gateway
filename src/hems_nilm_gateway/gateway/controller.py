from __future__ import annotations

# Zweck: Verwaltung der Gateway-Prozesse (Quelle -> Preprocessing -> Modell -> Publish)

import csv
import os
import time
from time import perf_counter
from typing import Optional, Dict

import numpy as np

from hems_nilm_gateway.gateway.io_adapters.interfaces import IMeterSource, ISignalPublisher
from hems_nilm_gateway.gateway.preprocessing.preprocessor import Preprocessor
from hems_nilm_gateway.gateway.nilm.engine import NILMEngine
from hems_nilm_gateway.gateway.telemetry import Telemetry
from hems_nilm_gateway.gateway.host_metrics import read_host_metrics
from hems_nilm_gateway.core.domain import SmartMeterSample, NILMResult


class GatewayController:
    def __init__(
        self,
        source: IMeterSource,
        engine: NILMEngine,
        preprocessor: Preprocessor,
        publisher: ISignalPublisher,
        telemetry: Optional[Telemetry] = None,
        host_metrics_interval_s: int = 5,
        groundtruth_on_w: float = 15.0,
        ema_alpha: float = 1.0,
    ):
        # Abhängigkeiten: Quelle, Engine, Preprocessing, Publisher
        self.source = source
        self.engine = engine
        self.pre = preprocessor
        self.pub = publisher

        # Telemetrie: Laufzeitmessung einzelner Schritte
        self.t = telemetry or Telemetry()

        # Intervall für Host-Metriken (Sekunden)
        self._host_metrics_interval_s = max(1, int(host_metrics_interval_s))

        # Wahrheits-Binarisierung: Schwelle
        self._on_w = float(getattr(self.engine, "truth_on_w", groundtruth_on_w))

        # Optional: EMA über Wahrscheinlichkeiten
        self._alpha = float(ema_alpha)
        self._ema: np.ndarray | None = None

        # Schwellwerte Tau aus Engine
        self._taus = getattr(self.engine, "thresholds", None)

        # Geräte-Reihenfolge
        self._device_ids = list(getattr(getattr(self.engine, "cfg", object), "device_ids", []))

        # Debug-CSV: Laufzeitdaten für Analyse/Plots etc.
        self._dbg_path = "debug_runtime.csv"
        need_header = not os.path.exists(self._dbg_path)
        self._dbg_f = open(self._dbg_path, "a", newline="", encoding="utf-8")
        self._dbg_w = csv.writer(self._dbg_f)
        if need_header:
            hdr = ["ts", "mains_W"]
            for did in self._device_ids:
                hdr += [
                    f"p_{did}",
                    f"tau_{did}",
                    f"state_{did}",
                    f"truthW_{did}",
                    f"truth_{did}",
                ]
            self._dbg_w.writerow(hdr)
            self._dbg_f.flush()

    def _truth_states(self, sample: SmartMeterSample) -> Dict[int, int]:
        # Wahrheitswerte: Leistung -> binärer Zustand je Gerät
        out: Dict[int, int] = {}
        if sample.actual_device_power_w:
            for did, p in sample.actual_device_power_w.items():
                out[int(did)] = 1 if float(p) >= self._on_w else 0
        return out

    def run_forever(self) -> None:
        # Hauptloop: fortlaufender Stream bis Quelle endet oder close ausgelöst wird
        self.pub.startup()
        next_metrics_ts = time.time()

        try:
            for sample in self.source:
                # (1) Timeseries publizieren (Mains + optional Wahrheitswerte)
                actual_states = self._truth_states(sample)
                self.pub.publish_timeseries(
                    mains_w=sample.power_w,
                    actual_power_w=sample.actual_device_power_w or {},
                    actual_state=actual_states,
                )

                # (2) Host-Metriken publizieren
                now = time.time()
                if now >= next_metrics_ts:
                    self.pub.publish_host_metrics(read_host_metrics())
                    next_metrics_ts = now + self._host_metrics_interval_s

                # (3) Vorverarbeitung: Sample in Feature-Fenster überführen
                t0 = perf_counter()
                x = self.pre.ingest_and_maybe_window(sample.power_w)
                self.t.log("ingest", t0)
                if x is None:
                    self._dbg_w.writerow(
                        [sample.timestamp.isoformat(), f"{float(sample.power_w):.2f}"]
                    )
                    self._dbg_f.flush()
                    continue

                # (4) Modell: Wahrscheinlichkeiten pro Gerät
                t_latency_start = perf_counter()
                t1 = t_latency_start
                probs = self.engine.infer_proba(x)  # (D,)
                self.t.log("infer", t1, extra="batch=1")

                # (5) EMA-Glättung
                if self._ema is None:
                    self._ema = probs.copy()
                else:
                    self._ema = self._alpha * probs + (1.0 - self._alpha) * self._ema

                # (5b) Schwellwertentscheidung (Tau)
                taus = self._taus if self._taus is not None else np.full_like(self._ema, 0.5)
                states = (self._ema >= taus).astype(np.uint8)

                # (6) Publish: Zustand + Konfidenz je Gerät
                t2 = perf_counter()
                for i, did in enumerate(self._device_ids):
                    res = NILMResult.now(
                        device_id=str(did),
                        state=int(states[i]),
                        confidence=float(self._ema[i]),
                    )
                    self.pub.publish(res)
                self.t.log("publish", t2, extra=f"n={len(states)}")

                # (6b) Publish: End-to-End-Latenz (Fenster -> Klassifikation)
                latency_ms = (perf_counter() - t_latency_start) * 1000.0
                self.pub.publish_latency(latency_ms)

                # (7) Debug-CSV
                row = [sample.timestamp.isoformat(), f"{float(sample.power_w):.2f}"]
                for i, did in enumerate(self._device_ids):
                    truthW = (sample.actual_device_power_w or {}).get(int(did), 0.0)
                    truthS = 1 if truthW >= self._on_w else 0
                    row += [
                        f"{self._ema[i]:.4f}",
                        f"{taus[i]:.3f}",
                        int(states[i]),
                        f"{float(truthW):.2f}",
                        truthS,
                    ]
                self._dbg_w.writerow(row)
                self._dbg_f.flush()

        finally:
            # Dateien schließen + Quelle + Publisher beenden
            try:
                self._dbg_f.close()
            except Exception:
                pass
            try:
                self.source.close()
            finally:
                self.pub.close()
