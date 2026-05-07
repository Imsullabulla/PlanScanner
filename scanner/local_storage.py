"""
Midlertidig SQLite-storage til brug mens SharePoint ikke er klar.
Kan udskiftes med sharepoint_storage.py uden ændringer i scan_job.py —
begge moduler eksporterer de samme tre funktioner:
  - get_token() -> any
  - plan_already_scanned(plan_id, token) -> bool
  - save_plan(plan, assessment, population, competitors, token)
"""
import sqlite3
import json
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "planscanner.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plans (
            plan_id          TEXT PRIMARY KEY,
            plannavn         TEXT,
            kommunenavn      TEXT,
            status           TEXT,
            anvgen           INTEGER,
            anvendelsegenerel TEXT,
            datooprt         TEXT,
            datoslut         TEXT,
            doklink          TEXT,
            relevant         INTEGER,
            prioritet        TEXT,
            format_match     TEXT,
            sammenfattning   TEXT,
            aktion           TEXT,
            population       INTEGER,
            konkurrenter     INTEGER,
            kannibal_risiko  TEXT,
            scannet          TEXT
        )
    """)
    conn.commit()


def get_token():
    """Ingen token nødvendig for SQLite — returnerer None som placeholder."""
    return None


def plan_already_scanned(plan_id: str, token=None) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        return row is not None


def save_plan(plan: dict, assessment: dict, population: int,
              competitors: list, token=None):
    """Gem plan og AI-vurdering i den lokale SQLite-database."""
    props = plan["properties"]
    with _get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO plans (
                plan_id, plannavn, kommunenavn, status, anvgen,
                anvendelsegenerel, datooprt, datoslut, doklink,
                relevant, prioritet, format_match, sammenfattning,
                aktion, population, konkurrenter, kannibal_risiko, scannet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(props.get("id", "")),
            props.get("plannavn", ""),
            props.get("kommunenavn", ""),
            props.get("status", ""),
            props.get("anvgen"),
            props.get("anvendelsegenerel", ""),
            props.get("datooprt", ""),
            props.get("datoslut", ""),
            props.get("doklink", ""),
            1 if assessment.get("relevant") else 0,
            assessment.get("prioritet", ""),
            json.dumps(assessment.get("format_match", []), ensure_ascii=False),
            assessment.get("sammenfattning", ""),
            assessment.get("aktion", ""),
            population,
            len(competitors),
            assessment.get("kannibaliseringsrisiko", ""),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
