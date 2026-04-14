import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from config import BASE_DIR, MIN_PREIS_EUR
from models import BoatListing
from scraper.base import BaseScraper

logger = logging.getLogger(__name__)

DEBUG_DIR = BASE_DIR / "debug"


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


class Boatshop24Scraper(BaseScraper):
    """Scraper for boatshop24.com using nodriver (Chrome CDP) to bypass Cloudflare."""

    platform_name = "boatshop24.com"

    BASE_URL = "https://www.boatshop24.com"
    # Query-parameter price filter
    SEARCH_URL = (
        "https://www.boatshop24.com/boats-for-sale/"
        "class-sailing-boats/?currency=EUR&price={min_price}-{max_price}&page={page}"
    )
    MAX_PAGES = 200

    def __init__(self) -> None:
        super().__init__()
        self._browser = None
        self._page = None
        self._search_meta: dict[str, dict] = {}
        self._maintenance = False

    # ── Browser management ──────────────────────────────────────────

    async def _ensure_browser(self):
        if self._browser is None:
            import nodriver as nd
            self._browser = await nd.start(headless=False)
        return self._browser

    async def _navigate(self, url: str, wait_selector: str = "") -> str:
        """Navigate in the same tab (preserves Cloudflare session cookies)."""
        if self._maintenance:
            raise RuntimeError("boatshop24 maintenance mode")

        browser = await self._ensure_browser()

        if self._page is None:
            self._page = await browser.get(url)
        else:
            await self._page.get(url)

        # Quick check: BoatsGroup maintenance page (static HTML, HTTP 200)
        await asyncio.sleep(2)
        try:
            title = await self._page.evaluate("document.title || ''")
            if isinstance(title, str) and title.strip().lower() == "maintenance":
                self._maintenance = True
                logger.warning("[boatshop24] Wartungsseite erkannt — breche ab")
                raise RuntimeError("boatshop24 maintenance mode")
        except RuntimeError:
            raise
        except Exception:
            pass

        # Wait for Cloudflare challenge to resolve — check both title and body content
        for _ in range(20):
            await asyncio.sleep(3)
            try:
                ready = await self._page.evaluate("""
                    (() => {
                        const t = document.title || '';
                        const body = document.body ? document.body.innerText.length : 0;
                        const cf = document.querySelector(
                            '#challenge-running, #challenge-stage, .cf-browser-verification, '
                            + 'iframe[src*="challenges.cloudflare"], iframe[title*="challenge"], '
                            + '#cf-challenge-running, [data-translate="checking_browser"]'
                        );
                        if (cf) return false;
                        const tl = t.toLowerCase();
                        if (tl.includes('moment') || tl.includes('checking')
                            || tl.includes('attention required') || tl.includes('verify')) return false;
                        return body > 100;
                    })()
                """)
                if ready is True:
                    break
            except Exception:
                pass
        else:
            logger.warning("[boatshop24] Cloudflare-Challenge nicht gelöst für %s", url)
            await self._dump_debug(url, "cf_unresolved")
            return await self._page.evaluate("document.documentElement.outerHTML")

        # Accept cookie consent if present
        try:
            await self._page.evaluate("""
                (() => {
                    const btns = document.querySelectorAll('button');
                    for (const btn of btns) {
                        const text = btn.innerText.toLowerCase();
                        if (text.includes('alle akzeptieren') || text.includes('accept all')
                            || text.includes('accept') || text.includes('akzeptieren')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                })()
            """)
            await asyncio.sleep(2)
        except Exception:
            pass

        # Wait for content to render
        if wait_selector:
            for _ in range(10):
                await asyncio.sleep(2)
                try:
                    found = await self._page.evaluate(
                        f"document.querySelectorAll('{wait_selector}').length"
                    )
                    if isinstance(found, (int, float)) and found > 0:
                        break
                except Exception:
                    pass
        else:
            await asyncio.sleep(5)

        return await self._page.evaluate("document.documentElement.outerHTML")

    def _long_pause(self) -> None:
        delay = random.uniform(4.0, 7.0)
        time.sleep(delay)

    async def _dump_debug(self, url: str, tag: str) -> None:
        """Save HTML + screenshot for offline inspection of Cloudflare failures."""
        try:
            out_dir = DEBUG_DIR / "boatshop24"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = re.sub(r"[^a-zA-Z0-9]+", "_", urlparse(url).path)[:80].strip("_") or "root"
            base = out_dir / f"{ts}_{tag}_{slug}"
            html = await self._page.evaluate("document.documentElement.outerHTML")
            Path(str(base) + ".html").write_text(html or "", encoding="utf-8")
            try:
                await self._page.save_screenshot(str(base) + ".png")
            except Exception as e:
                logger.debug("[boatshop24] Screenshot fehlgeschlagen: %s", e)
            logger.info("[boatshop24] Debug-Dump: %s.{html,png}", base)
        except Exception as e:
            logger.debug("[boatshop24] Debug-Dump fehlgeschlagen: %s", e)

    # ── BaseScraper overrides ───────────────────────────────────────

    def fetch_page(self, url: str) -> BeautifulSoup | None:
        """Load a page via headless Chrome (nodriver)."""
        if self._maintenance:
            return None
        try:
            html = _run_async(self._navigate(
                url, wait_selector='h1, script[type="application/ld+json"]'
            ))
            soup = BeautifulSoup(html, "html.parser")
            title = soup.select_one("title")
            if title and "moment" in (title.get_text(strip=True) or "").lower():
                logger.warning("[boatshop24] Cloudflare blockiert %s", url)
                return None
            return soup
        except Exception as e:
            logger.warning("[boatshop24] Fehler beim Laden von %s: %s", url, e)
            return None

    def get_listing_urls(self, max_price: int) -> list[str]:
        # Warm up: visit homepage to establish Cloudflare session
        logger.info("[boatshop24] Warmup: Lade Homepage...")
        try:
            _run_async(self._navigate(self.BASE_URL + "/", wait_selector="nav"))
            logger.info("[boatshop24] Homepage geladen, starte Suche")
            self._long_pause()
        except Exception as e:
            logger.warning("[boatshop24] Homepage-Warmup fehlgeschlagen: %s", e)

        urls: list[str] = []
        page = 1

        while page <= self.MAX_PAGES:
            search_url = self.SEARCH_URL.format(
                min_price=MIN_PREIS_EUR, max_price=max_price, page=page,
            )
            logger.info("[boatshop24] Lade Suchseite %d...", page)

            try:
                html = _run_async(self._navigate(
                    search_url, wait_selector="a.grid-listing-link, a[href*='/boat/'], a[href*='/yacht/']"
                ))
            except Exception as e:
                logger.warning("[boatshop24] Fehler Suchseite %d: %s", page, e)
                break

            new_urls = self._extract_listings(html)

            if not new_urls:
                logger.info("[boatshop24] Seite %d: Keine Inserate, stoppe", page)
                break

            fresh = [u for u in new_urls if u not in urls]
            if not fresh:
                logger.info("[boatshop24] Seite %d: Keine neuen Inserate, stoppe", page)
                break

            urls.extend(fresh)
            logger.info("[boatshop24] Seite %d: %d Inserate gefunden", page, len(fresh))
            page += 1
            self._long_pause()

        logger.info("[boatshop24] Insgesamt %d Inserate gesammelt", len(urls))
        return urls

    def _extract_listings(self, html: str) -> list[str]:
        """Extract listing URLs and cache metadata from a search results page."""
        soup = BeautifulSoup(html, "html.parser")
        urls = []

        # BoatsGroup sites use grid-listing-link with data-ssr-meta
        cards = soup.select("a.grid-listing-link, a[href*='/boat/'], a[href*='/yacht/']")
        logger.info("[boatshop24] %d Listing-Cards auf der Seite", len(cards))

        seen = set()
        for card in cards:
            href = card.get("href", "")
            if not href or ("/boat/" not in href and "/yacht/" not in href):
                continue

            full_url = href if href.startswith("http") else self.BASE_URL + href
            if full_url in seen:
                continue
            seen.add(full_url)

            # Cache metadata from data-ssr-meta if available
            ssr_meta = card.get("data-ssr-meta", "")
            if ssr_meta:
                parts = ssr_meta.split("|")
                if len(parts) >= 5:
                    self._search_meta[full_url] = {
                        "hersteller": parts[0],
                        "typ": parts[1],
                        "laenge_ft": parts[2],
                        "ort_code": parts[3],
                        "preis": parts[4],
                    }

            urls.append(full_url)

        return urls

    def parse_listing(self, url: str, soup: BeautifulSoup) -> BoatListing:
        listing = BoatListing(url=url, plattform=self.platform_name)

        # Pre-populate from cached search metadata
        meta = self._search_meta.get(url, {})
        if meta:
            listing.hersteller = meta.get("hersteller", "")
            length_ft = self.parse_float(meta.get("laenge_ft", ""))
            if length_ft:
                listing.laenge_m = round(length_ft * 0.3048, 2)
            listing.preis = self.parse_float(meta.get("preis", ""))

        # Enrich from JSON-LD structured data
        self._parse_json_ld(listing, soup)

        # Title
        if not listing.titel:
            title_el = soup.select_one("h1")
            if title_el:
                listing.titel = title_el.get_text(strip=True)
                listing.titel = re.sub(r"\s*\|\s*\d+\s*ft\s*$", "", listing.titel).strip()

        # Price fallback from page content
        if listing.preis is None:
            price_el = soup.select_one(
                "[data-e2e='listingPrice'], [class*='price'] p, [class*='Price'], [class*='price']"
            )
            if price_el:
                price_text = price_el.get_text(strip=True)
                listing.preis = self.parse_float(price_text)
                self._detect_currency(listing, price_text)

        # Location
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

        # Description
        if not listing.beschreibung:
            desc_el = soup.select_one(
                "[class*='html-inner-wrapper'], [class*='description'], [class*='Description']"
            )
            if desc_el:
                listing.beschreibung = desc_el.get_text(separator="\n", strip=True)

        # Specs from key-value pairs in the page
        self._parse_detail_specs(listing, soup)

        # Specs from free text as fallback
        self._parse_specs_from_text(listing, soup)

        # Extract year from title
        if listing.baujahr is None and listing.titel:
            year_match = re.match(r"(\d{4})\s", listing.titel)
            if year_match:
                listing.baujahr = int(year_match.group(1))

        # Extract make/model from title
        if listing.titel and (not listing.hersteller or not listing.modell):
            self._parse_title(listing)

        # Generate title from URL as last resort
        if not listing.titel:
            slug = url.rstrip("/").split("/")[-1]
            slug_parts = slug.rsplit("-", 1)[0]
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

    def _parse_detail_specs(self, listing: BoatListing, soup: BeautifulSoup) -> None:
        """Parse structured key-value spec rows from the detail page."""
        for cell in soup.select(
            "[class*='detail'] [class*='cell-content'], "
            "[class*='spec'] li, [class*='Spec'] li, "
            "[class*='boat-spec'] li, tr"
        ):
            val_el = cell.select_one("[class*='cell-content-value'], [class*='value'], [class*='Value']")
            if val_el:
                full_text = cell.get_text(strip=True)
                value = val_el.get_text(strip=True)
                label = full_text.replace(value, "").strip().rstrip(":").lower()
                if label and value:
                    self._map_detail(listing, label, value)
                continue

            cells = cell.find_all(["td", "th", "span", "div"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                value = cells[1].get_text(strip=True)
                self._map_detail(listing, label, value)

    def _parse_specs_from_text(self, listing: BoatListing, soup: BeautifulSoup) -> None:
        """Fallback: extract specs from free text using regex."""
        text = soup.get_text(separator="\n")

        if listing.laenge_m is None:
            match = re.search(
                r"(?:Length|LOA|Length Overall|Länge)[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.laenge_m = round(val * 0.3048, 2) if is_feet else val

        if listing.breite_m is None:
            match = re.search(
                r"(?:Beam|Breite)[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.breite_m = round(val * 0.3048, 2) if is_feet else val

        if listing.tiefgang_m is None:
            match = re.search(
                r"(?:Draft|Draught|Max Draft|Tiefgang)[:\s]*([\d.,]+)\s*(?:m\b|meter|ft|feet|')",
                text, re.IGNORECASE,
            )
            if match:
                val = self.parse_float(match.group(1))
                if val:
                    is_feet = bool(re.search(r"ft|feet|'", match.group(0), re.IGNORECASE))
                    listing.tiefgang_m = round(val * 0.3048, 2) if is_feet else val

        if not listing.material:
            match = re.search(r"(?:Hull Material|Hull Type|Material)[:\s]*([A-Za-z/ -]+)", text, re.IGNORECASE)
            if match:
                listing.material = match.group(1).strip()

        if not listing.motorisierung:
            match = re.search(r"(?:Engine Make|Engine/Fuel|Motor)[:\s]*([^\n]{3,80})", text, re.IGNORECASE)
            if match:
                listing.motorisierung = match.group(1).strip()

        if listing.motorstunden is None:
            match = re.search(r"(?:Engine Hours|Motorstunden)[:\s]*([\d,]+)", text, re.IGNORECASE)
            if match:
                listing.motorstunden = self.parse_int(match.group(1))

        if listing.anzahl_kabinen is None:
            match = re.search(r"(?:Cabins|Staterooms|Kabinen)[:\s]*(\d+)", text, re.IGNORECASE)
            if match:
                listing.anzahl_kabinen = self.parse_int(match.group(1))

        if listing.anzahl_kojen is None:
            match = re.search(r"(?:Berths|Sleeps|Kojen)[:\s]*(\d+)", text, re.IGNORECASE)
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
        blocked = ("servedbyadbutler", "servedby.boatsgroup", "adserve", "tracking", "pixel")

        # JSON-LD images
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

        # Gallery and CDN images
        for img in soup.select(
            "img[src*='images.boatsgroup.com'], "
            "img[src*='boatshop24'], "
            "[class*='gallery'] img, "
            "[class*='Gallery'] img, "
            "[class*='carousel'] img, "
            "[class*='Carousel'] img"
        ):
            src = img.get("data-src") or img.get("src") or ""
            if src and src.startswith("http") and src not in urls:
                if not any(b in src for b in blocked):
                    # Request larger image variant if available
                    src = re.sub(r"_\w+\.", "_XLARGE.", src)
                    urls.append(src)

        # og:image as fallback
        og_img = soup.select_one("meta[property='og:image']")
        if og_img:
            src = og_img.get("content", "")
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
            if not listing.material:
                listing.material = value
        elif any(k in label for k in ("engine power", "leistung", "hp", "ps", "kw")):
            listing.motorleistung_ps = self.parse_float(value)
        elif any(k in label for k in ("engine hours", "motorstunden")):
            listing.motorstunden = self.parse_int(value)
        elif any(k in label for k in ("engine", "motor")):
            listing.motorisierung = value
        elif any(k in label for k in ("cabin", "kabine")):
            listing.anzahl_kabinen = self.parse_int(value)
        elif any(k in label for k in ("berth", "koje", "sleeping")):
            listing.anzahl_kojen = self.parse_int(value)

    @staticmethod
    def _detect_currency(listing: BoatListing, text: str) -> None:
        if "USD" in text or "US$" in text or "$" in text:
            listing.waehrung = "USD"
        elif "GBP" in text or "£" in text:
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
