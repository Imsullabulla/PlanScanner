"""
Demo-scan: finder én plan fra hver plantype og skriver alle til Notion.
Kræver ingen SharePoint. Maks 6 AI-kald. Poster markeres med "TEST: ".
Kør: python demo_scan.py
"""
import pathlib, io, json, logging, sys
from dotenv import load_dotenv

load_dotenv(dotenv_path=pathlib.Path(__file__).parent / ".env", override=True)

import requests
import pdfplumber
from shapely.geometry import shape

from scanner.plandata_api import fetch_new_plans, fetch_adopted_plans
from scanner.enrichment import get_postal_from_coordinates, find_competitors_near_plan
from scanner.dst_api import get_population_by_municipality
from scanner.notion_output import write_plan_to_notion
from scanner.ai_classifier import OPENROUTER_URL, MODEL, SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger("demo")

# En repræsentativ plan fra hver plantype vi vil vise
TARGET_ANVGEN = {
    41: "Centeromraade",
    21: "Blandet bolig og erhverv",
    31: "Erhvervsomraade",
    11: "Boligomraade",
    71: "Offentlige formaal",
    51: "Rekreativt omraade",
}

MAX_PLANS = 6
# Kortere tekst = færre tokens = billigere
DEMO_MAX_CHARS = 5000
DEMO_MAX_PAGES = 12


def _extract_text_demo(pdf_url: str) -> str:
    r = requests.get(pdf_url, timeout=60)
    r.raise_for_status()
    parts = []
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        for page in pdf.pages[:DEMO_MAX_PAGES]:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)[:DEMO_MAX_CHARS]


def _classify(plan: dict, competitors: list, population: int) -> dict:
    import os
    props = plan["properties"]
    status_text = "Forslag" if props.get("status") == "F" else "Vedtaget"
    pdf_url = props.get("doklink", "")
    pdf_text = _extract_text_demo(pdf_url)

    pdf_section = (
        f"UDDRAG AF PLANTEKST:\n{pdf_text}"
        if pdf_text else
        "PLANTEKST: Ikke tilgaengelig (billede-PDF)."
    )

    user_prompt = f"""Analysér denne lokalplan for Salling Group.

PLANMETADATA:
- Plannavn: {props.get('plannavn')}
- Kommune: {props.get('kommunenavn')}
- Status: {status_text}
- Generel anvendelse: {props.get('anvendelsegenerel')}
- Høringsperiode: {props.get('datostart','?')} -> {props.get('datoslut','?')}

KONTEKSTDATA:
- Befolkning i kommunen: {population:,}
- Konkurrenter inden for 2km: {len(competitors)}
- Navne: {', '.join(c['name'] for c in competitors) if competitors else 'Ingen'}

{pdf_section}

Returner præcis dette JSON:
{{
  "relevant": true/false,
  "confidence": "høj"/"middel"/"lav",
  "prioritet": "høj"/"middel"/"lav"/"ikke relevant",
  "format_match": [],
  "max_butiksareal_m2": 0,
  "detailhandel_tilladt": true/false,
  "dagligvare_specifik": true/false,
  "estimeret_opland_beboere": 0,
  "kannibaliseringsrisiko": "ingen"/"lav"/"middel"/"høj",
  "hoering_aktiv": true/false,
  "sammenfattning": "2-3 sætninger om planen og dens relevans for Salling",
  "aktion": "Undersøg nærmere"/"Følg op ved vedtagelse"/"Ikke relevant — arkivér",
  "flags": []
}}"""

    resp = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {os.environ['ANTHROPIC_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 600,
            "temperature": 0.1
        },
        timeout=60
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    text = text.replace("```json", "").replace("```", "").strip()
    result = json.loads(text)

    return result


def run_demo():
    log.info("Henter planer fra de seneste 180 dage...")
    all_plans = fetch_new_plans(days_back=180) + fetch_adopted_plans(days_back=180)
    log.info(f"{len(all_plans)} planer hentet i alt")

    # Vælg én plan med gyldig PDF fra hver plantype
    selected: dict[int, dict] = {}
    for plan in all_plans:
        anvgen = plan["properties"].get("anvgen")
        if anvgen not in TARGET_ANVGEN:
            continue
        if anvgen in selected:
            continue
        doklink = plan["properties"].get("doklink", "")
        if not doklink or "null" in doklink.lower():
            continue
        selected[anvgen] = plan
        if len(selected) >= MAX_PLANS:
            break

    log.info(f"Udvalgte plantyper: {[TARGET_ANVGEN[k] for k in selected]}")
    log.info(f"Antal AI-kald: {len(selected)} (max {MAX_PLANS})")

    written = 0
    for anvgen, plan in selected.items():
        props = plan["properties"]
        name = props.get("plannavn", "?")
        kommune = props.get("kommunenavn", "?")
        plantype = props.get("anvendelsegenerel", "?")

        log.info(f"Analyserer [{plantype}]: {name} ({kommune})")

        try:
            centroid = shape(plan["geometry"]).centroid
            lat, lon = centroid.y, centroid.x
            population = get_population_by_municipality(props.get("komnr", 0))
            competitors = find_competitors_near_plan(lat, lon, radius_km=2.0)

            assessment = _classify(plan, competitors, population)

            log.info(f"  Relevant: {assessment['relevant']} | "
                     f"Prioritet: {assessment['prioritet']} | "
                     f"Format: {assessment.get('format_match', [])}")

            write_plan_to_notion(
                plan, assessment, population, competitors,
                title_prefix="TEST: "
            )
            written += 1
            log.info(f"  Skrevet til Notion")

        except Exception as e:
            log.error(f"  Fejl: {e}")

    log.info(f"Demo faerdig. {written} poster i Notion.")


if __name__ == "__main__":
    run_demo()
