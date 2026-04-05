import logging
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import cloudscraper
import requests
from bs4 import BeautifulSoup

from config import (
    IMAGES_DIR,
    PAUSE_MAX_SEKUNDEN,
    PAUSE_MIN_SEKUNDEN,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from models import BoatListing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """Abstract base class for all platform scrapers."""

    platform_name: str = ""

    def __init__(self) -> None:
        # cloudscraper handles Cloudflare challenges automatically
        self.session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True},
        )
        self.session.headers.update({
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        # Cache for robots.txt parsers per domain
        self._robots_cache: dict[str, RobotFileParser | None] = {}

    # ── Abstract methods ─────────────────────────────────────────────

    @abstractmethod
    def get_listing_urls(self, max_price: int) -> list[str]:
        """Return a list of individual boat listing URLs, filtered by max price."""

    @abstractmethod
    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        """Parse a single listing page into a BoatListing object."""

    @abstractmethod
    def get_image_urls(self, soup: BeautifulSoup) -> list[str]:
        """Extract all image URLs from a listing page."""

    # ── robots.txt ───────────────────────────────────────────────────

    def _get_robots_parser(self, url: str) -> RobotFileParser | None:
        """Fetch and cache robots.txt for the given URL's domain."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain in self._robots_cache:
            return self._robots_cache[domain]

        robots_url = f"{domain}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        try:
            resp = self.session.get(robots_url, timeout=10)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
                self._robots_cache[domain] = rp
                logger.info("[%s] robots.txt geladen", self.platform_name)
                return rp
        except Exception as e:
            logger.debug("[%s] robots.txt nicht erreichbar: %s", self.platform_name, e)

        self._robots_cache[domain] = None
        return None

    def is_allowed_by_robots(self, url: str) -> bool:
        """Check whether our user-agent is allowed to fetch this URL."""
        rp = self._get_robots_parser(url)
        if rp is None:
            return True  # No robots.txt → assume allowed
        return rp.can_fetch("*", url)

    # ── Shared helpers ───────────────────────────────────────────────

    def fetch_page(self, url: str) -> BeautifulSoup | None:
        if not self.is_allowed_by_robots(url):
            logger.info("[%s] Blockiert durch robots.txt: %s", self.platform_name, url)
            return None

        try:
            resp = self.session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.SSLError:
            try:
                logger.debug("SSL-Fehler bei %s, versuche ohne Verifizierung…", url)
                resp = self.session.get(url, timeout=REQUEST_TIMEOUT, verify=False)
                resp.raise_for_status()
                return BeautifulSoup(resp.text, "html.parser")
            except requests.RequestException as e:
                logger.warning("Fehler beim Laden von %s: %s", url, e)
                return None
        except requests.RequestException as e:
            logger.warning("Fehler beim Laden von %s: %s", url, e)
            return None

    def download_images(self, image_urls: list[str], boat_id: int) -> str:
        """Download images into images/{boat_id}/ and return the relative folder path."""
        folder = IMAGES_DIR / str(boat_id)
        folder.mkdir(parents=True, exist_ok=True)

        for i, img_url in enumerate(image_urls, start=1):
            try:
                resp = self.session.get(img_url, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()

                ext = self._guess_extension(resp.headers.get("Content-Type", ""), img_url)
                filepath = folder / f"{i:03d}{ext}"
                filepath.write_bytes(resp.content)
            except requests.RequestException as e:
                logger.warning("Bild-Download fehlgeschlagen %s: %s", img_url, e)

        return str(folder.relative_to(IMAGES_DIR.parent))

    def pause(self) -> None:
        delay = random.uniform(PAUSE_MIN_SEKUNDEN, PAUSE_MAX_SEKUNDEN)
        time.sleep(delay)

    @staticmethod
    def _guess_extension(content_type: str, url: str) -> str:
        ct = content_type.lower()
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
        if "gif" in ct:
            return ".gif"

        # Fallback: check URL
        url_lower = url.lower().split("?")[0]
        for ext in (".png", ".webp", ".gif"):
            if url_lower.endswith(ext):
                return ext

        return ".jpg"

    @staticmethod
    def parse_float(text: str | None) -> float | None:
        if not text:
            return None
        import re
        cleaned = text.strip()
        # Remove currency codes and symbols
        for code in ("EUR", "CHF", "USD", "GBP", "DKK", "SEK", "NOK", "approx."):
            cleaned = cleaned.replace(code, "")
        for char in "€$£":
            cleaned = cleaned.replace(char, "")
        # Remove unit suffixes (kg, m, PS, hp, HP, kW)
        cleaned = re.sub(r'\s*(kg|kW|PS|hp|HP|kn)\b', '', cleaned)
        cleaned = cleaned.strip()

        # Handle thousand/decimal separators:
        # "59,000" or "59.000" (thousands) vs "8.50" (decimal)
        # If both exist: last one is decimal separator
        has_dot = '.' in cleaned
        has_comma = ',' in cleaned
        if has_dot and has_comma:
            # Last separator is decimal, earlier ones are thousands
            if cleaned.rfind(',') > cleaned.rfind('.'):
                # German format: 59.000,50
                cleaned = cleaned.replace('.', '').replace(',', '.')
            else:
                # English format: 59,000.50
                cleaned = cleaned.replace(',', '')
        elif has_comma:
            # "6,200" or "6,5" — check if thousands separator
            parts = cleaned.split(',')
            if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
                cleaned = cleaned.replace(',', '')  # thousands: 6,200 → 6200
            else:
                cleaned = cleaned.replace(',', '.')  # decimal: 6,5 → 6.5
        elif has_dot:
            # "6.200" or "8.50"
            parts = cleaned.split('.')
            if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
                cleaned = cleaned.replace('.', '')  # thousands: 6.200 → 6200
            # else: normal decimal, keep as is

        # Keep only digits, dots, minus
        cleaned = re.sub(r'[^\d.\-]', '', cleaned)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None

    @staticmethod
    def parse_int(text: str | None) -> int | None:
        if not text:
            return None
        cleaned = text.replace("\xa0", "").replace(" ", "").replace(",", "").replace(".", "").strip()
        try:
            return int(cleaned)
        except ValueError:
            return None
