# PlanScanner — Teknisk Blueprint til Claude Code
**Udarbejdet:** 7. maj 2026  
**Sidst verificeret:** 7. maj 2026 (live API-test)  
**Kontekst:** Internt værktøj til Salling Groups ejendomsafdeling  
**Formål:** Automatisk overvågning af alle danske lokalplaner med AI-klassificering af relevans for nye butikslokaliteter  
**Målgruppe for dette dokument:** Claude Code / AI-assistent der skal hjælpe med at bygge systemet

---

## Arkitekturvalg (besluttet)

| Komponent | Valg | Begrundelse |
|---|---|---|
| **AI-klassificering** | Anthropic API (Claude) | Nemmest opsætning, bedst PDF-læsning |
| **Storage** | SharePoint | Lever inden for Sallings Microsoft 365-miljø |
| **Output** | Notion-database | Brugerne henter selv data ved behov, ingen e-mail |
| **Scheduler** | GitHub Actions cron | Gratis, enkel |

---

## 1. Hvad er PlanScanner?

PlanScanner er en automatiseret overvågningsrobot der:

1. **Dagligt** henter alle nye og ændrede lokalplaner fra Plandata.dk (gratis, åbne offentlige data)
2. **Klassificerer** dem med Claude AI: Er dette plan relevant for Salling Groups butiksformater?
3. **Scorer** relevante planer på befolkningspotentiale, konkurrencesituation og arealstørrelse
4. **Skriver** relevante planer til en Notion-database som ejendomsafdelingen selv åbner

**Kerneværdien:** Salling Group får information om nye butikslokaliteter 2–5 år før ejendommen er på markedet — allerede når kommunen begynder at planlægge et nyt centerområde.

**Brugere:** 3–5 personer i Salling Groups ejendomsafdeling. Ingen tekniske krav til brugeren.

---

## 2. Arkitektur — overblik

```
┌─────────────────────────────────────────────────────┐
│                  DAGLIGT SCANJOB (cron)             │
│                  Kører kl. 06:00 hver dag           │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │   Plandata.dk WFS API   │  ← Gratis, åbne data
          │  Hent nye lokalplaner   │    Ingen API-nøgle
          │  siden sidst scanned    │
          └────────────┬────────────┘
                       │  GeoJSON med plangeometri + metadata
          ┌────────────▼────────────┐
          │    PDF-tekstekstraktion │  ← Download og læs
          │    fra planens dokument │    plantekst-PDF (via doklink)
          └────────────┬────────────┘
                       │  Rå plantekst
          ┌────────────▼────────────┐
          │      Claude AI          │  ← api.anthropic.com
          │  Klassificér og vurdér  │    claude-sonnet-4-6
          │  planteksten            │
          └────────────┬────────────┘
                       │  Struktureret JSON-vurdering
          ┌────────────▼────────────┐
          │   Berigningslag         │  ← DST API (befolkning)
          │   Befolkning + konkur-  │    OSM Overpass (konkurrenter)
          │   renter i området      │    Dataforsyningen (geo)
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │       Storage           │  ← SharePoint-liste
          │   Gem plan + vurdering  │    (Microsoft 365)
          │   Undgå dubletter       │
          └────────────┬────────────┘
                       │
          ┌────────────▼────────────┐
          │        Output           │
          │  Notion-database        │  ← Brugeren åbner selv
          │  (ejendomsafd. ser det) │    ingen e-mail
          └─────────────────────────┘
```

---

## 3. API-dokumentation

### 3a. Plandata.dk WFS API ✅ (gratis, ingen nøgle)
**VERIFICERET 7. maj 2026 — live API-test**

**Base URL:** `https://geoserver.plandata.dk/geoserver/wfs`

**Relevante lag (verificerede navne):**

