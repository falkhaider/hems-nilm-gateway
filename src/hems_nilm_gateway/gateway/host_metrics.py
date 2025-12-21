from __future__ import annotations

# Zweck: Erfassen von Host-Metriken (Raspberry Pi) für das Monitoring via MQTT

import time
from typing import Dict, Any

import psutil


def _read_cpu_temp_fallback() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            v = f.read().strip()
            return float(v) / 1000.0
    except Exception:
        return None


def read_host_metrics() -> Dict[str, Any]:
    # Liefert die Metriken, die im Gateway veröffentlicht werden
    cpu = psutil.cpu_percent(interval=None)

    # RAM-Auslastung + belegter Speicher
    vm = psutil.virtual_memory()
    mem_pct = vm.percent
    mem_used_mb = round(vm.used / (1024 * 1024), 1)

    # Uptime: aktuelle Zeit minus Boot-Zeitpunkt
    boot_ts = psutil.boot_time()
    uptime_s = int(time.time() - boot_ts)

    # CPU-Temperatur: psutil
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        for key in ("cpu-thermal", "cpu_thermal", "coretemp"):
            if key in temps and temps[key]:
                temp = float(temps[key][0].current)
                break
    except Exception:
        pass
    if temp is None:
        temp = _read_cpu_temp_fallback()

    return {
        "cpu_percent": round(cpu, 1),
        "mem_percent": round(mem_pct, 1),
        "mem_used_mb": mem_used_mb,
        "temp_c": round(temp, 1) if temp is not None else "n/a",
        "uptime_s": uptime_s,
    }
