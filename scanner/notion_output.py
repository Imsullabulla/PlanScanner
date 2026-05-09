import requests
import os

NOTION_VERSION = "2022-06-28"

PRIORITY_COLORS = {"høj": "red", "middel": "yellow", "lav": "green", "ikke relevant": "gray"}
ACTION_OPTIONS = [
    "Undersøg nærmere",
    "Følg op ved vedtagelse",
    "Ikke relevant — arkivér"
]


def _resolve_aktion(aktion: str) -> str:
    """Keyword-based matching so minor AI phrasing differences don't fall to the default."""
    al = aktion.lower()
    if any(k in al for k in ("undersøg", "undersoeg", "undersog")):
        return ACTION_OPTIONS[0]
    if any(k in al for k in ("følg", "foelg", "folg op")):
        return ACTION_OPTIONS[1]
    return ACTION_OPTIONS[2]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION
    }


def write_plan_to_notion(plan: dict, assessment: dict,
                          population: int, competitors: list,
                          title_prefix: str = ""):
    """
    Skriv en plan som en ny side i Notion-databasen.
    title_prefix bruges til at markere testposter, fx "TEST: ".
    """
    props = plan["properties"]
    priority = assessment.get("prioritet", "lav")
    formats = assessment.get("format_match", [])
    hearing_deadline = props.get("datoslut")
    aktion = assessment.get("aktion", "Ikke relevant — arkivér")
    relevant = assessment.get("relevant", False)
    plantype = props.get("anvendelsegenerel", "")
    plannavn = props.get("plannavn", "Ukendt plan")

    if title_prefix:
        plannavn = f"{title_prefix}{plannavn}"

    page_properties = {
        "Plannavn": {
            "title": [{"text": {"content": plannavn}}]
        },
        "Relevant": {"checkbox": relevant},
        "Plantype": {
            "rich_text": [{"text": {"content": plantype}}]
        },
        "Prioritet": {
            "select": {
                "name": priority.capitalize(),
                "color": PRIORITY_COLORS.get(priority, "default")
            }
        },
        "Format": {
            "multi_select": [{"name": f} for f in formats]
        },
        "Kommune": {
            "rich_text": [{"text": {"content": props.get("kommunenavn", "")}}]
        },
        "Sammenfatning": {
            "rich_text": [{"text": {"content": assessment.get("sammenfattning", "")[:2000]}}]
        },
        "Aktion": {
            "select": {"name": _resolve_aktion(aktion)}
        },
        "Population": {"number": population},
        "Konkurrenter": {"number": len(competitors)},
        "Kannibaliseringsrisiko": {
            "select": {"name": assessment.get("kannibaliseringsrisiko", "ingen").capitalize()}
        },
        "Scannet": {
            "date": {"start": __import__("datetime").date.today().isoformat()}
        }
    }

    if hearing_deadline:
        page_properties["Høringsfrist"] = {"date": {"start": str(hearing_deadline)}}

    pdf_url = props.get("doklink", "")
    if pdf_url and "null" not in pdf_url.lower():
        page_properties["PDF-link"] = {"url": pdf_url}

    response = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_headers(),
        json={
            "parent": {"database_id": os.environ["NOTION_DATABASE_ID"]},
            "properties": page_properties
        },
        timeout=15
    )
    response.raise_for_status()
    return response.json().get("url", "")
