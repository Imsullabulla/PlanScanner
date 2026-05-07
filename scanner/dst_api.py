import requests

# Variable-koder fra FOLK1A tableinfo (indeholder danske tegn)
_OMRADE = "OMRADE"  # Opdateres dynamisk første gang
_KON = "KON"        # Opdateres dynamisk første gang
_CODES_FETCHED = False


def _fetch_variable_codes():
    """Hent de præcise variabel-koder fra FOLK1A (indeholder Å og Ø)."""
    global _OMRADE, _KON, _CODES_FETCHED
    if _CODES_FETCHED:
        return
    try:
        r = requests.get("https://api.statbank.dk/v1/tableinfo/FOLK1A", timeout=10)
        r.raise_for_status()
        variables = r.json().get("variables", [])
        if len(variables) >= 2:
            _OMRADE = variables[0]["id"]  # "OMRÅDE" med Å
            _KON = variables[1]["id"]     # "KØN"
        _CODES_FETCHED = True
    except Exception:
        pass


def get_population_by_municipality(komnr: int) -> int:
    """
    Hent seneste kvartalsbefokningstal for en kommune fra Danmarks Statistik (FOLK1A).
    komnr er det numeriske kommunenummer fra Plandata (fx 169 for Høje-Taastrup).
    Returnerer 0 hvis opslaget fejler.
    """
    _fetch_variable_codes()
    omrade_kode = str(komnr).zfill(3)
    try:
        response = requests.post(
            "https://api.statbank.dk/v1/data",
            json={
                "table": "FOLK1A",
                "format": "CSV",
                "variables": [
                    {"code": _OMRADE, "values": [omrade_kode]},
                    {"code": _KON, "values": ["TOT"]},
                    {"code": "ALDER", "values": ["IALT"]},
                    {"code": "CIVILSTAND", "values": ["TOT"]},
                    {"code": "Tid", "values": ["*"]}
                ]
            },
            timeout=15
        )
        response.raise_for_status()

        # CSV med mulig BOM — dekod som UTF-8-sig
        text = response.content.decode("utf-8-sig")
        lines = [l for l in text.strip().splitlines() if l]
        if len(lines) < 2:
            return 0

        # Seneste kvartal er den sidst viste række; befolkning er sidste kolonne
        last_value = lines[-1].split(";")[-1].strip().strip('"').replace(".", "")
        return int(last_value)
    except (requests.RequestException, ValueError, IndexError):
        return 0