| Lagnavn | Indhold |
|---|---|
| `pdk:theme_pdk_lokalplan_forslag` | Lokalplanforslag i høring (tidligste signal) |
| `pdk:theme_pdk_lokalplan_vedtaget` | Vedtagne lokalplaner |
| `pdk:theme_pdk_lokalplandelomraade_forslag` | Delområder i forslag |
| `pdk:theme_pdk_lokalplandelomraade_vedtaget` | Vedtagne delområder |

> ⚠️ Blueprint v1 brugte `_v`-suffix (fx `..._forslag_v`) — det er forkert. Lagene hedder **uden** `_v`.

**Eksempel — hent alle nye lokalplanforslag siden i går:**

```
GET https://geoserver.plandata.dk/geoserver/wfs?
  service=WFS
  &version=2.0.0
  &request=GetFeature
  &typeName=pdk:theme_pdk_lokalplan_forslag
  &outputFormat=application/json
  &CQL_FILTER=datooprt > '2026-05-06T00:00:00Z'
```

**Faktiske feltnavne i response (verificeret):**

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "id": "theme_pdk_lokalplan_forslag.636604",
    "properties": {
      "id": 636604,
      "planid": 12114696,
      "plannavn": "Lokalplan 200 - Stensballe Centervej",
      "komnr": 615,
      "kommunenavn": "Horsens",
      "status": "F",
      "anvgen": 41,
      "anvendelsegenerel": "Centerområde",
      "datoforsl": 20260502,
      "datoikraft": null,
      "datostart": "2026-05-02",
      "datoslut": "2026-06-15",
      "datooprt": "2026-05-02T08:00:00Z",
      "datoopdt": "2026-05-02T08:00:00Z",
      "doklink": "https://dokument.plandata.dk/20_12114696_xxx.pdf",
      "anvspec1": 4110,
      "anvspec2": null
    },
    "geometry": {
      "type": "MultiPolygon",
      "coordinates": [[...]]
    }
  }]
}
```

> ⚠️ **Vigtige korrektioner fra blueprint v1:**
> - `pdf_url` → **`doklink`** (kritisk — PDF-link hedder `doklink`)
> - `kommunekode` → **`komnr`** (numerisk, ikke tekst)
> - `dato_ikraft` → **`datoikraft`** (ingen underscore, og NULL for forslag)
> - Filtrer på **`datooprt`** (oprettelsesdato) ikke `datoikraft` (ikrafttrædelse)
> - `hoeringsstart` → **`datostart`**
> - `hoeringslut` → **`datoslut`**
> - `anvendelsesgenerel` (ét 'e' i 'generel') — ikke `anvendelsesgenerel`
> - `status` er kode: **`"F"`** = Forslag, **`"V"`** = Vedtaget

**`anvgen` kodeværdier (verificeret):**

| Kode | Tekst | Relevant for Salling |
|---|---|---|
| 41 | Centerområde | ✅ Ja |
| 21 | Blandet bolig og erhverv | ✅ Muligvis |
| 31 | Erhvervsområde | ✅ Muligvis |
| 11 | Boligområde | ❌ Nej |
| 51 | Rekreativt område | ❌ Nej |
| 61 | Sommerhusområde | ❌ Nej |
| 71 | Område til offentlige formål | ❌ Nej |
| 81 | Tekniske anlæg | ❌ Nej |
| 91 | Landområde | ❌ Nej |
| 96 | Andet | ⚠️ Ukendt — send til AI |

**Python-kode til at hente planer (korrigeret):**

```python
import requests
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

PLANDATA_WFS = "https://geoserver.plandata.dk/geoserver/wfs"

RELEVANT_ANVGEN_CODES = {41, 21, 31}  # Centerområde, Blandet, Erhverv
SKIP_ANVGEN_CODES = {11, 51, 61, 71, 81, 91}  # Bolig, Rekreativ, Teknisk osv.

