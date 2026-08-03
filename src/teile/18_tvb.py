"""
TVB-App – Spiele, Ergebnisse und Tabelle des TVB Stuttgart (Handball-Bundesliga).
URL-Präfix: /a/tvb/<token>/

Wunsch #120: Daten kommen live von handball.net – dem offiziellen Datenportal
des Deutschen Handballbundes (DHB), das u.a. die "Spielplan-Widgets" für
Vereins-Websites betreibt (auch TVB Stuttgarts eigene Website nutzt exakt
dieses System, dort aber ohne Fallback-Daten sichtbar - "Loading ..." bzw.
Platzhalter "99/99" im HTML, wenn man die Seite ohne JavaScript abruft).
Es gibt keine offizielle, dokumentierte Public API dafür; die hier genutzten
Endpunkte sind die, die handball.net selbst für sein eigenes einbettbares
"Spielplan-Widget"/"Tabelle-Widget" nutzt (unauthentifiziert, wird von
JavaScript auf tausenden Vereinsseiten so aufgerufen) - gefunden durch
Analyse von https://www.handball.net/widgets/embed/v1.js. Das Muster folgt
_hae_workouts() in 14_sportschau.py: On-the-fly-Abruf mit Timeout, bei
Fehler/Nichterreichbarkeit ein "fehler"-Flag statt eines Crashs.

Zwei Einschränkungen der Datenquelle, live geprüft:
- Das Tabellen-Widget liefert immer die VOLLSTÄNDIGE, aktuelle Tabelle -
  "Tabelle immer aktuell" (Wunsch-Text) ist damit trivial erfüllt.
- Das Team-Spielplan-Widget liefert laut handball.net-eigener Doku nur die
  naechsten ~3 Spiele, keinen kompletten Saisonkalender und (unklar, da zur
  Implementierungszeit noch keine Spiele der neuen Saison gelaufen sind) evtl.
  auch keine vergangenen Ergebnisse mehr, sobald ein Spieltag vorbei ist.
  Deshalb: jedes TVB-Spiel, das beim Seitenaufruf gesehen wird (aus dem
  Team-Widget UND aus dem Liga-Spielplan-Widget, das den jeweils aktuellen
  Spieltag aller 9 Begegnungen zeigt), wird in tvb_spiele gespeichert/
  aktualisiert (id = handball.net-Spiel-ID). So bleiben einmal gesehene
  Ergebnisse dauerhaft sichtbar, selbst wenn handball.net sie aus dem
  Widget-Fenster herausrollt. Einzige Lücke: ein Spieltag, waehrend dessen
  NIEMAND die App oeffnet, koennte so verpasst werden - fuer eine
  Familien-App akzeptabel, kein Cron-Job dafuer eingerichtet (siehe CLAUDE.md:
  keine Extra-Infrastruktur fuer hypothetische Faelle).
"""
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template
from teile.kern import grant as check_grant, get_db

bp  = Blueprint("tvb_app", __name__)
APP = "tvb"

_TZ = ZoneInfo("Europe/Berlin")

# handball.net-interne IDs fuer TVB Stuttgart (Herren) und die 1. Bundesliga
# (DAIKIN HBL), Saison 2026/27 - gefunden ueber die Vereinsseite
# https://www.handball.net/vereine/sr.competitor.6272 . Aendern sich vermutlich
# nur bei einem Vereins-Rebrand oder einer neuen Saison mit neuer Team-ID.
_TEAM_ID       = "sr.competitor.6272-143352"
_TOURNAMENT_ID = "sr.competition.149"
_API_BASE      = "https://www.handball.net/a/sportdata/1/widgets"


