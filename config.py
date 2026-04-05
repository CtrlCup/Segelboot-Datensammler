from pathlib import Path

# Projektverzeichnis
BASE_DIR = Path(__file__).parent

# Datenbank
DB_PATH = BASE_DIR / "data" / "segelboote.db"

# Bilder
IMAGES_DIR = BASE_DIR / "images"

# Scraping-Einstellungen
MIN_PREIS_EUR = 5_000
MAX_PREIS_EUR = 100_000
PAUSE_MIN_SEKUNDEN = 1.0
PAUSE_MAX_SEKUNDEN = 2.0

# HTTP-Header
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30  # Sekunden

# Aktive Scraper — hier Plattformen ein-/ausschalten
ACTIVE_SCRAPERS = [
    "boat24",
    "boatshop24",
    # "bootsboerse",  # Seite offline (SSL/Connection refused)
    "yachtworld",
    # "scanboat",
]
