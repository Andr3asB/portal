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

Wunsch #121: Unterseite /a/tvb/<token>/kader zeigt den Kader mit
statistischen Werten je Spieler. handball.net hat dafuer KEINEN Endpunkt
(alle Widget-Typen durchprobiert, nur table/schedule/team-schedule
existieren). Quelle ist stattdessen die HPI-API der Handball-Bundesliga
(`hpi.handball-bundesliga.de/api/...`, ebenfalls unauthentifiziert) - der
"Handball Performance Index" ist die offizielle Leistungskennzahl der HBL,
gefunden ueber das Statistik-Dashboard auf opel-hbl.de (dort per
`hpi.handball-bundesliga.de/js/widget.js` mit `data-tournament="1"`
eingebunden). Zwei Aufrufe: `/api/tournament/1` liefert die Saisonliste,
`/api/index/season/<id>` alle Spieler der Liga samt HPI-Werten; TVB wird
ueber `team.sportradar_id == 6272` herausgefiltert - dieselbe Sportradar-ID,
die auch in _TEAM_ID/_CLUB_SR_ID oben steckt, also kein zweites,
unabhaengiges Vereins-Mapping.

Drei bewusste Entscheidungen dabei:
- Die HPI-Liste enthaelt nur Spieler, die auch tatsaechlich gespielt haben.
  Eine frisch begonnene Saison hat deshalb gar keine Eintraege. Deshalb
  `_kader_saison_waehlen()`: es wird die NEUESTE Saison genommen, die
  ueberhaupt TVB-Spieler liefert - zu Saisonbeginn also noch die
  Vorsaison. Der Saisonname steht deshalb sichtbar ueber der Tabelle, damit
  nie unklar ist, worauf sich die Werte beziehen (Neuzugaenge fehlen dann
  noch, Abgaenge sind noch drin - das laesst sich ohne echte Kaderquelle
  nicht besser loesen).
- Die Antwort von `/api/index/season/<id>` ist ~400 KB (alle ~390
  Liga-Spieler), von denen wir 22 brauchen. Deshalb wird der Kader in
  `tvb_kader` zwischengespeichert und nur alle `_KADER_MAX_ALTER_STUNDEN`
  Stunden neu geholt - anders als bei den Spielen oben, wo die Antworten
  klein sind und jeder Aufruf frisch laden kann. Beim Neuladen wird die
  Tabelle geleert und neu gefuellt (ein Kader ist eine Momentaufnahme -
  wer weg ist, soll verschwinden; kein UPSERT wie bei tvb_spiele).
