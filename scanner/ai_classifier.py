import io
import json
import os
import requests
import pdfplumber

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4-5"

# Maks antal sider og tegn vi sender til AI — resten er typisk bilag og kort
MAX_PAGES = 25
MAX_CHARS = 12000

SYSTEM_PROMPT = """Du er ekspert i dansk planlægning og detailhandel for Salling Group.
Din opgave er at vurdere, om en ny lokalplan åbner en mulighed for en ny Salling-butik.

Salling Groups butiksformater og krav:
- NETTO: 400–900 m² butiksareal, discountdagligvarer, kræver min. 6.000 beboere i 1km radius
- FØTEX: 1.500–5.000 m², supermarked-format, kræver min. 15.000 beboere i 2km radius
- BILKA: 10.000+ m², varehus, kræver min. 50.000 beboere i 5km radius

Udtrækningsregler for nye felter (sæt null hvis ikke nævnt i planen):
- bebyggelsesprocent: tal i % angivet i planen (fx 40 for "40%")
- max_bygningshojde_m: maksimal bygningshøjde i meter
- max_etager: maksimalt antal etager
- parkeringsnorm: beskriv kortfattet parkeringskravet (fx "1 plads pr. 25 m² erhverv")
- planlagte_boliger: antal planlagte boliger hvis planen inkluderer boliger
- tidshorisont: hvornår forventes planen realiseret (fx "2026–2029" eller "ikke angivet")
- varetilkorsel_mulighed: true hvis planen eksplicit tillader lastbiltilkørsel/varegård
- specifikke_forbud: liste over eksplicitte forbud i planen (fx ["Ingen dagligvarer over 500 m²"])

Svar KUN med gyldigt JSON — ingen preamble, ingen markdown-backticks."""


def _extract_pdf_text(pdf_url: str) -> str:
    """
    Download PDF fra Plandata.dk og udtræk tekst med pdfplumber.
    Begrænset til MAX_PAGES sider og MAX_CHARS tegn.
    Returnerer tom streng hvis PDF er billede-baseret eller ikke tilgængelig.
    """
    response = requests.get(pdf_url, timeout=60)
    response.raise_for_status()

    text_parts = []
    with pdfplumber.open(io.BytesIO(response.content)) as pdf:
        for page in pdf.pages[:MAX_PAGES]:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    full_text = "\n".join(text_parts)
    return full_text[:MAX_CHARS]


def classify_plan_with_ai(plan: dict, competitors: list, population: int) -> dict:
    """
    Analysér en lokalplan med Claude via OpenRouter.
    Returnerer struktureret JSON-vurdering.
    Kaster ValueError hvis planen ikke har en gyldig PDF-URL.
    """
    props = plan["properties"]
    api_key = os.environ["ANTHROPIC_API_KEY"]

    pdf_url = props.get("doklink", "")
    if not pdf_url or "null" in pdf_url.lower():
        raise ValueError(f"Ingen gyldig PDF-URL for plan {props.get('id')}: {pdf_url!r}")

    pdf_text = _extract_pdf_text(pdf_url)

    if pdf_text:
        pdf_section = f"""UDDRAG AF PLANTEKST (første {MAX_PAGES} sider):
{pdf_text}"""
    else:
        pdf_section = "PLANTEKST: Ikke tilgængelig (billede-baseret PDF eller tom)."

    status_text = "Forslag" if props.get("status") == "F" else "Vedtaget"
    competitor_names = ", ".join(c["name"] for c in competitors) if competitors else "Ingen fundet"

    user_prompt = f"""Analysér denne lokalplan og vurdér dens relevans for Salling Group.

PLANMETADATA:
- Plannavn: {props.get('plannavn', 'Ukendt')}
- Kommune: {props.get('kommunenavn', 'Ukendt')}
- Status: {status_text}
- Generel anvendelse: {props.get('anvendelsegenerel', 'Ikke angivet')}
- Høringsperiode: {props.get('datostart', '?')} → {props.get('datoslut', '?')}

KONTEKSTDATA:
- Befolkning i kommunen: {population:,} personer
- Eksisterende konkurrenter inden for 2km: {len(competitors)} stk.
- Konkurrentnavne: {competitor_names}

{pdf_section}

Returner præcis dette JSON-objekt:
{{
  "relevant": true/false,
  "confidence": "høj"/"middel"/"lav",
  "prioritet": "høj"/"middel"/"lav"/"ikke relevant",
  "format_match": ["NETTO", "FØTEX", "BILKA"],
  "max_butiksareal_m2": null,
  "detailhandel_tilladt": true/false,
  "dagligvare_specifik": true/false,
  "estimeret_opland_beboere": 0,
  "kannibaliseringsrisiko": "ingen"/"lav"/"middel"/"høj",
  "hoering_aktiv": true/false,
  "bebyggelsesprocent": null,
  "max_bygningshojde_m": null,
  "max_etager": null,
  "parkeringsnorm": null,
  "planlagte_boliger": null,
  "tidshorisont": null,
  "varetilkorsel_mulighed": null,
  "specifikke_forbud": [],
  "sammenfattning": "2-3 sætninger om hvad planen indeholder og hvorfor den er/ikke er relevant",
  "aktion": "Undersøg nærmere"/"Følg op ved vedtagelse"/"Ikke relevant — arkivér",
  "flags": []
}}"""

    response = requests.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/planscanner",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.1
        },
        timeout=60
    )
    response.raise_for_status()

    text = response.json()["choices"][0]["message"]["content"].strip()
    text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)
