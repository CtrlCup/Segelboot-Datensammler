import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH
from models import BoatListing


def _ensure_db_dir() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_db_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS boote (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT    NOT NULL UNIQUE,
            plattform       TEXT    NOT NULL,
            titel           TEXT,
            hersteller      TEXT,
            modell          TEXT,
            preis           REAL,
            waehrung        TEXT    DEFAULT 'EUR',
            ort             TEXT,
            land            TEXT,
            zustand         TEXT,
            baujahr         INTEGER,
            laenge_m        REAL,
            breite_m        REAL,
            tiefgang_m      REAL,
            gewicht_kg      REAL,
            material        TEXT,
            motorisierung   TEXT,
            motorleistung_ps REAL,
            motorstunden    INTEGER,
            anzahl_kabinen  INTEGER,
            anzahl_kojen    INTEGER,
            beschreibung    TEXT,
            bilder_ordner   TEXT,
            erstellt_am     TEXT    NOT NULL,
            inserat_datum   TEXT,
            zuletzt_gesehen TEXT,
            dedupe_hash     TEXT    NOT NULL UNIQUE
        )
    """)
    # Migration: Spalte hinzufügen falls DB bereits existiert
    _migrate_add_column(conn, "zuletzt_gesehen", "TEXT")
    conn.commit()
    conn.close()


def _migrate_add_column(conn: sqlite3.Connection, column: str, col_type: str) -> None:
    """Add a column to boote if it doesn't exist yet (for existing databases)."""
    cursor = conn.execute("PRAGMA table_info(boote)")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE boote ADD COLUMN {column} {col_type}")



def compute_dedupe_hash(url: str, titel: str, preis: float | None) -> str:
    raw = f"{url}|{titel}|{preis}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def boat_exists(conn: sqlite3.Connection, dedupe_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM boote WHERE dedupe_hash = ?", (dedupe_hash,)
    ).fetchone()
    return row is not None


def update_zuletzt_gesehen(conn: sqlite3.Connection, dedupe_hash: str) -> None:
    """Update the 'zuletzt_gesehen' timestamp for a known duplicate."""
    jetzt = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE boote SET zuletzt_gesehen = ? WHERE dedupe_hash = ?",
        (jetzt, dedupe_hash),
    )
    conn.commit()


def insert_boat(conn: sqlite3.Connection, listing: BoatListing, bilder_ordner: str) -> int:
    dedupe_hash = compute_dedupe_hash(listing.url, listing.titel, listing.preis)
    erstellt_am = datetime.now(timezone.utc).isoformat()

    cursor = conn.execute(
        """
        INSERT INTO boote (
            url, plattform, titel, hersteller, modell, preis, waehrung,
            ort, land, zustand, baujahr, laenge_m, breite_m, tiefgang_m,
            gewicht_kg, material, motorisierung, motorleistung_ps,
            motorstunden, anzahl_kabinen, anzahl_kojen, beschreibung,
            bilder_ordner, erstellt_am, inserat_datum, dedupe_hash
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        """,
        (
            listing.url, listing.plattform, listing.titel, listing.hersteller,
            listing.modell, listing.preis, listing.waehrung,
            listing.ort, listing.land, listing.zustand, listing.baujahr,
            listing.laenge_m, listing.breite_m, listing.tiefgang_m,
            listing.gewicht_kg, listing.material, listing.motorisierung,
            listing.motorleistung_ps, listing.motorstunden,
            listing.anzahl_kabinen, listing.anzahl_kojen, listing.beschreibung,
            bilder_ordner, erstellt_am, listing.inserat_datum, dedupe_hash,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def get_boat_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) FROM boote").fetchone()
    return row[0]
