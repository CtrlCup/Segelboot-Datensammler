from dataclasses import dataclass, field


@dataclass
class BoatListing:
    """Represents a single sailboat listing scraped from a platform."""

    url: str
    plattform: str
    titel: str = ""
    hersteller: str = ""
    modell: str = ""
    preis: float | None = None
    waehrung: str = "EUR"
    ort: str = ""
    land: str = ""
    zustand: str = ""
    baujahr: int | None = None
    laenge_m: float | None = None
    breite_m: float | None = None
    tiefgang_m: float | None = None
    gewicht_kg: float | None = None
    material: str = ""
    motorisierung: str = ""
    motorleistung_ps: float | None = None
    motorstunden: int | None = None
    anzahl_kabinen: int | None = None
    anzahl_kojen: int | None = None
    beschreibung: str = ""
    inserat_datum: str = ""
    bild_urls: list[str] = field(default_factory=list)
