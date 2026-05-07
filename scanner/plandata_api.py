import requests
from datetime import date, timedelta

PLANDATA_WFS = "https://geoserver.plandata.dk/geoserver/wfs"

# anvgen-koder der er potentielt relevante for Salling
RELEVANT_ANVGEN_CODES = {41, 21, 31}  # Centerområde, Blandet, Erhverv
SKIP_ANVGEN_CODES = {11, 51, 61, 71, 81, 91}  # Bolig, Rekreativ, Teknisk, Natur osv.


def _fetch_plans(layer: str, days_back: int) -> list[dict]:
    since_dt = (date.today() - timedelta(days=days_back)).isoformat() + "T00:00:00Z"
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",   # WGS84 koordinater — standard uden dette er EPSG:25832 (UTM, meter)
        "CQL_FILTER": f"datooprt > '{since_dt}'"
    }
    response = requests.get(PLANDATA_WFS, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])


def fetch_new_plans(days_back: int = 1) -> list[dict]:
    """Hent lokalplanforslag oprettet inden for de seneste N dage."""
    return _fetch_plans("pdk:theme_pdk_lokalplan_forslag", days_back)


def fetch_adopted_plans(days_back: int = 1) -> list[dict]:
    """Hent vedtagne lokalplaner oprettet inden for de seneste N dage."""
    return _fetch_plans("pdk:theme_pdk_lokalplan_vedtaget", days_back)


def is_potentially_relevant(plan: dict) -> bool:
    """
    Hurtigfilter baseret på anvgen-kode.
    Returnerer False kun hvis koden er et klart negativt signal.
    Ukendt kode (None, 96) sender vi til AI — hellere falsk positiv end misset mulighed.
    """
    anvgen = plan["properties"].get("anvgen")
    if anvgen in SKIP_ANVGEN_CODES:
        return False
    return True
