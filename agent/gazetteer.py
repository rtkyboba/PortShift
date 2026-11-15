"""Known ports, airports and chokepoints, so events can only be placed somewhere we recognise.

The extractor (a small model) may name a place but must not be trusted with coordinates: the
monitor resolves the name here and drops events it cannot place. Coordinates are (lat, lon).
Matching is by lowercase whole-word alias; add places as the fleet grows.
"""
import re

PLACES: dict[str, tuple[float, float, list[str]]] = {
    "Port of Rotterdam": (51.95, 4.14, ["rotterdam", "maasvlakte"]),
    "Port of Antwerp": (51.27, 4.33, ["antwerp", "antwerpen", "antwerp-bruges"]),
    "Port of Hamburg": (53.54, 9.97, ["hamburg"]),
    "Port of Bremerhaven": (53.55, 8.58, ["bremerhaven", "bremen"]),
    "Port of Felixstowe": (51.96, 1.35, ["felixstowe"]),
    "Port of Dover": (51.12, 1.32, ["dover"]),
    "Calais": (50.97, 1.85, ["calais", "eurotunnel", "channel tunnel"]),
    "Dunkirk": (51.04, 2.38, ["dunkirk", "dunkerque"]),
    "Zeebrugge": (51.33, 3.2, ["zeebrugge"]),
    "Le Havre": (49.48, 0.11, ["le havre"]),
    "Duisburg": (51.43, 6.76, ["duisburg"]),
    "Frankfurt": (50.03, 8.57, ["frankfurt", "fraport"]),
    "Piraeus": (37.94, 23.64, ["piraeus"]),
    "Genoa": (44.4, 8.93, ["genoa", "genova"]),
    "Valencia": (39.45, -0.32, ["valencia"]),
    "Algeciras": (36.13, -5.43, ["algeciras", "strait of gibraltar", "gibraltar"]),
    "Suez Canal": (29.97, 32.55, ["suez", "suez canal"]),
    "Port Said": (31.26, 32.3, ["port said"]),
    "Red Sea": (20.0, 38.5, ["red sea", "bab el-mandeb", "bab-el-mandeb"]),
    "Jebel Ali": (25.0, 55.06, ["jebel ali", "dubai"]),
    "Colombo": (6.95, 79.85, ["colombo"]),
    "Singapore": (1.26, 103.82, ["singapore"]),
    "Strait of Malacca": (2.6, 101.3, ["malacca"]),
    "Shanghai": (31.23, 121.47, ["shanghai", "yangshan"]),
    "Ningbo": (29.87, 121.55, ["ningbo", "zhoushan"]),
    "Shenzhen": (22.5, 114.1, ["shenzhen", "yantian"]),
    "Hong Kong": (22.3, 114.17, ["hong kong"]),
    "Busan": (35.1, 129.04, ["busan"]),
    "Los Angeles / Long Beach": (33.75, -118.2, ["long beach", "los angeles"]),
    "Dallas": (32.78, -96.8, ["dallas"]),
    "Houston": (29.73, -95.27, ["houston"]),
    "Savannah": (32.08, -81.09, ["savannah"]),
    "New York / New Jersey": (40.68, -74.01, ["new york", "new jersey", "newark"]),
    "Santos": (-23.96, -46.33, ["santos"]),
    "Santiago": (-33.45, -70.67, ["santiago"]),
    "Sydney": (-33.87, 151.21, ["sydney", "botany"]),
    "Panama Canal": (9.08, -79.68, ["panama canal"]),
}


def resolve(name: str | None) -> tuple[str, float, float] | None:
    """(canonical name, lat, lon) for a place we know, else None."""
    if not name:
        return None
    text = name.lower()
    best = None
    for canonical, (lat, lon, aliases) in PLACES.items():
        for alias in aliases + [canonical.lower()]:
            if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", text):
                if best is None or len(alias) > best[0]:
                    best = (len(alias), canonical, lat, lon)
    return (best[1], best[2], best[3]) if best else None
