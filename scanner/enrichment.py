import requests
import math

COMPETITOR_NAMES = ["NETTO", "REMA 1000", "REMA", "LIDL", "ALDI", "FAKTA", "MENY", "COOP", "IRMA"]


def get_postal_from_coordinates(lat: float, lon: float) -> str:
    """Find postnummer for et koordinatpunkt via Dataforsyningen."""
    try:
        response = requests.get(
            "https://api.dataforsyningen.dk/postnumre/reverse",
            params={"x": lon, "y": lat},
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("nr", "")
    except requests.RequestException:
        pass
    return ""


def find_competitors_near_plan(lat: float, lon: float, radius_km: float = 2.0) -> list[dict]:
    """
    Find konkurrerende dagligvarebutikker nær planområdet via OpenStreetMap Overpass API.
    Returnerer liste med navn, koordinater og beregnet afstand fra centrum.
    """
    radius_m = int(radius_km * 1000)
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["shop"="supermarket"](around:{radius_m},{lat},{lon});
      node["shop"="convenience"](around:{radius_m},{lat},{lon});
    );
    out body;
    """
    try:
        response = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": overpass_query},
            timeout=30
        )
        response.raise_for_status()
    except requests.RequestException:
        return []

    competitors = []
    for el in response.json().get("elements", []):
        name = el.get("tags", {}).get("name", "").upper()
        if any(comp in name for comp in COMPETITOR_NAMES):
            el_lat = el.get("lat", 0)
            el_lon = el.get("lon", 0)
            competitors.append({
                "name": el["tags"].get("name"),
                "lat": el_lat,
                "lon": el_lon,
                "distance_m": _haversine_m(lat, lon, el_lat, el_lon)
            })

    return sorted(competitors, key=lambda c: c["distance_m"])


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Beregn afstand i meter mellem to koordinater."""
    r = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
