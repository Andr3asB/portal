"""
TVB-App – Spiele, Ergebnisse und Tabelle des TVB Stuttgart / TV Bittenfeld.
URL-Präfix: /a/tvb/<token>/

## Der Neubau vom 30.08.2026 (#191/#192/#193)

Mitte August 2026 hat handball.net einen Relaunch auf Handball360 bekommen.
Dabei sind DREI der vier Quellen verschwunden, an denen diese App hing: die
Widget-API (Spiele, Tabelle) und beide HTML-Seiten (Mannschaftsliste,
Liga-ID). Die Widget-Endpunkte antworten weiterhin mit **HTTP 200**, liefern
aber die leere Hülle der neuen Single-Page-App statt JSON - ein reiner
Erreichbarkeitstest hätte grün gemeldet. Deshalb prüft #190 auf "erreichbar
UND parsebar", und deshalb steht hier der Satz: **eine Quelle immer mit den
Headern testen, die dieser Code wirklich schickt.** Eine Sonde mit
`Accept: application/json` bekam bei handball.net 404 für Seiten, die es
sehr wohl noch gibt, und hätte fast zu einem falschen Befund geführt.

## Zwei Welten, zwei Quellen

Der Verein spielt in zwei getrennten Systemen, und die neue API bildet nur
eines davon ab:

1. **Amateur/Jugend → `https://www.handball.net/api/new/`** (Handball360,
   DHB-Spielbetrieb). Zugang über den Header `x-client-token`, dessen Wert
   als Meta-Tag in jeder normalen Seite steht (`_client_token()`). Das ist
   kein dokumentierter Zugang, sondern derselbe Weg, den die Weboberfläche
   selbst geht - er kann jederzeit zugedreht werden.
2. **Profis (Opel HBL) → Sportradar-Embed** (`_SR_EMBED`). Die 1. Bundesliga
   steckt NICHT im DHB-Spielbetrieb - dort gibt es nur die Jugend-Bundesligen.
   Gefunden über die offizielle Liga-Seite opel-hbl.de, die genau diese
   Adressen aufruft. Ohne Anmeldung.

Der Kader (Wunsch #121) kommt unverändert von der HPI-API der HBL - sie ist
als einzige der vier alten Quellen unbeschadet durch den Relaunch gekommen.
Zu #192 ("Kader direkt von handball.net"): für die PROFIS geht das nicht, sie
sind in jenem System gar nicht vorhanden. Die Prämisse des Wunsches trägt
also nur für Amateur-/Jugendmannschaften, und dort fehlt bis heute jede
Kaderquelle.

## Was die Umstellung gebracht - und was sie gekostet hat

Gewonnen: Die früheren ZWEI Vereinsobjekte (`sr.competitor.6272` für die
Profis, `handball4all.wuerttemberg.131` für den Rest) sind zu EINEM
zusammengefallen (`_NEU_CLUB`) - das war die größte Umständlichkeit des
Moduls und die ausdrückliche Frage aus #191. Altersklasse und Geschlecht
stehen jetzt als Felder an der Mannschaft, statt aus dem Liganamen geraten
zu werden.

Verloren: **Die neue API kennt 11 Verbände, HANDBALL WÜRTTEMBERG ist nicht
darunter.** Vom Verein liegen dort nur die überregionalen Mannschaften
(3. Liga, Jugendbundesliga). Die rund 14 württembergischen Bezirks- und
Jugendmannschaften, die die App vorher über handball.net bezog, haben seit
dem Relaunch gar keine Quelle mehr - handball.net hatte die
Handball4All-Plattform des Verbands mit aggregiert, und genau das ist
weggefallen. Der frühere offene Dienst `spo.handball4all.de/service/
if_g_json.php` antwortet inzwischen mit 401. Ersatzsuche läuft als **#230**.

Ihr letzter Bestand bleibt in der Datenbank stehen; sie verschwinden nur aus
dem Umschalter. Weil die Mannschaftsliste aus den SPIELEN entsteht und nicht
aus einem festen Verzeichnis, tauchen sie von selbst wieder auf, sobald es
für sie wieder Spiele gibt - ohne Codeänderung.

## Was gleich geblieben ist

- Jedes einmal gesehene Spiel wird in `tvb_spiele` gespeichert (id =
  Quell-ID mit Präfix). Das Sportradar-Embed liefert wie das alte Widget nur
  den aktuellen Spieltag, nicht den Saisonkalender - ohne diese Speicherung
  wären vergangene Ergebnisse nach einer Woche weg.
- Die Altersklassen-Kürzel ("mA", "Herren", ...) sind bewusst dieselben wie
  vorher: die pro Nutzer ausgeblendeten Klassen (#124) hängen daran, ein
  neues Schema hätte jedem stillschweigend seine Einstellungen zurückgesetzt.
- Der Kader-Knopf erscheint nur bei den Profis - der HPI ist eine reine
  Bundesliga-Kennzahl.
- Amateur- und Jugendligen veröffentlichen ihre Tabelle erst mit dem
  Saisonstart. Leere Liste heißt "noch keine Tabelle", None heißt "nicht
  abrufbar" - nur Letzteres zeigt die Seite als Störung.
- #190: `tvb_quellen` hält fest, wann eine Quelle zuletzt wirklich lieferte;
  die Seite warnt nach 3 Tagen und bremst nach einem Fehlschlag 30 Minuten.
"""
import base64
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import (
    Blueprint,
    Response,
    current_app,
    redirect,
    render_template,
    request,
    send_file,
)

from teile.kern import get_db, new_db, to_int, utc_zu_lokal
from teile.kern import grant as check_grant

_log = logging.getLogger(__name__)

bp  = Blueprint("tvb_app", __name__)
APP = "tvb"

_TZ = ZoneInfo("Europe/Berlin")

# --- Quellen nach dem Relaunch (#191/#192/#193, 30.08.2026) ---------------
# Die alte Widget-API und beide HTML-Seiten sind weg. An ihre Stelle treten
# ZWEI Quellen, weil der TVB in zwei getrennten Welten spielt:
#
#   1. Amateur/Jugend -> handball.net /api/new/ (Handball360, DHB-Spielbetrieb)
#   2. Profis (Opel HBL) -> Sportradar-Embed der Liga-Seite opel-hbl.de
#
# Die 1. Bundesliga steckt NICHT im DHB-Spielbetrieb - dort gibt es nur die
# Jugend-Bundesligen. Deshalb zwei Quellen und nicht eine.
_UA            = "Mozilla/5.0"
_HB_BASE       = "https://www.handball.net"
_NEU_API       = "https://www.handball.net/api/new"
# Vereins-ID im Handball360-System. Loest die frueheren ZWEI Vereinsobjekte
# ab (sr.competitor.6272 fuer die Profis, handball4all.wuerttemberg.131 fuer
# den Rest) - Handball360 fuehrt beide zusammen, was die groesste
# Umstaendlichkeit des Moduls beseitigt hat (die Frage aus #191).
_NEU_CLUB      = "00j8j80"
_SR_BASIS      = "https://embed-api.eui.connect.sportradar.com/v1/embed"
# Wunsch #151 wollte die Spiele ausserhalb der Liga sichtbar machen - der
# DHB-Pokal hat bei Sportradar ein EIGENES Embed. Ohne den zweiten Eintrag
# waeren die Pokalspiele nach dem Neubau lautlos verschwunden, genau der
# Zustand, den #151 behoben hatte.
_SR_EMBEDS = {248: "Opel HBL", 255: "DHB-Pokal"}
_SR_TABELLE_EMBED = 248          # eine Tabelle gibt es nur in der Liga

# ACHTUNG Reichweite (Wunsch #230): Die neue API kennt 11 Verbaende,
# HANDBALL WUERTTEMBERG ist NICHT darunter. Vom Verein liegen dort nur die
# ueberregionalen Mannschaften (3. Liga, Jugendbundesliga). Die rund 14
# wuerttembergischen Bezirks- und Jugendmannschaften haben seit dem Relaunch
# gar keine Quelle mehr - ihr letzter Bestand bleibt in der Datenbank stehen,
# sie verschwinden aber aus dem Umschalter. Ersatzquelle wird in #230 gesucht.

# Ein Mannschaftsbestand aendert sich allenfalls zum Saisonwechsel - der
# Abruf holt aber zugleich alle Spiele des Vereins, die sich sehr wohl
# aendern. Deshalb kein Tageswert mehr, sondern stuendlich.
_MANNSCHAFTEN_MAX_ALTER_STUNDEN = 1

# Wunsch #270: Das erste Oeffnen nach laengerer Pause dauerte rund acht
# Sekunden, weil der Seitenaufruf selbst sieben Fremdaufrufe nacheinander
# machte (Vereinsdaten, sechs Sportradar-Listen, Tabellen). Jetzt:
#   - die Sportradar-Listen laufen parallel (_profi_spiele),
#   - Tabellen werden zwischengespeichert (tvb_tabellen),
#   - ein Hintergrund-Thread frischt alles auf, bevor jemand die Seite oeffnet
#     (_hintergrund_schleife, Schalter TVB_HINTERGRUND in app.py).
# Der Seitenaufruf holt nur noch dann selbst, wenn der Stand aelter ist als
# erlaubt - stuendlich, waehrend eines Profispiels alle fuenf Minuten (der
# Ribbon soll mitgehen).
_PROFI_MAX_ALTER_MINUTEN = 60
_PROFI_MAX_ALTER_LIVE_MINUTEN = 5
_TABELLE_MAX_ALTER_MINUTEN = 60
_SPIELFENSTER_VOR_STUNDEN = 2
_SPIELFENSTER_NACH_STUNDEN = 3
_HINTERGRUND_TAKT_SEKUNDEN = 300
_HINTERGRUND_STARTVERZUG_SEKUNDEN = 15

# Wunsch #271: Spielerbilder. Die HPI-Antwort nennt je Spieler eine Adresse
# auf Sportradars Bild-CDN; nur DIESER Host wird vom Server geholt (die
# Adresse geht in einen Fremdabruf - ohne Allowlist waere das ein SSRF-Tor),
# hoechstens 2 MB, als webp in 400 px, unter DATA_DIR/tvb_bilder abgelegt und
# nach einer Woche erneuert. Der Browser bekommt das Bild von hier (#119).
_BILD_HOST = "images.dc.connect.sportradar.com"
_BILD_MAX_BYTES = 2 * 1024 * 1024
_BILD_MAX_ALTER_TAGE = 7

# Wunsch #190: Die Mannschaftsliste konnte still veralten - schlaegt der
# Abruf fehl, bleibt der alte Stand stehen, und niemand erfaehrt davon.
# Ab wann die Seite warnt:
_QUELLE_WARNUNG_TAGE = 3
# ... und wie lange nach einem Fehlschlag nicht erneut versucht wird. Ohne
# diese Bremse fragt JEDER Seitenaufruf die tote Quelle neu an, mit dem
# vollen Zeitlimit vor dem Seitenaufbau. Genau das war nach dem Relaunch
# der Dauerzustand.
_QUELLE_PAUSE_MINUTEN = 30

# Schluessel in tvb_quellen - je Aussenquelle einer.
_QUELLE_MANNSCHAFTEN = "mannschaften"
_QUELLE_PROFIS       = "profis"

