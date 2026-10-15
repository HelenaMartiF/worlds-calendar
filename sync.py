"""Sincronitza els partits del Mundial de LoL (Worlds) amb un Google Calendar.

Llegeix el calendari de l'API pública de lolesports.com i crea o actualitza un
esdeveniment per partit. Cada esdeveniment té un ID fix derivat de l'ID del
partit, així que executar-lo moltes vegades no crea duplicats: només actualitza
el que ha canviat (equips que deixen de ser "TBD", canvis d'hora, resultats).

Ús:
    python sync.py --dry-run     # mostra què faria, sense tocar el calendari
    python sync.py               # sincronitza de veritat

Variables d'entorn:
    GOOGLE_CALENDAR_ID           ID del calendari dedicat (obligatori si no és dry-run)
    GOOGLE_SERVICE_ACCOUNT_JSON  contingut del JSON de la service account
    SHOW_RESULTS                 "true" per posar el resultat al títol (spoilers!)
    TOURNAMENT_SLUG              per defecte, el Worlds més recent (p. ex. worlds_2026)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import requests

API = "https://esports-api.lolesports.com/persisted/gw"
# Clau pública que fa servir la mateixa web de lolesports.com
API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
WORLDS_LEAGUE_ID = "98767975604431411"
EVENT_ID_PREFIX = "lol"  # els IDs de Google només admeten a-v i 0-9

# Durada aproximada d'una sèrie segons el format
HOURS_PER_BEST_OF = {1: 1, 3: 3, 5: 5}


def api_get(endpoint, **params):
    params["hl"] = "es-ES"
    r = requests.get(f"{API}/{endpoint}", params=params, headers={"x-api-key": API_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()["data"]


def current_tournament(slug=None):
    tournaments = api_get("getTournamentsForLeague", leagueId=WORLDS_LEAGUE_ID)["leagues"][0]["tournaments"]
    if slug:
        return next(t for t in tournaments if t["slug"] == slug)
    return max(tournaments, key=lambda t: t["startDate"])


def fetch_matches(tournament):
    """Retorna tots els partits del torneig, recorrent totes les pàgines de l'API."""
    first = api_get("getSchedule", leagueId=WORLDS_LEAGUE_ID)["schedule"]
    events = list(first["events"])
    for direction in ("older", "newer"):
        token = first["pages"][direction]
        while token:
            page = api_get("getSchedule", leagueId=WORLDS_LEAGUE_ID, pageToken=token)["schedule"]
            events.extend(page["events"])
            token = page["pages"][direction]
            # Les pàgines antigues ja són d'edicions anteriors: parem quan sortim del torneig
            if direction == "older" and page["events"] and page["events"][0]["startTime"] < tournament["startDate"]:
                break

    start, end = tournament["startDate"], tournament["endDate"] + "T23:59:59Z"
    seen, matches = set(), []
    for e in sorted(events, key=lambda e: e["startTime"]):
        m = e.get("match")
        if e.get("type") != "match" or not m or not (start <= e["startTime"] <= end) or m["id"] in seen:
            continue
        seen.add(m["id"])
        matches.append(e)
    return matches


def to_calendar_event(e, show_results):
    m = e["match"]
    teams = m["teams"]
    best_of = m.get("strategy", {}).get("count", 1)
    names = [t["code"] if t["code"] != "TBD" else "TBD" for t in teams]
    title = f"{names[0]} vs {names[1]}"
    if show_results and e["state"] == "completed":
        title = f"{names[0]} {teams[0]['result']['gameWins']}–{teams[1]['result']['gameWins']} {names[1]}"

    start = datetime.fromisoformat(e["startTime"].replace("Z", "+00:00"))
    end = start + timedelta(hours=HOURS_PER_BEST_OF.get(best_of, best_of))
    full_names = " vs ".join(t["name"] for t in teams)
    return {
        "id": f"{EVENT_ID_PREFIX}{m['id']}",
        "summary": f"🏆 Worlds · {e.get('blockName', '')} · {title} (Bo{best_of})",
        "description": f"{full_names}\nFase: {e.get('blockName', '')} · Bo{best_of}\n\nEn directe: https://lolesports.com/live",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "status": "confirmed",
        "transparency": "transparent",  # no et marca com a "ocupada"
        "source": {"title": "LoL Esports", "url": "https://lolesports.com/schedule?leagues=worlds"},
    }


def needs_update(existing, wanted):
    def norm(dt):
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))

    return (
        existing.get("status") != "confirmed"
        or existing.get("summary") != wanted["summary"]
        or existing.get("description") != wanted["description"]
        or norm(existing["start"]["dateTime"]) != norm(wanted["start"]["dateTime"])
        or norm(existing["end"]["dateTime"]) != norm(wanted["end"]["dateTime"])
    )


def calendar_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar.events"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def sync(wanted_events, calendar_id, service):
    from googleapiclient.errors import HttpError

    created = updated = unchanged = 0
    for wanted in wanted_events:
        events = service.events()
        try:
            existing = events.get(calendarId=calendar_id, eventId=wanted["id"]).execute()
        except HttpError as err:
            if err.resp.status != 404:
                raise
            events.insert(calendarId=calendar_id, body=wanted).execute()
            created += 1
            print(f"  + {wanted['summary']}")
            continue
        # Si l'has esborrat a mà, queda "cancelled": el tornem a activar
        if needs_update(existing, wanted):
            events.update(calendarId=calendar_id, eventId=wanted["id"], body=wanted).execute()
            updated += 1
            print(f"  ~ {wanted['summary']}")
        else:
            unchanged += 1
    print(f"Creats: {created} · Actualitzats: {updated} · Sense canvis: {unchanged}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="no toca el calendari, només mostra els partits")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no sap pintar emojis

    tournament = current_tournament(os.environ.get("TOURNAMENT_SLUG") or None)
    show_results = os.environ.get("SHOW_RESULTS", "").lower() == "true"
    wanted = [to_calendar_event(e, show_results) for e in fetch_matches(tournament)]
    print(f"{tournament['slug']}: {len(wanted)} partits")

    if args.dry_run:
        for w in wanted:
            print(f"  {w['start']['dateTime']}  {w['summary']}")
        return

    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not calendar_id or not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        sys.exit("Falten GOOGLE_CALENDAR_ID o GOOGLE_SERVICE_ACCOUNT_JSON")
    sync(wanted, calendar_id, calendar_service())


if __name__ == "__main__":
    main()
