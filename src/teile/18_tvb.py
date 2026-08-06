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

Wunsch #122: Umschalter fuer ALLE Mannschaften des Vereins, jede Seite
gleich aufgebaut. Wichtig: die Profis und der Amateur-/Jugendbereich sind
auf handball.net ZWEI VERSCHIEDENE Vereinsobjekte -
`sr.competitor.6272` ("TVB Stuttgart", nur Profis, 2 Teams: HBL + DHB-Pokal)
und `handball4all.wuerttemberg.131` ("TV Bittenfeld", 17 Teams: 2./3./4.
Herren plus die komplette Jugend von der A- bis zur F-Jugend). Der
Umschalter fuehrt beide zusammen; die Profis stehen fest verdrahtet an
Position 0, der Rest kommt dynamisch dazu.

Die Team-Liste selbst gibt es NICHT als API - `club/<id>/teams` und
`.../mannschaften` liefern 404, nur `club/<id>/schedule` existiert und
zeigt lediglich Teams mit Spielen in den naechsten 14 Tagen (in der
Sommerpause also gar keine). Deshalb wird die Vereinsseite geparst
(Team-ID, Name, Liga-Bezeichnung stehen dort als HTML) und das Ergebnis in
`tvb_mannschaften` gespeichert - erneuert nur alle
_MANNSCHAFTEN_MAX_ALTER_STUNDEN Stunden, weil sich ein Mannschaftsbestand
allenfalls zum Saisonwechsel aendert. Faellt das Parsen aus (Seite
umgebaut, Netz weg), bleibt der zuletzt gespeicherte Stand stehen, statt
dass der Umschalter verschwindet.

Fuer die Tabelle braucht es zusaetzlich die Liga-ID. Die steht in den
Spieldaten (`tournament.id`), die in der Sommerpause aber leer sind -
deshalb zusaetzlich `_liga_id_der_mannschaft()`, das sie von der
/tabelle-Seite der Mannschaft holt. Dort stehen mehrere `/ligen/<id>`;
die eigene ist immer die `handball4all.*` (die `sportradar.dhbdata.*`
sind die immer gleichen Navigationslinks zu den Bundesligen) - an fuenf
Mannschaften quer durch alle Altersklassen gegengeprueft.