def _handball_net_get(pfad):
    """Ruft einen handball.net-Widget-Endpunkt ab. None bei Fehler/Timeout."""
    req = urllib.request.Request(
        f"{_API_BASE}/{pfad}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _spiel_aus_roh(roh):
    """Wandelt ein rohes handball.net-Spiel-JSON in unser Anzeigeformat um."""
    anstoss_utc = datetime.fromtimestamp(roh["startsAt"] / 1000, tz=timezone.utc)
    return {
        "id":        roh["id"],
        "spieltag":  (roh.get("round") or {}).get("name"),
        "heim":      roh["homeTeam"]["name"],
        "gast":      roh["awayTeam"]["name"],
        "heim_ist_tvb": roh["homeTeam"]["id"] == _TEAM_ID,
        "gast_ist_tvb": roh["awayTeam"]["id"] == _TEAM_ID,
        "heim_tore": roh.get("homeGoals"),
        "gast_tore": roh.get("awayGoals"),
        "anstoss":   anstoss_utc.astimezone(_TZ).isoformat(),
        "ort":       (roh.get("field") or {}).get("name"),
        "status":    roh.get("state") or "Pre",
    }


def _ist_tvb_spiel(roh):
    return roh["homeTeam"]["id"] == _TEAM_ID or roh["awayTeam"]["id"] == _TEAM_ID


def _tvb_spiele_aktualisieren(db, spiele):
    """UPSERT gesehener TVB-Spiele nach tvb_spiele - siehe Docstring oben."""
    for s in spiele:
        db.execute("""
            INSERT INTO tvb_spiele(id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                spieltag=excluded.spieltag, heim_tore=excluded.heim_tore, gast_tore=excluded.gast_tore,
                status=excluded.status, aktualisiert_am=excluded.aktualisiert_am
        """, (s["id"], s["spieltag"], s["heim"], s["gast"], s["heim_tore"], s["gast_tore"],
              s["anstoss"], s["ort"], s["status"]))
    db.commit()


@bp.route("/a/tvb/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    db = get_db()

    team_antwort = _handball_net_get(f"team/{_TEAM_ID}/team-schedule")
    liga_antwort = _handball_net_get(f"tournament/{_TOURNAMENT_ID}/schedule")
    tabelle_antwort = _handball_net_get(f"tournament/{_TOURNAMENT_ID}/table")

    fehler_spiele = team_antwort is None and liga_antwort is None
    fehler_tabelle = tabelle_antwort is None

    gesehene_tvb_spiele = []
    for antwort in (team_antwort, liga_antwort):
        if not antwort:
            continue
        for roh in antwort["schedule"]["data"]:
            if _ist_tvb_spiel(roh):
                gesehene_tvb_spiele.append(_spiel_aus_roh(roh))
    if gesehene_tvb_spiele:
        _tvb_spiele_aktualisieren(db, gesehene_tvb_spiele)

    gespeicherte = db.execute(
        "SELECT * FROM tvb_spiele ORDER BY anstoss ASC"
    ).fetchall()
    jetzt_iso = datetime.now(_TZ).isoformat()
    vergangene, kommende = [], []
    for s in gespeicherte:
        (vergangene if s["status"] == "Ended" or s["anstoss"] < jetzt_iso else kommende).append(dict(s))
    vergangene.reverse()  # neueste zuerst

    tabelle = None
    if tabelle_antwort:
        tabelle = [
            {
                "rang": r["rank"],
                "team": r["team"]["name"],
                "hervorgehoben": r["team"]["id"].startswith("sr.competitor.6272"),
                "spiele": r["games"],
                "siege": r["wins"],
                "unentschieden": r["draws"],
                "niederlagen": r["losses"],
                "tore": r["goals"],
                "gegentore": r["goalsAgainst"],
                "tordifferenz": r["goalDifference"],
                "punkte": r["points"],
            }
            for r in tabelle_antwort["table"]["rows"]
        ]

    return render_template("tvb.html",
        user=user, token=token, farbe=user["farbe"],
        fehler_spiele=fehler_spiele, fehler_tabelle=fehler_tabelle,
        vergangene=vergangene, kommende=kommende, tabelle=tabelle,
    )


def init_app(app):
    app.register_blueprint(bp)
