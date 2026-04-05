import logging

from bs4 import BeautifulSoup

from models import BoatListing
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class BootsboerseScraper(BaseScraper):
    platform_name = "bootsboerse.de"

    BASE_URL = "https://www.bootsboerse.de"
    SEARCH_URL = (
        "https://www.bootsboerse.de/segelboote"
        "?preis_bis={max_price}&seite={page}"
    )

    def get_listing_urls(self, max_price: int) -> list[str]:
        urls: list[str] = []
        page = 1

        while True:
            search_url = self.SEARCH_URL.format(max_price=max_price, page=page)
            soup = self.fetch_page(search_url)
            if soup is None:
                break

            links = soup.select("a[href*='/segelboot/'], a[href*='/boot/']")
            new_urls = []
            for link in links:
                href = link.get("href", "")
                if href:
                    full_url = href if href.startswith("http") else self.BASE_URL + href
                    if full_url not in urls and full_url not in new_urls:
                        new_urls.append(full_url)

            if not new_urls:
                break

            urls.extend(new_urls)
            logger.info("[bootsboerse] Seite %d: %d Inserate gefunden", page, len(new_urls))
            page += 1
            self.pause()

        return urls

    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        listing = BoatListing(url=url, plattform=self.platform_name)

        title_el = soup.select_one("h1")
        if title_el:
            listing.titel = title_el.get_text(strip=True)

        price_el = soup.select_one("[class*='preis'], [class*='price']")
        if price_el:
            listing.preis = self.parse_float(price_el.get_text())

        desc_el = soup.select_one("[class*='beschreibung'], [class*='description']")
        if desc_el:
            listing.beschreibung = desc_el.get_text(separator="\n", strip=True)

        for row in soup.select("tr, [class*='detail'], [class*='merkmal']"):
            cells = row.find_all(["td", "th", "span", "div"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                self._map_detail(listing, label, value)

        return listing

    def get_image_urls(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for img in soup.select("[class*='gallery'] img, [class*='bild'] img, img[data-src]"):
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and src not in urls:
                urls.append(src)
        return urls

    def _map_detail(self, listing: BoatListing, label: str, value: str) -> None:
        if any(k in label for k in ("hersteller", "marke", "werft")):
            listing.hersteller = value
        elif any(k in label for k in ("modell", "typ")):
            listing.modell = value
        elif any(k in label for k in ("standort", "liegeplatz", "ort")):
            listing.ort = value
        elif "land" in label:
            listing.land = value
        elif "zustand" in label:
            listing.zustand = value
        elif any(k in label for k in ("baujahr", "year")):
            listing.baujahr = self.parse_int(value)
        elif any(k in label for k in ("länge", "length")):
            listing.laenge_m = self.parse_float(value)
        elif any(k in label for k in ("breite", "beam")):
            listing.breite_m = self.parse_float(value)
        elif any(k in label for k in ("tiefgang", "draft")):
            listing.tiefgang_m = self.parse_float(value)
        elif any(k in label for k in ("gewicht", "weight")):
            listing.gewicht_kg = self.parse_float(value)
        elif "material" in label:
            listing.material = value
        elif any(k in label for k in ("motor", "engine")):
            listing.motorisierung = value
        elif any(k in label for k in ("leistung", "ps", "power")):
            listing.motorleistung_ps = self.parse_float(value)
        elif any(k in label for k in ("motorstunden", "hours")):
            listing.motorstunden = self.parse_int(value)
        elif any(k in label for k in ("kabine", "cabin")):
            listing.anzahl_kabinen = self.parse_int(value)
        elif any(k in label for k in ("koje", "berth")):
            listing.anzahl_kojen = self.parse_int(value)
