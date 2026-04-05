import logging

from bs4 import BeautifulSoup

from models import BoatListing
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class ScanboatScraper(BaseScraper):
    platform_name = "scanboat.com"

    BASE_URL = "https://www.scanboat.com"
    SEARCH_URL = (
        "https://www.scanboat.com/en/sailboats"
        "?priceto={max_price}&currency=EUR&page={page}"
    )

    def get_listing_urls(self, max_price: int) -> list[str]:
        urls: list[str] = []
        page = 1

        while True:
            search_url = self.SEARCH_URL.format(max_price=max_price, page=page)
            soup = self.fetch_page(search_url)
            if soup is None:
                break

            links = soup.select("a[href*='/en/boat/'], a[href*='/boat/']")
            new_urls = []
            for link in links:
                href = link.get("href", "")
                if href and "/boat/" in href:
                    full_url = href if href.startswith("http") else self.BASE_URL + href
                    if full_url not in urls and full_url not in new_urls:
                        new_urls.append(full_url)

            if not new_urls:
                break

            urls.extend(new_urls)
            logger.info("[scanboat] Seite %d: %d Inserate gefunden", page, len(new_urls))
            page += 1
            self.pause()

        return urls

    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        listing = BoatListing(url=url, plattform=self.platform_name)

        title_el = soup.select_one("h1")
        if title_el:
            listing.titel = title_el.get_text(strip=True)

        price_el = soup.select_one("[class*='price']")
        if price_el:
            price_text = price_el.get_text(strip=True)
            listing.preis = self.parse_float(price_text)
            if "DKK" in price_text:
                listing.waehrung = "DKK"
            elif "SEK" in price_text:
                listing.waehrung = "SEK"
            elif "NOK" in price_text:
                listing.waehrung = "NOK"
            elif "USD" in price_text:
                listing.waehrung = "USD"
            elif "GBP" in price_text:
                listing.waehrung = "GBP"

        desc_el = soup.select_one("[class*='description']")
        if desc_el:
            listing.beschreibung = desc_el.get_text(separator="\n", strip=True)

        location_el = soup.select_one("[class*='location']")
        if location_el:
            loc_text = location_el.get_text(strip=True)
            parts = [p.strip() for p in loc_text.split(",")]
            listing.ort = parts[0] if parts else loc_text
            if len(parts) > 1:
                listing.land = parts[-1]

        for row in soup.select("tr, [class*='detail'], [class*='spec']"):
            cells = row.find_all(["td", "th", "span"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                self._map_detail(listing, label, value)

        return listing

    def get_image_urls(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for img in soup.select("[class*='gallery'] img, [class*='slider'] img, img[data-src]"):
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and src not in urls:
                urls.append(src)
        return urls

    def _map_detail(self, listing: BoatListing, label: str, value: str) -> None:
        if any(k in label for k in ("manufacturer", "make", "builder", "brand")):
            listing.hersteller = value
        elif any(k in label for k in ("model", "type")):
            listing.modell = value
        elif any(k in label for k in ("condition", "status")):
            listing.zustand = value
        elif any(k in label for k in ("year", "built")):
            listing.baujahr = self.parse_int(value)
        elif any(k in label for k in ("length", "loa")):
            listing.laenge_m = self.parse_float(value)
        elif any(k in label for k in ("beam", "width")):
            listing.breite_m = self.parse_float(value)
        elif any(k in label for k in ("draft", "draught")):
            listing.tiefgang_m = self.parse_float(value)
        elif any(k in label for k in ("weight", "displacement")):
            listing.gewicht_kg = self.parse_float(value)
        elif any(k in label for k in ("hull material", "material")):
            listing.material = value
        elif any(k in label for k in ("engine", "propulsion")):
            listing.motorisierung = value
        elif any(k in label for k in ("power", "hp", "horsepower", "kw")):
            listing.motorleistung_ps = self.parse_float(value)
        elif any(k in label for k in ("engine hours", "hours")):
            listing.motorstunden = self.parse_int(value)
        elif any(k in label for k in ("cabin",)):
            listing.anzahl_kabinen = self.parse_int(value)
        elif any(k in label for k in ("berth", "sleeping")):
            listing.anzahl_kojen = self.parse_int(value)
