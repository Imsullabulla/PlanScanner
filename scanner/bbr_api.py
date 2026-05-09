"""
Undersøger eksisterende bebyggelse og arealanvendelse via Overpass API (OSM).
OSM har fremragende dækning i Danmark og kræver ingen API-nøgle.

For autoritative BBR-data (bygningsareal, opførelsesår, officiel anvendelseskode):
Registrér gratis på dataforsyningen.dk og brug Datafordelens BBR-API.
"""
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM-tags → dansk beskrivelse
BUILDING_DK = {
    "supermarket":      "Dagligvarebutik",
    "convenience":      "Nærbutik",
    "hypermarket":      "Hypermarked",
    "retail":           "Butik / detail",
    "commercial":       "Erhvervsbyggeri",
    "industrial":       "Industribyggeri",
    "warehouse":        "Lager / logistik",
    "office":           "Kontor",
    "residential":      "Boligbebyggelse",
    "house":            "Enfamilieshus",
    "detached":         "Fritliggende hus",
    "semidetached_house": "Dobbelthus",
    "apartments":       "Etageboliger",
    "dormitory":        "Kollegie / bofællesskab",
    "hotel":            "Hotel",
    "school":           "Skole",
    "hospital":         "Hospital/klinik",
    "church":           "Kirke",
    "public":           "Offentlig bygning",
    "civic":            "Kommunal bygning",
    "parking":          "Parkeringsanlæg",
    "garage":           "Garage / værksted",
    "farm":             "Landbrugsbygning",
    "greenhouse":       "Drivhus",
    "construction":     "Under opførelse",
    "yes":              "Bygning (uspecificeret)",
}

LANDUSE_DK = {
    "commercial":       "Erhvervsareal",
    "industrial":       "Industriareal",
    "residential":      "Boligområde",
    "retail":           "Butiksareal",
    "farmland":         "Landbrugsareal",
    "forest":           "Skov",
    "grass":            "Grønt areal",
    "recreation_ground":"Rekreativt areal",
    "allotments":       "Kolonihaver",
    "construction":     "Byggegrund",
    "brownfield":       "Brownfield / tidligere erhverv",
    "greenfield":       "Ubebygget greenfield",
    "cemetery":         "Kirkegård",
    "military":         "Militærområde",
    "railway":          "JernbaneaReal",
    "depot":            "Depot",
}


def get_existing_land_use(lat: float, lon: float, radius_m: int = 150) -> dict:
    """
    Finder bygninger, arealanvendelse og faciliteter inden for radius af planens centroid.
    Radius 150 m giver et godt billede af selve plangrunden uden for meget støj.
    """
    query = f"""
    [out:json][timeout:15];
    (
      way(around:{radius_m},{lat},{lon})[building];
      relation(around:{radius_m},{lat},{lon})[building];
      way(around:{radius_m},{lat},{lon})[landuse];
      node(around:{radius_m},{lat},{lon})[shop~"supermarket|convenience|department_store|mall"];
      node(around:{radius_m},{lat},{lon})[amenity~"fuel|fast_food|restaurant|bank|pharmacy"];
    );
    out tags;
    """
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        elements = r.json().get("elements", [])
    except Exception:
        return _empty("Opslag fejlede")

    if not elements:
        return _empty("Ingen registreret bebyggelse (OSM)")

    buildings: list[dict] = []
    landuse_set: set[str] = set()
    pois: list[str] = []

    for el in elements:
        tags = el.get("tags", {})

        # --- Bygning ---
        if "building" in tags:
            raw = tags.get("building", "yes")
            # Overskriv med mere præcis tag hvis til stede
            for key in ("shop", "amenity", "office", "leisure"):
                if key in tags:
                    raw = tags[key]
                    break
            name = tags.get("name", "")
            dk = BUILDING_DK.get(raw, raw.replace("_", " ").capitalize())
            buildings.append({"type_dk": dk, "raw": raw, "name": name})

        # --- Arealanvendelse ---
        if "landuse" in tags:
            lu = tags["landuse"]
            landuse_set.add(LANDUSE_DK.get(lu, lu.replace("_", " ").capitalize()))

        # --- Punktfaciliteter (ingen bygnings-tag) ---
        if "building" not in tags:
            for key in ("shop", "amenity"):
                if key in tags:
                    pois.append(tags.get("name") or tags[key])

    if not buildings and not pois:
        lu_list = list(landuse_set)[:2]
        desc = f"Ubebygget — {', '.join(lu_list)}" if lu_list else "Ubebygget grund"
        return _empty(desc)

    # Dominerende type
    dominant = buildings[0]["type_dk"] if buildings else (pois[0] if pois else "Ukendt")

    named = [b["name"] for b in buildings if b["name"]]
    type_list = list({b["type_dk"] for b in buildings})[:5]

    return {
        "har_bebyggelse":         True,
        "antal_bygninger":        len(buildings),
        "bygningstyper":          type_list,
        "dominerende_anvendelse": dominant,
        "eksisterende_navne":     named[:3],
        "arealanvendelse":        list(landuse_set)[:3],
        "faciliteter":            list(set(pois))[:4],
        "kilde":                  "OpenStreetMap",
        "beskrivelse":            _summarize(buildings, pois, landuse_set),
    }


def _summarize(buildings, pois, landuse_set) -> str:
    parts = []
    if buildings:
        types = list({b["type_dk"] for b in buildings})
        named = [b["name"] for b in buildings if b["name"]]
        if named:
            parts.append(f"{', '.join(named[:2])} ({', '.join(types[:2])})")
        else:
            n = len(buildings)
            parts.append(f"{n} bygning{'er' if n != 1 else ''}: {', '.join(types[:3])}")
    if pois:
        parts.append(f"Eksisterende: {', '.join(pois[:2])}")
    if not parts and landuse_set:
        parts.append(f"Arealanvendelse: {', '.join(list(landuse_set)[:2])}")
    return " · ".join(parts) if parts else "Ingen data"


def _empty(beskrivelse: str) -> dict:
    return {
        "har_bebyggelse":         False,
        "antal_bygninger":        0,
        "bygningstyper":          [],
        "dominerende_anvendelse": "Ubebygget",
        "eksisterende_navne":     [],
        "arealanvendelse":        [],
        "faciliteter":            [],
        "kilde":                  "OpenStreetMap",
        "beskrivelse":            beskrivelse,
    }
