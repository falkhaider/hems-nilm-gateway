from __future__ import annotations

# Zweck: Zentrale Datentypen für Messdaten (Input) und Modellvorhersagen (Output)

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict


@dataclass(frozen=True)
class SmartMeterSample:
    # Eingangsdaten: Smart-Meter Messpunkt (Zeitstempel + Summenleistung)
    timestamp: datetime
    power_w: float
    # Optional: Referenz-/Ground-Truth je Gerät (nur bei Replay/Submeter)
    actual_device_power_w: Optional[Dict[int, float]] = None


@dataclass(frozen=True)
class NILMResult:
    # Ausgangsdaten: Vorhersage pro Gerät und Zeitpunkt
    ts: datetime
    device_id: str          # Geräte-ID
    state: int              # Binärzustand: 0=OFF, 1=ON
    confidence: float       # Modellkonfidenz [0..1]

    @staticmethod
    def now(device_id: str, state: int, confidence: float) -> "NILMResult":
        # Ergebnis mit aktuellem UTC-Zeitstempel erzeugen
        from datetime import datetime as _dt

        return NILMResult(
            ts=_dt.utcnow(),
            device_id=str(device_id),
            state=int(state),
            confidence=float(confidence),
        )
