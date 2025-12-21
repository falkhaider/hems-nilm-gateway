from __future__ import annotations

# Zweck: Runtime-Engine für das trainierte M-GRU Seq2Seq-Modell

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple
import json

import numpy as np
import torch
import yaml

from hems_nilm_gateway.gateway.nilm.engine import NILMEngine
from hems_nilm_gateway.core.model_mgru import MGRUNetMultiSeq2Seq


@dataclass
class MGRURuntimeConfig:
    # Runtime-Konfiguration: Modellpfad + Zielgeräte (Runtime-Reihenfolge)
    artifact_dir: Path
    device_ids: List[int]


class MGRUSeq2SeqEngine(NILMEngine):
    # Engine: lädt Seq2Seq-Netz, liefert das Ergebnis des letzten Zeitschritts
    def __init__(self, cfg: MGRURuntimeConfig):
        self.cfg = cfg
        adir = cfg.artifact_dir

        # Normalisierung (mean/std)
        norm = json.loads((adir / "normalizer.json").read_text(encoding="utf-8"))
        self._mean = float(norm["mean"])
        self._std = float(norm["std"])

        # Trainingsparameter + Train-Device-Order aus config.yaml
        hid, layers, drop, train_ids, on_w = self._read_train_config(adir)
        self._train_ids = [int(x) for x in train_ids]
        self._truth_on_w = float(on_w)

        # Modell laden
        self._device = torch.device("cpu")
        self._model = self._load_model(
            adir,
            D=len(self._train_ids),
            hidden=hid,
            layers=layers,
            dropout=drop,
        )
        self._model.to(self._device).eval()

        # Schwellenwerte "Tau" laden und auf Runtime-Geräte-Reihenfolge abbilden
        taus_train = self._read_thresholds_tau(adir, len(self._train_ids))
        self._runtime_ids = [int(x) for x in cfg.device_ids]
        self._map_train_to_runtime, self._taus_runtime = self._build_mapping_and_reorder_taus(
            self._train_ids,
            self._runtime_ids,
            np.asarray(taus_train, dtype=float),
        )

        # Logging: geladene Modell-Parameter
        print(
            f"[INFO] Lade MGRUNetMultiSeq2Seq(hidden={hid}, layers={layers}, dropout={drop}, D={len(self._train_ids)})"
        )
        print(f"[INFO] Train IDs:   {self._train_ids}")
        print(f"[INFO] Runtime IDs: {self._runtime_ids}")
        print(f"[INFO] τ (runtime): {self._taus_runtime.tolist()}")

    # ---------- Artefakte lesen ----------
    def _read_train_config(self, artifact_dir: Path) -> Tuple[int, int, float, List[int], float]:
        # YAML: Modellparameter + Zielgeräte etc. aus Trainingskonfig laden
        p = artifact_dir / "config.yaml"
        hidden, layers, dropout = 64, 1, 0.0
        ids, on_w = [], 15.0
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            m = cfg.get("model", {}) or {}
            hidden = int(m.get("hidden", hidden))
            layers = int(m.get("layers", layers))
            dropout = float(m.get("dropout", dropout))
            d = cfg.get("dataset", {}) or {}
            ids = [int(x) for x in d.get("target_item_ids", [])]
            on_w = float(d.get("on_w", on_w))
        except Exception as e:
            print(f"[WARN] {p} nicht lesbar ({e}); Defaults.")
        if not ids:
            raise RuntimeError("config.yaml ohne dataset.target_item_ids")
        return hidden, layers, dropout, ids, on_w

    def _read_thresholds_tau(self, artifact_dir: Path, D: int) -> List[float]:
        # KPIs: Tau-Schwellenwerte aus kpis.json
        p = artifact_dir / "kpis.json"
        try:
            kpis = json.loads(p.read_text(encoding="utf-8"))
            taus = kpis.get("thresholds_tau") or [0.5] * D
            if len(taus) != D:
                print(f"[WARN] thresholds_tau Länge {len(taus)} != {D}; pad/trim.")
                taus = (taus + [0.5] * D)[:D]
            return [float(t) for t in taus]
        except Exception as e:
            print(f"[WARN] {p} nicht lesbar ({e}); fallback τ=0.5.")
            return [0.5] * D

    def _load_model(
        self,
        artifact_dir: Path,
        D: int,
        hidden: int,
        layers: int,
        dropout: float,
    ) -> torch.nn.Module:
        # Torch: Netz instanziieren + laden
        net = MGRUNetMultiSeq2Seq(
            num_devices=D,
            hidden=hidden,
            layers=layers,
            dropout=dropout,
            in_channels=2,
        )
        state = torch.load(artifact_dir / "model.pt", map_location="cpu")
        net.load_state_dict(state, strict=True)
        return net

    # ---------- TRAIN -> RUNTIME ----------
    def _build_mapping_and_reorder_taus(
        self,
        train_ids: List[int],
        runtime_ids: List[int],
        taus_train: np.ndarray,
    ):
        # Mapping: Train-Order (Artefakt) -> Runtime-Order (Gateway-Konfig)
        set_tr, set_rt = set(train_ids), set(runtime_ids)
        if set_tr != set_rt:
            missing = sorted(set_tr - set_rt)
            extra = sorted(set_rt - set_tr)
            if missing:
                print(f"[WARN] Runtime fehlt Geräte aus Training: {missing}")
            if extra:
                print(f"[WARN] Runtime enthält Geräte ohne Training: {extra} (τ=0.5; Proba=0)")

        rt_idx = {d: i for i, d in enumerate(runtime_ids)}
        map_tr2rt = [-1] * len(train_ids)

        taus_rt = np.full((len(runtime_ids),), 0.5, dtype=float)

        # Tau in Runtime-Reihenfolge übertragen
        for j_tr, did in enumerate(train_ids):
            if did in rt_idx:
                j_rt = rt_idx[did]
                map_tr2rt[j_tr] = j_rt
                taus_rt[j_rt] = float(taus_train[j_tr])

        return map_tr2rt, taus_rt

    # ---------- Public API ----------
    def reset(self) -> None:
        pass

    @property
    def normalizer(self) -> tuple[float, float]:
        # Rückgabe: mean/std für gleiche Vorverarbeitung wie im Training
        return self._mean, self._std

    @property
    def thresholds(self) -> np.ndarray:
        # Rückgabe: Tau-Schwellenwerte in Runtime-Geräte-Reihenfolge
        return self._taus_runtime.copy()

    @property
    def truth_on_w(self) -> float:
        # Rückgabe: On-Schwelle für Wahrheits-Binarisierung
        return float(self._truth_on_w)

    @torch.no_grad()
    def infer_proba(self, x_btC: torch.Tensor) -> np.ndarray:
        # Inferenz/Modell: Sigmoid-Wahrscheinlichkeiten für letzten Zeitschritt
        logits_btD = self._model(x_btC.to(self._device, dtype=torch.float32))
        probs_train = torch.sigmoid(logits_btD[:, -1, :]).squeeze(0).cpu().numpy()

        probs_rt = np.zeros((len(self._runtime_ids),), dtype=float)
        for j_tr, j_rt in enumerate(self._map_train_to_runtime):
            if j_rt >= 0:
                probs_rt[j_rt] = float(probs_train[j_tr])
        return probs_rt


def build_mgru_engine(
    artifact_dir: str,
    device_ids: List[int],
) -> MGRUSeq2SeqEngine:
    return MGRUSeq2SeqEngine(MGRURuntimeConfig(Path(artifact_dir), device_ids))
