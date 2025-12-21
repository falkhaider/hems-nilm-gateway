# NILM-Gateway

Dieses Repository enthält die Python-Implementierung eines des NILM-Gateways (Non-Intrusive Load Monitoring) im Kontext einer Masterthesis. Das Gateway verarbeitet 1-Hz-Summenleistungsdaten, erzeugt daraus Merkmale (Fensterbildung, z-Normalisierung, dP/dt), führt eine Inferenz mit einem trainierten GRU-basierten Mehrgeräte-Modell durch und publiziert die vorhergesagten Gerätezustände via MQTT, einschließlich Home-Assistant-Discovery.

Der Code ist so aufgebaut, dass sowohl ein Live-Betrieb (hier: Shelly 3EM) als auch ein Replay-Betrieb (DEDDIAG-Postgres) möglich ist.

## Projektziel und Kontext

Ziel der Implementierung ist die technische Realisierung und experimentelle Evaluation eines NILM-Gateways auf Edge-Hardware. Im Fokus steht die Ableitung binärer Gerätezustände (ON/OFF) für mehrere Zielgeräte aus niederfrequenten Smart-Meter-Daten und die Bereitstellung der Ergebnisse in einem Home Energy Management System (HEMS) über MQTT.

## Voraussetzungen

- Python >= 3.10
- Linux für systemd-Betrieb (z. B. Raspberry Pi OS)
- MQTT-Broker (z. B. Mosquitto)
- Optional für Replay: Postgres + DEDDIAG-Datenbankzugriff

Hinweis: Abhängigkeiten werden über `pyproject.toml` verwaltet.

## Installation

make venv
make install


## Konfiguration

Die Runtime wird über Umgebungsvariablen konfiguriert (hier .env.run, welche beim Start geladen wird).

## Modellartefakte

Für den Gateway-Betrieb werden Artefakte aus dem Training benötigt. Der MODEL_ARTIFACT_DIR muss mindestens enthalten:
- model.pt
- normalizer.json
- kpis.json
- config.yaml

## Starten der Runtime

make run

## Betrieb als systemd-Service

Für den Betrieb auf einem Raspberry Pi wird der systemd-Service verwendet:
- make service-install
- make service-start
- make service-stop
- make service-status
- make logs
