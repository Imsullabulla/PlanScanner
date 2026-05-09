"""
PlanScanner — dagligt scanjob.
Kør lokalt:  python scan_job.py
Med flag:    python scan_job.py --days 7   (scan de seneste 7 dage)
"""
import argparse
import json
import logging
import os
import sys

import pathlib
from datetime import date, timedelta
from dotenv import load_dotenv
from shapely.geometry import shape

load_dotenv(dotenv_path=pathlib.Path(__file__).parent / ".env", override=True)

from scanner.plandata_api import fetch_new_plans, fetch_adopted_plans, is_potentially_relevant
from scanner.dst_api import get_population_by_municipality
from scanner.ai_classifier import classify_plan_with_ai
from scanner.overpass_client import fetch_site_context

# Brug lokal SQLite indtil SharePoint er konfigureret
# Skift til: from scanner.sharepoint_storage import get_token, plan_already_scanned, save_plan
from scanner.local_storage import get_token, plan_already_scanned, save_plan

# Notion er valgfrit — hvis NOTION_API_KEY ikke er sat, springes det over
NOTION_ENABLED = bool(os.environ.get("NOTION_API_KEY") and os.environ.get("NOTION_DATABASE_ID"))
if NOTION_ENABLED:
    from scanner.notion_output import write_plan_to_notion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("planscanner")


def compute_centroid(geometry: dict) -> tuple[float, float]:
    polygon = shape(geometry)
    centroid = polygon.centroid
    return centroid.y, centroid.x  # lat, lon


def run_scan(days_back: int = 1):
    log.info(f"=== PlanScanner start — scanner {days_back} dag(e) tilbage ===")
    log.info(f"Notion-output: {'aktiveret' if NOTION_ENABLED else 'deaktiveret (ingen nøgle)'}")

    scan_date = date.today().isoformat()
    report = {
        "date": scan_date,
        "days_back": days_back,
        "period_start": (date.today() - timedelta(days=days_back)).isoformat(),
        "period_end": scan_date,
        "relevant_plans": [],
    }

    token = get_token()

    new_plans = fetch_new_plans(days_back)
    adopted_plans = fetch_adopted_plans(days_back)
    all_plans = new_plans + adopted_plans

    log.info(f"Hentet {len(new_plans)} forslag + {len(adopted_plans)} vedtagne = {len(all_plans)} total")

    skipped_duplicate = 0
    skipped_irrelevant = 0
    ai_analysed = 0
    notion_written = 0

    for plan in all_plans:
        plan_id = str(plan["properties"]["id"])
        plan_name = plan["properties"].get("plannavn", "Ukendt")

        if plan_already_scanned(plan_id, token):
            skipped_duplicate += 1
            log.debug(f"Skip duplikat: {plan_name}")
            continue

        if not is_potentially_relevant(plan):
            skipped_irrelevant += 1
            anvgen = plan["properties"].get("anvgen")
            log.info(f"Skip (anvgen={anvgen}): {plan_name}")
            save_plan(plan,
                      {"relevant": False, "prioritet": "ikke relevant",
                       "sammenfattning": f"Filtreret fra — anvgen-kode {anvgen} ikke relevant.",
                       "aktion": "Ikke relevant — arkivér",
                       "format_match": [], "kannibaliseringsrisiko": "ingen"},
                      0, [], token)
            continue

        try:
            lat, lon = compute_centroid(plan["geometry"])
        except Exception as e:
            log.warning(f"Centroid-fejl for {plan_id}: {e}")
            continue

        komnr = plan["properties"].get("komnr")
        population = get_population_by_municipality(komnr) if komnr else 0
        site = fetch_site_context(lat, lon)
        competitors = site["competitors"]
        roads       = site["roads"]
        land_use    = site["land_use"]

        kommune = plan["properties"].get("kommunenavn", "?")
        log.info(f"AI-analyse: {plan_name} ({kommune}) — befolkning: {population:,} — konkurrenter: {len(competitors)}")

        try:
            assessment = classify_plan_with_ai(plan, competitors, population)
        except ValueError as e:
            log.warning(f"Springer over (ingen PDF): {e}")
            continue
        except Exception as e:
            log.error(f"AI-fejl for {plan_id}: {e}")
            continue

        ai_analysed += 1
        save_plan(plan, assessment, population, competitors, token)

        prioritet = assessment.get("prioritet", "")
        log.info(f"  Relevant: {assessment.get('relevant')} | Prioritet: {prioritet} | Format: {assessment.get('format_match')}")

        if NOTION_ENABLED and assessment.get("relevant") and prioritet != "ikke relevant":
            try:
                notion_url = write_plan_to_notion(plan, assessment, population, competitors)
                notion_written += 1
                log.info(f"  Skrevet til Notion")

                props = plan["properties"]
                report["relevant_plans"].append({
                    "name": plan_name,
                    "kommune": props.get("kommunenavn", ""),
                    "status": "Forslag" if props.get("status") == "F" else "Vedtaget",
                    "plantype": props.get("anvendelsegenerel", ""),
                    "prioritet": prioritet,
                    "population": population,
                    "format_match": assessment.get("format_match", []),
                    "aktion": assessment.get("aktion", ""),
                    "kannibaliseringsrisiko": assessment.get("kannibaliseringsrisiko", "ingen"),
                    "hoering_aktiv": assessment.get("hoering_aktiv", False),
                    "horingsfrist": str(props.get("datoslut", "") or ""),
                    "sammenfatning": assessment.get("sammenfattning", ""),
                    # AI-udtræk fra PDF
                    "bebyggelsesprocent": assessment.get("bebyggelsesprocent"),
                    "max_bygningshojde_m": assessment.get("max_bygningshojde_m"),
                    "max_etager": assessment.get("max_etager"),
                    "parkeringsnorm": assessment.get("parkeringsnorm"),
                    "planlagte_boliger": assessment.get("planlagte_boliger"),
                    "tidshorisont": assessment.get("tidshorisont"),
                    "varetilkorsel_mulighed": assessment.get("varetilkorsel_mulighed"),
                    "specifikke_forbud": assessment.get("specifikke_forbud", []),
                    # Trafik og bebyggelse
                    "trafikdata": roads,
                    "bebyggelse": land_use,
                    # Meta
                    "pdf_url": props.get("doklink", ""),
                    "notion_url": notion_url or "",
                    "scannet": scan_date,
                })
            except Exception as e:
                log.error(f"  Notion-fejl: {e}")

    report["stats"] = {
        "total_fetched": len(all_plans),
        "ai_analysed": ai_analysed,
        "notion_written": notion_written,
        "skipped_irrelevant": skipped_irrelevant,
        "skipped_duplicate": skipped_duplicate,
    }

    summary_path = pathlib.Path(__file__).parent / "scan_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info(f"Rapport gemt: {summary_path}")

    log.info(
        f"=== Færdig === "
        f"Analyseret: {ai_analysed} | "
        f"Til Notion: {notion_written} | "
        f"Irrelevante sprunget over: {skipped_irrelevant} | "
        f"Dubletter: {skipped_duplicate}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PlanScanner — dagligt scanjob")
    parser.add_argument("--days", type=int, default=1,
                        help="Antal dage tilbage at scanne (default: 1)")
    args = parser.parse_args()
    run_scan(days_back=args.days)
