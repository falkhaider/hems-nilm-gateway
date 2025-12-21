from __future__ import annotations

# Zweck: Schnittstellen für Datenquelle (Input "Smart-Meter") und Ausgabe (MQTT/HEMS)

from typing import Protocol, Iterator, Dict, Any

from hems_nilm_gateway.core.domain import SmartMeterSample, NILMResult


class IMeterSource(Protocol):
    # Input-Interface: liefert fortlaufend SmartMeterSample-Objekte
    def __iter__(self) -> Iterator[SmartMeterSample]:
        ...

    # Ressourcen freigeben
    def close(self) -> None:
        ...


class ISignalPublisher(Protocol):
    # Initialisierung
    def startup(self) -> None:
        ...

    # Publish: NILM-Ergebnis pro Gerät
    def publish(self, result: NILMResult) -> None:
        ...

    # Publish: Host-/Gateway-Metriken
    def publish_host_metrics(self, metrics: Dict[str, Any]) -> None:
        ...

    # Publish: Wahren Zustände/Timeseries für die Evaluierung
    def publish_timeseries(
        self,
        mains_w: float,
        actual_power_w: Dict[int, float],
        actual_state: Dict[int, int],
    ) -> None:
        ...

    # Publish: End-to-End Latenz eines Modellfensters (ms)
    def publish_latency(self, latency_ms: float) -> None:
        ...

    # Ressourcen wieder freigeben
    def close(self) -> None:
        ...
