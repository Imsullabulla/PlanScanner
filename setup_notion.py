"""
Opsæt Notion-databasen med alle nødvendige kolonner.
Kør én gang: python setup_notion.py
"""
import pathlib
from dotenv import load_dotenv
import requests, os

load_dotenv(dotenv_path=pathlib.Path(__file__).parent / ".env", override=True)

HEADERS = {
    "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}
DB_ID = os.environ["NOTION_DATABASE_ID"]

NEW_PROPERTIES = {
    "Relevant": {"checkbox": {}},
    "Plantype": {"rich_text": {}},
    "Prioritet": {
        "select": {
            "options": [
                {"name": "Høj", "color": "red"},
                {"name": "Middel", "color": "yellow"},
                {"name": "Lav", "color": "green"},
                {"name": "Ikke relevant", "color": "gray"}
            ]
        }
    },
    "Format": {
        "multi_select": {
            "options": [
                {"name": "NETTO", "color": "blue"},
                {"name": "FØTEX", "color": "orange"},
                {"name": "BILKA", "color": "purple"}
            ]
        }
    },
    "Kommune": {"rich_text": {}},
    "Sammenfatning": {"rich_text": {}},
    "Aktion": {
        "select": {
            "options": [
                {"name": "Undersøg nærmere", "color": "red"},
                {"name": "Følg op ved vedtagelse", "color": "yellow"},
                {"name": "Ikke relevant — arkivér", "color": "gray"}
            ]
        }
    },
    "Høringsfrist": {"date": {}},
    "Population": {"number": {"format": "number"}},
    "Konkurrenter": {"number": {"format": "number"}},
    "Kannibaliseringsrisiko": {
        "select": {
            "options": [
                {"name": "Ingen", "color": "green"},
                {"name": "Lav", "color": "blue"},
                {"name": "Middel", "color": "yellow"},
                {"name": "Høj", "color": "red"}
            ]
        }
    },
    "PDF-link": {"url": {}},
    "Scannet": {"date": {}}
}

r = requests.patch(
    f"https://api.notion.com/v1/databases/{DB_ID}",
    headers=HEADERS,
    json={"properties": NEW_PROPERTIES},
    timeout=15
)

if r.status_code == 200:
    props = list(r.json().get("properties", {}).keys())
    print(f"Database opdateret. Kolonner: {props}")
else:
    print(f"Fejl {r.status_code}:", r.text[:500])