def fetch_new_plans(days_back: int = 1) -> list[dict]:
    """Hent alle nye lokalplanforslag oprettet siden i går."""
    since_dt = (date.today() - timedelta(days=days_back)).isoformat() + "T00:00:00Z"
    
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "pdk:theme_pdk_lokalplan_forslag",
        "outputFormat": "application/json",
        "CQL_FILTER": f"datooprt > '{since_dt}'"
    }
    
    response = requests.get(PLANDATA_WFS, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])

def fetch_adopted_plans(days_back: int = 1) -> list[dict]:
    """Hent vedtagne lokalplaner oprettet siden i går."""
    since_dt = (date.today() - timedelta(days=days_back)).isoformat() + "T00:00:00Z"
    
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": "pdk:theme_pdk_lokalplan_vedtaget",
        "outputFormat": "application/json",
        "CQL_FILTER": f"datooprt > '{since_dt}'"
    }
    
    response = requests.get(PLANDATA_WFS, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("features", [])
```

---

### 3b. Danmarks Statistik API ✅ (gratis, ingen nøgle)

**Base URL:** `https://api.statbank.dk/v1`

**Brug:** Hent befolkningstal for planområdets postnummer.

```python
import requests

def get_population_by_postal(postal_code: str) -> int:
    """Hent seneste befolkningstal for et postnummer fra DST. Returnerer int."""
    response = requests.post(
        "https://api.statbank.dk/v1/data",
        json={
            "table": "BEF44",
            "format": "JSON",
            "variables": [
                {"code": "POSTNR", "values": [postal_code]},
                {"code": "Tid", "values": ["*"]}
            ]
        },
        timeout=15
    )
    response.raise_for_status()
    data = response.json()
    
    # DST returnerer {'data': [{'INDHOLD': '12345', ...}]}
    rows = data.get("data", [])
    if not rows:
        return 0
    
    # Tag den nyeste (sidste) række og konvertér til int
    try:
        return int(rows[-1].get("INDHOLD", "0").replace(".", ""))
    except (ValueError, AttributeError):
        return 0
```

> ⚠️ Blueprint v1 returnerede rå DST-objekt og kaldte `.get("total", 0)` — det felt eksisterer ikke.
> Korrigeret til at returnere `int` direkte.

---

### 3c. Dataforsyningen ✅ (gratis, ingen nøgle)

```python
import requests

def get_postal_from_coordinates(lat: float, lon: float) -> str:
    """Find postnummer for et koordinatpunkt (planens centrum)."""
    response = requests.get(
        "https://api.dataforsyningen.dk/postnumre/reverse",
        params={"x": lon, "y": lat},
        timeout=10
    )
    if response.status_code == 200:
        return response.json().get("nr", "")
    return ""
```

---

### 3d. OpenStreetMap Overpass API ✅ (gratis, rate-limited)

```python
import requests

COMPETITOR_NAMES = ["NETTO", "REMA 1000", "LIDL", "ALDI", "FAKTA", "MENY", "COOP"]

def find_competitors_near_plan(lat: float, lon: float, radius_km: float = 2.0) -> list[dict]:
    """Find konkurrerende dagligvarebutikker nær planområdet via OpenStreetMap."""
    overpass_query = f"""
    [out:json][timeout:25];
    (
      node["shop"="supermarket"](around:{int(radius_km * 1000)},{lat},{lon});
      node["shop"="convenience"](around:{int(radius_km * 1000)},{lat},{lon});
    );
    out body;
    """
    response = requests.post(
        "https://overpass-api.de/api/interpreter",
        data={"data": overpass_query},
        timeout=30
    )
    response.raise_for_status()
    
    competitors = []
    for el in response.json().get("elements", []):
        name = el.get("tags", {}).get("name", "").upper()
        if any(comp in name for comp in COMPETITOR_NAMES):
            competitors.append({
                "name": el["tags"].get("name"),
                "lat": el.get("lat"),
                "lon": el.get("lon"),
            })
    return competitors
```

---

### 3e. Claude API 💰 (betalt — ~50–150 kr./md.)

```python
import anthropic
import base64
import json
import requests

client = anthropic.Anthropic()  # Henter ANTHROPIC_API_KEY fra miljøvariabel

CLAUDE_MODEL = "claude-sonnet-4-6"  # Korrekt model-ID

def classify_plan_with_ai(plan: dict, competitors: list, population: int) -> dict:
    """Send plandata til Claude og få en struktureret vurdering tilbage."""
    props = plan["properties"]
    
    # Download PDF
    pdf_url = props.get("doklink", "")
    if not pdf_url or "null" in pdf_url:
        raise ValueError(f"Ingen gyldig PDF-URL for plan {props.get('id')}")
    
    pdf_response = requests.get(pdf_url, timeout=30)
    pdf_response.raise_for_status()
    pdf_base64 = base64.standard_b64encode(pdf_response.content).decode("utf-8")
    
    system_prompt = """Du er ekspert i dansk planlægning og detailhandel for Salling Group.
Din opgave er at vurdere, om en ny lokalplan åbner en mulighed for en ny Salling-butik.

Salling Groups butiksformater og krav:
- NETTO: 400–900 m² butiksareal, discountdagligvarer, kræver min. 6.000 beboere i 1km radius
- FØTEX: 1.500–5.000 m², supermarked-format, kræver min. 15.000 beboere i 2km radius
- BILKA: 10.000+ m², varehus, kræver min. 50.000 beboere i 5km radius, kræver stor grund + parkering

Du skal svare KUN med gyldigt JSON og ingen andet — ingen preamble, ingen markdown-backticks."""

    hearing_deadline = props.get("datoslut", "Ikke angivet")
    hearing_start = props.get("datostart", "Ikke angivet")
    
    user_prompt = f"""Analysér denne lokalplan og vurdér dens relevans for Salling Group.

PLANMETADATA:
- Plannavn: {props.get('plannavn', 'Ukendt')}
- Kommune: {props.get('kommunenavn', 'Ukendt')}
- Status: {'Forslag' if props.get('status') == 'F' else 'Vedtaget'}
- Generel anvendelse: {props.get('anvendelsegenerel', 'Ikke angivet')}
- Høringsperiode: {hearing_start} → {hearing_deadline}

KONTEKSTDATA:
- Befolkning i nærmeste postnummer: {population:,} personer
- Eksisterende konkurrenter inden for 2km: {len(competitors)} stk.
- Konkurrentnavne: {', '.join([c['name'] for c in competitors]) if competitors else 'Ingen fundet'}

Returner dette JSON-objekt:
{{
  "relevant": true/false,
  "confidence": "høj"/"middel"/"lav",
  "prioritet": "høj"/"middel"/"lav"/"ikke relevant",
  "format_match": ["NETTO", "FØTEX", "BILKA"],
  "max_butiksareal_m2": 0,
  "detailhandel_tilladt": true/false,
  "dagligvare_specifik": true/false,
  "estimeret_opland_beboere": 0,
  "kannibaliseringsrisiko": "ingen"/"lav"/"middel"/"høj",
  "hoering_aktiv": true/false,
  "sammenfattning": "2-3 sætninger om hvad planen indeholder og hvorfor den er/ikke er relevant",
  "aktion": "Undersøg nærmere"/"Følg op ved vedtagelse"/"Ikke relevant — arkivér",
  "flags": ["evt. særlige bemærkninger"]
}}"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_base64
                    }
                },
                {"type": "text", "text": user_prompt}
            ]
        }]
    )
    
    text = response.content[0].text.strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)
```

---

## 4. Storage — SharePoint-liste

I stedet for Supabase bruges en SharePoint-liste i Sallings Microsoft 365-miljø.

**Fordele:**
- Ingen ny leverandør — lever i Sallings eksisterende IT-infrastruktur
- Automatisk adgangsstyring via Azure AD
- Nemt at vise data i Teams og Power BI

**Opsætning:**
1. Opret en SharePoint-site kaldet "PlanScanner" i Sallings tenant
2. Opret en liste med de relevante kolonner (se nedenfor)
3. Opret en Azure App Registration til scanjobbet med `Sites.ReadWrite.All`-permission

**SharePoint-liste: `Lokalplaner`**

| Kolonne | Type | Indhold |
|---|---|---|
| Title | Tekst | Plannavn |
| PlanID | Tekst | Plandata.dk ID |
| Kommune | Tekst | Kommunenavn |
| Status | Tekst | F / V |
| AnvGen | Tal | anvgen-kode |
| AnvGenTekst | Tekst | "Centerområde" osv. |
| DatoOprettet | Dato | datooprt |
| DatoHøringSlut | Dato | datoslut |
| DokLink | Hyperlink | PDF-URL |
| Relevant | Ja/Nej | AI: relevant |
| Prioritet | Tekst | høj/middel/lav |
| FormatMatch | Tekst | NETTO, FØTEX |
| Sammenfatning | Lang tekst | AI-sammenfatning |
| Aktion | Tekst | AI-anbefaling |
| Population | Tal | Befolkning postnr. |
| Konkurrenter | Tal | Antal inden for 2km |
| KannibalRisiko | Tekst | ingen/lav/middel/høj |
| ScannetTidspunkt | Dato+tid | Hvornår scannet |

**Python-kode til SharePoint-gem (via Microsoft Graph API):**

```python
import requests
import os
from datetime import datetime

# Hentes fra miljøvariabler
TENANT_ID = os.environ["AZURE_TENANT_ID"]
CLIENT_ID = os.environ["AZURE_CLIENT_ID"]
CLIENT_SECRET = os.environ["AZURE_CLIENT_SECRET"]
SHAREPOINT_SITE_ID = os.environ["SHAREPOINT_SITE_ID"]
SHAREPOINT_LIST_ID = os.environ["SHAREPOINT_LIST_ID"]

def get_graph_token() -> str:
    """Hent OAuth2-token til Microsoft Graph API."""
    response = requests.post(
        f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "scope": "https://graph.microsoft.com/.default"
        },
        timeout=15
    )
    response.raise_for_status()
    return response.json()["access_token"]

def plan_already_scanned(plan_id: str, token: str) -> bool:
    """Tjek om en plan allerede er gemt i SharePoint-listen."""
    headers = {"Authorization": f"Bearer {token}"}
    filter_query = f"fields/PlanID eq '{plan_id}'"
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_ID}"
        f"/lists/{SHAREPOINT_LIST_ID}/items"
        f"?$filter={filter_query}&$select=id&$top=1"
    )
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return len(response.json().get("value", [])) > 0

def save_plan_to_sharepoint(plan: dict, assessment: dict,
                             population: int, competitors: list, token: str):
    """Gem plan og AI-vurdering som en ny række i SharePoint-listen."""
    props = plan["properties"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    item_fields = {
        "Title": props.get("plannavn", "Ukendt"),
        "PlanID": str(props.get("id", "")),
        "Kommune": props.get("kommunenavn", ""),
        "Status": props.get("status", ""),
        "AnvGen": props.get("anvgen"),
        "AnvGenTekst": props.get("anvendelsegenerel", ""),
        "DatoOprettet": props.get("datooprt", ""),
        "DatoHøringSlut": props.get("datoslut", ""),
        "DokLink": props.get("doklink", ""),
        "Relevant": assessment.get("relevant", False),
        "Prioritet": assessment.get("prioritet", ""),
        "FormatMatch": ", ".join(assessment.get("format_match", [])),
        "Sammenfatning": assessment.get("sammenfattning", ""),
        "Aktion": assessment.get("aktion", ""),
        "Population": population,
        "Konkurrenter": len(competitors),
        "KannibalRisiko": assessment.get("kannibaliseringsrisiko", ""),
        "ScannetTidspunkt": datetime.utcnow().isoformat() + "Z"
    }
    
    url = (
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_ID}"
        f"/lists/{SHAREPOINT_LIST_ID}/items"
    )
    response = requests.post(
        url, headers=headers, json={"fields": item_fields}, timeout=15
    )
    response.raise_for_status()
```

---

## 5. Output — Notion-database

Relevante planer (prioritet høj eller middel) skrives til en Notion-database som ejendomsafdelingen selv åbner.

**Fordele:**
- Ingen e-mail-konfiguration
- Brugerne ser planerne når det passer dem
- Kan filtrere, sortere og tilknytte noter i Notion
- Nemt at dele med nye kolleger

**Opsætning:**
1. Opret en Notion-integration på notion.so/my-integrations
2. Opret en database-side og del den med integrationen
3. Sæt `NOTION_API_KEY` og `NOTION_DATABASE_ID` som miljøvariabler

**Notion-database kolonner:**

| Kolonne | Type |
|---|---|
| Plannavn | Title |
| Prioritet | Select (Høj/Middel/Lav) |
| Format | Multi-select (NETTO/FØTEX/BILKA) |
| Kommune | Text |
| Sammenfatning | Text |
| Aktion | Select |
| Høringsfrist | Date |
| Population | Number |
| Konkurrenter | Number |
| PDF-link | URL |
| Scannet | Date |

**Python-kode til Notion-gem:**

```python
import requests
import os

NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

PRIORITY_COLORS = {"høj": "red", "middel": "yellow", "lav": "green"}

def write_plan_to_notion(plan: dict, assessment: dict,
                          population: int, competitors: list):
    """Skriv en relevant plan til Notion-databasen."""
    props = plan["properties"]
    priority = assessment.get("prioritet", "lav")
    formats = assessment.get("format_match", [])
    hearing_deadline = props.get("datoslut")
    
    page_properties = {
        "Plannavn": {
            "title": [{"text": {"content": props.get("plannavn", "Ukendt")}}]
        },
        "Prioritet": {
            "select": {"name": priority.capitalize(), "color": PRIORITY_COLORS.get(priority, "default")}
        },
        "Format": {
            "multi_select": [{"name": f} for f in formats]
        },
        "Kommune": {
            "rich_text": [{"text": {"content": props.get("kommunenavn", "")}}]
        },
        "Sammenfatning": {
            "rich_text": [{"text": {"content": assessment.get("sammenfattning", "")}}]
        },
        "Aktion": {
            "select": {"name": assessment.get("aktion", "Ikke relevant — arkivér")}
        },
        "Population": {"number": population},
        "Konkurrenter": {"number": len(competitors)},
        "PDF-link": {"url": props.get("doklink", "")},
        "Scannet": {"date": {"start": __import__('datetime').date.today().isoformat()}}
    }
    
    if hearing_deadline:
        page_properties["Høringsfrist"] = {"date": {"start": hearing_deadline}}
    
    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=NOTION_HEADERS,
        json={"parent": {"database_id": NOTION_DATABASE_ID}, "properties": page_properties},
        timeout=15
    )
    response.raise_for_status()
```

---

## 6. Hoved-scanjob (korrigeret)

```python
# scan_job.py — kører dagligt via GitHub Actions
import os
import logging
from datetime import date
from dotenv import load_dotenv
from shapely.geometry import shape

load_dotenv()  # Indlæs .env lokalt (ignoreres i GitHub Actions hvor secrets bruges)

from plandata_api import fetch_new_plans, fetch_adopted_plans, RELEVANT_ANVGEN_CODES
from enrichment import get_postal_from_coordinates, find_competitors_near_plan
from dst_api import get_population_by_postal
from ai_classifier import classify_plan_with_ai
from sharepoint_storage import get_graph_token, plan_already_scanned, save_plan_to_sharepoint
from notion_output import write_plan_to_notion

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("planscanner")

def compute_centroid(geometry: dict) -> tuple[float, float]:
    polygon = shape(geometry)
    centroid = polygon.centroid
    return centroid.y, centroid.x  # lat, lon

def is_potentially_relevant(plan: dict) -> bool:
    """Hurtigfilter — skip åbenlyst irrelevante planer baseret på anvgen-kode."""
    anvgen = plan["properties"].get("anvgen")
    
    if anvgen in RELEVANT_ANVGEN_CODES:  # {41, 21, 31}
        return True
    
    # Kode 96 (Andet) og None — ukendt, send til AI
    if anvgen is None or anvgen == 96:
        return True
    
    # Alt andet (bolig, rekreativ, teknisk, natur) — skip
    return False

def run_scan(days_back: int = 1):
    log.info(f"=== PlanScanner start — scanner {days_back} dag(e) tilbage ===")
    
    token = get_graph_token()
    
    new_plans = fetch_new_plans(days_back)
    adopted_plans = fetch_adopted_plans(days_back)
    all_plans = new_plans + adopted_plans
    
    log.info(f"Hentet {len(new_plans)} forslag + {len(adopted_plans)} vedtagne = {len(all_plans)} total")
    
    notion_entries = 0
    
    for plan in all_plans:
        plan_id = str(plan["properties"]["id"])
        
        if plan_already_scanned(plan_id, token):
            log.debug(f"Skip (allerede scannet): {plan_id}")
            continue
        
        if not is_potentially_relevant(plan):
            log.info(f"Skip (anvgen={plan['properties'].get('anvgen')}): {plan['properties'].get('plannavn')}")
            save_plan_to_sharepoint(plan, {"relevant": False, "prioritet": "ikke relevant",
                                           "sammenfattning": "Filtreret fra — ikke relevant anvendelse",
                                           "aktion": "Ikke relevant — arkivér",
                                           "format_match": [], "kannibaliseringsrisiko": "ingen"},
                                    0, [], token)
            continue
        
        try:
            lat, lon = compute_centroid(plan["geometry"])
        except Exception as e:
            log.warning(f"Kunne ikke beregne centroid for {plan_id}: {e}")
            continue
        
        postal_code = get_postal_from_coordinates(lat, lon)
        population = get_population_by_postal(postal_code) if postal_code else 0
        competitors = find_competitors_near_plan(lat, lon, radius_km=2.0)
        
        log.info(f"AI-analyse: {plan['properties'].get('plannavn')} ({plan['properties'].get('kommunenavn')})")
        try:
            assessment = classify_plan_with_ai(plan, competitors, population)
        except Exception as e:
            log.error(f"AI-fejl for {plan_id}: {e}")
            continue
        
        save_plan_to_sharepoint(plan, assessment, population, competitors, token)
        
        if assessment.get("relevant") and assessment.get("prioritet") != "ikke relevant":
            write_plan_to_notion(plan, assessment, population, competitors)
            notion_entries += 1
    
    log.info(f"Scan færdig. {notion_entries} planer skrevet til Notion.")

if __name__ == "__main__":
    run_scan(days_back=1)
```

---

## 7. Deployment og opsætning

### Miljøvariabler

```bash
# AI
ANTHROPIC_API_KEY=sk-ant-...

# SharePoint / Azure
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
SHAREPOINT_SITE_ID=...
SHAREPOINT_LIST_ID=...

# Notion
NOTION_API_KEY=secret_...
NOTION_DATABASE_ID=...
```

### GitHub Actions cron-job

```yaml
# .github/workflows/planscanner.yml
name: PlanScanner daglig scan

on:
  schedule:
    - cron: '0 5 * * *'    # kl. 05:00 UTC = 06:00 dansk tid (sommertid)
  workflow_dispatch:

jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Opsæt Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Installer afhængigheder
        run: pip install -r requirements.txt
      
      - name: Kør PlanScanner
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          AZURE_TENANT_ID: ${{ secrets.AZURE_TENANT_ID }}
          AZURE_CLIENT_ID: ${{ secrets.AZURE_CLIENT_ID }}
          AZURE_CLIENT_SECRET: ${{ secrets.AZURE_CLIENT_SECRET }}
          SHAREPOINT_SITE_ID: ${{ secrets.SHAREPOINT_SITE_ID }}
          SHAREPOINT_LIST_ID: ${{ secrets.SHAREPOINT_LIST_ID }}
          NOTION_API_KEY: ${{ secrets.NOTION_API_KEY }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
        run: python scan_job.py
```

### requirements.txt

```
anthropic>=0.40.0
requests>=2.31.0
shapely>=2.0.0
python-dotenv>=1.0.0
```

---

## 8. Projektfiler — mappestruktur

```
planscanner/
├── .github/
│   └── workflows/
│       └── planscanner.yml         ← Cron-job
├── scanner/
│   ├── __init__.py
│   ├── plandata_api.py             ← Plandata.dk WFS-kald (verificerede feltnavne)
│   ├── enrichment.py               ← Geo (Dataforsyningen) + OSM konkurrenter
│   ├── dst_api.py                  ← Danmarks Statistik befolkningsdata
│   ├── ai_classifier.py            ← Claude AI-klassificering
│   ├── sharepoint_storage.py       ← Microsoft Graph API → SharePoint
│   └── notion_output.py            ← Notion API → database
├── scan_job.py                     ← Hoved-entry point
├── requirements.txt
├── .env.example
└── README.md
```

---

## 9. MVP byggerækkefølge

```
Uge 1:
  ✅ Plandata.dk WFS API verificeret (feltnavne bekræftet 7. maj 2026)
  ○ plandata_api.py — fetch + hurtigfilter
  ○ enrichment.py — geo + OSM
  ○ dst_api.py — befolkningsdata
  ○ ai_classifier.py — Claude PDF-analyse

Uge 2:
  ○ sharepoint_storage.py — Graph API + dublet-check
  ○ notion_output.py — skriv til Notion
  ○ scan_job.py — sæt det hele sammen
  ○ Testkørsel lokalt med .env

Uge 3:
  ○ GitHub repo med secrets
  ○ GitHub Actions cron-job kører stabilt
  ○ Validering af AI-klassificering over 2 uger

Fase 2 (efterfølgende):
  ○ Notion-filtre og views tilpasset arbejdsflow
  ○ Power BI-rapport fra SharePoint-data
  ○ Evt. Teams-notifikation ved høj-prioritet planer
```

---

## 10. Oversigt over alle kendte korrektioner fra blueprint v1

| # | Problem | Løsning |
|---|---|---|
| 1 | Lagnavne havde `_v`-suffix | Fjernet — fx `pdk:theme_pdk_lokalplan_forslag` |
| 2 | `pdf_url` → faktisk `doklink` | Alle referencer opdateret |
| 3 | `kommunekode` → faktisk `komnr` | Opdateret |
| 4 | Filter på `dato_ikraft` (ofte NULL) | Skiftet til `datooprt` |
| 5 | Dato-format manglede `T00:00:00Z` | Tilføjet i alle filterkald |
| 6 | `hoeringsstart`/`hoeringslut` | Skiftet til `datostart`/`datoslut` |
| 7 | `anvendelsesgenerel` stavefejl | Rettet til `anvendelsegenerel` |
| 8 | Status som tekst ("Forslag") | Er kode "F" / "V" |
| 9 | `load_dotenv()` manglede | Tilføjet øverst i scan_job.py |
| 10 | Forkert model-navn | `claude-sonnet-4-6` |
| 11 | DST returnerede rå objekt | Returnerer nu `int` direkte |
| 12 | `database.py` manglede helt | Erstattet af `sharepoint_storage.py` |
| 13 | E-mail output | Erstattet af Notion-output |

---

*Alle offentlige datakilder er gratis og kræver ingen forudgående aftale. Eneste betalte komponent er Claude API — estimeret til 50–150 kr./md. ved normal drift.*
