from __future__ import annotations

# Zweck: Abstrakte Engine-Schnittstelle für das NILM-Modell

import numpy as np
import torch


class NILMEngine:
    # Reset: internen Zustand zurücksetzen
    def reset(self) -> None:
        ...

    @torch.no_grad()
    def infer_proba(self, x_btC: torch.Tensor) -> np.ndarray:
        # Modell liefert Wahrscheinlichkeiten pro Gerät (D,)
        raise NotImplementedError
