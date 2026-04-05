from scraper.boat24 import Boat24Scraper
from scraper.boatshop24 import Boatshop24Scraper
from scraper.bootsboerse import BootsboerseScraper
from scraper.yachtworld import YachtworldScraper
from scraper.scanboat import ScanboatScraper

SCRAPER_REGISTRY: dict[str, type] = {
    "boat24": Boat24Scraper,
    "boatshop24": Boatshop24Scraper,
    "bootsboerse": BootsboerseScraper,
    "yachtworld": YachtworldScraper,
    "scanboat": ScanboatScraper,
}
