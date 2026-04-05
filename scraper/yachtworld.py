import asyncio
import json
import logging
import random
import re
import time

from bs4 import BeautifulSoup

from models import BoatListing
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class YachtworldScraper(BaseScraper):
    """Scraper for yachtworld.com using nodriver (Chrome CDP) to bypass Cloudflare."""

    platform_name = "yachtworld.com"

    BASE_URL = "https://www.yachtworld.com"
    SEARCH_URL = (
        "https://www.yachtworld.com/boats-for-sale/type/sail/"
        "?currency=EUR&price=EUR-0-{max_price}&page={page}"
    )

    def __init__(self) -> None:
        super().__init__()
        self._browser = None
        self._page = None
        # Pre-populated data from search results (URL → ssr-meta dict)
        self._search_meta: dict[str, dict] = {}

    # ── Browser management ──────────────────────────────────────────

    async def _ensure_browser(self):
        if self._browser is None:
            import nodriver as nd
            self._browser = await nd.start(headless=False)
        return self._browser

    async def _navigate(self, url: str, wait_selector: str = "") -> str:
        """Navigate in the same tab (preserves Cloudflare session cookies)."""
        browser = await self._ensure_browser()

        if self._page is None:
            self._page = await browser.get(url)
        else:
            await self._page.get(url)

        # Phase 1: Wait for Cloudflare challenge to resolve
        for _ in range(20):
            await asyncio.sleep(3)
            title = await self._page.evaluate("document.title")
            if title and "moment" not in title.lower() and "checking" not in title.lower():
                break
        else:
            logger.warning("[yachtworld] Cloudflare-Challenge nicht gelöst für %s", url)
            return await self._page.evaluate("document.documentElement.outerHTML")

        # Phase 2: Wait for content to render
        if wait_selector:
            for _ in range(10):
                await asyncio.sleep(2)
                found = await self._page.evaluate(
                    f"document.querySelectorAll('{wait_selector}').length"
                )
                if found and found > 0:
                    break
        else:
            await asyncio.sleep(5)

        return await self._page.evaluate("document.documentElement.outerHTML")

    def _long_pause(self) -> None:
        """Longer pause between navigations to avoid Cloudflare rate-limits."""
        delay = random.uniform(4.0, 7.0)
        time.sleep(delay)

    # ── BaseScraper overrides ───────────────────────────────────────

    def fetch_page(self, url: str) -> BeautifulSoup | None:
        """Load a page via headless Chrome (nodriver)."""
        try:
            html = _run_async(self._navigate(
                url, wait_selector='script[type="application/ld+json"]'
            ))
            soup = BeautifulSoup(html, "html.parser")
            # Verify we got past Cloudflare
            title = soup.select_one("title")
            if title and "moment" in (title.get_text(strip=True) or "").lower():
                logger.warning("[yachtworld] Cloudflare blockiert %s", url)
                return None
            return soup
        except Exception as e:
            logger.warning("[yachtworld] Fehler beim Laden von %s: %s", url, e)
            return None

    def get_listing_urls(self, max_price: int) -> list[str]:
        # Warm up: visit homepage first to establish Cloudflare session
        logger.info("[yachtworld] Warmup: Lade Homepage...")
        try:
            _run_async(self._navigate(self.BASE_URL + "/", wait_selector="nav"))
            logger.info("[yachtworld] Homepage geladen, starte Suche")
            self._long_pause()
        except Exception as e:
            logger.warning("[yachtworld] Homepage-Warmup fehlgeschlagen: %s", e)

        urls: list[str] = []
        page = 1
        max_pages = 10

        while page <= max_pages:
            search_url = self.SEARCH_URL.format(max_price=max_price, page=page)
            logger.info("[yachtworld] Lade Suchseite %d...", page)

            try:
                html = _run_async(self._navigate(
                    search_url, wait_selector="a.grid-listing-link"
                ))
            except Exception as e:
                logger.warning("[yachtworld] Fehler Suchseite %d: %s", page, e)
                break

            new_urls = self._extract_sail_listings(html)

            if not new_urls:
                logger.info("[yachtworld] Seite %d: Keine neuen Segelboote, stoppe", page)
                break

            fresh = [u for u in new_urls if u not in urls]
            if not fresh:
                break

            urls.extend(fresh)
            logger.info("[yachtworld] Seite %d: %d Segelboot-Inserate", page, len(fresh))
            page += 1
            self._long_pause()

        return urls

    def _extract_sail_listings(self, html: str) -> list[str]:
        """Extract sail boat listing URLs and cache metadata from search results."""
        soup = BeautifulSoup(html, "html.parser")
        urls = []

        all_links = soup.select("a.grid-listing-link")
        logger.info("[yachtworld] %d Listing-Cards auf der Seite gefunden", len(all_links))

        for link in all_links:
            href = link.get("href", "")
            ssr_meta = link.get("data-ssr-meta", "")

            if "sail-" not in ssr_meta.lower():
                continue

            if not href:
                continue

            full_url = href if href.startswith("http") else self.BASE_URL + href

            # Cache search-result metadata as fallback
            # Format: "Make|sail-type|length_ft|location_code|price"
            parts = ssr_meta.split("|")
            if len(parts) >= 5:
                self._search_meta[full_url] = {
                    "hersteller": parts[0],
                    "typ": parts[1],
                    "laenge_ft": parts[2],
                    "ort_code": parts[3],
                    "preis": parts[4],
                }

            if full_url not in urls:
                urls.append(full_url)

        return urls

    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        listing = BoatListing(url=url, plattform=self.platform_name)

        # Pre-populate from search-result metadata (always available)
        meta = self._search_meta.get(url, {})
        if meta:
            listing.hersteller = meta.get("hersteller", "")
            length_ft = self.parse_float(meta.get("laenge_ft", ""))
            if length_ft:
                listing.laenge_m = round(length_ft * 0.3048, 2)
            listing.preis = self.parse_float(meta.get("preis", ""))

        # Enrich from detail page
        self._parse_json_ld(listing, soup)

        if not listing.titel:
            title_el = soup.select_one("h1")
            if title_el:
                listing.titel = title_el.get_text(strip=True)
                # Remove dimension suffix like " | 37ft"
                listing.titel = re.sub(r"\s*\|\s*\d+\s*ft\s*$", "", listing.titel).strip()

        if listing.preis is None:
            price_el = soup.select_one("[class*='price'], [class*='Price']")
            if price_el:
                price_text = price_el.get_text(strip=True)
                listing.preis = self.parse_float(price_text)
                self._detect_currency(listing, price_text)

        if not listing.ort:
            location_el = soup.select_one(
                "[class*='location'], [class*='Location'], "
                "[class*='BoatLocation'], [class*='boat-location']"
            )
            if location_el:
                loc_text = location_el.get_text(strip=True)
                parts = [p.strip() for p in loc_text.split(",")]
                listing.ort = parts[0] if parts else loc_text
                if len(parts) > 1:
                    listing.land = parts[-1]

        if not listing.beschreibung:
            desc_el = soup.select_one("[class*='description'], [class*='Description']")
            if desc_el:
                listing.beschreibung = desc_el.get_text(separator="\n", strip=True)

        self._parse_specs_from_text(listing, soup)

        # Extract year from title
        if listing.baujahr is None and listing.titel:
            year_match = re.match(r"(\d{4})\s", listing.titel)
            if year_match:
                listing.baujahr = int(year_match.group(1))

        # Extract year from URL as last resort
        if listing.baujahr is None:
            url_year = re.search(r"/(\d{4})-", url)
            if url_year:
                listing.baujahr = int(url_year.group(1))

        # Extract make/model from title
        if listing.titel and (not listing.hersteller or not listing.modell):
            self._parse_title(listing)

        # Generate a title from URL if nothing else worked
        if not listing.titel:
            slug = url.rstrip("/").split("/")[-1]
            # "1986-tayana-37-10044362" → "1986 Tayana 37"
            slug_parts = slug.rsplit("-", 1)[0]  # Remove ID
            listing.titel = slug_parts.replace("-", " ").title()

        return listing

    # ── Parsing helpers ─────────────────────────────────────────────

    def _parse_json_ld(self, listing: BoatListing, soup: BeautifulSoup) -> None:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                if not isinstance(data, dict) or data.get("@type") != "Product":
                    continue

                if not listing.titel:
                    name = data.get("name", "")
                    listing.titel = re.sub(r"\s*\|\s*\d+.*$", "", name).strip()

                brand = data.get("brand", {})
                if isinstance(brand, dict) and not listing.hersteller:
                    listing.hersteller = brand.get("name", "")

                offers = data.get("offers", {})
                if isinstance(offers, dict):
                    price = self.parse_float(str(offers.get("price", "")))
                    if price is not None:
                        listing.preis = price
                    currency = offers.get("priceCurrency", "")
                    if currency:
                        listing.waehrung = currency

                weight = data.get("weight", {})
                if isinstance(weight, dict) and listing.gewicht_kg is None:
                    val = weight.get("value")
                    unit = weight.get("unitCode", "").lower()
                    if val is not None:
                        if "lb" in unit:
                            listing.gewicht_kg = round(float(val) * 0.453592)
                        elif "kg" in unit:
                            listing.gewicht_kg = self.parse_float(str(val))

                condition = data.get("itemCondition", "")
                if condition and not listing.zustand:
                    listing.zustand = (
                        condition
                        .replace("Condition", "")
                        .replace("https://schema.org/", "")
                    )

                if not listing.beschreibung:
                    listing.beschreibung = data.get("description", "")

            except (json.JSONDecodeError, AttributeError):
                pass

    def _parse_specs_from_text(self, listing: BoatListing, soup: BeautifulSoup) -> None:
        text = soup.get_text(separator="\n")

        if listing.laenge_m is None:
            match = re.search(
                r"(?:Length|LOA|Length Overall)[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.laenge_m = round(val * 0.3048, 2) if is_feet else val

        if listing.breite_m is None:
            match = re.search(
                r"Beam[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.breite_m = round(val * 0.3048, 2) if is_feet else val

        if listing.tiefgang_m is None:
            match = re.search(
                r"(?:Draft|Draught|Max Draft)[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.tiefgang_m = round(val * 0.3048, 2) if is_feet else val

        if not listing.material:
            match = re.search(r"(?:Hull Material|Hull Type)[:\s]*([A-Za-z/ -]+)", text, re.IGNORECASE)
            if match:
                listing.material = match.group(1).strip()

        if not listing.motorisierung:
            match = re.search(r"(?:Engine Make|Engine/Fuel)[:\s]*([^\n]{3,80})", text, re.IGNORECASE)
            if match:
                listing.motorisierung = match.group(1).strip()

        if listing.motorstunden is None:
            match = re.search(r"Engine Hours[:\s]*([\d,]+)", text, re.IGNORECASE)
            if match:
                listing.motorstunden = self.parse_int(match.group(1))

        if listing.anzahl_kabinen is None:
            match = re.search(r"(?:Cabins|Staterooms)[:\s]*(\d+)", text, re.IGNORECASE)
            if match:
                listing.anzahl_kabinen = self.parse_int(match.group(1))

        if listing.anzahl_kojen is None:
            match = re.search(r"(?:Berths|Sleeps)[:\s]*(\d+)", text, re.IGNORECASE)
            if match:
                listing.anzahl_kojen = self.parse_int(match.group(1))

    def _parse_title(self, listing: BoatListing) -> None:
        match = re.match(r"(\d{4})\s+(.+)", listing.titel)
        if not match:
            return
        rest = match.group(2).strip()
        parts = rest.split(None, 1)
        if parts and not listing.hersteller:
            listing.hersteller = parts[0]
        if len(parts) > 1 and not listing.modell:
            listing.modell = parts[1]

    def get_image_urls(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str] = []

        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, dict) and data.get("@type") == "Product":
                    img = data.get("image", "")
                    if isinstance(img, str) and img.startswith("http"):
                        urls.append(img)
                    elif isinstance(img, list):
                        for i in img:
                            if isinstance(i, str) and i.startswith("http"):
                                urls.append(i)
            except (json.JSONDecodeError, AttributeError):
                pass

        for img in soup.select("img[src*='boatsgroup.com'], img[src*='yachtworld']"):
            src = img.get("src", "")
            if src and src.startswith("http") and src not in urls:
                src = re.sub(r"_\w+\.", "_XLARGE.", src)
                urls.append(src)

        og_img = soup.select_one("meta[property='og:image']")
        if og_img:
            src = og_img.get("content", "")
            if src and src.startswith("http") and src not in urls:
                urls.append(src)

        return urls

    @staticmethod
    def _detect_currency(listing: BoatListing, text: str) -> None:
        if "USD" in text or "US$" in text or "$" in text:
            listing.waehrung = "USD"
        elif "GBP" in text or "\u00a3" in text:
            listing.waehrung = "GBP"
        elif "DKK" in text:
            listing.waehrung = "DKK"
        elif "SEK" in text:
            listing.waehrung = "SEK"
        elif "NOK" in text:
            listing.waehrung = "NOK"

    def __del__(self):
        if self._browser:
            try:
                self._browser.stop()
            except Exception:
                pass
