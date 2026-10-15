"""Sincronitza els partits del Mundial de LoL (Worlds) amb un Google Calendar.

Llegeix el calendari de l'API pública de lolesports.com i crea o actualitza un
esdeveniment per partit. Cada esdeveniment té un ID fix derivat de l'ID del
partit, així que executar-lo moltes vegades no crea duplicats: només actualitza
el que ha canviat (equips que deixen de ser "TBD", canvis d'hora, resultats).

Els partits de l'equip preferit (T1) es destaquen: color vermell, títol en
majúscules i un avís de "tot el dia" a dalt de tot. Si hi ha un calendari propi
per a l'equip (GOOGLE_FAVORITE_CALENDAR_ID), aquests partits hi van a parar
(i desapareixen del general), perquè així se li poden posar notificacions pròpies.

Ús:
    python sync.py --dry-run     # mostra què faria, sense tocar el calendari
    python sync.py               # sincronitza de veritat

Variables d'entorn:
    GOOGLE_CALENDAR_ID           ID del calendari dedicat (obligatori si no és dry-run)
    GOOGLE_FAVORITE_CALENDAR_ID  (opcional) calendari només per als partits de l'equip preferit
    GOOGLE_SERVICE_ACCOUNT_JSON  contingut del JSON de la service account
    FAVORITE_TEAM                codi de l'equip preferit (per defecte T1)
    SHOW_RESULTS                 "true" per posar el resultat al títol (spoilers!)
    TOURNAMENT_SLUG              per defecte, el Worlds més recent (p. ex. worlds_2026)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

API = "https://esports-api.lolesports.com/persisted/gw"
# Clau pública que fa servir la mateixa web de lolesports.com
API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
WORLDS_LEAGUE_ID = "98767975604431411"
EVENT_ID_PREFIX = "lol"  # els IDs de Google només admeten a-v i 0-9
BANNER_ID_SUFFIX = "d"   # l'avís de "tot el dia" d'un partit: lol<id>d
LOCAL_TZ = ZoneInfo("Europe/Madrid")

# Colors de Google Calendar: https://developers.google.com/calendar/api/v3/reference/colors
FAVORITE_COLOR_ID = "11"  # "Tomate", el vermell més intens

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


def is_favorite(e, team):
    return any(t["code"] == team for t in e["match"]["teams"])


def to_calendar_events(e, show_results, favorite_team):
    """Retorna l'esdeveniment del partit i, si juga l'equip preferit, l'avís de tot el dia."""
    m = e["match"]
    teams = m["teams"]
    best_of = m.get("strategy", {}).get("count", 1)
    phase = e.get("blockName", "")
    names = [t["code"] for t in teams]
    title = f"{names[0]} vs {names[1]}"
    if show_results and e["state"] == "completed":
        title = f"{names[0]} {teams[0]['result']['gameWins']}–{teams[1]['result']['gameWins']} {names[1]}"

    start = datetime.fromisoformat(e["startTime"].replace("Z", "+00:00"))
    end = start + timedelta(hours=HOURS_PER_BEST_OF.get(best_of, best_of))
    full_names = " vs ".join(t["name"] for t in teams)
    match_event = {
        "id": f"{EVENT_ID_PREFIX}{m['id']}",
        "summary": f"🏆 Worlds · {phase} · {title} (Bo{best_of})",
        "description": f"{full_names}\nFase: {phase} · Bo{best_of}\n\nEn directe: https://lolesports.com/live",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "status": "confirmed",
        "transparency": "transparent",  # no et marca com a "ocupada"
        "source": {"title": "LoL Esports", "url": "https://lolesports.com/schedule?leagues=worlds"},
    }
    if not is_favorite(e, favorite_team):
        return [match_event]

    rival = next((t["code"] for t in teams if t["code"] != favorite_team), favorite_team)
    local = start.astimezone(LOCAL_TZ)
    match_event.update(
        summary=f"🔴🔴 ¡¡JUEGA {favorite_team}!! {title.upper()} · {phase} (Bo{best_of}) 🔴🔴",
        colorId=FAVORITE_COLOR_ID,
        transparency="opaque",  # aquest sí que ocupa l'agenda: no hi ha res més important
    )
    banner = {
        "id": f"{match_event['id']}{BANNER_ID_SUFFIX}",
        "summary": f"🔴🔴🔴 HOY JUEGA {favorite_team} · {local:%H:%M} vs {rival} 🔴🔴🔴",
        "description": match_event["description"],
        "start": {"date": local.date().isoformat()},
        "end": {"date": (local.date() + timedelta(days=1)).isoformat()},
        "status": "confirmed",
        "colorId": FAVORITE_COLOR_ID,
        "transparency": "transparent",
        "source": match_event["source"],
    }
    return [match_event, banner]


