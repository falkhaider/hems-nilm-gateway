from __future__ import annotations

# Zweck: GRU-basierte Netze für Mehrgeräte-NILM (Klassifikation auf Fensterbasis)

import torch
import torch.nn as nn


class MGRUNetMultiSeq2Seq(nn.Module):
    # Modelltyp: Seq2Seq (Vorhersage für jeden Zeitschritt; Stellt das in dieser Arbeit umgesetzte Modell dar)
    def __init__(
        self,
        num_devices: int,
        hidden: int = 64,
        layers: int = 1,
        dropout: float = 0.0,
        in_channels: int = 2,
    ):
        super().__init__()

        # Parameter: Anzahl Zielgeräte
        self.num_devices = int(num_devices)

        # GRU über Zeitfenster
        self.rnn = nn.GRU(
            input_size=in_channels,
            hidden_size=hidden,
            num_layers=layers,
            batch_first=True,
            dropout=dropout if layers > 1 else 0.0,
        )

        # Klassifikationskopf: Hidden-State je Zeitschritt -> Logits pro Gerät
        self.head = nn.Linear(hidden, self.num_devices)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Input: (B, T, C)
        o, _ = self.rnn(x)     # Hidden-Repräsentation: (B, T, H)

        # Output: Logits pro Zeitschritt und Gerät: (B, T, D)
        logits = self.head(o)
        return logits


# B = Batch size (Anzahl Fenster/Sequenzen pro Batch)
# T = Time steps (Länge des Zeitfensters)
# C = Channels (Anzahl Eingangskanäle/Features pro Zeitschritt)
# H = Hidden size (Größe des GRU-Hidden-States)
# D = Devices (Anzahl Zielgeräte)
