import logging
import re

from bs4 import BeautifulSoup

from models import BoatListing
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


class Boat24Scraper(BaseScraper):
    platform_name = "boat24.com"

    BASE_URL = "https://www.boat24.com"
    SEARCH_URL = (
        "https://www.boat24.com/en/sailingboats/"
        "?prs=eur&prn=0&prx={max_price}&cur=EUR&page={page}"
    )

    def get_listing_urls(self, max_price: int) -> list[str]:
        urls: list[str] = []
        page = 1

        while True:
            search_url = self.SEARCH_URL.format(max_price=max_price, page=page)
            soup = self.fetch_page(search_url)
            if soup is None:
                break

            # Listing links inside blurb cards or title links
            links = soup.select("h3.blurb__title a, a.blurb__button, div.blurb a[href*='/detail/']")
            new_urls = []
            for link in links:
                href = link.get("href", "")
                if href and "/detail/" in href:
                    full_url = href if href.startswith("http") else self.BASE_URL + href
                    if full_url not in urls and full_url not in new_urls:
                        new_urls.append(full_url)

            if not new_urls:
                break

            urls.extend(new_urls)
            logger.info("[boat24] Seite %d: %d Inserate gefunden", page, len(new_urls))
            page += 1
            self.pause()

        return list(dict.fromkeys(urls))  # dedupe, preserve order

    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        listing = BoatListing(url=url, plattform=self.platform_name)

        # Title
        title_el = soup.select_one("h1")
        if title_el:
            listing.titel = title_el.get_text(strip=True)

        # Price — span.list__value--large contains e.g. "EUR 59,000"
        price_el = soup.select_one("span.list__value--large, [class*='price']")
        if price_el:
            price_text = price_el.get_text(strip=True)
            listing.preis = self.parse_float(price_text)
            if "USD" in price_text:
                listing.waehrung = "USD"
            elif "GBP" in price_text or "£" in price_text:
                listing.waehrung = "GBP"

        # Description
        desc_el = soup.select_one("[class*='description']")
        if desc_el:
            listing.beschreibung = desc_el.get_text(separator="\n", strip=True)

        # Specs — key-value list with span.list__key and span.list__value
        for li in soup.select("ul.list--key-value li, [class*='key-value'] li"):
            key_el = li.select_one("span.list__key, [class*='key']")
            val_el = li.select_one("span.list__value, [class*='value']")
            if key_el and val_el:
                label = key_el.get_text(strip=True).lower()
                value = val_el.get_text(strip=True)
                self._map_detail(listing, label, value)

        return listing

    def get_image_urls(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []
        for img in soup.select("img[data-srcset], img[src*='static.b24'], img[src*='boat']"):
            # Prefer data-srcset for full resolution
            srcset = img.get("data-srcset", "")
            if srcset:
                # Take the largest image from srcset
                src = srcset.split(",")[-1].strip().split(" ")[0]
            else:
                src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and src not in urls:
                urls.append(src)
        return urls

    def _map_detail(self, listing: BoatListing, label: str, value: str) -> None:
        if any(k in label for k in ("manufacturer", "hersteller", "make", "builder")):
            listing.hersteller = value
        elif any(k in label for k in ("model", "modell")) and "keel" not in label and "mast" not in label:
            listing.modell = value
        elif any(k in label for k in ("location", "standort", "liegeplatz", "ort")):
            listing.ort = value
        elif any(k in label for k in ("country", "land")):
            listing.land = value
        elif any(k in label for k in ("condition", "zustand")):
            listing.zustand = value
        elif any(k in label for k in ("year", "baujahr", "built")):
            listing.baujahr = self.parse_int(value)
        elif "length" in label and "beam" in label:
            # Combined "Length x Beam" field, e.g. "8.50 m x 2.45 m"
            parts = value.split("x")
            if len(parts) == 2:
                listing.laenge_m = self.parse_float(parts[0])
                listing.breite_m = self.parse_float(parts[1])
        elif any(k in label for k in ("length", "länge", "loa")) and "beam" not in label:
            listing.laenge_m = self.parse_float(value)
        elif any(k in label for k in ("beam", "breite", "width")):
            listing.breite_m = self.parse_float(value)
        elif any(k in label for k in ("draft", "tiefgang", "draught")):
            listing.tiefgang_m = self.parse_float(value)
        elif any(k in label for k in ("weight", "gewicht", "displacement")):
            listing.gewicht_kg = self.parse_float(value)
        elif "hull" in label and "material" in label:
            listing.material = value
        elif label == "material":
            # Only set if not already set by "hull material"
            if not listing.material:
                listing.material = value
        elif "mast" in label and "material" in label:
            pass  # Ignore mast material
        elif any(k in label for k in ("engine power", "leistung", "hp", "ps", "kw")):
            listing.motorleistung_ps = self.parse_float(value)
        elif any(k in label for k in ("engine hours", "motorstunden")):
            listing.motorstunden = self.parse_int(value)
        elif any(k in label for k in ("engine", "motor")):
            listing.motorisierung = value
        elif "propulsion" in label:
            pass  # Ignore propulsion type (shaft drive etc.)
        elif any(k in label for k in ("cabin", "kabine")):
            listing.anzahl_kabinen = self.parse_int(value)
        elif any(k in label for k in ("berth", "koje", "sleeping")):
            listing.anzahl_kojen = self.parse_int(value)
