from __future__ import annotations

# Zweck: Feature-Bildung wie im Training (Fensterbildung + z-Norm + dP/dt)

from collections import deque
import numpy as np
import torch


class Preprocessor:
    # Erzeugt alle STRIDE Schritte ein Feature-Tensorfenster (1, T, 2)
    def __init__(self, window: int, stride: int, mean: float, std: float):
        # Fenster- und Normierungsparameter
        self.window = int(window)
        self.stride = int(stride)
        self.mean = float(mean)
        self.std = float(std) if std > 1e-9 else 1.0  # Schutz gegen Division durch 0

        # Ringpuffer: window+1, um den Wert vor dem Fenster für dP/dt zu haben
        self.buf = deque(maxlen=self.window + 1)
        self._since_last = 0 

    def ingest_and_maybe_window(self, p_total_w: float) -> torch.Tensor | None:
        # Sample aufnehmen + Stride zählen
        self.buf.append(float(p_total_w))
        self._since_last += 1

        # Gate: erst ausgeben, wenn genug Samples + Stride erreicht
        if len(self.buf) < (self.window + 1) or (self._since_last < self.stride):
            return None
        self._since_last = 0

        # Buffer -> numpy (letzte window+1 Werte)
        buf_np = np.asarray(self.buf, dtype=np.float32)
        prev = buf_np[-(self.window + 1)]
        x = buf_np[-self.window:]

        # Feature-Kanal 0: z-Normalisierung der Summenleistung
        x_norm = (x - self.mean) / self.std

        # Feature-Kanal 1: erste Differenz (dP/dt) mit prev als Startwert (Leistungsänderung)
        dp = np.diff(np.concatenate(([prev], x))).astype(np.float32)

        # Stacking: (T, 2) -> Torch: (1, T, 2)
        feats = np.stack([x_norm, dp], axis=-1).astype(np.float32)
        return torch.from_numpy(feats).unsqueeze(0)
