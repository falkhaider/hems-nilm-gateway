from __future__ import annotations

# Zweck: Meter-Adapter für DEDDIAG-Replay aus Postgres und Live-Messung via Shelly 3EM

from datetime import datetime
from time import monotonic, sleep
from typing import Iterator, Optional, List, Dict

import psycopg2
import psycopg2.extras
from psycopg2 import sql
import requests

from hems_nilm_gateway.gateway.io_adapters.interfaces import IMeterSource
from hems_nilm_gateway.core.domain import SmartMeterSample


class DeddiagReplayMeter(IMeterSource):
    # Quelle: 1-Hz-Stream aus DEDDIAG-Postgres
    def __init__(
        self,
        db_cfg: dict,
        mains_item_id: int,
        start: str,
        end: str,
        sample_rate_hz: float = 1.0,
        speed: float = 1.0,
        schema: Optional[str] = None,
        truth_device_ids: Optional[List[int]] = None,
    ):
        # Konfiguration: Mains-ID
        self.item_mains = int(mains_item_id)
        self.truth_ids: List[int] = list(truth_device_ids or [])

        # Zeitfenster + Sampling
        self.start = start
        self.end = end
        self.sample_rate_hz = float(sample_rate_hz)
        self.speed = max(0.01, float(speed))

        self._closed = False

        # DB-Verbindung (aus Konfig)
        dsn = (
            f"host={db_cfg['host']} port={db_cfg['port']} dbname={db_cfg['dbname']} "
            f"user={db_cfg['user']} password={db_cfg['password']}"
        )
        self._conn = psycopg2.connect(dsn)

        cur0 = self._conn.cursor()
        try:
            cur0.execute("BEGIN")
            if schema:
                cur0.execute(
                    sql.SQL("SET LOCAL search_path TO {}, public").format(
                        sql.Identifier(schema)
                    )
                )
        finally:
            cur0.close()

        # Server-seitiger Cursor
        self._cur = self._conn.cursor(
            name="deddiag_stream",
            cursor_factory=psycopg2.extras.DictCursor,
        )

        # SQL: Mains als Basis + Zustände der Geräte (Wahr)
        select_cols = ["m.time", "m.value AS mains"]
        joins: List[str] = []
        params: List[object] = [self.item_mains, self.start, self.end]

        for did in self.truth_ids:
            alias = f"d{did}"
            select_cols.append(f"{alias}.value AS dev_{did}")
            joins.append(
                "LEFT JOIN get_measurements(%s, %s, %s) " + alias + " USING (time)"
            )
            params.extend([int(did), self.start, self.end])

        sql_query = f"""
            SELECT {", ".join(select_cols)}
            FROM get_measurements(%s, %s, %s) m
            {' '.join(joins)}
            ORDER BY m.time ASC
        """
        self._cur.execute(sql_query, params)

    def __iter__(self) -> Iterator[SmartMeterSample]:
        # Iterator liest DB in Batches
        dt_target = 1.0 / max(1e-6, self.sample_rate_hz)
        t_ref = monotonic()
        fetch_size = 1000

        while not self._closed:
            rows = self._cur.fetchmany(fetch_size)
            if not rows:
                break

            for r in rows:
                if self._closed:
                    break

                # Mains
                ts: datetime = r["time"]
                mains = float(r["mains"]) if r["mains"] is not None else 0.0

                # Optional: Wahrheits-Leistungen je Gerät
                actual: Dict[int, float] = {}
                for did in self.truth_ids:
                    key = f"dev_{did}"
                    v = r.get(key, None)
                    actual[int(did)] = float(v) if v is not None else 0.0

                # Output: ein Sample pro Zeitschritt
                yield SmartMeterSample(
                    timestamp=ts,
                    power_w=mains,
                    actual_device_power_w=actual if actual else None,
                )

                t_ref += dt_target / self.speed
                delay = t_ref - monotonic()
                if delay > 0:
                    sleep(delay)

    def close(self) -> None:
        # Cursor schließen + Verbindung schließen
        self._closed = True
        try:
            try:
                if self._cur:
                    self._cur.close()
            finally:
                if self._conn:
                    try:
                        self._conn.rollback()
                    except Exception:
                        pass
                    self._conn.close()
        except Exception:
            pass


class ShellyPro3EmMeter(IMeterSource):
    # Quelle: Live-Summenleistung über Shelly 3EM Gen1 HTTP-API
    def __init__(
        self,
        host: str,
        port: int = 80,
        sample_rate_hz: float = 1.0,
        timeout_s: float = 3.0,
    ):
        # Konfiguration: Endpoint + Sampling
        self.host = host
        self.port = int(port)
        self.sample_rate_hz = float(sample_rate_hz)
        self.timeout_s = float(timeout_s)
        self._closed = False

        # URL zusammensetzen
        base = f"http://{self.host}"
        if self.port not in (80, 0):
            base = f"{base}:{self.port}"
        self._url_status = f"{base}/status"

    def __iter__(self) -> Iterator[SmartMeterSample]:
        # Iterator: zyklischer HTTP-Polling-Loop mit 1-Hz Rate
        dt_target = 1.0 / max(1e-6, self.sample_rate_hz)
        t_ref = monotonic()

        while not self._closed:
            ts = datetime.utcnow()
            mains = 0.0

            try:
                # HTTP GET /status + JSON-Parse
                resp = requests.get(self._url_status, timeout=self.timeout_s)
                resp.raise_for_status()
                data = resp.json()

                # Gen1: Summe aus "emeters"[i]["power"]
                ems = data.get("emeters") or []
                if isinstance(ems, list):
                    mains = sum(float(em.get("power") or 0.0) for em in ems)

                if mains == 0.0 and data.get("total_power") is not None:
                    mains = float(data["total_power"])

            except Exception as e:
                # Bei Fehlern weitermachen, sodass kein Abbruch des Streams entsteht
                print(f"[WARN] Shelly3Em: Fehler beim Lesen der Daten: {e}")

            # Output: Live-Sample
            yield SmartMeterSample(
                timestamp=ts,
                power_w=float(mains),
                actual_device_power_w=None,
            )

            # Echtzeit-Pacing
            t_ref += dt_target
            delay = t_ref - monotonic()
            if delay > 0:
                sleep(delay)

    def close(self) -> None:
        # Loop beenden
        self._closed = True
