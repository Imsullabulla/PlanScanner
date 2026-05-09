"""
Henter trafikdata for nærmeste veje via Overpass API (OSM-vejklassificering).
Returnerer vejnavn, vejtype og estimeret ÅDT (Års Døgn Trafik).

Note: Vejdirektoratets officielle trafiktælledata (eksakte ÅDT-tal)
kræver adgang til Vejman.dk. OSM-estimater er dækkende til første screening.
"""
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Estimerede ÅDT-intervaller baseret på dansk vejklassificering
# Kilde: Vejdirektoratets statistik for statsveje og kommuneveje
ADT_ESTIMATES = {
    "motorway":      (25000, 80000,  "Motorvej"),
    "motorway_link": (8000,  25000,  "Motorvejsrampe"),
    "trunk":         (8000,  30000,  "Primærrute"),
    "trunk_link":    (4000,  12000,  "Primærrute tilkørsel"),
    "primary":       (4000,  20000,  "Primær vej"),
    "primary_link":  (2000,  8000,   "Primær vej tilkørsel"),
    "secondary":     (1500,  8000,   "Sekundær vej"),
    "secondary_link":(800,   3000,   "Sekundær vej tilkørsel"),
    "tertiary":      (400,   3000,   "Lokal gennemfartsvej"),
    "tertiary_link": (200,   1200,   "Lokal vej tilkørsel"),
    "residential":   (80,    1000,   "Boligvej"),
    "unclassified":  (80,    800,    "Uklassificeret vej"),
    "living_street": (30,    300,    "Stillevej / gågade"),
    "service":       (30,    500,    "Servicevej"),
}

ROAD_PRIORITY = [
    "motorway", "trunk", "primary", "secondary",
    "tertiary", "residential", "unclassified",
    "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
    "living_street", "service",
]


def get_nearest_roads(lat: float, lon: float, radius_m: int = 500) -> list[dict]:
    """
    Finder de vigtigste veje inden for radius og estimerer ÅDT.
    Returnerer op til 3 veje sorteret efter vejbetydning.
    """
    query = f"""
    [out:json][timeout:15];
    way(around:{radius_m},{lat},{lon})
      [highway~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|unclassified|living_street|service)$"];
    out tags;
    """
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception:
        return []

    roads = []
    seen_names: set[str] = set()

    for el in elements:
        tags = el.get("tags", {})
        highway = tags.get("highway", "")
        if highway not in ADT_ESTIMATES:
            continue

        name = tags.get("name") or tags.get("ref") or ""
        display_name = name if name else f"Unavngivet {ADT_ESTIMATES[highway][2].lower()}"

        if display_name in seen_names:
            continue
        seen_names.add(display_name)

        adt_low, adt_high, road_type_dk = ADT_ESTIMATES[highway]
        adt_mid = (adt_low + adt_high) // 2

        roads.append({
            "vejnavn":      display_name,
            "vejtype":      road_type_dk,
            "osm_type":     highway,
            "adt_estimat":  adt_mid,
            "adt_interval": f"{adt_low:,}–{adt_high:,}".replace(",", "."),
            "kilde":        "Estimeret · OSM vejklassificering",
        })

    # Sortér efter vejbetydning
    roads.sort(
        key=lambda r: ROAD_PRIORITY.index(r["osm_type"])
        if r["osm_type"] in ROAD_PRIORITY else 99
    )

    return roads[:3]
