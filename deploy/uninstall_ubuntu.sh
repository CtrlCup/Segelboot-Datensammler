#!/usr/bin/env bash
# Deinstallation des Segelboot-Scrapers auf einem Ubuntu-Server.
# Stoppt + entfernt systemd-Units, loescht venv und optional Daten.
#
# Nutzung:
#   cd /opt/segelboot-scraper
#   sudo bash deploy/uninstall_ubuntu.sh
#
# Das Skript fragt interaktiv, bevor es etwas loescht.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="segelboot-scraper"
SYSTEMD_DIR="/etc/systemd/system"

if [ "$(id -u)" -ne 0 ]; then
    echo "Dieses Skript muss mit sudo ausgefuehrt werden." >&2
    exit 1
fi

confirm() {
    # $1 = Frage, $2 = Default (y|n)
    local default="${2:-n}"
    local prompt="[y/N]"
    [ "$default" = "y" ] && prompt="[Y/n]"
    read -rp "$1 $prompt " answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy]$ ]]
}

echo "==> Segelboot-Scraper Deinstallation"
echo "    Projekt-Verzeichnis: $PROJECT_DIR"
echo

# 1. systemd-Timer + Service stoppen und deaktivieren
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.timer"; then
    echo "==> Stoppe und deaktiviere systemd-Units"
    systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
    systemctl disable --now "${SERVICE_NAME}.service" 2>/dev/null || true
else
    echo "==> Keine systemd-Units gefunden — ueberspringe"
fi

# 2. Unit-Dateien entfernen
for unit in "${SERVICE_NAME}.timer" "${SERVICE_NAME}.service"; do
    if [ -f "${SYSTEMD_DIR}/${unit}" ]; then
        echo "    Entferne ${SYSTEMD_DIR}/${unit}"
        rm -f "${SYSTEMD_DIR}/${unit}"
    fi
done
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

# 3. Journal-Logs (optional)
if confirm "Journal-Logs des Services loeschen?" n; then
    journalctl --vacuum-time=1s --unit="${SERVICE_NAME}.service" 2>/dev/null || true
fi

# 4. venv entfernen
if [ -d "$PROJECT_DIR/.venv" ]; then
    if confirm "Virtuelles Environment ($PROJECT_DIR/.venv) loeschen?" y; then
        rm -rf "$PROJECT_DIR/.venv"
        echo "    .venv entfernt"
    fi
fi

# 5. Daten + Bilder (gefaehrlich — Default NEIN)
if [ -d "$PROJECT_DIR/data" ] || [ -d "$PROJECT_DIR/images" ]; then
    echo
    echo "!! Daten + Bilder loeschen: dabei gehen lokale Scrape-Ergebnisse verloren."
    echo "   (Sofern ein WebDAV-Push gelaufen ist, liegen sie weiterhin auf dem Server.)"
    if confirm "data/ und images/ loeschen?" n; then
        rm -rf "$PROJECT_DIR/data" "$PROJECT_DIR/images"
        echo "    data/ und images/ entfernt"
    fi
fi

# 6. WebDAV-Zugangsdaten
if [ -f "$PROJECT_DIR/webdav_config.py" ]; then
    if confirm "webdav_config.py (Zugangsdaten) loeschen?" n; then
        rm -f "$PROJECT_DIR/webdav_config.py"
        echo "    webdav_config.py entfernt"
    fi
fi

# 7. Projekt-Verzeichnis komplett?
echo
if confirm "Gesamtes Projekt-Verzeichnis $PROJECT_DIR loeschen?" n; then
    cd /
    rm -rf "$PROJECT_DIR"
    echo "    $PROJECT_DIR entfernt"
fi

echo
echo "==> Deinstallation abgeschlossen."