_token_cache = {"wert": None, "geholt": 0.0}
_TOKEN_MAX_ALTER_SEKUNDEN = 900

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
# Eigene, quellenunabhaengige Kennung: die Profis kommen von Sportradar,
# dessen IDs (UUIDs je Spiel) sich nicht als stabile Mannschafts-ID eignen.
_PROFI_TEAM_ID = "profis"
_KLASSEN_NAMEN = {
    _PROFI_KLASSE: "Profis (1. Mannschaft)",
    "Herren": "Herren",           "Damen": "Damen",
    "mA": "männliche A-Jugend",   "mB": "männliche B-Jugend",
    "mC": "männliche C-Jugend",   "mD": "männliche D-Jugend",
    "mE": "männliche E-Jugend",   "mF": "männliche F-Jugend",
    "wA": "weibliche A-Jugend",   "wB": "weibliche B-Jugend",
    "wC": "weibliche C-Jugend",   "wD": "weibliche D-Jugend",
    # Seit dem Neubau (#193) entstehen die Kuerzel aus Altersklasse UND
    # Geschlecht der API, nicht mehr aus dem Liganamen. Damit sind alle
    # Kombinationen moeglich - vorher standen hier nur die, die zufaellig
    # schon einmal vorkamen, und eine neue Mannschaft haette auf der
    # Einstellungsseite einen leeren Haken bekommen.
    "wE": "weibliche E-Jugend",   "wF": "weibliche F-Jugend",
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


def _client_token(erneuern=False):
    """Zugangstoken fuer die neue handball.net-API (#192/#193).

    Der Relaunch hat die alte Widget-API abgeraeumt; die neue verlangt den
    Header `x-client-token`. Sein Wert steht als Meta-Tag in jeder normalen
    Seite - wir holen also die Startseite und schneiden ihn heraus. Das ist
    kein dokumentierter Zugang, sondern derselbe Weg, den die Web-Oberflaeche
    selbst geht; er kann jederzeit zugedreht werden (siehe journal.md,
    30.08.2026). Deshalb faellt jede Funktion hier auf den gespeicherten
    Bestand zurueck, statt einen Fehler zu werfen.

    Der Token wird zwischengespeichert - ihn je Anfrage neu zu holen hiesse,
    fuer jeden Seitenaufruf eine 1,4 MB grosse Startseite mitzuladen."""
    jetzt = time.time()
    if (not erneuern and _token_cache["wert"]
            and jetzt - _token_cache["geholt"] < _TOKEN_MAX_ALTER_SEKUNDEN):
        return _token_cache["wert"]
    req = urllib.request.Request(_HB_BASE + "/", headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception:
        return _token_cache["wert"]          # abgelaufen ist besser als keiner
    treffer = re.findall(
        r'<meta name="client-token"[^>]*content="([^"]*)"', html)
    if treffer:
        _token_cache["wert"] = treffer[0]
        _token_cache["geholt"] = jetzt
    return _token_cache["wert"]


def _neu_api_get(pfad, _zweiter_versuch=False):
    """Ruft die neue handball.net-API. None bei Fehler/Timeout.

    Bei 403 wird EINMAL mit frisch geholtem Token wiederholt: der Token
    laeuft ab, und die Oberflaeche selbst behandelt genau diesen Fall
    (CLIENT_TOKEN_EXPIRED) mit einem Neuladen."""
    token = _client_token()
    if not token:
        return None
    req = urllib.request.Request(
        f"{_NEU_API}/{pfad}",
        headers={"Accept": "application/json", "User-Agent": _UA,
                 "x-client-token": token, "Referer": _HB_BASE + "/"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as fehler:
        if fehler.code == 403 and not _zweiter_versuch:
            _client_token(erneuern=True)
            return _neu_api_get(pfad, _zweiter_versuch=True)
        return None
    except Exception:
        return None


def _neu_api_alle_seiten(pfad, grenze=10):
    """Sammelt eine seitenweise ausgelieferte Liste ein (`pagination`).

    `grenze` ist eine Reissleine, keine Erwartung: der Verein hat rund 60
    Spiele, also drei Seiten. Ohne sie wuerde ein Fehler in der
    Seitenzaehlung der Gegenstelle zu einer Endlosschleife im Seitenaufbau."""
    gesammelt, seite = [], 1
    while seite <= grenze:
        trenner = "&" if "?" in pfad else "?"
        antwort = _neu_api_get(f"{pfad}{trenner}per_page=50&page={seite}")
        if not antwort or not antwort.get("data"):
            break
        gesammelt.extend(antwort["data"])
        seitenzahl = (antwort.get("pagination") or {}).get("last_page") or 1
        if seite >= seitenzahl:
            break
        seite += 1
    return gesammelt


def _sr_get(pfad, embed=248):
    """Sportradar-Embed der Opel HBL - die einzige Quelle fuer Spiele und
    Tabelle der Profis (#191): die 1. Bundesliga steckt NICHT im
    DHB-Spielbetrieb, den die neue handball.net-API abbildet. Gefunden ueber
    die offizielle Liga-Seite opel-hbl.de, die genau diese Adressen aufruft.
    Ohne Anmeldung, aber ebenso wenig zugesagt wie alles andere hier."""
    req = urllib.request.Request(
        f"{_SR_BASIS}/{embed}/{pfad}",
        headers={"Accept": "application/json", "User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _hpi_get(pfad):
    """Ruft einen HPI-Endpunkt der HBL ab (Kader, Wunsch #121). None bei
    Fehler/Timeout. Als einzige der vier alten Quellen unbeschadet durch den
    Relaunch gekommen - siehe Modul-Docstring."""
    req = urllib.request.Request(
        f"{_HPI_BASE}/{pfad}",
        headers={"Accept": "application/json", "User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _aktuelle_saison():
    """Saison-ID der laufenden Spielzeit, oder None.

    Bewusst nicht als Konstante: die ID wechselt jeden Sommer, und eine
    festgeschriebene Zahl waere genau die Sorte Wartungsaufgabe, die
    niemandem auffaellt, bis die App im September leer ist."""
    antwort = _neu_api_get("seasons")
    for saison in (antwort or {}).get("data") or []:
        if saison.get("is_active"):
            return saison["id"]
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


def _quelle_melden(db, quelle, ok, fehler=None):
    """Wunsch #190: haelt je Quelle fest, wann sie zuletzt WIRKLICH lieferte.

    `zuletzt_versuch` wird immer gesetzt, `zuletzt_ok` nur im Erfolgsfall -
    die Luecke zwischen beiden ist genau das, was vorher niemand sehen
    konnte."""
    db.execute("""
        INSERT INTO tvb_quellen(quelle, zuletzt_ok, zuletzt_versuch, letzter_fehler)
        VALUES (?, CASE WHEN ? THEN datetime('now') END, datetime('now'), ?)
        ON CONFLICT(quelle) DO UPDATE SET
            zuletzt_versuch = datetime('now'),
            zuletzt_ok      = CASE WHEN ? THEN datetime('now')
                                   ELSE tvb_quellen.zuletzt_ok END,
            letzter_fehler  = excluded.letzter_fehler
    """, (quelle, 1 if ok else 0, None if ok else (fehler or "unbekannt"),
          1 if ok else 0))
    db.commit()


def _quelle_status(db, quelle):
    """Zeile aus tvb_quellen als dict, oder None wenn die Quelle noch nie
    angefasst wurde."""
    z = db.execute("SELECT * FROM tvb_quellen WHERE quelle=?", (quelle,)).fetchone()
    return dict(z) if z else None


def _quelle_pausiert(db, quelle):
    """True, wenn der letzte Versuch fehlschlug und die Pause noch laeuft."""
    z = db.execute("""
        SELECT 1 FROM tvb_quellen
        WHERE quelle=? AND letzter_fehler IS NOT NULL
          AND zuletzt_versuch > datetime('now', ?)
    """, (quelle, f"-{_QUELLE_PAUSE_MINUTEN} minutes")).fetchone()
    return z is not None


def _quelle_warnung(db, quelle):
    """Wunsch #190: Text fuer die Seite, oder None wenn alles in Ordnung ist.

    Warnt erst nach `_QUELLE_WARNUNG_TAGE` - ein einzelner Aussetzer der
    Gegenstelle ist normal und soll die Familie nicht beunruhigen."""
    z = _quelle_status(db, quelle)
    if not z or not z["letzter_fehler"]:
        return None

    zuletzt_ok = z["zuletzt_ok"]
    if zuletzt_ok is None and quelle == _QUELLE_MANNSCHAFTEN:
        # tvb_quellen gibt es erst seit #190 - der Bestand davor ist deshalb
        # ohne Erfolgsdatum, obwohl er nachweislich einmal geladen wurde.
        # `tvb_mannschaften.aktualisiert_am` IST dieses Datum: die Tabelle wird
        # ausschliesslich im Erfolgsfall neu geschrieben. Ohne diesen Rueckgriff
        # meldete die Seite beim ersten Ausfall nach der Auslieferung "noch nie"
        # und damit etwas Falsches - der Stand vom 14.08.2026 war echt.
        zeile = db.execute(
            "SELECT MAX(aktualisiert_am) AS m FROM tvb_mannschaften").fetchone()
        zuletzt_ok = zeile["m"] if zeile else None
    if zuletzt_ok is None:
        return "noch nie"
    veraltet = db.execute(
        "SELECT ? < datetime('now', ?)", (zuletzt_ok, f"-{_QUELLE_WARNUNG_TAGE} days")
    ).fetchone()[0]
    return utc_zu_lokal(zuletzt_ok) if veraltet else None


def _klassen_kuerzel(alters_name, geschlecht_id):
    """Baut aus den API-Feldern das Altersklassen-Kuerzel (#124).

    Bewusst dasselbe Schema wie vor dem Relaunch ("mA", "Herren", ...): Die
    pro Nutzer ausgeblendeten Klassen sind unter genau diesen Kuerzeln
    gespeichert. Ein neues Schema haette jedem stillschweigend seine
    Einstellungen zurueckgesetzt."""
    alters_name = (alters_name or "").upper()
    if alters_name == "ERWACHSENE":
        return "Damen" if geschlecht_id == "F" else "Herren"
    treffer = re.match(r"([A-F])-JUGEND", alters_name)
    if not treffer:
        return "Herren"
    vorsatz = {"M": "m", "F": "w"}.get(geschlecht_id, "g")
    return f"{vorsatz}{treffer.group(1)}"


def _liga_kurz(liga):
    """Kurzform der Liga fuers Chip-Label ("3. Liga Maenner" -> "3.Liga")."""
    if not liga:
        return ""
    for lang, kurz in [("Jugendbundesliga", "JBL"), ("3. Liga", "3.Liga"),
                       ("2. Liga", "2.Liga"), ("Bundesliga", "BL")]:
        if lang.lower() in liga.lower():
            return kurz
    return _kurzlabel(liga, "") or liga[:8]


def _mannschaften_von_api():
    """Mannschaften des Vereins mit ihren Spielen, aus der neuen API.

    Die Liste entsteht aus den SPIELEN, nicht aus dem Mannschafts-Endpunkt -
    und das ist Absicht. `teams?club_id=...` kennt zwar alle gemeldeten
    Mannschaften, aber weder ihre Liga noch ihre Tabelle; beides haengt an
    der Phase, die erst am Spiel steht. Eine Mannschaft ohne ein einziges
    Spiel waere im Umschalter ein Knopf, hinter dem nichts ist.

    Der angenehme Nebeneffekt: Sobald der Verband die wuerttembergischen
    Ligen ansetzt (#230), tauchen diese Mannschaften von selbst wieder auf -
    ohne Codeaenderung.

    Rueckgabe: (mannschaften, spiele) oder ([], []) bei Fehler."""
    saison = _aktuelle_saison()
    if not saison:
        return [], []

    spiele_roh = _neu_api_alle_seiten(f"matches?club_id={_NEU_CLUB}")
    if not spiele_roh:
        return [], []

    # Altersklasse und Geschlecht stehen nur am Mannschafts-Endpunkt.
    stammdaten = {}
    antwort = _neu_api_get(f"teams?club_id={_NEU_CLUB}&season_id={saison}&per_page=50")
    for t in (antwort or {}).get("data") or []:
        stammdaten[t["id"]] = t

    gefunden, spiele = {}, []
    for roh in spiele_roh:
        phase = roh.get("phase") or {}
        liga = ((phase.get("competition") or {}).get("name") or "").strip()
        for seite in ("local", "visitor"):
            mannschaft = roh.get(seite) or {}
            if ((mannschaft.get("club") or {}).get("id")) != _NEU_CLUB:
                continue
            tid = str(mannschaft["id"])
            if tid not in gefunden:
                stamm = stammdaten.get(mannschaft["id"], {})
                gefunden[tid] = {
                    "team_id": tid,
                    "name": mannschaft.get("name") or _VEREIN_AMATEUR,
                    "liga": liga,
                    "phase_id": phase.get("id"),
                    "altersklasse": _klassen_kuerzel(
                        (stamm.get("age_category") or {}).get("name"),
                        (stamm.get("gender") or {}).get("id")),
                }
            spiele.append(_spiel_aus_neu(roh, tid))
    return list(gefunden.values()), spiele


def _mannschaften_aktualisieren(db):
    """Baut die Mannschaftsliste neu auf. Laesst den bestehenden Stand
    unangetastet, wenn nichts geladen werden konnte - besser ein veralteter
    Umschalter als gar keiner."""
    gefunden, spiele = _mannschaften_von_api()
    if not gefunden:
        _quelle_melden(db, _QUELLE_MANNSCHAFTEN, False,
                       "Vereinsdaten der neuen API nicht abrufbar")
        return

    db.execute("DELETE FROM tvb_mannschaften")
    db.execute("""
        INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse,
                                     turnier_id, position, ist_profi, aktualisiert_am)
        VALUES (?,?,?,?,?,?,?,1, datetime('now'))
    """, (_PROFI_TEAM_ID, _VEREIN_PROFIS, "Opel HBL",
          "Profis", _PROFI_KLASSE, None, 0))

    labels = {}
    # Feste Reihenfolge: erst Erwachsene, dann Jugend von A nach F - sonst
    # haengt die Reihenfolge der Knoepfe daran, welches Spiel zufaellig
    # zuerst aus der API kam, und wechselt bei jedem Aktualisieren.
    def sortierung(m):
        k = m["altersklasse"]
        return (0 if k in ("Herren", "Damen") else 1, k)

    for pos, m in enumerate(sorted(gefunden, key=sortierung), start=1):
        kurz = f"{m['altersklasse']} {_liga_kurz(m['liga'])}".strip()
        labels[kurz] = labels.get(kurz, 0) + 1
        if labels[kurz] > 1:
            kurz = f"{kurz} ({labels[kurz]})"
        db.execute("""
            INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse,
                                         turnier_id, position, ist_profi, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,0, datetime('now'))
        """, (m["team_id"], m["name"], m["liga"], kurz, m["altersklasse"],
              str(m["phase_id"]) if m["phase_id"] else None, pos))
    db.commit()
    _quelle_melden(db, _QUELLE_MANNSCHAFTEN, True)
    if spiele:
        _tvb_spiele_aktualisieren(db, spiele)



def _mannschaften_frisch(db):
    return db.execute("""
        SELECT 1 FROM tvb_mannschaften
        WHERE aktualisiert_am > datetime('now', ?) LIMIT 1
    """, (f"-{_MANNSCHAFTEN_MAX_ALTER_STUNDEN} hours",)).fetchone() is not None


def _mannschaften_holen(db):
    """Mannschaftsliste, bei Bedarf vorher aktualisiert."""
    if not _mannschaften_frisch(db) and not _quelle_pausiert(db, _QUELLE_MANNSCHAFTEN):
        _mannschaften_aktualisieren(db)
    return [dict(z) for z in db.execute(
        "SELECT * FROM tvb_mannschaften ORDER BY position"
    ).fetchall()]


# --- Wunsch #270: Zwischenspeicher fuer Tabellen, Frische der Profis -------------

def _tabelle_speichern(db, team_id, antwort):
    db.execute("""
        INSERT INTO tvb_tabellen(team_id, daten, aktualisiert_am) VALUES (?, ?, datetime('now'))
        ON CONFLICT(team_id) DO UPDATE SET daten=excluded.daten, aktualisiert_am=excluded.aktualisiert_am
    """, (team_id, json.dumps(antwort, ensure_ascii=False)))
    db.commit()


def _tabelle_laden(db, team_id, max_minuten=_TABELLE_MAX_ALTER_MINUTEN):
    """Gespeicherte Rohantwort, oder None wenn sie fehlt oder zu alt ist."""
    z = db.execute(
        "SELECT daten FROM tvb_tabellen WHERE team_id=? AND aktualisiert_am > datetime('now', ?)",
        (team_id, f"-{max_minuten} minutes")).fetchone()
    return json.loads(z["daten"]) if z else None


def _spiel_im_fenster(db):
    """Laeuft gerade ein Profispiel (oder faengt es gleich an, oder ist es
    eben zu Ende)? Dann darf der Stand nur Minuten alt sein."""
    jetzt = datetime.now(_TZ)
    von = (jetzt - timedelta(hours=_SPIELFENSTER_NACH_STUNDEN)).isoformat()
    bis = (jetzt + timedelta(hours=_SPIELFENSTER_VOR_STUNDEN)).isoformat()
    return db.execute(
        "SELECT 1 FROM tvb_spiele WHERE team_id=? AND anstoss BETWEEN ? AND ? LIMIT 1",
        (_PROFI_TEAM_ID, von, bis)).fetchone() is not None


def _profis_frisch(db):
    grenze = _PROFI_MAX_ALTER_LIVE_MINUTEN if _spiel_im_fenster(db) else _PROFI_MAX_ALTER_MINUTEN
    return db.execute(
        "SELECT 1 FROM tvb_quellen WHERE quelle=? AND zuletzt_ok > datetime('now', ?)",
        (_QUELLE_PROFIS, f"-{grenze} minutes")).fetchone() is not None


def _profis_auffrischen(db):
    """Spiele, Tabelle und Nachladen der Profis - EIN Weg fuer Seitenaufruf
    und Hintergrund. Gibt (gesehene_spiele, tabelle_antwort) zurueck."""
    tabelle_antwort = _sr_get("standings?locale=de-DE", embed=_SR_TABELLE_EMBED)
    gesehene = _profi_spiele()
    if gesehene:
        _tvb_spiele_aktualisieren(db, gesehene)
    if tabelle_antwort is not None:
        _tabelle_speichern(db, _PROFI_TEAM_ID, tabelle_antwort)
    _quelle_melden(db, _QUELLE_PROFIS, tabelle_antwort is not None,
                   None if tabelle_antwort is not None else "Sportradar nicht abrufbar")
    # Wunsch #263: verpasste Ergebnisse und unbestaetigte Staende ueber den
    # Einzelspiel-Endpunkt nachziehen - nach dem Ribbon, damit ein frisch
    # bestaetigtes Spiel nicht noch einmal angefragt wird.
    _profi_nachladen(db)
    return gesehene, tabelle_antwort


def _amateur_tabelle(db, team_id, phase_id):
    """Tabelle einer Amateurmannschaft: gespeichert, sonst geholt und gespeichert."""
    if not phase_id:
        return None
    antwort = _tabelle_laden(db, team_id)
    if antwort is None:
        antwort = _neu_api_get(f"standings?phase_id={phase_id}")
        if antwort is not None:
            _tabelle_speichern(db, team_id, antwort)
    return antwort


def _hintergrund_auffrischen(app):
    """Ein Durchlauf: alles auffrischen, was zu alt ist. Laeuft im Thread mit
    eigener Verbindung (new_db), nie mit g.db."""
    with app.app_context(), new_db() as db:
        if not _mannschaften_frisch(db) and not _quelle_pausiert(db, _QUELLE_MANNSCHAFTEN):
            _mannschaften_aktualisieren(db)
        if not _profis_frisch(db) and not _quelle_pausiert(db, _QUELLE_PROFIS):
            _profis_auffrischen(db)
        for m in db.execute("SELECT team_id, turnier_id FROM tvb_mannschaften WHERE ist_profi=0"):
            if m["turnier_id"] and _tabelle_laden(db, m["team_id"]) is None:
                _amateur_tabelle(db, m["team_id"], m["turnier_id"])


def _hintergrund_schleife(app):
    time.sleep(_HINTERGRUND_STARTVERZUG_SEKUNDEN)
    while True:
        try:
            _hintergrund_auffrischen(app)
        except Exception:
            # Ein Fehler darf die Schleife nicht beenden - sonst holt ab da
            # wieder jeder Seitenaufruf alles selbst, und niemand merkt es.
            _log.exception("TVB-Auffrischung im Hintergrund fehlgeschlagen")
        time.sleep(_HINTERGRUND_TAKT_SEKUNDEN)


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


def _spiel_aus_neu(roh, team_id):
    """Spiel der neuen handball.net-API in unser Anzeigeformat."""
    zustand = roh.get("status") or {}
    ergebnis = roh.get("result") or {}
    try:
        anstoss = datetime.fromisoformat(roh["date"]).astimezone(_TZ).isoformat()
    except Exception:
        anstoss = roh.get("date") or ""
    runde = roh.get("round")
    return {
        "id":         f"n{roh['id']}",
        "team_id":    team_id,
        "spieltag":   f"{runde}. Spieltag" if runde else None,
        "heim":       (roh.get("local") or {}).get("name") or "?",
        "gast":       (roh.get("visitor") or {}).get("name") or "?",
        "heim_tore":  ergebnis.get("local"),
        "gast_tore":  ergebnis.get("visitor"),
        "anstoss":    anstoss,
        "ort":        (roh.get("field") or {}).get("name"),
        "status":     "Ended" if zustand.get("is_finished") else "Pre",
        "wettbewerb": ((roh.get("phase") or {}).get("competition") or {}).get("name"),
        # Wunsch #264: is_finished ist die Aussage der Quelle, dass es der
        # Endstand ist - nicht bloss "es gibt Tore".
        "bestaetigt": 1 if zustand.get("is_finished") else 0,
    }


def _sr_spiel(eintrag, wettbewerb):
    """Ein Sportradar-Spiel in unser Anzeigeformat - oder None.

    Die beiden benutzten Endpunkte liefern DASSELBE Spiel in ZWEI Formen:
    `fixtures_ribbon` verpackt Zeit und Zustand in einem `fixture`-Objekt,
    `fixtures` legt sie flach daneben (`startTimeUTC`, `status`). Beide
    Formen hier zu behandeln ist billiger, als zwei fast gleiche Funktionen
    auseinanderlaufen zu lassen."""
    beteiligte = eintrag.get("competitors") or []
    if len(beteiligte) != 2 or not any(_IST_TVB(b.get("name")) for b in beteiligte):
        return None
    heim = next((b for b in beteiligte if b.get("isHome")), beteiligte[0])
    gast = next((b for b in beteiligte if b is not heim), beteiligte[1])

    partie = eintrag.get("fixture") or eintrag
    kennung = partie.get("fixtureId")
    zeit_utc, zeit_lokal = partie.get("startTimeUTC"), partie.get("date")
    if not kennung or not (zeit_utc or zeit_lokal):
        return None
    try:
        # Wunsch #264: `startTimeUTC` ist UTC ohne Zeitzonenangabe, `date`
        # im Ribbon dagegen ORTSZEIT (20:00 fuer ein 18:00-UTC-Spiel). Bis
        # #264 wurde `date` bevorzugt und als UTC gelesen - jeder Anwurf aus
        # dem Ribbon stand damit zwei Stunden zu spaet in der Datenbank.
        if zeit_utc:
            anstoss = datetime.fromisoformat(zeit_utc).replace(
                tzinfo=UTC).astimezone(_TZ).isoformat()
        else:
            anstoss = datetime.fromisoformat(zeit_lokal).replace(tzinfo=_TZ).isoformat()
    except Exception:
        return None

    # Tore kommen im Ribbon als Zahl, in fixture_detail als Zeichenkette.
    tore_heim, tore_gast = to_int(heim.get("score")), to_int(gast.get("score"))
    zustand = partie.get("status")
    zustand_wert = (zustand.get("value") if isinstance(zustand, dict) else zustand) or ""
    # Wunsch #264: Nur die Quelle sagt, ob es der ENDSTAND ist (isFinal bzw.
    # Status CONFIRMED). Waehrend das Spiel laeuft, traegt der Ribbon schon
    # Zwischenstaende mit isLive=true - die galten bisher als Endstand, und
    # ein 33:31 aus der Schlussphase blieb als Ergebnis stehen (Hamburg,
    # 02.09.2026, wirklich 34:34). Tore ohne beides (Pokal-Spielplan) zaehlen
    # weiter als gespielt, aber unbestaetigt - fixture_detail prueft nach.
    final = bool(partie.get("isFinal")) or zustand_wert == "CONFIRMED"
    live = not final and (bool(partie.get("isLive")) or zustand_wert in ("LIVE", "IN_PROGRESS"))
    hat_tore = tore_heim is not None and tore_gast is not None
    if final:
        status = "Ended"
    elif live:
        status = "Live"
    else:
        status = "Ended" if hat_tore else "Pre"
    # Die Ergebnisliste nennt den Spieltag als Text ("Spieltag: 3"), der
    # Ribbon gar nicht. Gleiche Schreibweise wie bei handball.net.
    runde = partie.get("round")
    spieltag = None
    if isinstance(runde, str) and runde.lower().startswith("spieltag"):
        nummer = to_int(runde.split(":", 1)[1].strip()) if ":" in runde else None
        spieltag = f"{nummer}. Spieltag" if nummer else None
    return {
        "id":         f"sr{kennung}",
        "team_id":    _PROFI_TEAM_ID,
        "spieltag":   spieltag,
        "heim":       heim.get("name") or "?",
        "gast":       gast.get("name") or "?",
        "heim_tore":  tore_heim,
        "gast_tore":  tore_gast,
        "anstoss":    anstoss,
        "ort":        (partie.get("venue") or {}).get("name") if isinstance(partie.get("venue"), dict) else None,
        "status":     status,
        "wettbewerb": wettbewerb,
        "bestaetigt": 1 if final else 0,
    }


def _sr_spiel_aus_detail(antwort, wettbewerb):
    """Wunsch #263: Ein Spiel aus `fixture_detail?fixtureId=<id>` - der
    Einzelspiel-Endpunkt, der zu JEDER Kennung Status und Endstand liefert,
    egal wie lange das Spiel her ist. `data.fixture` traegt dort die
    competitors selbst, der Status ist eine Zeichenkette ("CONFIRMED")."""
    partie = ((antwort or {}).get("data") or {}).get("fixture")
    if not isinstance(partie, dict):
        return None
    return _sr_spiel({"competitors": partie.get("competitors"), "fixture": partie},
                     wettbewerb)


# Wunsch #263: Wie viele vergangene Spiele ein Seitenaufruf hoechstens
# nachprueft. Ein Aufruf je Spiel; mehr als das braucht es nur nach einer
# langen Pause, und dann holt es der naechste Aufruf nach.
_NACHLADEN_JE_AUFRUF = 6


def _profi_nachladen(db, grenze=_NACHLADEN_JE_AUFRUF):
    """Wunsch #263/#264: Vergangene Profi-Spiele ohne bestaetigten Endstand
    ueber fixture_detail nachziehen - Spiele ohne Ergebnis (Ribbon-Fenster
    verpasst) genauso wie Zwischenstaende, die vor #264 als Endstand
    gespeichert wurden. Je Spiel hoechstens ein Versuch pro Stunde
    (aktualisiert_am), damit ein Spiel, das die Quelle nicht kennt, nicht
    bei jedem Seitenaufruf neu angefragt wird. Gibt die uebernommenen Spiele
    zurueck."""
    jetzt = datetime.now(_TZ).isoformat()
    offen = db.execute("""
        SELECT id, wettbewerb FROM tvb_spiele
        WHERE  id LIKE 'sr%' AND bestaetigt = 0 AND anstoss < ?
          AND  aktualisiert_am < datetime('now', '-1 hour')
        ORDER  BY anstoss ASC LIMIT ?
    """, (jetzt, grenze)).fetchall()
    uebernommen = []
    for zeile in offen:
        kennung = zeile["id"][2:]
        # Pokalspiele liegen im Pokal-Embed; ist der Wettbewerb unbekannt
        # (Altbestand), erst die Liga, dann der Pokal.
        embeds = [255, 248] if zeile["wettbewerb"] == "DHB-Pokal" else [248, 255]
        spiel = None
        for embed in embeds:
            antwort = _sr_get(f"fixture_detail?locale=de-DE&fixtureId={kennung}", embed=embed)
            spiel = _sr_spiel_aus_detail(antwort, _SR_EMBEDS.get(embed))
            if spiel:
                break
        if spiel and spiel["status"] == "Ended" and spiel["bestaetigt"]:
            uebernommen.append(spiel)
        else:
            db.execute("UPDATE tvb_spiele SET aktualisiert_am=datetime('now') WHERE id=?",
                       (zeile["id"],))
    if uebernommen:
        _tvb_spiele_aktualisieren(db, uebernommen)
    db.commit()
    return uebernommen


def _profi_spiele():
    """Spiele der Profis aus den Sportradar-Embeds von Liga und Pokal.

    Zwei Endpunkte je Wettbewerb, weil keiner allein reicht (Wunsch #231):

    - `fixtures` liefert den kompletten weiteren Spielplan - in der Liga
      allerdings AUSSCHLIESSLICH Angesetztes: 297 Spiele, kein einziges mit
      Ergebnis. Beim Pokal ist es umgekehrt, dort steht das gespielte Spiel
      samt Resultat drin.
    - `fixtures_ribbon` liefert den AKTUELLEN Spieltag - und nur dort stehen
      die Liga-Ergebnisse, solange die Runde laeuft.

    Daraus folgt die Einschraenkung, die man kennen muss: Ein Liga-Ergebnis
    wird nur eingesammelt, wenn die App waehrend oder kurz nach dem Spieltag
    geoeffnet wird. Danach rollt es aus dem Ribbon heraus und ist von keiner
    erreichbaren Stelle mehr zu holen. Deshalb bleibt jedes einmal gesehene
    Spiel in tvb_spiele stehen."""
    # Wunsch #270: Die sechs Listen liefen nacheinander (5,5 s gemessen) -
    # jetzt in zwei parallelen Runden: erst die Spielplaene beider Embeds
    # (aus ihnen kommt der Zustand fuer den Ergebnisse-Reiter), dann
    # Ergebnisse und Ribbon fuer beide zugleich. Die Reihenfolge beim
    # Zusammenfuehren bleibt Spielplan, Ergebnisse, Ribbon je Embed.
    embeds = list(_SR_EMBEDS.items())
    with ThreadPoolExecutor(max_workers=4) as pool:
        plaene = dict(zip([e for e, _ in embeds],
                          pool.map(lambda e: _sr_get("fixtures?locale=de-DE", embed=e),
                                   [e for e, _ in embeds])))
        auftraege = []
        for embed, _ in embeds:
            # Wunsch #263, Nachtrag (07.09.2026): Der "Ergebnisse"-Reiter des
            # Widgets ist derselbe Endpunkt mit dem Widget-Zustand als `state`
            # - und liefert ALLE gespielten Spiele der Saison mit Endstand.
            # Damit bekommt auch ein Spiel eine Kennung, das nie im
            # Ribbon-Fenster gesehen wurde (das erste Saisonspiel fehlte genau
            # deshalb).
            zustand = _sr_ergebnis_zustand(plaene[embed])
            if zustand:
                auftraege.append((embed, f"fixtures?locale=de-DE&state={zustand}"))
            auftraege.append((embed, "fixtures_ribbon?locale=de-DE"))
        geholt = dict(zip(auftraege,
                          pool.map(lambda a: _sr_get(a[1], embed=a[0]), auftraege)))

    spiele = {}
    for embed, wettbewerb in embeds:
        antworten = [plaene[embed]] + [geholt[a] for a in auftraege if a[0] == embed]
        for antwort in antworten:
            for eintrag in ((antwort or {}).get("data") or {}).get("fixtures") or []:
                spiel = _sr_spiel(eintrag, wettbewerb)
                if not spiel:
                    continue
                # Dasselbe Spiel kommt aus mehreren Endpunkten. Die Fassung MIT
                # Ergebnis gewinnt - sonst ueberschriebe der reine Spielplan
                # ein gerade eingesammeltes Resultat wieder mit None - und ein
                # bestaetigter Endstand wird nicht von einem Zwischenstand
                # ersetzt (#264). Der Spieltag bleibt stehen, wenn die neuere
                # Fassung keinen kennt (der Ribbon nennt keinen).
                vorher = spiele.get(spiel["id"])
                if vorher:
                    if vorher["heim_tore"] is not None and spiel["heim_tore"] is None:
                        continue
                    if vorher["bestaetigt"] and not spiel["bestaetigt"]:
                        continue
                    if spiel["spieltag"] is None:
                        spiel["spieltag"] = vorher["spieltag"]
                spiele[spiel["id"]] = spiel
    return list(spiele.values())


def _sr_ergebnis_zustand(plan):
    """Wunsch #263, Nachtrag: Der Widget-Zustand fuer den Ergebnisse-Reiter.

    Die `fixtures`-Antwort traegt in `subPageTabs` den Link des Reiters
    (`&~w=fl~<zlib+base64>`); der Teil nach `fl~` ist genau der Wert, den
    der Endpunkt als `state` versteht. Fehlt der Reiter, wird der Zustand
    aus der Saison-Kennung selbst gebaut ({"l","s","z":"RESULTS"}, zlib,
    base64 ohne Fuellzeichen) - so ist er entstanden, nachgeprueft am
    07.09.2026. None, wenn beides fehlt."""
    daten = (plan or {}).get("data") or {}
    for reiter in daten.get("subPageTabs") or []:
        if isinstance(reiter, dict) and reiter.get("value") == "RESULTS" and "fl~" in str(reiter.get("link") or ""):
            return str(reiter["link"]).split("fl~", 1)[1]
    saison = daten.get("seasonId")
    if not saison:
        return None
    roh = json.dumps({"l": "de-DE", "s": saison, "z": "RESULTS"}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(zlib.compress(roh)).decode().rstrip("=")



def _IST_TVB(name):
    """Der Vereinsname ist bei Sportradar der einzige Anhaltspunkt - eine
    ID-Zuordnung gaebe es nur mit einem zweiten, festgeschriebenen Mapping."""
    return "tvb" in (name or "").lower() or "bittenfeld" in (name or "").lower()



def _tvb_spiele_aktualisieren(db, spiele):
    """UPSERT gesehener Spiele nach tvb_spiele - siehe Docstring oben."""
    # Wunsch #264: Ein BESTAETIGTER Endstand wird von einem unbestaetigten
    # Stand (Ribbon waehrend des Spiels, Spielplan ohne Tore) nie mehr
    # ueberschrieben; `bestaetigt` kann nur steigen. Der Anwurf wird
    # dagegen immer uebernommen - Verlegungen und die #264-Korrektur der
    # Ribbon-Zeit sollen ankommen.
    for s in spiele:
        db.execute("""
            INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, wettbewerb, bestaetigt, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                spieltag=COALESCE(excluded.spieltag, tvb_spiele.spieltag),
                heim_tore=CASE WHEN tvb_spiele.bestaetigt=1 AND excluded.bestaetigt=0
                               THEN tvb_spiele.heim_tore ELSE excluded.heim_tore END,
                gast_tore=CASE WHEN tvb_spiele.bestaetigt=1 AND excluded.bestaetigt=0
                               THEN tvb_spiele.gast_tore ELSE excluded.gast_tore END,
                status=CASE WHEN tvb_spiele.bestaetigt=1 AND excluded.bestaetigt=0
                            THEN tvb_spiele.status ELSE excluded.status END,
                anstoss=excluded.anstoss,
                wettbewerb=COALESCE(excluded.wettbewerb, tvb_spiele.wettbewerb),
                bestaetigt=MAX(tvb_spiele.bestaetigt, excluded.bestaetigt),
                aktualisiert_am=excluded.aktualisiert_am
        """, (s["id"], s["team_id"], s["spieltag"], s["heim"], s["gast"],
              s["heim_tore"], s["gast_tore"], s["anstoss"], s["ort"], s["status"],
              s["wettbewerb"], 1 if s.get("bestaetigt") else 0))
    db.commit()


def _tabelle_aus_neu(antwort, team_name):
    """Tabellenzeilen der neuen handball.net-API fuers Template.

    Leere Liste heisst "Liga hat noch keine Tabelle" (Jugend- und
    Amateurligen vor dem ersten Spieltag) - das ist kein Fehler. None heisst
    "nicht abrufbar", und nur das zeigt die Seite als Stoerung."""
    if not antwort:
        return None
    zeilen = antwort.get("data")
    if not zeilen:
        return []

    # Die API liefert die Tabelle JE SPIELTAG - fuer die 3. Liga sind das
    # 30 Runden a 16 Mannschaften, also 480 Zeilen in einer Antwort. Ohne
    # diese Auswahl stuenden alle 480 untereinander auf der Seite.
    # Genommen wird die Runde mit den meisten ausgetragenen Spielen: das ist
    # der aktuelle Stand. (Nicht die hoechste Rundennummer - die Runden sind
    # fuer die ganze Saison vorangelegt und traegen bis dahin denselben
    # Zwischenstand; und nicht Runde 1, die den Stand nach dem ersten
    # Spieltag zeigt.)
    if any(z.get("round") is not None for z in zeilen):
        nach_runde = {}
        for z in zeilen:
            nach_runde.setdefault(z.get("round"), []).append(z)
        runde = max(nach_runde,
                    key=lambda r: (sum(z.get("played") or 0 for z in nach_runde[r]),
                                   r or 0))
        zeilen = nach_runde[runde]

    # Vor dem ersten Spieltag legt die API die Tabelle bereits an, aber mit
    # `position` 0 und ueberall Nullen. Ausgegeben saehe das aus wie eine
    # echte Tabelle, in der alle auf Rang 0 stehen - der vorhandene Hinweis
    # "Fuer diese Liga gibt es noch keine Tabelle" sagt die Wahrheit besser.
    if not any((z.get("played") or 0) > 0 for z in zeilen):
        return []

    zeilen = sorted(zeilen, key=lambda z: z.get("position") or 0)
    aufbereitet = []
    for r in zeilen:
        name = ((r.get("team") or {}).get("name") or "").strip()
        aufbereitet.append({
            "rang": r.get("position"),
            "team": name,
            "hervorgehoben": name.casefold() == (team_name or "").casefold(),
            "spiele": r.get("played"),
            "siege": r.get("won"),
            "unentschieden": r.get("drawn"),
            "niederlagen": r.get("lost"),
            "tore": r.get("goals_for"),
            "gegentore": r.get("goals_against"),
            "tordifferenz": r.get("goals_diff"),
            "punkte": r.get("points"),
        })
    return aufbereitet


def _tabelle_aus_sr(antwort):
    """Tabelle der Profis aus dem Sportradar-Embed.

    Die Punkte stehen dort als "2:0" (Plus- und Minuspunkte); die Anzeige
    zeigt wie bisher nur die Pluspunkte."""
    if not antwort:
        return None
    gruppen = ((antwort.get("data") or {}).get("standings")) or []
    zeilen = gruppen[0].get("rows") if gruppen else None
    if not zeilen:
        return []
    aufbereitet = []
    for r in zeilen:
        werte = r.get("results") or {}
        name = ((r.get("team") or {}).get("name") or "").strip()
        punkte = werte.get("combinedStandingPoints")
        if isinstance(punkte, str) and ":" in punkte:
            punkte = to_int(punkte.split(":")[0], None)
        aufbereitet.append({
            "rang": r.get("position"),
            "team": name,
            "hervorgehoben": _IST_TVB(name),
            "spiele": werte.get("played"),
            "siege": werte.get("wins"),
            "unentschieden": werte.get("draws"),
            "niederlagen": werte.get("losses"),
            "tore": werte.get("scoredFor"),
            "gegentore": werte.get("scoredAgainst"),
            "tordifferenz": werte.get("pointDifference"),
            "punkte": punkte,
        })
    return aufbereitet



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
        # Vereinsdaten noch nie erreichbar gewesen: Profis trotzdem anzeigen.
        gewaehlt = {"team_id": _PROFI_TEAM_ID, "name": _VEREIN_PROFIS,
                    "kurz": "Profis", "liga": "Opel HBL", "turnier_id": None,
                    "ist_profi": 1, "altersklasse": _PROFI_KLASSE}

    team_id = gewaehlt["team_id"]

    # Zwei Welten, zwei Quellen (#191): die Profis spielen in der Opel HBL,
    # die NICHT im DHB-Spielbetrieb steckt, den die neue handball.net-API
    # abbildet. Deshalb hier die Weiche.
    if gewaehlt["ist_profi"]:
        # Wunsch #270: Frisch genug (Hintergrund-Thread) -> nur lesen. Sonst
        # selbst holen, wie vor #270 - als Rueckfall, nicht als Regel.
        if _profis_frisch(db):
            gesehene_spiele, tabelle_antwort = [], _tabelle_laden(db, _PROFI_TEAM_ID, 24 * 60)
            fehler_spiele = False
        else:
            gesehene_spiele, tabelle_antwort = _profis_auffrischen(db)
            fehler_spiele = not gesehene_spiele and tabelle_antwort is None
        tabelle = _tabelle_aus_sr(tabelle_antwort)
        fehler_tabelle = tabelle_antwort is None
    else:
        # Die Spiele der Amateur-/Jugendmannschaften kommen gesammelt beim
        # Aktualisieren der Mannschaftsliste herein (ein Aufruf fuer den
        # ganzen Verein statt einer je Mannschaft) - hier ist deshalb nichts
        # mehr zu holen; gezeigt wird der gespeicherte Bestand.
        gesehene_spiele = []
        phase_id = gewaehlt.get("turnier_id")
        tabelle_antwort = _amateur_tabelle(db, team_id, phase_id)
        tabelle = _tabelle_aus_neu(tabelle_antwort, gewaehlt["name"])
        fehler_spiele  = False
        fehler_tabelle = phase_id is not None and tabelle_antwort is None

    gespeicherte = db.execute(
        "SELECT * FROM tvb_spiele WHERE team_id=? ORDER BY anstoss ASC", (team_id,)
    ).fetchall()
    jetzt_iso = datetime.now(_TZ).isoformat()
    vergangene, kommende = [], []
    for s in gespeicherte:
        (vergangene if s["status"] in ("Ended", "Live") or s["anstoss"] < jetzt_iso
         else kommende).append(dict(s))
    vergangene.reverse()  # neueste zuerst

    # Wunsch #123: Der Kopf nennt den Verein der GEWAEHLTEN Mannschaft -
    # nur die 1. Mannschaft heisst "TVB Stuttgart" und spielt in der
    # Handball-Bundesliga, alle uebrigen laufen unter "TV Bittenfeld".
    if gewaehlt["ist_profi"]:
        kopf_verein, kopf_liga = _VEREIN_PROFIS, "Opel HBL"
    else:
        kopf_verein = _VEREIN_AMATEUR
        kopf_liga = _liga_ohne_verband(gewaehlt["liga"]) or gewaehlt["kurz"]

    return render_template("tvb.html",
        user=user, token=token, farbe=user["farbe"],
        mannschaften=mannschaften, gewaehlt=gewaehlt,
        kopf_verein=kopf_verein, kopf_liga=kopf_liga,
        fehler_spiele=fehler_spiele, fehler_tabelle=fehler_tabelle,
        vergangene=vergangene, kommende=kommende,
        haupt_wettbewerb=gewaehlt.get("liga"),
        tabelle=tabelle,
        # Wunsch #190: None, solange die Liste frisch ist - erst wenn das
        # Erneuern seit Tagen scheitert, steht hier das Datum des letzten
        # geglueckten Laufs (oder "noch nie").
        liste_veraltet=_quelle_warnung(db, _QUELLE_MANNSCHAFTEN),
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
                                  spieltage, aktionen, saison_name, dc_id, bild_url, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
        """, (
            s.get("id"), s.get("firstname") or "", s.get("lastname") or "",
            s.get("position"),
            index.get("avg"), index.get("max"), index.get("last"), index.get("trend"),
            index.get("matchdays"), index.get("events"), saison_name,
            # Wunsch #265: nur eine echte Sportradar-Kennung wird verlinkt.
            s.get("dc_id") if _DC_ID.match(str(s.get("dc_id") or "")) else None,
            # Wunsch #271: nur eine Adresse auf dem erlaubten Bild-Host.
            _bild_url_erlaubt(s.get("image")),
        ))
    db.commit()


def _bild_url_erlaubt(url):
    """Die Bild-Adresse, wenn sie auf dem erlaubten Host liegt - sonst None.
    Sie wird spaeter vom Server abgerufen; alles andere als https auf genau
    diesem Host waere ein Fremdabruf an beliebige Ziele."""
    from urllib.parse import urlsplit
    if not isinstance(url, str):
        return None
    teile = urlsplit(url.strip())
    if teile.scheme != "https" or teile.netloc.lower() != _BILD_HOST or not teile.path:
        return None
    return url.strip()


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


# --- Wunsch #265: Spielerprofile -------------------------------------------
#
# Die HPI-API kennt je Spieler nur den Index. Steckbrief und Laufbahn stehen
# auf der Spielerseite der Liga (opel-hbl.de/de/player/<dc_id>) - eine
# Nuxt-Seite, die ihre Daten serverseitig als "devalue"-Nutzlast in einem
# <script id="__NUXT_DATA__"> mitliefert: ein flaches Array, in dem Objekte
# ihre Kinder ueber Indizes referenzieren. Kein JSON-Endpunkt, den man
# direkt fragen koennte (Sportradar-Embed: kein Spieler-Endpunkt, HPI: nur
# der Index); die Seite ist ~1,5 MB gross, deshalb je Spieler ein Tag Cache
# und nur auf Knopfdruck. Fotos kommen von images.dc.connect.sportradar.com
# und werden bewusst NICHT eingebunden (kein fremder Host im Frontend, #119).
_PROFIL_BASIS = "https://www.opel-hbl.de/de/player/"
_PROFIL_MAX_ALTER_STUNDEN = 24
_DC_ID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

_PROFIL_POSITIONEN = {
    "GK": "Tor", "LW": "Linksaußen", "LB": "Rückraum links", "CB": "Rückraum Mitte",
    "RB": "Rückraum rechts", "RW": "Rechtsaußen", "P": "Kreisläufer",
}
_NATIONEN = {
    "DEU": "Deutschland", "GER": "Deutschland", "AUT": "Österreich", "SUI": "Schweiz",
    "CHE": "Schweiz", "DNK": "Dänemark", "DEN": "Dänemark", "SWE": "Schweden",
    "NOR": "Norwegen", "ISL": "Island", "FIN": "Finnland", "ESP": "Spanien",
    "FRA": "Frankreich", "PRT": "Portugal", "POR": "Portugal", "NLD": "Niederlande",
    "NED": "Niederlande", "BEL": "Belgien", "POL": "Polen", "CZE": "Tschechien",
    "SVK": "Slowakei", "HUN": "Ungarn", "HRV": "Kroatien", "CRO": "Kroatien",
    "SVN": "Slowenien", "SLO": "Slowenien", "SRB": "Serbien", "BIH": "Bosnien-Herzegowina",
    "MNE": "Montenegro", "MKD": "Nordmazedonien", "ROU": "Rumänien", "UKR": "Ukraine",
    "LTU": "Litauen", "EGY": "Ägypten", "TUN": "Tunesien", "BRA": "Brasilien",
    "ARG": "Argentinien", "JPN": "Japan", "KOR": "Südkorea", "QAT": "Katar",
    "GRC": "Griechenland", "ITA": "Italien", "LUX": "Luxemburg",
}


def _profil_html_holen(dc_id):
    """Die Spielerseite der Liga als Text - oder None."""
    req = urllib.request.Request(
        f"{_PROFIL_BASIS}{dc_id}",
        headers={"User-Agent": _UA, "Accept": "text/html"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read().decode("utf-8", "replace")
    except Exception:
        return None


def _devalue(arr, index, tiefe=0, gesehen=frozenset()):
    """Einen Knoten der devalue-Nutzlast aufloesen (Indizes -> Werte).
    Sonderformen wie ["Date", i] werden auf ihren Inhalt reduziert."""
    if not isinstance(index, int) or index < 0 or index >= len(arr):
        return index
    if index in gesehen or tiefe > 16:
        return None
    wert = arr[index]
    weiter = gesehen | {index}
    if isinstance(wert, list):
        if wert and isinstance(wert[0], str) and wert[0] in (
                "Date", "Set", "Map", "NaN", "undefined", "Infinity", "-Infinity", "BigInt"):
            return _devalue(arr, wert[1], tiefe + 1, weiter) if len(wert) > 1 else None
        return [_devalue(arr, x, tiefe + 1, weiter) for x in wert]
    if isinstance(wert, dict):
        return {k: _devalue(arr, v, tiefe + 1, weiter) for k, v in wert.items()}
    return wert


def _zahl(wert):
    return to_int(wert) if wert is not None and wert != "" else None


def _profil_statistik(roh):
    """Die Zaehler einer Saison/Station/Liga in unsere Feldnamen."""
    roh = roh or {}
    return {
        "spiele":     _zahl(roh.get("played")),
        "tore":       _zahl(roh.get("goals")),
        "siebenmeter": _zahl(roh.get("7mGoals")),
        "gelb":       _zahl(roh.get("yellowCards")),
        "zeitstrafen": _zahl(roh.get("sinBins")),
        "rot":        _zahl(roh.get("redCards")),
        "paraden":    _zahl(roh.get("goalKeeperShotsSaved")),
        "gegentore":  _zahl(roh.get("goalKeeperGoalsAgainst")),
    }


def _spieler_profil_aus_html(html):
    """Steckbrief und Laufbahn aus der Spielerseite der Liga - oder None."""
    if not html:
        return None
    treffer = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not treffer:
        return None
    try:
        arr = json.loads(treffer.group(1))
    except ValueError:
        return None
    if not isinstance(arr, list):
        return None
    for i, knoten in enumerate(arr):
        if isinstance(knoten, dict) and {"header", "overview", "career"} <= set(knoten):
            daten = _devalue(arr, i)
            break
    else:
        return None
    kopf = daten.get("header") or {}
    info = (daten.get("overview") or {}).get("info") or {}
    laufbahn = daten.get("career") or {}
    kontext = daten.get("context") or {}
    if not kopf.get("playerFamilyName") and not kopf.get("playerFullName"):
        return None
    geburtstag = str(info.get("birthday") or "")[:10] or None
    position = info.get("position")
    stationen = []
    for eintrag in laufbahn.get("perTeam") or []:
        verein = (eintrag or {}).get("team") or {}
        stationen.append({
            "verein":  verein.get("name") or "?",
            "aktuell": bool(verein.get("teamId")) and verein.get("teamId") == kontext.get("currentTeamId"),
            "gesamt":  _profil_statistik(eintrag.get("totals")),
            "saisons": [{"name": s.get("seasonName") or "", **_profil_statistik(s)}
                        for s in (eintrag.get("seasons") or [])],
        })
    ligen = [{"liga": t.get("leagueName") or "?", "saisons": _zahl(t.get("seasonCount")),
              **_profil_statistik(t)} for t in (laufbahn.get("totals") or [])]
    return {
        "vorname":    kopf.get("playerGivenName") or "",
        "nachname":   kopf.get("playerFamilyName") or "",
        "name":       kopf.get("playerFullName") or f"{kopf.get('playerGivenName', '')} {kopf.get('playerFamilyName', '')}".strip(),
        "nummer":     kopf.get("bib") or None,
        "verein":     kopf.get("teamName") or None,
        "position":   _PROFIL_POSITIONEN.get(position, position) if position else None,
        "geburtstag": geburtstag,
        "alter":      _zahl(info.get("age")),
        "nation":     _NATIONEN.get(info.get("nationality"), info.get("nationality")) if info.get("nationality") else None,
        "groesse":    _zahl(info.get("height")),
        "gewicht":    _zahl(info.get("weight")),
        "ligen":      ligen,
        "stationen":  stationen,
        "torwart":    position == "GK",
    }


def _spieler_profil(db, dc_id):
    """Profil aus dem Cache oder frisch von der Liga-Seite. Gibt
    (profil, veraltet) zurueck: veraltet=True, wenn nur ein alter Stand da
    ist, weil die Seite gerade nicht erreichbar war."""
    zeile = db.execute(
        "SELECT daten, aktualisiert_am > datetime('now', ?) AS frisch "
        "FROM tvb_spieler_profile WHERE dc_id=?",
        (f"-{_PROFIL_MAX_ALTER_STUNDEN} hours", dc_id)).fetchone()
    if zeile and zeile["frisch"]:
        return json.loads(zeile["daten"]), False
    profil = _spieler_profil_aus_html(_profil_html_holen(dc_id))
    if profil:
        db.execute("""
            INSERT INTO tvb_spieler_profile(dc_id, daten, aktualisiert_am)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(dc_id) DO UPDATE SET daten=excluded.daten,
                                             aktualisiert_am=excluded.aktualisiert_am
        """, (dc_id, json.dumps(profil, ensure_ascii=False)))
        db.commit()
        return profil, False
    if zeile:
        return json.loads(zeile["daten"]), True
    return None, False


@bp.route("/a/tvb/kader/<dc_id>", defaults={"token": None})
@bp.route("/a/tvb/<token>/kader/<dc_id>")
def spieler(token, dc_id):
    """Wunsch #265: Steckbrief, Statistik und Laufbahn eines Spielers."""
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    # Die Kennung geht in den Pfad der Fremdanfrage - nur das UUID-Muster.
    if not _DC_ID.match(dc_id or ""):
        return render_template("denied.html", reason="invalid"), 404
    db = get_db()
    profil, veraltet = _spieler_profil(db, dc_id)
    kader = db.execute(
        "SELECT vorname, nachname, position, hpi_schnitt, hpi_letzter, hpi_trend, "
        "spieltage, aktionen, saison_name FROM tvb_kader WHERE dc_id=?", (dc_id,)).fetchone()
    return render_template("tvb_spieler.html",
        user=user, token=token, farbe=user["farbe"],
        profil=profil, veraltet=veraltet, kader=dict(kader) if kader else None,
        positionen=dict(_POSITIONEN), dc_id=dc_id,
    )


# --- Wunsch #267/#268: Spieldetails -------------------------------------------
#
# Ein Tipp auf ein Spiel (kommend oder gespielt) oeffnet /spiel/<id>. Die
# Kennung ist tvb_spiele.id samt Quellen-Praefix: `sr<uuid>` (Sportradar,
# Profis) oder `n<nr>` (handball.net, Amateur/Jugend). Beide Quellen werden
# auf EIN Format gebracht (_spiel_details), damit die Vorlage nur eines
# kennt:
#   kopf        - Wettbewerb, Spieltag, Anwurf, Halle, Zuschauer, Status,
#                 beide Teams mit Endstand und Halbzeitstand
#   ticker      - Ereignisse in Reihenfolge, je mit Minute, Text, Spieler,
#                 Seite (heim/gast), Spielstand danach, Art (tor/strafe/...)
#   statistik   - je Team: Spielerzeilen mit Toren/Wuerfen, 7m, HPI, Assists,
#                 Blocks, Steals, 2 min, Karten, Spielzeit
#   aufstellung - je Team: Spieler (Nummer, Name, Position, Start/Bank),
#                 Team-Offizielle; dazu die Schiedsrichter
# Sportradar: fixture_detail (Kopf, Halbzeit, Statistik) + &sub=pbp (Ticker)
# + &sub=preview (Aufstellung, Offizielle). handball.net:
# matches/<id>/events + matches/<id>/lineups. Bilder beider Quellen werden
# nicht eingebunden (#119).
_SPIEL_ID = re.compile(r"\A(sr[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|n[0-9]{1,12})\Z")
# Wie lange ein Stand gilt: beendet und bestaetigt einen Tag (Statistiken
# werden gelegentlich nachkorrigiert), kommend sechs Stunden (Verlegung,
# Halle), laufend zwei Minuten (der Ticker soll mitgehen).
_DETAILS_ALTER = {"Ended": "-24 hours", "Pre": "-6 hours", "Live": "-2 minutes"}

_SR_STAT_SPALTEN = [
    # (Schluessel bei Sportradar, Ueberschrift, Kurzcode fuer die Legende)
    ("goalsScored:shots",        "Tore/W.", "Tore und Wuerfe"),
    ("shootingAccuracy",         "W%",     "Wurfquote"),
    ("sevenMetreGoalsScored:sevenMetreShots", "7m", "Siebenmeter Tore/Wuerfe"),
    ("handballPerformanceIndex", "HPI",    "Handball Performance Index"),
    ("assists",                  "Ass.",   "Assists"),
    ("blocks",                   "Bl.",    "Blocks"),
    ("steals",                   "St.",    "Steals"),
    ("twoMinuteSuspensions",     "2 min",  "Zeitstrafen"),
    ("technicalFaults",          "TF",     "Technische Fehler"),
    ("redCards",                 "Rot",    "Rote Karten"),
    ("timeOnPlayingField",       "Min",    "Spielzeit"),
]
def _sr_ereignis_art(ev):
    """Art eines Sportradar-Ereignisses. Nachgesehen an einem echten Spiel
    (07.09.2026): ein Wurf ist IMMER eventType "goal", `success` sagt, ob er
    drin war - der Fehlwurf ist kein eigener Typ. Zeitstrafen heissen
    "suspension", Auszeiten "timeOut"."""
    typ = ev.get("eventType")
    if typ == "goal":
        return "fehlwurf" if ev.get("success") is False else "tor"
    if typ == "suspension":
        return "strafe"
    if typ in ("yellowCard", "redCard", "blueCard"):
        return "karte"
    if typ == "timeOut":
        return "auszeit"
    if typ == "goalKeeperChange":
        return "wechsel"
    return "sonst"


def _dauer_lesbar(iso):
    """'PT27M44S' -> '27:44'; None bleibt None."""
    if not iso or not isinstance(iso, str):
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return f"{h * 60 + mi}:{s:02d}"


def _spielminute(clock, periode, laenge=30):
    """Sportradar-Uhr 'PT12M5S' im 2. Abschnitt -> '42:05'."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", clock or "")
    if not m:
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return f"{(max(periode, 1) - 1) * laenge + h * 60 + mi}:{s:02d}"


def _sr_details(zeile):
    """Sportradar -> Detailformat, oder None wenn die Quelle nicht antwortet."""
    kennung = zeile["id"][2:]
    embeds = [255, 248] if zeile["wettbewerb"] == "DHB-Pokal" else [248, 255]
    basis, embed = None, None
    for e in embeds:
        basis = _sr_get(f"fixture_detail?locale=de-DE&fixtureId={kennung}", embed=e)
        if (basis or {}).get("data", {}).get("fixture"):
            embed = e
            break
    if not embed:
        return None
    daten = basis["data"]
    partie = daten["fixture"]
    heim = next((c for c in partie.get("competitors") or [] if c.get("isHome")), None)
    gast = next((c for c in partie.get("competitors") or [] if c is not heim), None)
    if not heim or not gast:
        return None
    seiten = {heim.get("entityId"): "heim", gast.get("entityId"): "gast"}
    zustand = partie.get("status")
    zustand = zustand.get("value") if isinstance(zustand, dict) else zustand
    status = "Ended" if zustand == "CONFIRMED" else ("Live" if zustand in ("LIVE", "IN_PROGRESS") else "Pre")

    # Halbzeit: periodData.teamScores[entityId] = [{periodId:1, score}, ...]
    # - Tore JE ABSCHNITT, nicht kumuliert.
    abschnitte = {}
    for eid, liste in ((daten.get("periodData") or {}).get("teamScores") or {}).items():
        for a in liste or []:
            abschnitte.setdefault(a.get("periodId"), {})[seiten.get(eid, eid)] = to_int(a.get("score"))
    halbzeit = abschnitte.get(1)

    def team(c):
        return {"name": c.get("name") or "?", "kuerzel": c.get("code"),
                "tore": to_int(c.get("score")), "sieger": c.get("resultPlace") == 1 and not c.get("draw")}

    kopf = {
        "wettbewerb": partie.get("competitionName") or zeile["wettbewerb"],
        "spieltag": zeile["spieltag"],
        "anstoss": zeile["anstoss"],
        "halle": partie.get("venue") if isinstance(partie.get("venue"), str) else (partie.get("venue") or {}).get("name"),
        "zuschauer": to_int(partie.get("attendance")),
        "status": status,
        "heim": team(heim), "gast": team(gast),
        "halbzeit": (halbzeit.get("heim"), halbzeit.get("gast")) if halbzeit else None,
    }

    # Statistik: statistics.data.base.{home,away}.persons[0].rows
    statistik = {}
    basis_stat = ((daten.get("statistics") or {}).get("data") or {}).get("base") or {}
    for seite, schluessel in (("heim", "home"), ("gast", "away")):
        block = basis_stat.get(schluessel) or {}
        tabellen = block.get("persons") or []
        zeilen = []
        for r in (tabellen[0].get("rows") if tabellen else []) or []:
            st = r.get("statistics") or {}
            if not r.get("participated", True):
                continue
            werte = {}
            for key, _, _ in _SR_STAT_SPALTEN:
                w = st.get(key)
                if key == "timeOnPlayingField":
                    w = _dauer_lesbar(w)
                elif isinstance(w, float):
                    w = round(w, 1)
                werte[key] = w
            zeilen.append({"nummer": r.get("bib"), "name": r.get("personName") or "?",
                           "position": r.get("position"), "start": bool(r.get("starter")), **werte})
        if zeilen:
            statistik[seite] = zeilen

    # Ticker: &sub=pbp -> pbp.{"1","2",...}.events. Die Quelle kennt keine
    # Abschnittsmarken, deshalb je Block eine "n. Halbzeit"-Zeile davor und
    # nach dem letzten beendeten Block "Spielende" mit dem Endstand.
    ticker = []
    if status != "Pre":
        pbp = _sr_get(f"fixture_detail?locale=de-DE&fixtureId={kennung}&sub=pbp", embed=embed)
        bloecke = sorted(((pbp or {}).get("data") or {}).get("pbp", {}).items(),
                         key=lambda kv: to_int(kv[0]) or 0)
        letzter_stand = None
        for pid, block in bloecke:
            periode = to_int(pid) or 1
            dauer = (block or {}).get("durationMinutes") or 30
            ticker.append({"periode": periode, "minute": f"{(periode - 1) * dauer}:00",
                           "text": f"{periode}. Halbzeit", "spieler": None, "nummer": None,
                           "seite": None, "stand": None, "art": "abschnitt"})
            for ev in (block or {}).get("events") or []:
                st = ev.get("scores") or {}
                stand = (f"{to_int(st.get(heim.get('entityId')), 0)}:{to_int(st.get(gast.get('entityId')), 0)}"
                         if st else None)
                letzter_stand = stand or letzter_stand
                ticker.append({
                    "periode": periode,
                    "minute": _spielminute(ev.get("clock"), periode, dauer),
                    "text": ev.get("desc") or ev.get("eventType") or "",
                    "spieler": ev.get("name"), "nummer": ev.get("bib"),
                    "seite": seiten.get(ev.get("entityId")),
                    "stand": stand,
                    "art": _sr_ereignis_art(ev),
                })
        if bloecke and (bloecke[-1][1] or {}).get("ended"):
            periode = to_int(bloecke[-1][0]) or 1
            dauer = (bloecke[-1][1] or {}).get("durationMinutes") or 30
            ticker.append({"periode": periode, "minute": f"{periode * dauer}:00", "text": "Spielende",
                           "spieler": None, "nummer": None, "seite": None,
                           "stand": letzter_stand, "art": "abschnitt"})

    # Aufstellung + Offizielle: &sub=preview -> preview.persons
    aufstellung, schiedsrichter = {}, []
    vorschau = _sr_get(f"fixture_detail?locale=de-DE&fixtureId={kennung}&sub=preview", embed=embed)
    personen = (((vorschau or {}).get("data") or {}).get("preview") or {}).get("persons") or {}
    for eid, seite in seiten.items():
        block = personen.get(eid) or {}
        spieler = ([{"nummer": p.get("bib"), "name": p.get("name") or "?", "position": p.get("position"),
                     "alter": to_int(p.get("age")), "start": True} for p in block.get("starters") or []]
                   + [{"nummer": p.get("bib"), "name": p.get("name") or "?", "position": p.get("position"),
                       "alter": to_int(p.get("age")), "start": False} for p in block.get("substitutes") or []])
        stab = [{"name": p.get("name") or "?", "rolle": p.get("roleLabel") or p.get("role")}
                for p in block.get("staff") or []]
        if spieler or stab:
            aufstellung[seite] = {"spieler": spieler, "stab": stab}
    schiedsrichter = [{"name": p.get("name") or "?", "rolle": p.get("roleLabel") or p.get("role")}
                      for p in personen.get("matchOfficials") or []]
    return {"quelle": "Sportradar / Handball-Bundesliga", "kopf": kopf, "ticker": ticker,
            "statistik": statistik, "aufstellung": aufstellung, "schiedsrichter": schiedsrichter}


def _neu_details(zeile):
    """handball.net -> Detailformat. Kopf aus der eigenen Zeile (die API hat
    keinen Einzelspiel-Endpunkt), Ereignisse und Aufstellungen aus
    matches/<id>/events und /lineups. None nur, wenn beides fehlt."""
    nr = zeile["id"][1:]
    ereignisse = _neu_api_get(f"matches/{nr}/events")
    aufstellungen = _neu_api_get(f"matches/{nr}/lineups")
    if ereignisse is None and aufstellungen is None:
        return None
    ereignisse = (ereignisse or {}).get("data", ereignisse) or []
    aufstellungen = (aufstellungen or {}).get("data", aufstellungen) or {}

    # Nachgesehen an einem echten Spiel (07.09.2026): die Liste kommt NICHT
    # chronologisch (Halbzeitpause zuerst, dann absteigend), und das Feld
    # `score` ist ausserhalb der beiden Halbzeit-Bloecke unbrauchbar (0:1 bei
    # 9:15). Deshalb: nach Zeitstempel sortieren und den Spielstand selbst
    # aus den Toren mitzaehlen. Die Halbzeit ist der Stand beim ersten
    # Ereignis der 2. Halbzeit.
    ticker, halbzeit = [], None
    heim_tore = gast_tore = 0
    roh = sorted((ereignisse if isinstance(ereignisse, list) else []),
                 key=lambda e: (str(e.get("timestamp") or ""), to_int(e.get("id"), 0)))
    for ev in roh:
        typ = ev.get("event_type") or {}
        name = typ.get("name") or ""
        if "aufgestellt" in name:
            continue                      # Aufstellungsmeldungen sind kein Spielverlauf
        block = str(ev.get("block") or "")
        periode = 2 if block.startswith("2") else 1
        if periode == 2 and halbzeit is None:
            halbzeit = (heim_tore, gast_tore)
        if typ.get("is_goal"):
            art = "tor"
            if ev.get("is_home"):
                heim_tore += 1
            else:
                gast_tore += 1
        elif "Fehlwurf" in name:
            art = "fehlwurf"
        elif "Minuten" in name or "Disqualifikation" in name:
            art = "strafe"
        elif "Verwarnung" in name or "Karte" in name:
            art = "karte"
        elif "Auszeit" in name:
            art = "auszeit"
        elif "Spielende" in name or ("Teil" in name and "Start" in name):
            art = "abschnitt"
            name = "Spielende" if "Spielende" in name else f"{periode}. Halbzeit"
        else:
            art = "sonst"
        roh_minute = str(ev.get("minute") or "0:00")
        mm, _, ss = roh_minute.partition(":")
        if block.startswith("Halbzeit"):
            minute = "30:00"
        else:
            minute = f"{to_int(mm, 0) + (30 if periode == 2 else 0)}:{(ss or '00')[:2].rjust(2, '0')}"
        sp = ev.get("player") or {}
        ticker.append({
            "periode": periode, "minute": minute, "text": name,
            "spieler": f"{sp.get('first_name', '')} {sp.get('last_name', '')}".strip() or None,
            "nummer": None,
            "seite": "heim" if ev.get("is_home") else ("gast" if ev.get("team") else None),
            "stand": f"{heim_tore}:{gast_tore}",
            "art": art,
        })
    if halbzeit is None and ticker and zeile["heim_tore"] is not None:
        halbzeit = None               # kein zweiter Abschnitt gesehen - lieber nichts behaupten

    aufstellung, statistik = {}, {}
    for seite, schluessel in (("heim", "local"), ("gast", "visitor")):
        block = aufstellungen.get(schluessel) or {}
        spieler, zeilen = [], []
        for p in block.get("players") or []:
            person = p.get("player") or {}
            name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip() or "?"
            spieler.append({"nummer": p.get("number"), "name": name,
                            "position": "Tor" if p.get("is_goalkeeper") else None,
                            "alter": None, "start": bool(p.get("is_starter"))})
            zeilen.append({"nummer": p.get("number"), "name": name, "position": None,
                           "start": bool(p.get("is_starter")),
                           "goalsScored:shots": to_int(p.get("goals")),
                           "sevenMetreGoalsScored:sevenMetreShots":
                               f"{to_int(p.get('seven_meter_goals'), 0)}/{to_int(p.get('seven_meter_attempts'), 0)}"
                               if p.get("seven_meter_attempts") else None,
                           "twoMinuteSuspensions": to_int(p.get("two_minutes"))})
        stab = [{"name": f"{(p.get('player') or {}).get('first_name', '')} {(p.get('player') or {}).get('last_name', '')}".strip() or "?",
                 "rolle": (p.get("role") or {}).get("name")} for p in block.get("staff") or []]
        if spieler or stab:
            aufstellung[seite] = {"spieler": spieler, "stab": stab}
        if zeilen and zeile["heim_tore"] is not None:
            statistik[seite] = zeilen

    kopf = {
        "wettbewerb": zeile["wettbewerb"], "spieltag": zeile["spieltag"], "anstoss": zeile["anstoss"],
        "halle": zeile["ort"], "zuschauer": None, "status": zeile["status"],
        "heim": {"name": zeile["heim"], "kuerzel": None, "tore": zeile["heim_tore"],
                 "sieger": zeile["heim_tore"] is not None and zeile["gast_tore"] is not None and zeile["heim_tore"] > zeile["gast_tore"]},
        "gast": {"name": zeile["gast"], "kuerzel": None, "tore": zeile["gast_tore"],
                 "sieger": zeile["heim_tore"] is not None and zeile["gast_tore"] is not None and zeile["gast_tore"] > zeile["heim_tore"]},
        "halbzeit": halbzeit,
    }
    return {"quelle": "handball.net", "kopf": kopf, "ticker": ticker, "statistik": statistik,
            "aufstellung": aufstellung, "schiedsrichter": []}


def _spiel_details(db, zeile):
    """Details aus dem Cache oder frisch. (details, veraltet) - veraltet=True
    bedeutet: die Quelle war gerade nicht erreichbar, das ist ein alter Stand."""
    frist = _DETAILS_ALTER.get(zeile["status"], "-6 hours")
    cache = db.execute(
        "SELECT daten, aktualisiert_am > datetime('now', ?) AS frisch "
        "FROM tvb_spiel_details WHERE id=?", (frist, zeile["id"])).fetchone()
    if cache and cache["frisch"]:
        return json.loads(cache["daten"]), False
    details = _sr_details(zeile) if zeile["id"].startswith("sr") else _neu_details(zeile)
    if details:
        db.execute("""
            INSERT INTO tvb_spiel_details(id, daten, aktualisiert_am) VALUES (?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET daten=excluded.daten, aktualisiert_am=excluded.aktualisiert_am
        """, (zeile["id"], json.dumps(details, ensure_ascii=False)))
        db.commit()
        return details, False
    if cache:
        return json.loads(cache["daten"]), True
    return None, False


def _kopf_aus_zeile(zeile):
    """Notnagel ohne Quelle: das, was die eigene Zeile hergibt."""
    return {
        "wettbewerb": zeile["wettbewerb"], "spieltag": zeile["spieltag"], "anstoss": zeile["anstoss"],
        "halle": zeile["ort"], "zuschauer": None, "status": zeile["status"],
        "heim": {"name": zeile["heim"], "kuerzel": None, "tore": zeile["heim_tore"], "sieger": False},
        "gast": {"name": zeile["gast"], "kuerzel": None, "tore": zeile["gast_tore"], "sieger": False},
        "halbzeit": None,
    }


@bp.route("/a/tvb/spiel/<sid>", defaults={"token": None})
@bp.route("/a/tvb/<token>/spiel/<sid>")
def spiel(token, sid):
    """Wunsch #267/#268: Details zu einem Spiel - kommend oder gespielt."""
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    if not _SPIEL_ID.match(sid or ""):
        return render_template("denied.html", reason="invalid"), 404
    db = get_db()
    zeile = db.execute("SELECT * FROM tvb_spiele WHERE id=?", (sid,)).fetchone()
    if not zeile:
        return render_template("denied.html", reason="invalid"), 404
    details, veraltet = _spiel_details(db, zeile)
    mannschaft = db.execute(
        "SELECT name FROM tvb_mannschaften WHERE team_id=?", (zeile["team_id"],)).fetchone()
    tvb_name = mannschaft["name"] if mannschaft else _VEREIN_PROFIS
    return render_template("tvb_spiel.html",
        user=user, token=token, farbe=user["farbe"],
        zeile=dict(zeile), details=details, veraltet=veraltet,
        kopf=(details or {}).get("kopf") or _kopf_aus_zeile(zeile),
        tvb_name=tvb_name, team_id=zeile["team_id"],
        stat_spalten=_SR_STAT_SPALTEN,
    )


# --- Wunsch #271: Spielerbilder ----------------------------------------------------

def _bild_holen(url):
    """Laedt das Bild vom erlaubten Host: (bytes, mimetype) oder None. Die
    CDN-Adresse nimmt Groesse und Format als Parameter - 400 px webp sind
    rund 30 KB statt 190 KB als PNG."""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    teile = urlsplit(url)
    parameter = dict(parse_qsl(teile.query))
    parameter.update({"size": "400", "format": "webp"})
    ziel = urlunsplit((teile.scheme, teile.netloc, teile.path, urlencode(parameter), ""))
    req = urllib.request.Request(ziel, headers={"User-Agent": _UA, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            mime = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            daten = resp.read(_BILD_MAX_BYTES + 1)
    except Exception:
        return None
    if not mime.startswith("image/") or len(daten) > _BILD_MAX_BYTES or not daten:
        return None
    return daten, mime


def _bild_pfad(dc_id):
    return os.path.join(current_app.config["DATA_DIR"], "tvb_bilder", f"{dc_id}.webp")


def _bild_platzhalter(vorname, nachname):
    """Ein SVG mit den Initialen - fuer Spieler ohne (erreichbares) Bild.
    Ein Bild, das sicher kommt, statt eines kaputten Bildsymbols."""
    initialen = "".join(t[:1] for t in (vorname or "", nachname or "") if t).upper() or "?"
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<circle cx="50" cy="50" r="50" fill="#c7ccd6"/>'
           '<text x="50" y="62" text-anchor="middle" font-family="sans-serif" '
           f'font-size="38" font-weight="700" fill="#ffffff">{initialen}</text></svg>')
    return Response(svg, mimetype="image/svg+xml", headers={"Cache-Control": "max-age=3600"})


@bp.route("/a/tvb/bild/<dc_id>", defaults={"token": None})
@bp.route("/a/tvb/<token>/bild/<dc_id>")
def spieler_bild(token, dc_id):
    """Wunsch #271: Das Spielerbild aus dem eigenen Zwischenspeicher - einmal
    vom CDN geholt, eine Woche behalten, dann erneuert. Ohne Bild-Adresse
    oder wenn das CDN nicht liefert: Initialen als SVG."""
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    if not _DC_ID.match(dc_id or ""):
        return render_template("denied.html", reason="invalid"), 404
    db = get_db()
    zeile = db.execute(
        "SELECT vorname, nachname, bild_url FROM tvb_kader WHERE dc_id=?", (dc_id,)).fetchone()
    if not zeile:
        return render_template("denied.html", reason="invalid"), 404
    pfad = _bild_pfad(dc_id)
    frisch = (os.path.exists(pfad)
              and time.time() - os.path.getmtime(pfad) < _BILD_MAX_ALTER_TAGE * 86400)
    if not frisch and zeile["bild_url"]:
        geholt = _bild_holen(zeile["bild_url"])
        if geholt:
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            with open(pfad, "wb") as f:
                f.write(geholt[0])
            frisch = True
    if not os.path.exists(pfad):
        return _bild_platzhalter(zeile["vorname"], zeile["nachname"])
    return send_file(pfad, mimetype="image/webp", max_age=86400, conditional=True)


def init_app(app):
    app.register_blueprint(bp)
    # Wunsch #270: Auffrischung im Hintergrund. Schalter wie bei #145/#183;
    # in der Testumgebung aus (tests/conftest.py).
    if str(app.config.get("TVB_HINTERGRUND", "1")).strip() in ("1", "true", "ja"):
        threading.Thread(target=_hintergrund_schleife, args=(app,), daemon=True).start()
