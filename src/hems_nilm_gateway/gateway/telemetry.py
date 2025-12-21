from __future__ import annotations

# Zweck: Telemetrie-Logging (Latenzen pro Modell-Stufe als CSV)

from pathlib import Path
from time import perf_counter


class Telemetry:
    def __init__(self, out_path: str = "telemetry.csv"):
        # Output-Datei initialisieren
        self.path = Path(out_path)
        if not self.path.exists():
            self.path.write_text("ts,stage,latency_ms,extra\n", encoding="utf-8")

    def log(self, stage: str, t_start: float, extra: str = "") -> None:
        # Latenz seit t_start messen
        dt_ms = (perf_counter() - t_start) * 1000.0
        self.path.open("a", encoding="utf-8").write(
            f"{perf_counter():.6f},{stage},{dt_ms:.3f},{extra}\n"
        )
