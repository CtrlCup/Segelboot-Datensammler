# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Segelboot-Datensammler: scrapes sailboat listings from multiple international platforms into a local SQLite database with images. Target: boats up to 100,000 EUR for market/price analysis.

## Environment

Python 3.12.7 virtual environment at `.venv/` (MSYS2 ucrt64 base).

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
python main.py
```

Scrapes all active platforms, deduplicates via SHA256(url+title+price), downloads images to `images/{boat_id}/`, stores data in `data/segelboote.db`.

## Architecture

- `main.py` — Entry point, orchestrates scraping pipeline
- `config.py` — All settings (active scrapers, max price, pause timing, paths)
- `database.py` — SQLite schema, insert/dedup logic
- `models.py` — `BoatListing` dataclass
- `scraper/base.py` — `BaseScraper` ABC with shared HTTP, image download, parsing helpers
- `scraper/{platform}.py` — One scraper per platform (boat24, boatshop24, bootsboerse, kleinanzeigen, willhaben, yachtworld, scanboat)
- `scraper/__init__.py` — `SCRAPER_REGISTRY` dict mapping name → class

## Adding a New Scraper

1. Create `scraper/newplatform.py` inheriting `BaseScraper`
2. Implement `get_listing_urls()`, `parse_listing()`, `get_image_urls()`
3. Add to `SCRAPER_REGISTRY` in `scraper/__init__.py`
4. Add name to `ACTIVE_SCRAPERS` in `config.py`

## Key Conventions

- Scraper selectors are best-effort CSS selectors that will need tuning when sites change their HTML
- Each scraper pauses 1–2s between requests to avoid overloading sites
- Deduplication hash: SHA256 of `url|titel|preis`
- All timestamps stored as ISO 8601 UTC
