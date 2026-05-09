"""
Enkelt Overpass-kald pr. plan der henter konkurrenter, veje og bebyggelse på én gang.
Erstatter tre separate kald og undgår rate limiting på overpass-api.de.
"""
import math
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

COMPETITOR_NAMES = ["NETTO", "REMA 1000", "REMA", "LIDL", "ALDI",
                    "FAKTA", "MENY", "COOP", "IRMA", "SPAR", "DAGLI'BRUGSEN"]

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
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "unclassified", "motorway_link", "trunk_link",
    "primary_link", "secondary_link", "tertiary_link", "living_street", "service",
]

BUILDING_DK = {
    "supermarket": "Dagligvarebutik", "convenience": "Nærbutik",
    "hypermarket": "Hypermarked",     "retail":      "Butik / detail",
    "commercial":  "Erhvervsbyggeri", "industrial":  "Industribyggeri",
    "warehouse":   "Lager / logistik","office":      "Kontor",
    "residential": "Boligbebyggelse", "house":       "Enfamilieshus",
    "detached":    "Fritliggende hus","apartments":  "Etageboliger",
    "hotel":       "Hotel",           "school":      "Skole",
    "hospital":    "Hospital / klinik","public":     "Offentlig bygning",
    "civic":       "Kommunal bygning","parking":     "Parkeringsanlæg",
    "garage":      "Garage / værksted","construction":"Under opførelse",
    "yes":         "Bygning",
}

LANDUSE_DK = {
    "commercial": "Erhvervsareal",  "industrial":  "Industriareal",
    "residential":"Boligområde",    "retail":      "Butiksareal",
    "farmland":   "Landbrugsareal", "grass":       "Grønt areal",
    "brownfield": "Tidligere erhverv (brownfield)",
    "greenfield": "Ubebygget greenfield",
    "construction":"Byggegrund",    "allotments":  "Kolonihaver",
}


def fetch_site_context(lat: float, lon: float,
                       competitor_radius_m: int = 2000,
                       road_radius_m: int = 500,
                       building_radius_m: int = 150) -> dict:
    """
    Ét Overpass-kald der returnerer konkurrenter, veje og bebyggelse.
    Returnerer dict med nøglerne: competitors, roads, land_use.
    """
    query = f"""
[out:json][timeout:30];
(
  node["shop"="supermarket"](around:{competitor_radius_m},{lat},{lon});
  node["shop"="convenience"](around:{competitor_radius_m},{lat},{lon});
  way(around:{road_radius_m},{lat},{lon})
    [highway~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|residential|unclassified|living_street|service)$"];
  way(around:{building_radius_m},{lat},{lon})[building];
  way(around:{building_radius_m},{lat},{lon})[landuse];
  node(around:{building_radius_m},{lat},{lon})[shop~"supermarket|convenience|department_store"];
  node(around:{building_radius_m},{lat},{lon})[amenity~"fuel|fast_food|restaurant|bank"];
);
out tags;
"""
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=35)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception as e:
        print(f"  [overpass] Fejl: {e}")
        return {
            "competitors": [],
            "roads": [],
            "land_use": _empty_land_use("Overpass-opslag fejlede"),
        }

    competitors = _parse_competitors(elements, lat, lon)
    roads       = _parse_roads(elements)
    land_use    = _parse_land_use(elements)

    return {"competitors": competitors, "roads": roads, "land_use": land_use}


# ── Parsere ───────────────────────────────────────────────────────────────────

def _parse_competitors(elements, lat, lon):
    result = []
    for el in elements:
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {})
        if tags.get("shop") not in ("supermarket", "convenience"):
            continue
        name = tags.get("name", "").upper()
        if not any(c in name for c in COMPETITOR_NAMES):
            continue
        el_lat, el_lon = el.get("lat", 0), el.get("lon", 0)
        result.append({
            "name": tags.get("name"),
            "lat": el_lat,
            "lon": el_lon,
            "distance_m": _haversine_m(lat, lon, el_lat, el_lon),
        })
    return sorted(result, key=lambda c: c["distance_m"])


def _parse_roads(elements):
    seen: set[str] = set()
    roads = []
    for el in elements:
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {})
        highway = tags.get("highway", "")
        if highway not in ADT_ESTIMATES:
            continue
        name = tags.get("name") or tags.get("ref") or ""
        display = name if name else f"Unavngivet {ADT_ESTIMATES[highway][2].lower()}"
        if display in seen:
            continue
        seen.add(display)
        lo, hi, dk = ADT_ESTIMATES[highway]
        roads.append({
            "vejnavn":      display,
            "vejtype":      dk,
            "osm_type":     highway,
            "adt_estimat":  (lo + hi) // 2,
            "adt_interval": f"{lo:,}–{hi:,}".replace(",", "."),
            "kilde":        "Estimeret · OSM vejklassificering",
        })
    roads.sort(key=lambda r: ROAD_PRIORITY.index(r["osm_type"])
               if r["osm_type"] in ROAD_PRIORITY else 99)
    return roads[:3]


def _parse_land_use(elements):
    buildings, landuse_set, pois = [], set(), []

    for el in elements:
        tags = el.get("tags", {})

        if "building" in tags:
            raw = tags.get("building", "yes")
            for key in ("shop", "amenity", "office", "leisure"):
                if key in tags:
                    raw = tags[key]
                    break
            name = tags.get("name", "")
            dk = BUILDING_DK.get(raw, raw.replace("_", " ").capitalize())
            buildings.append({"type_dk": dk, "raw": raw, "name": name})

        if "landuse" in tags:
            lu = tags["landuse"]
            landuse_set.add(LANDUSE_DK.get(lu, lu.replace("_", " ").capitalize()))

        if "building" not in tags:
            for key in ("shop", "amenity"):
                if key in tags and el.get("type") == "node":
                    pois.append(tags.get("name") or tags[key])

    if not buildings and not pois:
        lu_list = list(landuse_set)
        desc = f"Ubebygget — {', '.join(lu_list[:2])}" if lu_list else "Ubebygget grund"
        return _empty_land_use(desc)

    dominant = buildings[0]["type_dk"] if buildings else (pois[0] if pois else "Ukendt")
    type_list = list({b["type_dk"] for b in buildings})[:5]
    named = [b["name"] for b in buildings if b["name"]]

    parts = []
    if buildings:
        types = list({b["type_dk"] for b in buildings})
        if named:
            parts.append(f"{', '.join(named[:2])} ({', '.join(types[:2])})")
        else:
            n = len(buildings)
            parts.append(f"{n} bygning{'er' if n != 1 else ''}: {', '.join(types[:3])}")
    if pois:
        parts.append(f"Faciliteter: {', '.join(set(pois[:2]))}")

    return {
        "har_bebyggelse":         True,
        "antal_bygninger":        len(buildings),
        "bygningstyper":          type_list,
        "dominerende_anvendelse": dominant,
        "eksisterende_navne":     named[:3],
        "arealanvendelse":        list(landuse_set)[:3],
        "faciliteter":            list(set(pois))[:4],
        "kilde":                  "OpenStreetMap",
        "beskrivelse":            " · ".join(parts) if parts else "Ingen data",
    }


def _empty_land_use(beskrivelse: str) -> dict:
    return {
        "har_bebyggelse": False, "antal_bygninger": 0,
        "bygningstyper": [], "dominerende_anvendelse": "Ubebygget",
        "eksisterende_navne": [], "arealanvendelse": [],
        "faciliteter": [], "kilde": "OpenStreetMap",
        "beskrivelse": beskrivelse,
    }


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * r * math.asin(math.sqrt(a))