Zwei Abweichungen vom "immer gleich aufgebaut":
- Der Kader-Knopf erscheint nur bei den Profis. Der HPI (Wunsch #121) ist
  eine reine Bundesliga-Kennzahl, fuer Amateur-/Jugendmannschaften gibt es
  ihn schlicht nicht - ein Knopf auf eine garantiert leere Seite waere
  schlechter als keiner.
- Amateur- und Jugendligen veroeffentlichen ihre Tabelle erst, wenn die
  Saison laeuft; `table` ist bis dahin `null` (nicht etwa eine leere
  Liste). Das wird abgefangen und als "noch keine Tabelle" angezeigt.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, redirect, render_template, request
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
_HB_BASE       = "https://www.handball.net"

# Wunsch #122: Verein der Amateur-/Jugendmannschaften (anderes Vereinsobjekt
# als die Profis, siehe Docstring).
_AMATEUR_VEREIN_ID = "handball4all.wuerttemberg.131"
_MANNSCHAFTEN_MAX_ALTER_STUNDEN = 24

# Kurzlabels fuer den Umschalter aus der langen Liga-Bezeichnung bauen -
# "Stuttgart-Rems-Murr - maennliche B-Jugend Bezirksoberliga Staffel 2"
# wuerde als Knopfbeschriftung sonst die halbe Seite fuellen.
_ALTERSKLASSEN = [
    ("männliche A-Jugend", "mA"), ("männliche B-Jugend", "mB"),
    ("männliche C-Jugend", "mC"), ("männliche D-Jugend", "mD"),
    ("weibliche A-Jugend", "wA"),  ("weibliche B-Jugend", "wB"),
    ("weibliche C-Jugend", "wC"),  ("weibliche D-Jugend", "wD"),
    ("gemischte A-Jugend", "gA"),  ("gemischte B-Jugend", "gB"),
    ("gemischte C-Jugend", "gC"),  ("gemischte D-Jugend", "gD"),
    ("gemischte Jugend E", "gE"),  ("gemischte E-Jugend", "gE"),
    ("gemischte F-Jugend", "gF"),  ("männliche F-Jugend", "mF"),
    ("Männer", "Herren"),          ("Frauen", "Damen"),
]
_LIGA_STUFEN = [
    ("Bundesliga", "BL"), ("Verbandsliga", "VL"), ("Bezirksoberliga", "BOL"),
    ("Bezirksklasse", "BK"), ("Bezirksliga", "BZL"), ("Regionalliga", "RL"),
    ("Oberliga", "OL"), ("Landesliga", "LL"), ("Kreisliga", "KL"),
]

# Wunsch #123: Die Profis heissen "TVB Stuttgart", alle uebrigen Mannschaften
# laufen unter dem Stammverein "TV Bittenfeld" - der Kopf der Seite muss das
# zeigen, "Handball-Bundesliga" stimmt nur fuer die 1. Mannschaft.
_VEREIN_PROFIS  = "TVB Stuttgart"
_VEREIN_AMATEUR = "TV Bittenfeld"

# Wunsch #124: Anzeigenamen je Altersklassen-Kuerzel (das Kuerzel aus
# _ALTERSKLASSEN ist der stabile Schluessel in der DB - "gemischte Jugend E"
# und "gemischte E-Jugend" sind zwei Schreibweisen derselben Klasse und
# muessen auf denselben Schluessel fallen, sonst waeren es zwei Haken).
_PROFI_KLASSE = "Profis"
_KLASSEN_NAMEN = {
    _PROFI_KLASSE: "Profis (1. Mannschaft)",
    "Herren": "Herren",           "Damen": "Damen",
    "mA": "männliche A-Jugend",   "mB": "männliche B-Jugend",
    "mC": "männliche C-Jugend",   "mD": "männliche D-Jugend",
    "mF": "männliche F-Jugend",
    "wA": "weibliche A-Jugend",   "wB": "weibliche B-Jugend",
    "wC": "weibliche C-Jugend",   "wD": "weibliche D-Jugend",
    "gA": "gemischte A-Jugend",   "gB": "gemischte B-Jugend",
    "gC": "gemischte C-Jugend",   "gD": "gemischte D-Jugend",
    "gE": "gemischte E-Jugend",   "gF": "gemischte F-Jugend",
}

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


def _hb_seite_holen(pfad):
    """Laedt eine handball.net-HTML-Seite (kein JSON-Endpunkt vorhanden,
    siehe Docstring). None bei Fehler/Timeout."""
    req = urllib.request.Request(
        f"{_HB_BASE}/{pfad}", headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def _liga_ohne_verband(liga):
    """Nur der eigentliche Ligateil - der Verband/Bezirk davor
    ("Stuttgart-Rems-Murr - …") interessiert weder im Kopf noch auf dem Knopf."""
    return (liga or "").split(" - ", 1)[-1]


def _altersklasse(liga):
    """Altersklassen-Kuerzel zur Liga ("mB", "gE", "Herren", …) oder None.
    Wunsch #124: zugleich der Schluessel, unter dem sich eine ganze Klasse
    ausblenden laesst."""
    rest = _liga_ohne_verband(liga).lower()
    for lang, kurz in _ALTERSKLASSEN:
        if lang.lower() in rest:
            return kurz
    return None


def _kurzlabel(liga, name):
    """Baut aus der langen Liga-Bezeichnung ein knappes Knopf-Label,
    z. B. "männliche B-Jugend Bezirksoberliga Staffel 2" -> "mB BOL 2"."""
    if not liga:
        return name
    rest = _liga_ohne_verband(liga)
    teile = []
    klasse = _altersklasse(liga)
    if klasse:
        teile.append(klasse)
    for lang, kurz in _LIGA_STUFEN:
        if lang.lower() in rest.lower():
            teile.append(kurz)
            break
    staffel = re.search(r"Staffel\s+(\d+)", rest)
    if staffel:
        teile.append(staffel.group(1))
    return " ".join(teile) if teile else rest[:24]


def _mannschaften_von_handball_net():
    """Parst die Vereinsseite und gibt [(team_id, name, liga)] zurueck.
    Leere Liste, wenn die Seite nicht erreichbar/nicht parsebar ist."""
    html = _hb_seite_holen(f"vereine/{_AMATEUR_VEREIN_ID}")
    if not html:
        return []
    muster = re.compile(
        r'href="/mannschaften/([A-Za-z0-9._-]+)/spielplan".*?'
        r'list-item-title">(.*?)</div>.*?'
        r'list-item-text">(.*?)</div>',
        re.S,
    )
    gefunden = []
    gesehen = set()
    for team_id, name, liga in muster.findall(html):
        if team_id in gesehen:
            continue
        gesehen.add(team_id)
        gefunden.append((
            team_id,
            re.sub(r"\s+", " ", name).strip(),
            re.sub(r"\s+", " ", liga).strip(),
        ))
    return gefunden


def _liga_id_der_mannschaft(team_id):
    """Liga-ID fuer die Tabelle. In der Sommerpause stehen keine Spiele zur
    Verfuegung, aus denen sie ableitbar waere - deshalb von der /tabelle-Seite
    der Mannschaft lesen. Die eigene Liga ist immer die `handball4all.*`
    (die `sportradar.dhbdata.*` sind die immer gleichen Navigationslinks)."""
    html = _hb_seite_holen(f"mannschaften/{team_id}/tabelle")
    if not html:
        return None
    treffer = re.findall(r"/ligen/(handball4all\.[A-Za-z0-9._-]+)", html)
    return treffer[0] if treffer else None


def _mannschaften_aktualisieren(db):
    """Baut die Mannschaftsliste neu auf (Profis fest, Rest von handball.net).
    Laesst den bestehenden Stand unangetastet, wenn nichts geladen werden
    konnte - besser ein veralteter Umschalter als gar keiner."""
    gefunden = _mannschaften_von_handball_net()
    if not gefunden:
        return

    db.execute("DELETE FROM tvb_mannschaften")
    db.execute("""
        INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse,
                                     turnier_id, position, ist_profi, aktualisiert_am)
        VALUES (?,?,?,?,?,?,?,1, datetime('now'))
    """, (_TEAM_ID, _VEREIN_PROFIS, "Handball-Bundesliga",
          "Profis", _PROFI_KLASSE, _TOURNAMENT_ID, 0))

    labels = {}
    for pos, (team_id, name, liga) in enumerate(gefunden, start=1):
        kurz = _kurzlabel(liga, name)
        # Mehrere Mannschaften koennen in derselben Liga/Staffel spielen
        # (z. B. zwei E-Jugend-Turniermannschaften) - dann durchnummerieren,
        # sonst waeren zwei Knoepfe nicht unterscheidbar.
        labels[kurz] = labels.get(kurz, 0) + 1
        if labels[kurz] > 1:
            kurz = f"{kurz} ({labels[kurz]})"
        # turnier_id bleibt hier absichtlich leer und wird erst geholt, wenn
        # die Mannschaft auch wirklich angesehen wird (_turnier_id_sichern):
        # sie kostet je Mannschaft einen eigenen Seitenabruf, 17 Stueck am
        # Stueck wuerden den Seitenaufbau desjenigen, der die Aktualisierung
        # ausloest, um etliche Sekunden verzoegern.
        db.execute("""
            INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse,
                                         turnier_id, position, ist_profi, aktualisiert_am)
            VALUES (?,?,?,?,?,NULL,?,0, datetime('now'))
        """, (team_id, name, liga, kurz, _altersklasse(liga), pos))
    db.commit()


def _turnier_id_sichern(db, mannschaft, spiel_antworten):
    """Liefert die Liga-ID der Mannschaft und merkt sie sich dauerhaft.

    Bevorzugt aus den Spieldaten (kostenlos mitgeliefert), sonst einmalig
    von der /tabelle-Seite. Profis haben sie fest hinterlegt."""
    if mannschaft.get("turnier_id"):
        return mannschaft["turnier_id"]

    turnier_id = None
    for antwort in spiel_antworten:
        for roh in ((antwort or {}).get("schedule") or {}).get("data") or []:
            turnier_id = (roh.get("tournament") or {}).get("id")
            if turnier_id:
                break
        if turnier_id:
            break
    if not turnier_id:
        turnier_id = _liga_id_der_mannschaft(mannschaft["team_id"])
    if turnier_id:
        db.execute("UPDATE tvb_mannschaften SET turnier_id=? WHERE team_id=?",
                   (turnier_id, mannschaft["team_id"]))
        db.commit()
        mannschaft["turnier_id"] = turnier_id
    return turnier_id


def _mannschaften_holen(db):
    """Mannschaftsliste, bei Bedarf vorher aktualisiert."""
    frisch = db.execute("""
        SELECT 1 FROM tvb_mannschaften
        WHERE aktualisiert_am > datetime('now', ?) LIMIT 1
    """, (f"-{_MANNSCHAFTEN_MAX_ALTER_STUNDEN} hours",)).fetchone()
    if not frisch:
        _mannschaften_aktualisieren(db)
    return [dict(z) for z in db.execute(
        "SELECT * FROM tvb_mannschaften ORDER BY position"
    ).fetchall()]


def _ausgeblendete_klassen(db, user_id):
    """Wunsch #124: Altersklassen, die DIESER Nutzer ausgeblendet hat."""
    return {z["altersklasse"] for z in db.execute(
        "SELECT altersklasse FROM tvb_ausgeblendet WHERE user_id=?", (user_id,)
    ).fetchall()}


def _sichtbare_mannschaften(mannschaften, versteckt):
    """Mannschaften ohne die ausgeblendeten Altersklassen. Die Profis bleiben
    immer sichtbar - sonst koennte der Umschalter komplett leer werden und
    die App haette gar keinen Einstieg mehr."""
    return [
        m for m in mannschaften
        if m["ist_profi"] or (m["altersklasse"] not in versteckt)
    ]


def _klassen_uebersicht(mannschaften, versteckt):
    """Altersklassen fuer die Einstellungsseite: Reihenfolge wie im
    Umschalter, mit Anzahl Mannschaften und aktuellem Zustand."""
    klassen = []
    gesehen = {}
    for m in mannschaften:
        if m["ist_profi"]:
            continue
        schluessel = m["altersklasse"] or "?"
        if schluessel not in gesehen:
            gesehen[schluessel] = {
                "schluessel": schluessel,
                "name": _KLASSEN_NAMEN.get(schluessel, schluessel),
                "anzahl": 0,
                "sichtbar": schluessel not in versteckt,
            }
            klassen.append(gesehen[schluessel])
        gesehen[schluessel]["anzahl"] += 1
    return klassen


def _spiel_aus_roh(roh, team_id):
    """Wandelt ein rohes handball.net-Spiel-JSON in unser Anzeigeformat um."""
    anstoss_utc = datetime.fromtimestamp(roh["startsAt"] / 1000, tz=timezone.utc)
    return {
        "id":        roh["id"],
        "team_id":   team_id,
        "spieltag":  (roh.get("round") or {}).get("name"),
        "heim":      roh["homeTeam"]["name"],
        "gast":      roh["awayTeam"]["name"],
        "heim_tore": roh.get("homeGoals"),
        "gast_tore": roh.get("awayGoals"),
        "anstoss":   anstoss_utc.astimezone(_TZ).isoformat(),
        "ort":       (roh.get("field") or {}).get("name"),
        "status":    roh.get("state") or "Pre",
    }


def _ist_eigenes_spiel(roh, team_id):
    return roh["homeTeam"]["id"] == team_id or roh["awayTeam"]["id"] == team_id


def _tvb_spiele_aktualisieren(db, spiele):
    """UPSERT gesehener Spiele nach tvb_spiele - siehe Docstring oben."""
    for s in spiele:
        db.execute("""
            INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                spieltag=excluded.spieltag, heim_tore=excluded.heim_tore, gast_tore=excluded.gast_tore,
                status=excluded.status, aktualisiert_am=excluded.aktualisiert_am
        """, (s["id"], s["team_id"], s["spieltag"], s["heim"], s["gast"],
              s["heim_tore"], s["gast_tore"], s["anstoss"], s["ort"], s["status"]))
    db.commit()


def _tabelle_aufbereiten(tabelle_antwort, team_name):
    """Tabellenzeilen fuers Template. `table` ist `null`, solange eine Liga
    ihre Tabelle noch nicht veroeffentlicht hat (Amateur-/Jugendligen vor
    Saisonstart) - das ist kein Fehler, sondern "noch nichts da"."""
    if not tabelle_antwort:
        return None
    tabelle = tabelle_antwort.get("table")
    if not tabelle or not tabelle.get("rows"):
        return []
    return [
        {
            "rang": r["rank"],
            "team": r["team"]["name"],
            # Der Vereinsname ist in Amateurligen der zuverlaessigere
            # Anhaltspunkt als die Team-ID (die Tabelle nennt die Mannschaft
            # genauso wie die Vereinsseite, waehrend die IDs je nach Liga aus
            # verschiedenen Namensraeumen stammen).
            "hervorgehoben": r["team"]["name"] == team_name,
            "spiele": r["games"],
            "siege": r["wins"],
            "unentschieden": r["draws"],
            "niederlagen": r["losses"],
            "tore": r["goals"],
            "gegentore": r["goalsAgainst"],
            "tordifferenz": r["goalDifference"],
            "punkte": r["points"],
        }
        for r in tabelle["rows"]
    ]


@bp.route("/a/tvb/", defaults={"token": None})
@bp.route("/a/tvb/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    db = get_db()
    alle_mannschaften = _mannschaften_holen(db)
    # Wunsch #124: ausgeblendete Altersklassen dieses Nutzers herausfiltern.
    mannschaften = _sichtbare_mannschaften(
        alle_mannschaften, _ausgeblendete_klassen(db, user["id"])
    )

    # Wunsch #122: ?team=<id> waehlt die Mannschaft. Unbekannte oder fehlende
    # Angabe faellt auf die Profis zurueck, damit ein alter Link (oder eine
    # Mannschaft, die es nach dem Saisonwechsel nicht mehr gibt) nie ins Leere
    # laeuft. Eine ausgeblendete Mannschaft bleibt per Direktlink erreichbar -
    # sie taucht dann nur nicht im Umschalter auf.
    gewaehlt = None
    gewuenscht = request.args.get("team")
    if gewuenscht:
        gewaehlt = next((m for m in alle_mannschaften if m["team_id"] == gewuenscht), None)
    if not gewaehlt:
        gewaehlt = next((m for m in mannschaften if m["ist_profi"]), None)
    if not gewaehlt:
        # Vereinsseite noch nie erreichbar gewesen: Profis trotzdem anzeigen.
        gewaehlt = {"team_id": _TEAM_ID, "name": _VEREIN_PROFIS, "kurz": "Profis",
                    "liga": "Handball-Bundesliga", "turnier_id": _TOURNAMENT_ID,
                    "ist_profi": 1, "altersklasse": _PROFI_KLASSE}

    team_id = gewaehlt["team_id"]

    team_antwort = _handball_net_get(f"team/{team_id}/team-schedule")
    turnier_id   = _turnier_id_sichern(db, gewaehlt, [team_antwort])

    liga_antwort = _handball_net_get(f"tournament/{turnier_id}/schedule") if turnier_id else None
    tabelle_antwort = _handball_net_get(f"tournament/{turnier_id}/table") if turnier_id else None

    fehler_spiele  = team_antwort is None and liga_antwort is None
    fehler_tabelle = turnier_id is not None and tabelle_antwort is None

    gesehene_spiele = []
    for antwort in (team_antwort, liga_antwort):
        if not antwort:
            continue
        for roh in antwort["schedule"]["data"]:
            if _ist_eigenes_spiel(roh, team_id):
                gesehene_spiele.append(_spiel_aus_roh(roh, team_id))
    if gesehene_spiele:
        _tvb_spiele_aktualisieren(db, gesehene_spiele)

    gespeicherte = db.execute(
        "SELECT * FROM tvb_spiele WHERE team_id=? ORDER BY anstoss ASC", (team_id,)
    ).fetchall()
    jetzt_iso = datetime.now(_TZ).isoformat()
    vergangene, kommende = [], []
    for s in gespeicherte:
        (vergangene if s["status"] == "Ended" or s["anstoss"] < jetzt_iso else kommende).append(dict(s))
    vergangene.reverse()  # neueste zuerst

    # Wunsch #123: Der Kopf nennt den Verein der GEWAEHLTEN Mannschaft -
    # nur die 1. Mannschaft heisst "TVB Stuttgart" und spielt in der
    # Handball-Bundesliga, alle uebrigen laufen unter "TV Bittenfeld".
    if gewaehlt["ist_profi"]:
        kopf_verein, kopf_liga = _VEREIN_PROFIS, "Handball-Bundesliga"
    else:
        kopf_verein = _VEREIN_AMATEUR
        kopf_liga = _liga_ohne_verband(gewaehlt["liga"]) or gewaehlt["kurz"]

    return render_template("tvb.html",
        user=user, token=token, farbe=user["farbe"],
        mannschaften=mannschaften, gewaehlt=gewaehlt,
        kopf_verein=kopf_verein, kopf_liga=kopf_liga,
        fehler_spiele=fehler_spiele, fehler_tabelle=fehler_tabelle,
        vergangene=vergangene, kommende=kommende,
        tabelle=_tabelle_aufbereiten(tabelle_antwort, gewaehlt["name"]),
    )


@bp.route("/a/tvb/mannschaften", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/tvb/<token>/mannschaften", methods=["GET", "POST"])
def mannschaften_einstellen(token):
    """Wunsch #124: Jeder Nutzer blendet fuer sich Altersklassen aus - der
    Umschalter mit allen Jugendklassen ist sonst sehr lang. Bewusst ohne
    Admin-Pruefung: der Wunsch sagt ausdruecklich "das soll jeder Nutzer
    machen koennen", und es aendert nur die eigene Ansicht."""
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    db = get_db()
    alle = _mannschaften_holen(db)

    if request.method == "POST":
        # Angehakt = sichtbar. Alles, was nicht angehakt ist, kommt in
        # tvb_ausgeblendet - so wirkt sich eine neu dazugekommene Klasse
        # (naechste Saison) automatisch als "sichtbar" aus.
        sichtbar = set(request.form.getlist("sichtbar"))
        db.execute("DELETE FROM tvb_ausgeblendet WHERE user_id=?", (user["id"],))
        for klasse in {m["altersklasse"] for m in alle
                       if not m["ist_profi"] and m["altersklasse"]}:
            if klasse not in sichtbar:
                db.execute(
                    "INSERT INTO tvb_ausgeblendet(user_id, altersklasse) VALUES(?,?)",
                    (user["id"], klasse),
                )
        db.commit()
        return redirect(f"/a/tvb/{token}/mannschaften?gespeichert=1")

    versteckt = _ausgeblendete_klassen(db, user["id"])
    return render_template("tvb_mannschaften.html",
        user=user, token=token, farbe=user["farbe"],
        klassen=_klassen_uebersicht(alle, versteckt),
        profi_anzahl=sum(1 for m in alle if m["ist_profi"]),
        gespeichert=request.args.get("gespeichert") == "1",
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


@bp.route("/a/tvb/kader", defaults={"token": None})
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
