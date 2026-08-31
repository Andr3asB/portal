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
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, redirect, render_template, request
from teile.kern import grant as check_grant, get_db, to_int, utc_zu_lokal

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



def _mannschaften_holen(db):
    """Mannschaftsliste, bei Bedarf vorher aktualisiert."""
    frisch = db.execute("""
        SELECT 1 FROM tvb_mannschaften
        WHERE aktualisiert_am > datetime('now', ?) LIMIT 1
    """, (f"-{_MANNSCHAFTEN_MAX_ALTER_STUNDEN} hours",)).fetchone()
    if not frisch and not _quelle_pausiert(db, _QUELLE_MANNSCHAFTEN):
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
    zeit = partie.get("date") or partie.get("startTimeUTC")
    if not kennung or not zeit:
        return None
    try:
        # Beide Endpunkte liefern UTC OHNE Zeitzonenangabe. Wird das als
        # Ortszeit gelesen, liegt jeder Anwurf zwei Stunden daneben.
        anstoss = datetime.fromisoformat(zeit).replace(
            tzinfo=timezone.utc).astimezone(_TZ).isoformat()
    except Exception:
        return None

    tore_heim, tore_gast = heim.get("score"), gast.get("score")
    fertig = partie.get("isFinal") or (tore_heim is not None and tore_gast is not None)
    return {
        "id":         f"sr{kennung}",
        "team_id":    _PROFI_TEAM_ID,
        "spieltag":   None,
        "heim":       heim.get("name") or "?",
        "gast":       gast.get("name") or "?",
        "heim_tore":  tore_heim,
        "gast_tore":  tore_gast,
        "anstoss":    anstoss,
        "ort":        (partie.get("venue") or {}).get("name") if isinstance(partie.get("venue"), dict) else None,
        "status":     "Ended" if fertig else "Pre",
        "wettbewerb": wettbewerb,
    }


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
    spiele = {}
    for embed, wettbewerb in _SR_EMBEDS.items():
        for pfad in ("fixtures?locale=de-DE", "fixtures_ribbon?locale=de-DE"):
            antwort = _sr_get(pfad, embed=embed)
            for eintrag in ((antwort or {}).get("data") or {}).get("fixtures") or []:
                spiel = _sr_spiel(eintrag, wettbewerb)
                if not spiel:
                    continue
                # Dasselbe Spiel kommt aus beiden Endpunkten. Die Fassung MIT
                # Ergebnis gewinnt - sonst ueberschriebe der reine Spielplan
                # ein gerade eingesammeltes Resultat wieder mit None.
                vorher = spiele.get(spiel["id"])
                if vorher and vorher["heim_tore"] is not None and spiel["heim_tore"] is None:
                    continue
                spiele[spiel["id"]] = spiel
    return list(spiele.values())



def _IST_TVB(name):
    """Der Vereinsname ist bei Sportradar der einzige Anhaltspunkt - eine
    ID-Zuordnung gaebe es nur mit einem zweiten, festgeschriebenen Mapping."""
    return "tvb" in (name or "").lower() or "bittenfeld" in (name or "").lower()



def _tvb_spiele_aktualisieren(db, spiele):
    """UPSERT gesehener Spiele nach tvb_spiele - siehe Docstring oben."""
    for s in spiele:
        db.execute("""
            INSERT INTO tvb_spiele(id, team_id, spieltag, heim, gast, heim_tore, gast_tore, anstoss, ort, status, wettbewerb, aktualisiert_am)
            VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                spieltag=excluded.spieltag, heim_tore=excluded.heim_tore, gast_tore=excluded.gast_tore,
                status=excluded.status, wettbewerb=excluded.wettbewerb,
                aktualisiert_am=excluded.aktualisiert_am
        """, (s["id"], s["team_id"], s["spieltag"], s["heim"], s["gast"],
              s["heim_tore"], s["gast_tore"], s["anstoss"], s["ort"], s["status"],
              s["wettbewerb"]))
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
        tabelle_antwort = _sr_get("standings?locale=de-DE", embed=_SR_TABELLE_EMBED)
        gesehene_spiele = _profi_spiele()
        tabelle = _tabelle_aus_sr(tabelle_antwort)
        fehler_spiele  = not gesehene_spiele and tabelle_antwort is None
        fehler_tabelle = tabelle_antwort is None
        _quelle_melden(db, _QUELLE_PROFIS, tabelle_antwort is not None,
                       None if tabelle_antwort is not None else "Sportradar nicht abrufbar")
    else:
        # Die Spiele der Amateur-/Jugendmannschaften kommen gesammelt beim
        # Aktualisieren der Mannschaftsliste herein (ein Aufruf fuer den
        # ganzen Verein statt einer je Mannschaft) - hier ist deshalb nichts
        # mehr zu holen; gezeigt wird der gespeicherte Bestand.
        gesehene_spiele = []
        phase_id = gewaehlt.get("turnier_id")
        tabelle_antwort = (_neu_api_get(f"standings?phase_id={phase_id}")
                           if phase_id else None)
        tabelle = _tabelle_aus_neu(tabelle_antwort, gewaehlt["name"])
        fehler_spiele  = False
        fehler_tabelle = phase_id is not None and tabelle_antwort is None

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
