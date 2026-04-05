# Segelboot-Datensammler

Scraper-Pipeline, die Segelboot-Inserate von mehreren internationalen Plattformen sammelt und in einer lokalen SQLite-Datenbank mit Bildern speichert. Zielgruppe: Boote bis 100.000 EUR zur Markt- und Preisanalyse.

## Unterstützte Plattformen

| Plattform | Modul | Status |
|-----------|-------|--------|
| [Boat24](https://www.boat24.com) | `scraper/boat24.py` | aktiv |
| [BoatShop24](https://www.boatshop24.com) | `scraper/boatshop24.py` | aktiv |
| [YachtWorld](https://www.yachtworld.com) | `scraper/yachtworld.py` | aktiv |
| [Bootsboerse](https://www.bootsboerse.de) | `scraper/bootsboerse.py` | pausiert (Seite offline) |
| [Scanboat](https://www.scanboat.com) | `scraper/scanboat.py` | pausiert |

## Installation

```bash
git clone https://github.com/<user>/segelboot-datensammler.git
cd segelboot-datensammler

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Nutzung

```bash
python main.py
```

Das Skript durchläuft alle aktiven Plattformen, sammelt Inserate im konfigurierten Preisbereich und speichert sie in `data/segelboote.db`. Bilder werden nach `images/{boot_id}/` heruntergeladen.

## Konfiguration

Alle Einstellungen befinden sich in `config.py`:

- `MIN_PREIS_EUR` / `MAX_PREIS_EUR` — Preisfilter (Standard: 5.000–100.000 EUR)
- `ACTIVE_SCRAPERS` — Liste der aktiven Plattformen
- `PAUSE_MIN_SEKUNDEN` / `PAUSE_MAX_SEKUNDEN` — Wartezeit zwischen Requests (1–2s)

## Projektstruktur

```
├── main.py              # Einstiegspunkt, orchestriert die Scraping-Pipeline
├── config.py            # Einstellungen (Scraper, Preise, Pausen, Pfade)
├── database.py          # SQLite-Schema, Insert/Deduplizierung
├── models.py            # BoatListing-Dataclass
├── requirements.txt     # Python-Abhängigkeiten
├── scraper/
│   ├── __init__.py      # SCRAPER_REGISTRY
│   ├── base.py          # BaseScraper-ABC mit HTTP, Bilddownload, Parsing
│   ├── boat24.py        # Boat24-Scraper
│   ├── boatshop24.py    # BoatShop24-Scraper
│   ├── bootsboerse.py   # Bootsboerse-Scraper
│   ├── scanboat.py      # Scanboat-Scraper
│   └── yachtworld.py    # YachtWorld-Scraper
├── data/                # SQLite-Datenbank (nicht im Repo)
└── images/              # Heruntergeladene Bilder (nicht im Repo)
```

## Deduplizierung

Inserate werden per SHA-256-Hash von `url|titel|preis` dedupliziert. Bereits bekannte Inserate werden beim erneuten Scrapen mit einem `zuletzt_gesehen`-Zeitstempel aktualisiert.

## Neuen Scraper hinzufuegen

1. Neue Datei `scraper/plattform.py` erstellen, die `BaseScraper` erbt
2. `get_listing_urls()`, `parse_listing()` und `get_image_urls()` implementieren
3. In `scraper/__init__.py` zum `SCRAPER_REGISTRY` hinzufuegen
4. Namen in `ACTIVE_SCRAPERS` in `config.py` eintragen

## Gesammelte Daten pro Inserat

Titel, Hersteller, Modell, Preis, Waehrung, Standort, Land, Zustand, Baujahr, Laenge, Breite, Tiefgang, Gewicht, Material, Motorisierung, Motorleistung, Motorstunden, Kabinen, Kojen, Beschreibung, Bilder.

## Lizenz

Dieses Projekt dient ausschliesslich der privaten Marktanalyse. Die Nutzung erfolgt auf eigene Verantwortung und unter Beachtung der jeweiligen Nutzungsbedingungen der gescrapten Plattformen.
