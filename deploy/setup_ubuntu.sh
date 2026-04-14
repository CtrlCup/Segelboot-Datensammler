#!/usr/bin/env bash
# Einmaliges Setup auf einem Ubuntu-Server.
# Erstellt venv, installiert Abhängigkeiten, legt Verzeichnisse an.
#
# Nutzung:
#   cd /opt/segelboot-scraper          # Projekt-Root
#   bash deploy/setup_ubuntu.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "==> Projekt-Verzeichnis: $PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
    echo "==> Installiere python3 + venv"
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip
fi

if [ ! -d ".venv" ]; then
    echo "==> Erzeuge virtuelles Environment (.venv)"
    python3 -m venv .venv
fi

echo "==> Installiere Python-Abhängigkeiten"
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

mkdir -p data images

if [ ! -f webdav_config.py ]; then
    echo "==> webdav_config.py fehlt — kopiere Template"
    cp webdav_config.example.py webdav_config.py
    echo "    Bitte webdav_config.py mit echten Zugangsdaten bearbeiten."
fi

echo "==> Setup fertig. Teste mit:"
echo "    ./.venv/bin/python main.py"
