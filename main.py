#!/usr/bin/env python3
"""
Segelboot-Datensammler
======================
Scrapt Segelboot-Inserate von mehreren Plattformen und speichert sie
in einer lokalen SQLite-Datenbank inkl. Bilder.

Nutzung:
    python main.py
"""

import logging
import sqlite3
import sys

from config import ACTIVE_SCRAPERS, MAX_PREIS_EUR, MIN_PREIS_EUR
from database import boat_exists, compute_dedupe_hash, get_boat_count, get_connection, init_db, insert_boat, update_zuletzt_gesehen
from scraper import SCRAPER_REGISTRY
from scraper.base import BaseScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_scraper(scraper: BaseScraper, conn: sqlite3.Connection) -> dict[str, int]:
    """Run a single scraper and return stats."""
    stats = {"neu": 0, "übersprungen": 0, "fehler": 0}

    logger.info("━━━ Starte %s ━━━", scraper.platform_name)

    try:
        listing_urls = scraper.get_listing_urls(MAX_PREIS_EUR)
    except Exception as e:
        logger.error("[%s] Fehler beim Laden der Inserat-Liste: %s", scraper.platform_name, e)
        stats["fehler"] += 1
        return stats

    logger.info("[%s] %d Inserate gefunden", scraper.platform_name, len(listing_urls))

    total = len(listing_urls)
    for idx, url in enumerate(listing_urls, 1):
        try:
            # Fetch and check for duplicates early (by URL)
            soup = scraper.fetch_page(url)
            if soup is None:
                stats["fehler"] += 1
                scraper.pause()
                continue

            # Parse listing to get title and price for dedup hash
            listing = scraper.parse_listing(url, soup)

            # Filter: kein Preis, unter Minimum oder über Maximum → überspringen
            if listing.preis is None or listing.preis < MIN_PREIS_EUR or listing.preis > MAX_PREIS_EUR:
                logger.info(
                    "[%s] (%d/%d) Übersprungen (Preis: %s): %s",
                    scraper.platform_name, idx, total, listing.preis, listing.titel[:50],
                )
                stats["übersprungen"] += 1
                scraper.pause()
                continue

            dedupe_hash = compute_dedupe_hash(listing.url, listing.titel, listing.preis)

            if boat_exists(conn, dedupe_hash):
                update_zuletzt_gesehen(conn, dedupe_hash)
                logger.info(
                    "[%s] (%d/%d) Übersprungen (Duplikat): %s",
                    scraper.platform_name, idx, total, listing.titel[:50],
                )
                stats["übersprungen"] += 1
                scraper.pause()
                continue

            # Download images
            image_urls = scraper.get_image_urls(soup)
            listing.bild_urls = image_urls

            # Insert first to get the ID, then download images
            boat_id = insert_boat(conn, listing, "")

            # Download images into images/{boat_id}/
            bilder_ordner = ""
            if image_urls:
                bilder_ordner = scraper.download_images(image_urls, boat_id)
                conn.execute(
                    "UPDATE boote SET bilder_ordner = ? WHERE id = ?",
                    (bilder_ordner, boat_id),
                )
                conn.commit()

            logger.info(
                "[%s] (%d/%d) NEU: %s | %.0f %s | %d Bilder",
                scraper.platform_name,
                idx, total,
                listing.titel[:60],
                listing.preis or 0,
                listing.waehrung,
                len(image_urls),
            )
            stats["neu"] += 1

        except sqlite3.IntegrityError:
            # Duplicate detected at DB level
            stats["übersprungen"] += 1
        except Exception as e:
            logger.error("[%s] Fehler bei %s: %s", scraper.platform_name, url, e)
            stats["fehler"] += 1

        scraper.pause()

    return stats


def main() -> None:
    logger.info("=" * 60)
    logger.info("Segelboot-Datensammler gestartet")
    logger.info("Max. Preis: %d EUR", MAX_PREIS_EUR)
    logger.info("Aktive Scraper: %s", ", ".join(ACTIVE_SCRAPERS))
    logger.info("=" * 60)

    init_db()
    conn = get_connection()

    count_before = get_boat_count(conn)
    total_stats: dict[str, int] = {"neu": 0, "übersprungen": 0, "fehler": 0}

    for name in ACTIVE_SCRAPERS:
        scraper_cls = SCRAPER_REGISTRY.get(name)
        if scraper_cls is None:
            logger.warning("Unbekannter Scraper: %s — übersprungen", name)
            continue

        scraper = scraper_cls()
        stats = run_scraper(scraper, conn)

        for key in total_stats:
            total_stats[key] += stats[key]

    count_after = get_boat_count(conn)
    conn.close()

    # Summary
    logger.info("=" * 60)
    logger.info("ZUSAMMENFASSUNG")
    logger.info("  Neue Boote:        %d", total_stats["neu"])
    logger.info("  Übersprungen:      %d", total_stats["übersprungen"])
    logger.info("  Fehler:            %d", total_stats["fehler"])
    logger.info("  Boote in DB:       %d (vorher: %d)", count_after, count_before)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
