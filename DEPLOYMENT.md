# Deployment auf Ubuntu-Server

Anleitung, um den Segelboot-Datensammler auf einem Ubuntu-Server im
Hintergrund laufen zu lassen und ihn automatisch **zu zwei festen
Uhrzeiten pro Tag** zu starten.

Getestet auf Ubuntu 22.04 / 24.04. Vorausgesetzt: `sudo`-Rechte,
Internetverbindung.

---

## 1. Projekt auf den Server kopieren

```bash
sudo mkdir -p /opt/segelboot-scraper
sudo chown $USER:$USER /opt/segelboot-scraper
git clone <DEIN-GITHUB-REPO> /opt/segelboot-scraper
cd /opt/segelboot-scraper
```

Alternativ: per `scp`/`rsync` hochladen.

---

## 2. Setup ausführen

```bash
bash deploy/setup_ubuntu.sh
```

Das Skript:
- installiert `python3`/`python3-venv` falls nötig,
- legt `.venv/` an und installiert `requirements.txt`,
- erstellt `data/` und `images/`,
- kopiert `webdav_config.example.py` → `webdav_config.py` falls nicht
  vorhanden.

Danach `webdav_config.py` editieren und pCloud-Zugangsdaten eintragen:

```bash
nano webdav_config.py
```

Test-Lauf:

```bash
./.venv/bin/python main.py
```

---

## 3. systemd-Service + Timer installieren

Die mitgelieferten Unit-Dateien liegen in `deploy/`. Vor dem Kopieren
den Nutzernamen im Service anpassen:

```bash
sed -i "s/REPLACE_USER/$USER/" deploy/segelboot-scraper.service
```

Falls dein Projekt **nicht** unter `/opt/segelboot-scraper` liegt,
zusätzlich `WorkingDirectory` und `ExecStart` in
`deploy/segelboot-scraper.service` anpassen.

Units nach `/etc/systemd/system/` kopieren und aktivieren:

```bash
sudo cp deploy/segelboot-scraper.service /etc/systemd/system/
sudo cp deploy/segelboot-scraper.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now segelboot-scraper.timer
```

Ab jetzt läuft der Scraper automatisch im Hintergrund — standardmäßig
um **07:00** und **19:00** Uhr (Serverzeit).

---

## 4. Uhrzeiten ändern

In `/etc/systemd/system/segelboot-scraper.timer` die Zeilen
`OnCalendar=` anpassen, z. B.:

```
OnCalendar=*-*-* 06:30:00
OnCalendar=*-*-* 18:45:00
```

Format: `OnCalendar=*-*-* HH:MM:SS` (Serverzeit). Mehrere Zeiten =
mehrere `OnCalendar=`-Zeilen. `Persistent=true` sorgt dafür, dass ein
verpasster Lauf nach dem Booten nachgeholt wird.

Nach Änderungen neu laden:

```bash
sudo systemctl daemon-reload
sudo systemctl restart segelboot-scraper.timer
```

Zeitzone des Servers prüfen/setzen:

```bash
timedatectl
sudo timedatectl set-timezone Europe/Berlin
```

---

## 5. Überwachung

Status des Timers + nächste geplante Läufe:

```bash
systemctl status segelboot-scraper.timer
systemctl list-timers segelboot-scraper.timer
```

Aktuellen/letzten Lauf ansehen:

```bash
systemctl status segelboot-scraper.service
journalctl -u segelboot-scraper.service -n 200 --no-pager
journalctl -u segelboot-scraper.service -f      # live
```

Manuell anstoßen (ohne auf die Uhrzeit zu warten):

```bash
sudo systemctl start segelboot-scraper.service
```

Deaktivieren:

```bash
sudo systemctl disable --now segelboot-scraper.timer
```

---

## 6. Updates einspielen

```bash
cd /opt/segelboot-scraper
git pull
./.venv/bin/pip install -r requirements.txt
```

Keine weiteren Schritte nötig — beim nächsten Timer-Lauf ist der neue
Code aktiv.

---

## Deinstallation

Mitgeliefertes Skript entfernt systemd-Units, venv und (optional) alle
lokalen Daten. Es fragt vor jedem destruktiven Schritt nach.

```bash
cd /opt/segelboot-scraper
sudo bash deploy/uninstall_ubuntu.sh
```

Das Skript führt folgende Schritte aus:

1. Stoppt und deaktiviert `segelboot-scraper.timer` + `.service`
2. Entfernt die Unit-Dateien aus `/etc/systemd/system/` und lädt systemd neu
3. Optional: löscht die Journal-Logs des Services
4. Optional: löscht das virtuelle Environment `.venv/`
5. Optional: löscht `data/` und `images/` (lokale Scrape-Ergebnisse)
6. Optional: löscht `webdav_config.py` (Zugangsdaten)
7. Optional: löscht das gesamte Projekt-Verzeichnis

Alle löschenden Schritte haben **NEIN als Default** — einfach Enter
drücken, um sie zu überspringen.

### Manuelle Deinstallation (falls gewünscht)

```bash
sudo systemctl disable --now segelboot-scraper.timer
sudo systemctl disable --now segelboot-scraper.service
sudo rm /etc/systemd/system/segelboot-scraper.{service,timer}
sudo systemctl daemon-reload
sudo rm -rf /opt/segelboot-scraper
```

---

## Alternative: cron statt systemd

Falls systemd nicht gewünscht ist, einen Eintrag in die User-Crontab
(`crontab -e`) hinzufügen:

```
0 7,19 * * * cd /opt/segelboot-scraper && ./.venv/bin/python main.py >> /var/log/segelboot-scraper.log 2>&1
```

systemd-Timer werden hier trotzdem empfohlen: saubere Logs via
`journalctl`, `Persistent=true` für verpasste Läufe, einfache
Status-Abfrage.