def needs_update(existing, wanted):
    def when(field):
        value = field.get("dateTime") or field.get("date")
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else value

    return (
        existing.get("status") != "confirmed"
        or existing.get("summary") != wanted["summary"]
        or existing.get("description") != wanted["description"]
        or existing.get("colorId") != wanted.get("colorId")
        or existing.get("transparency", "opaque") != wanted["transparency"]
        or when(existing["start"]) != when(wanted["start"])
        or when(existing["end"]) != when(wanted["end"])
    )


def calendar_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar.events"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class Calendar:
    """Operacions sobre un calendari concret, comptant què s'ha fet."""

    def __init__(self, service, calendar_id):
        self.events = service.events()
        self.id = calendar_id
        self.stats = {"creats": 0, "actualitzats": 0, "sense canvis": 0, "esborrats": 0}

    def _get(self, event_id):
        from googleapiclient.errors import HttpError

        try:
            return self.events.get(calendarId=self.id, eventId=event_id).execute()
        except HttpError as err:
            if err.resp.status in (404, 410):
                return None
            raise

    def upsert(self, wanted):
        existing = self._get(wanted["id"])
        if existing is None:
            self.events.insert(calendarId=self.id, body=wanted).execute()
            self.stats["creats"] += 1
            print(f"  + {wanted['summary']}")
        # Si l'has esborrat a mà, queda "cancelled": el tornem a activar
        elif needs_update(existing, wanted):
            self.events.update(calendarId=self.id, eventId=wanted["id"], body=wanted).execute()
            self.stats["actualitzats"] += 1
            print(f"  ~ {wanted['summary']}")
        else:
            self.stats["sense canvis"] += 1

    def remove(self, event_id):
        existing = self._get(event_id)
        if existing and existing.get("status") != "cancelled":
            self.events.delete(calendarId=self.id, eventId=event_id).execute()
            self.stats["esborrats"] += 1
            print(f"  - {existing.get('summary')}")


def sync(matches, show_results, favorite_team, general, favorite):
    """general/favorite: objectes Calendar (favorite pot ser el mateix que general)."""
    for e in matches:
        wanted = to_calendar_events(e, show_results, favorite_team)
        target, other = (favorite, general) if is_favorite(e, favorite_team) else (general, favorite)
        for event in wanted:
            target.upsert(event)
        if other is not target:
            # Un partit que ha canviat de calendari (p. ex. un TBD que resulta ser de T1)
            match_id = wanted[0]["id"]
            for event_id in (match_id, match_id + BANNER_ID_SUFFIX):
                other.remove(event_id)
        elif len(wanted) == 1:
            # Ja no és de l'equip preferit (no hauria de passar): treiem l'avís si hi era
            target.remove(wanted[0]["id"] + BANNER_ID_SUFFIX)

    for name, cal in (("General", general), (favorite_team, favorite)):
        print(f"[{name}] " + " · ".join(f"{k}: {v}" for k, v in cal.stats.items()))
        if favorite is general:
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="no toca el calendari, només mostra els partits")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # la consola de Windows no sap pintar emojis

    tournament = current_tournament(os.environ.get("TOURNAMENT_SLUG") or None)
    show_results = os.environ.get("SHOW_RESULTS", "").lower() == "true"
    favorite_team = os.environ.get("FAVORITE_TEAM") or "T1"
    matches = fetch_matches(tournament)
    print(f"{tournament['slug']}: {len(matches)} partits · equip preferit: {favorite_team}")

    if args.dry_run:
        for e in matches:
            for w in to_calendar_events(e, show_results, favorite_team):
                when = w["start"].get("dateTime") or w["start"]["date"] + " (tot el dia)"
                print(f"  {when}  {w['summary']}")
        return

    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not calendar_id or not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        sys.exit("Falten GOOGLE_CALENDAR_ID o GOOGLE_SERVICE_ACCOUNT_JSON")
    service = calendar_service()
    general = Calendar(service, calendar_id)
    favorite_id = os.environ.get("GOOGLE_FAVORITE_CALENDAR_ID")
    favorite = Calendar(service, favorite_id) if favorite_id else general
    sync(matches, show_results, favorite_team, general, favorite)


if __name__ == "__main__":
    main()