- Spielerfotos liefert die API zwar mit (externes CDN
  images.dc.prod.cloud.atriumsports.com), werden aber bewusst NICHT
  eingebunden: das Portal laedt grundsaetzlich nichts von fremden Hosts
  (siehe CLAUDE.md und Wunsch #119), und jedes Foto wuerde die IP-Adressen
  der Familie an einen Dritt-Server melden.
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

# Wunsch #121: HPI-API der HBL (andere Quelle als oben, siehe Docstring).
# _HPI_TURNIER=1 ist die 1. Bundesliga der Maenner (aus data-tournament="1"
# auf opel-hbl.de), _CLUB_SR_ID die Sportradar-Vereins-ID des TVB - dieselbe
# 6272 wie in _TEAM_ID, dort nur zusaetzlich um die Saison-ID ergaenzt.
_HPI_BASE      = "https://hpi.handball-bundesliga.de/api"
_HPI_TURNIER   = 1
_CLUB_SR_ID    = 6272
_KADER_MAX_ALTER_STUNDEN = 6

# Die HPI-API liefert Positionen englisch. Reihenfolge = Anzeigereihenfolge
# auf der Kaderseite (Tor zuerst, dann von links nach rechts, Kreis zuletzt) -
# die uebliche Sortierung eines Handball-Kaders.
_POSITIONEN = [
    ("Goalkeeper",  "Tor"),
    ("Left Wing",   "Linksaußen"),
    ("Left Back",   "Rückraum links"),
    ("Centre Back", "Rückraum Mitte"),
    ("Right Back",  "Rückraum rechts"),
    ("Right Wing",  "Rechtsaußen"),
    ("Pivot",       "Kreisläufer"),
]


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


def _hpi_get(pfad):
    """Ruft einen HPI-Endpunkt der HBL ab. None bei Fehler/Timeout."""
    req = urllib.request.Request(
        f"{_HPI_BASE}/{pfad}",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
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


def _kader_saison_waehlen():
    """Neueste Saison, die ueberhaupt TVB-Spieler liefert (siehe Docstring).

    Gibt (saison_name, [spieler-rohdaten]) zurueck oder (None, None), wenn
    die HPI-API nicht erreichbar ist bzw. gar keine Saison Daten hat."""
    turnier = _hpi_get(f"tournament/{_HPI_TURNIER}")
    if not turnier:
        return None, None
    saisons = (turnier.get("data") or {}).get("seasons") or []
    # Die API liefert aufsteigend (aelteste zuerst) - rueckwaerts durchgehen,
    # damit die aktuelle Saison gewinnt, sobald sie Daten hat.
    for saison in reversed(saisons):
        antwort = _hpi_get(f"index/season/{saison['id']}")
        if not antwort:
            continue
        spieler = [
            s for s in (antwort.get("data") or [])
            if (s.get("team") or {}).get("sportradar_id") == _CLUB_SR_ID
        ]
        if spieler:
            return saison.get("name") or saison.get("year") or "", spieler
    return None, None


def _kader_speichern(db, saison_name, spieler_roh):
    """Ersetzt den gespeicherten Kader komplett - ein Kader ist eine
    Momentaufnahme, Abgaenge sollen verschwinden (kein UPSERT)."""
    db.execute("DELETE FROM tvb_kader")
    for s in spieler_roh:
        index = s.get("index") or {}
        db.execute("""
            INSERT INTO tvb_kader(spieler_id, vorname, nachname, position,
                                  hpi_schnitt, hpi_bestwert, hpi_letzter, hpi_trend,
                                  spieltage, aktionen, saison_name, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
        """, (
            s.get("id"), s.get("firstname") or "", s.get("lastname") or "",
            s.get("position"),
            index.get("avg"), index.get("max"), index.get("last"), index.get("trend"),
            index.get("matchdays"), index.get("events"), saison_name,
        ))
    db.commit()


def _kader_ist_frisch(db):
    zeile = db.execute("""
        SELECT 1 FROM tvb_kader
        WHERE aktualisiert_am > datetime('now', ?)
        LIMIT 1
    """, (f"-{_KADER_MAX_ALTER_STUNDEN} hours",)).fetchone()
    return zeile is not None


def _kader_gruppiert(db):
    """Gespeicherten Kader nach Position gruppiert, innerhalb der Gruppe nach
    HPI-Schnitt absteigend. Unbekannte Positionen landen in "Weitere"."""
    zeilen = [dict(z) for z in db.execute(
        "SELECT * FROM tvb_kader ORDER BY hpi_schnitt DESC"
    ).fetchall()]

    gruppen = []
    for engl, deutsch in _POSITIONEN:
        spieler = [z for z in zeilen if z["position"] == engl]
        if spieler:
            gruppen.append({"name": deutsch, "spieler": spieler})
    bekannt = {engl for engl, _ in _POSITIONEN}
    rest = [z for z in zeilen if z["position"] not in bekannt]
    if rest:
        gruppen.append({"name": "Weitere", "spieler": rest})
    return gruppen


@bp.route("/a/tvb/<token>/kader")
def kader(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    db = get_db()
    if not _kader_ist_frisch(db):
        saison_name, spieler_roh = _kader_saison_waehlen()
        if spieler_roh:
            _kader_speichern(db, saison_name, spieler_roh)

    gruppen = _kader_gruppiert(db)
    saison_zeile = db.execute("SELECT saison_name FROM tvb_kader LIMIT 1").fetchone()

    return render_template("tvb_kader.html",
        user=user, token=token, farbe=user["farbe"],
        gruppen=gruppen,
        saison_name=saison_zeile["saison_name"] if saison_zeile else None,
        anzahl=sum(len(g["spieler"]) for g in gruppen),
    )


def init_app(app):
    app.register_blueprint(bp)
