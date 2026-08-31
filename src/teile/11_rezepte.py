"""
Rezepte-App – Lieblingsrezepte mit Zutaten und Zubereitung.
URL-Präfix: /a/rezepte/<token>/
Fehlende Zutaten lassen sich mit einem Klick auf die Einkaufsliste setzen.

Zubereitung liegt als eigene Schritte in rezept_schritte (analog zu
rezept_zutaten), nicht als ein Textblock – näher an schema.org/Recipes
HowToStep-Liste, weniger Informationsverlust beim Import. rezepte.portionen
speichert recipeYield als Freitext (z. B. "4" oder "4-6 Portionen").

Rezept-Import per URL: eingebettete schema.org/Recipe-Daten (JSON-LD) werden
zuerst versucht (kostenlos, zuverlässig, keine KI nötig), erst wenn eine Seite
keine liefert, geht der sichtbare Text an ki_anfrage(). Das Ergebnis landet in
beiden Fällen nur vorausgefüllt im bestehenden Neu-Formular – nie ungeprüft
direkt in der DB, weil sowohl JSON-LD als auch KI-Extraktion daneben liegen
können.

Wunsch #137: Die KI-Antwort selbst (URL- wie Foto-Import) läuft zusätzlich
durch `_ki_rezept_validieren()` – striktes Schema statt blindem `json.loads()`.
Eine präparierte Webseite könnte dem Sprachmodell sonst Anweisungen
unterschieben; der direkte Schaden wäre zwar begrenzt (die Ausgabe landet
escaped in einem Rezept, das der Nutzer ohnehin anlegen darf), aber nur
bekannte Felder werden gelesen, Listen-Einträge, die keine Zeichenkette/Zahl
sind, werden verworfen statt mit `str(...)` verunstaltet übernommen, und jedes
Feld hat eine feste Längen-/Mengenobergrenze.

Rezept-Import per Foto (Wunsch #97): Kamera oder Mediathek, OCR+Extraktion
über ki_anfrage() mit Bildeingabe (eigener KI-Zweck "rezepte_foto_import",
unabhängig vom URL-Import konfigurierbar). Liefert dieselbe Datenform wie
_rezept_aus_jsonld()/_rezept_per_ki() (name/portionen/zutaten/schritte) und
landet deshalb genau wie der URL-Import nur vorausgefüllt im bestehenden
Neu-Formular - keine eigene Prüf-Seite nötig, anders als beim Vokabeln-
Foto-Import (Wunsch #80), wo ein Foto mehrere Vokabelpaare gleichzeitig
liefert und deshalb eine eigene Zeilen-Prüf-Ansicht braucht. Der Datei-
Input in rezept_bild_importieren.html hat bewusst KEIN capture="environment"
mehr (Wunsch #106) - das Attribut zwingt iOS Safari, direkt die Kamera zu
öffnen, OHNE die Option "Mediathek" in der nativen Auswahl anzuzeigen, ein
bekanntes Verhalten mobiler Browser. Ohne capture zeigt iOS die normale
Auswahl (Foto aufnehmen ODER aus Mediathek wählen).

Bearbeiten (bearbeiten()) nutzt dasselbe Formular (rezept_neu.html) wie
Neuanlegen und Import-Vorschau, unterschieden nur über den bearbeiten-Parameter
(Ziel-Route, Titel, Speichern-Button-Text). Zutaten/Schritte werden beim
Speichern komplett ersetzt, kein Zeilen-Diffing.
"""
import base64
import http.client
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from teile.kern import (
    KiLimitError,
    bereinige_erfuellte_rezeptwuensche,
    get_db,
    ki_anfrage,
    to_int,
)
from teile.kern import (
    grant as check_grant,
)
from teile.kern import (
    ip_ist_oeffentlich as _ip_ist_oeffentlich,
)
from teile.kern import (
    ist_oeffentliche_url as _ist_oeffentliche_url,
)

MAX_REZEPT_WUENSCHE = 5
# Wunsch #127: Obergrenze fuer selbst gefolgte Weiterleitungen.
_MAX_WEITERLEITUNGEN = 5

bp  = Blueprint("rezepte_app", __name__)
APP = "rezepte"

KATEGORIEN = {"kochen": "🍳 Kochen", "backen": "🍰 Backen"}

# Wunsch #184: Das Symbol vor einem Rezept folgt der Kategorie. Es ist
# absichtlich DASSELBE Zeichen wie im Kategorie-Label darueber - zwei
# verschiedene Symbole fuer dieselbe Sache muesste man erst lernen.
# Ohne Kategorie bleibt der neutrale Topf; er heisst hier "unbekannt",
# nicht "kochen", damit man den Unterschied auf der Seite noch sieht.
KATEGORIE_SYMBOL = {"kochen": "🍳", "backen": "🍰"}
SYMBOL_OHNE_KATEGORIE = "🍲"


def kategorie_symbol(wert) -> str:
    return KATEGORIE_SYMBOL.get(wert or "", SYMBOL_OHNE_KATEGORIE)

# Wunsch #97: Foto-Import - gleiche Grenzen/MIME-Zuordnung wie beim
# Vokabeln-Foto-Import (16_vokabeln.py), bewusst dupliziert statt
# cross-importiert (kleine Konstanten, kein gemeinsames Modul dafür noetig).
_FOTO_MAX_BYTES = 8 * 1024 * 1024
_FOTO_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic"}


def _clean_kategorie(value):
    value = (value or "").strip()
    return value if value in KATEGORIEN else None


_JSONLD_RE      = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_MAX_FETCH_BYTES = 3 * 1024 * 1024
_FETCH_TIMEOUT   = 10


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


class _TextExtractor(HTMLParser):
    """Simple Textextraktion für die KI-Eingabe – ignoriert Script/Style/Nav."""
    _IGNORE_TAGS = frozenset({"script", "style", "nav", "header", "footer", "noscript"})

    def __init__(self):
        super().__init__()
        self._ignore_depth = 0
        self.text_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._IGNORE_TAGS:
            self._ignore_depth += 1

    def handle_endtag(self, tag):
        if tag in self._IGNORE_TAGS and self._ignore_depth > 0:
            self._ignore_depth -= 1

    def handle_data(self, data):
        if self._ignore_depth == 0:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)


# Wunsch #203 (Sicherheitsaudit 11.08.2026): _ist_oeffentliche_url() und
# _ip_ist_oeffentlich() sind nach teile/00_kern.py umgezogen, weil 07_push.py
# dieselbe Pruefung fuer Web-Push-Endpunkte braucht - der Import oben bindet
# die Namen unveraendert wieder hier an, damit an dieser Datei sonst nichts
# angepasst werden muss.


class _RohantwortDurchreichen(urllib.request.HTTPErrorProcessor):
    """Wunsch #127: urllib folgte Weiterleitungen automatisch und OHNE das
    Ziel erneut zu pruefen - eine harmlos aussehende, oeffentliche URL mit
    einem 302 auf http://172.30.0.10:2019/ landete damit direkt bei der
    Caddy-Admin-API.

    Wir wollen die 3xx-Antwort selbst in der Hand haben, um jede
    Zwischenstation erneut durch _ist_oeffentliche_url zu schicken.
    Weiterleitungen ganz zu verbieten waere einfacher, wuerde den Import aber
    fuer die halbe Welt kaputtmachen: Rezeptseiten leiten staendig um
    (http->https, ohne->mit www, Trailing-Slash).

    Achtung, Stolperstein: Es genuegt NICHT, in einem HTTPRedirectHandler
    `redirect_request` None zurueckgeben zu lassen. urllib wertet das als
    "nicht behandelt" und laesst dann den Standard-Fehlerhandler einen
    HTTPError werfen - die Weiterleitung kaeme nie bei uns an. Stattdessen
    wird hier der HTTPErrorProcessor ersetzt, der sonst jede Antwort ausser
    2xx in einen HTTPError verwandelt; so bekommen wir die Antwort roh."""

    def http_response(self, request, response):
        return response

    https_response = http_response


# Wunsch #127, zweite Luecke: DNS-Rebinding. Zwischen der Pruefung in
# _ist_oeffentliche_url und dem eigentlichen Abruf loeste urllib den Hostnamen
# ein zweites Mal auf. Ein Angreifer-DNS mit sehr kurzer TTL konnte beim ersten
# Mal eine oeffentliche und beim zweiten Mal eine interne Adresse liefern - die
# Pruefung lief dann ins Leere. Die beiden Klassen unten verbinden deshalb
# genau zu der IP, die geprueft wurde. Wichtig: der HOSTNAME bleibt in
# self.host stehen, damit Host-Header, SNI und die Zertifikatspruefung
# weiterhin auf den echten Namen laufen - nur das Verbindungsziel ist gepinnt.
class _GepinnteHTTPVerbindung(http.client.HTTPConnection):
    def __init__(self, host, ziel_ip=None, **kw):
        super().__init__(host, **kw)
        self._ziel_ip = ziel_ip

    def connect(self):
        self.sock = socket.create_connection(
            (self._ziel_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _GepinnteHTTPSVerbindung(http.client.HTTPSConnection):
    def __init__(self, host, ziel_ip=None, **kw):
        super().__init__(host, **kw)
        self._ziel_ip = ziel_ip

    def connect(self):
        sock = socket.create_connection(
            (self._ziel_ip, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            sock = self.sock
        # server_hostname = echter Name -> Zertifikat wird korrekt geprueft
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _GepinnterHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, ziel_ip):
        super().__init__()
        self._ziel_ip = ziel_ip

    def http_open(self, req):
        return self.do_open(
            lambda host, **kw: _GepinnteHTTPVerbindung(host, ziel_ip=self._ziel_ip, **kw), req)


class _GepinnterHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, ziel_ip):
        super().__init__()
        self._ziel_ip = ziel_ip

    def https_open(self, req):
        return self.do_open(
            lambda host, **kw: _GepinnteHTTPSVerbindung(host, ziel_ip=self._ziel_ip, **kw), req)


def _oeffentliche_ip_zu(hostname: str) -> str:
    """Loest auf und gibt die erste oeffentliche Adresse zurueck.
    ValueError, wenn keine gefunden wird."""
    for info in socket.getaddrinfo(hostname, None):
        kandidat = info[4][0].split("%")[0]
        try:
            if _ip_ist_oeffentlich(ipaddress.ip_address(kandidat)):
                return kandidat
        except ValueError:
            continue
    raise ValueError("Zieladresse ist nicht öffentlich erreichbar")


def _einmal_abrufen(url: str):
    """Ein einzelner Sprung: aufloesen, pruefen, zur gepinnten IP verbinden.
    Folgt KEINER Weiterleitung - die wertet _seite_abrufen selbst aus."""
    parsed = urlparse(url)
    ziel_ip = _oeffentliche_ip_zu(parsed.hostname)
    opener = urllib.request.build_opener(
        _RohantwortDurchreichen,
        _GepinnterHTTPHandler(ziel_ip),
        _GepinnterHTTPSHandler(ziel_ip),
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FamilienportalRezeptImport/1.0)",
    })
    return opener.open(req, timeout=_FETCH_TIMEOUT)


def _seite_abrufen(url: str) -> str:
    """Laedt eine Rezeptseite und folgt dabei Weiterleitungen selbst, damit
    JEDE Station erneut geprueft wird (Wunsch #127). Setzt voraus, dass die
    erste URL bereits durch _ist_oeffentliche_url gelaufen ist."""
    gesehen = set()
    for _ in range(_MAX_WEITERLEITUNGEN + 1):
        if url in gesehen:
            raise ValueError("Weiterleitungsschleife")
        gesehen.add(url)

        resp = _einmal_abrufen(url)
        with resp:
            if resp.status in (301, 302, 303, 307, 308):
                ziel = resp.headers.get("Location")
                if not ziel:
                    raise ValueError("Weiterleitung ohne Ziel")
                # Relative Ziele ("/rezept/123") gegen die aktuelle URL aufloesen
                url = urljoin(url, ziel)
                # Das ist der entscheidende Punkt: die neue Adresse wird
                # genauso streng geprueft wie die erste. Eine Weiterleitung
                # auf 172.30.0.10 oder 127.0.0.1 endet hier.
                if not _ist_oeffentliche_url(url):
                    raise ValueError("Weiterleitung zeigt auf eine interne Adresse")
                continue

            # Seit _RohantwortDurchreichen wirft urllib bei Fehlerstatus nicht
            # mehr von selbst - hier explizit abbrechen, sonst wuerde eine
            # 404-Fehlerseite als Rezept interpretiert.
            if resp.status != 200:
                raise ValueError(f"Seite nicht abrufbar (HTTP {resp.status})")

            raw = resp.read(_MAX_FETCH_BYTES + 1)
            if len(raw) > _MAX_FETCH_BYTES:
                raise ValueError("Seite zu groß")
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")

    raise ValueError("Zu viele Weiterleitungen")


def _jsonld_kandidaten(data):
    """JSON-LD kann ein einzelnes Objekt, eine Liste oder @graph sein."""
    if isinstance(data, list):
        for item in data:
            yield from _jsonld_kandidaten(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _jsonld_kandidaten(data["@graph"])
        else:
            yield data


def _anleitung_schritt(schritt) -> str:
    """Ein einzelnes Element aus recipeInstructions: HowToStep (hat "text")
    oder ein einfacher Freitext-Eintrag."""
    if isinstance(schritt, dict):
        return (schritt.get("text") or schritt.get("name") or "").strip()
    return str(schritt).strip()


def _anleitung_zu_liste(roh) -> list:
    """recipeInstructions -> Liste einzelner Schritte (Wunsch: Zubereitung als
    eigene Schritte statt ein Textblock, näher an schema.org/Recipe). Deckt
    HowToStep-Listen, verschachtelte HowToSection (itemListElement) und den
    Fallback auf einen einzelnen Freitext-Block ab (zeilenweise als Schritte)."""
    if isinstance(roh, str):
        return [z.strip() for z in roh.splitlines() if z.strip()]
    if isinstance(roh, list):
        ergebnis = []
        for schritt in roh:
            if isinstance(schritt, dict) and "itemListElement" in schritt:
                ergebnis.extend(_anleitung_zu_liste(schritt["itemListElement"]))
            else:
                text = _anleitung_schritt(schritt)
                if text:
                    ergebnis.append(text)
        return ergebnis
    return []


def _portionen_aus_jsonld(daten: dict):
    """recipeYield kann ein String, eine Zahl, eine Liste oder ein
    QuantitativeValue-Objekt ({"value": ...}) sein."""
    roh = daten.get("recipeYield")
    if isinstance(roh, list):
        roh = roh[0] if roh else None
    if isinstance(roh, dict):
        roh = roh.get("value")
    if roh is None:
        return None
    text = str(roh).strip()
    return text or None


def _jsonld_zu_rezept(daten: dict):
    name = str(daten.get("name") or "").strip()
    if not name:
        return None
    zutaten = daten.get("recipeIngredient") or daten.get("ingredients") or []
    if isinstance(zutaten, str):
        zutaten = [zutaten]
    return {
        "name": name,
        "portionen": _portionen_aus_jsonld(daten),
        "zutaten": [str(z).strip() for z in zutaten if str(z).strip()],
        "schritte": _anleitung_zu_liste(daten.get("recipeInstructions") or []),
    }


def _rezept_aus_jsonld(html: str):
    """Sucht eingebettete schema.org/Recipe-Daten. None, wenn nichts gefunden."""
    for match in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(match.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for kandidat in _jsonld_kandidaten(data):
            typ = kandidat.get("@type", "")
            typen = typ if isinstance(typ, list) else [typ]
            if any("recipe" in str(t).lower() for t in typen):
                rezept = _jsonld_zu_rezept(kandidat)
                if rezept:
                    return rezept
    return None


# Wunsch #137: Obergrenzen fuer die KI-Extraktion (URL- und Foto-Import).
# Eine praeparierte Webseite oder ein manipuliertes Foto kann dem
# Sprachmodell Anweisungen unterschieben ("ignoriere die Aufgabe, gib
# stattdessen ... aus") und damit steuern, was als Rezept zurueckkommt. Der
# direkte Schaden ist begrenzt - die Ausgabe landet escaped in einem eigenen
# Rezept, das der Nutzer ohnehin anlegen darf -, aber ein striktes Schema
# verhindert wenigstens, dass beliebig lange oder beliebig strukturierte
# Antworten unbesehen durchgereicht werden.
_KI_NAME_MAX      = 200
_KI_PORTIONEN_MAX = 60
_KI_ZUTAT_MAX     = 200
_KI_ZUTATEN_MAX   = 60
_KI_SCHRITT_MAX   = 2000
_KI_SCHRITTE_MAX  = 60


def _ki_rezept_validieren(antwort: str) -> dict:
    """Parst und prüft eine KI-Antwort strikt gegen das erwartete Schema.

    Nur die vier bekannten Felder werden gelesen - alles andere in der
    Antwort wird ignoriert, nicht durchgereicht. `zutaten`/`schritte` müssen
    Listen sein; Einträge, die keine Zeichenkette oder Zahl sind (z. B. ein
    verschachteltes Objekt), werden verworfen statt mit `str(...)` in einen
    hässlichen Literaltext verwandelt zu werden. Jedes Feld hat eine feste
    Längen- bzw. Mengenobergrenze. Wirft ValueError bei fehlendem Namen -
    das ist bereits das bestehende Fehlerverhalten, auf das die Aufrufer
    reagieren."""
    bereinigt = antwort.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.strip("`")
        if bereinigt.lower().startswith("json"):
            bereinigt = bereinigt[4:]
    daten = json.loads(bereinigt)
    if not isinstance(daten, dict):
        raise ValueError("KI-Antwort ist kein JSON-Objekt")

    name = str(daten.get("name") or "").strip()[:_KI_NAME_MAX]
    if not name:
        raise ValueError("KI hat keinen Rezeptnamen erkannt")

    portionen = str(daten.get("portionen") or "").strip()[:_KI_PORTIONEN_MAX] or None

    def _liste(schluessel, max_laenge, max_anzahl):
        roh = daten.get(schluessel)
        if not isinstance(roh, list):
            return []
        raus = []
        for eintrag in roh[:max_anzahl]:
            if not isinstance(eintrag, (str, int, float)):
                continue                      # kein verschachteltes Objekt
            text = str(eintrag).strip()[:max_laenge]
            if text:
                raus.append(text)
        return raus

    return {
        "name": name,
        "portionen": portionen,
        "zutaten":  _liste("zutaten",  _KI_ZUTAT_MAX,   _KI_ZUTATEN_MAX),
        "schritte": _liste("schritte", _KI_SCHRITT_MAX, _KI_SCHRITTE_MAX),
    }


def _rezept_per_ki(user_id: int, html: str, url: str):
    """Fallback, falls die Seite kein JSON-LD liefert – KI-Extraktion über
    ki_anfrage() (Wunsch: KI-Rezept-Import). Wirft KiLimitError/KiFehler/
    ValueError bei Problemen, der Aufrufer fängt sie ab und zeigt eine
    freundliche Fehlermeldung statt eines defekten Rezepts."""
    parser = _TextExtractor()
    parser.feed(html)
    text = " ".join(parser.text_parts)[:6000]
    system = (
        'Du extrahierst Kochrezepte aus Webseiten-Text. Antworte AUSSCHLIESSLICH mit '
        'einem JSON-Objekt der Form {"name": "...", "portionen": "...", "zutaten": ["..."], '
        '"schritte": ["..."]}. "portionen" ist die Anzahl Personen/Portionen als kurzer '
        'Text (z. B. "4" oder "4-6 Portionen"), leerer String wenn nicht erkennbar. '
        '"schritte" ist eine Liste einzelner Zubereitungsschritte, kein zusammenhängender '
        'Text. Keine Erklärung, kein Markdown, kein Codeblock.'
    )
    prompt  = f"Seiten-URL: {url}\n\nSeitentext:\n{text}"
    antwort = ki_anfrage(user_id, "rezepte_import", system, prompt)
    return _ki_rezept_validieren(antwort)


@bp.route("/a/rezepte/", defaults={"token": None})
@bp.route("/a/rezepte/<token>/")
def index(token):
    """Wunsch #49: Suche filtert clientseitig über Titel + Zutaten – dafür
    wird der Zutatentext hier mit ausgeliefert (data-Attribut im Template).
    Wunsch #54: Durchschnittsbewertung, Wunsch #55: Kategorie je Rezept mit."""
    user = _user(token)
    db   = get_db()
    bereinige_erfuellte_rezeptwuensche(db)
    rezepte = db.execute("""
        SELECT r.id, r.name, r.kategorie,
               (SELECT COUNT(*) FROM rezept_zutaten z WHERE z.rezept_id = r.id) AS anzahl_zutaten,
               (SELECT GROUP_CONCAT(z.name, ' ') FROM rezept_zutaten z WHERE z.rezept_id = r.id) AS zutaten_text,
               (SELECT AVG(sterne) FROM rezept_bewertungen b WHERE b.rezept_id = r.id) AS durchschnitt,
               (SELECT COUNT(*) FROM rezept_bewertungen b WHERE b.rezept_id = r.id) AS anzahl_bewertungen,
               (SELECT COUNT(*) FROM rezept_wuensche w WHERE w.rezept_id = r.id) AS wunsch_anzahl,
               EXISTS(SELECT 1 FROM rezept_wuensche w WHERE w.rezept_id = r.id AND w.user_id = ?) AS eigener_wunsch
        FROM   rezepte r
        ORDER  BY r.name COLLATE NOCASE
    """, (user["id"],)).fetchall()
    return render_template("rezepte.html",
        user=user, token=token, farbe=user["farbe"], rezepte=rezepte,
        kategorien=KATEGORIEN, symbol=kategorie_symbol)


@bp.route("/a/rezepte/neu", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/rezepte/<token>/neu", methods=["GET", "POST"])
def neu(token):
    """Wunsch #48: eigene Unterseite statt dauerhaft sichtbarer Eingabemaske
    auf der Übersicht – nur noch über den "+ Neues Rezept"-Button erreichbar."""
    user = _user(token)
    if request.method == "GET":
        return render_template("rezept_neu.html",
            user=user, token=token, farbe=user["farbe"], kategorien=KATEGORIEN)

    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("rezepte_app.neu", token=token))
    portionen  = request.form.get("portionen", "").strip() or None
    kategorie  = _clean_kategorie(request.form.get("kategorie"))
    quelle_url = request.form.get("quelle_url", "").strip() or None
    if quelle_url and not _ist_oeffentliche_url(quelle_url):
        quelle_url = None
    schritte  = [z.strip() for z in request.form.get("anleitung", "").splitlines() if z.strip()]
    zutaten   = [z.strip() for z in request.form.get("zutaten", "").splitlines() if z.strip()]

    db  = get_db()
    cur = db.execute(
        "INSERT INTO rezepte(name, portionen, kategorie, quelle_url, erstellt_von) VALUES(?,?,?,?,?)",
        (name, portionen, kategorie, quelle_url, user["id"]),
    )
    rezept_id = cur.lastrowid
    for position, zutat_name in enumerate(zutaten):
        db.execute(
            "INSERT INTO rezept_zutaten(rezept_id, name, position) VALUES(?,?,?)",
            (rezept_id, zutat_name, position),
        )
    for position, schritt_text in enumerate(schritte):
        db.execute(
            "INSERT INTO rezept_schritte(rezept_id, text, position) VALUES(?,?,?)",
            (rezept_id, schritt_text, position),
        )
    db.commit()
    return redirect(url_for("rezepte_app.detail", token=token, rid=rezept_id))


def _rezept_per_ki_bild(user_id: int, mime: str, bild_b64: str):
    """Wunsch #97: Rezept aus einem Foto (Kochbuch-Seite, handschriftliches
    Rezept) per KI-Vision extrahieren – gleiches Muster wie _vokabeln_per_ki()
    in 16_vokabeln.py, eigener KI-Zweck 'rezepte_foto_import'. Wirft
    KiLimitError/KiFehler/ValueError, der Aufrufer faengt sie ab."""
    system = (
        'Du liest ein Foto einer Rezeptseite (Kochbuch, handschriftliches Rezept, '
        'Zeitschriftenausschnitt) und extrahierst das Rezept. Antworte AUSSCHLIESSLICH '
        'mit einem JSON-Objekt der Form {"name": "...", "portionen": "...", '
        '"zutaten": ["..."], "schritte": ["..."]}. "portionen" ist die Anzahl '
        'Personen/Portionen als kurzer Text (z. B. "4" oder "4-6 Portionen"), leerer '
        'String wenn nicht erkennbar. "schritte" ist eine Liste einzelner '
        'Zubereitungsschritte, kein zusammenhängender Text. Keine Erklärung, kein '
        'Markdown, kein Codeblock.'
    )
    antwort = ki_anfrage(
        user_id, "rezepte_foto_import", system,
        "Extrahiere das Rezept von diesem Foto.",
        max_tokens=4000, bilder=[(mime, bild_b64)],
    )
    return _ki_rezept_validieren(antwort)


@bp.route("/a/rezepte/importieren-bild", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/rezepte/<token>/importieren-bild", methods=["GET", "POST"])
def importieren_bild(token):
    """Wunsch #97: Rezept per Foto (Kamera/Mediathek) importieren. Ergebnis
    landet wie beim URL-Import nur vorausgefuellt im Neu-Formular, nie direkt
    gespeichert – keine eigene Pruef-Ansicht noetig (siehe Docstring oben)."""
    user = _user(token)
    if request.method == "GET":
        return render_template("rezept_bild_importieren.html",
            user=user, token=token, farbe=user["farbe"], fehler=None)

    def _fehler(text):
        return render_template("rezept_bild_importieren.html",
            user=user, token=token, farbe=user["farbe"], fehler=text)

    datei = request.files.get("foto")
    if not datei or not datei.filename:
        return _fehler("Bitte ein Foto auswählen.")
    endung = datei.filename.rsplit(".", 1)[-1].lower() if "." in datei.filename else ""
    mime = _FOTO_MIME.get(endung)
    if not mime:
        return _fehler("Nur JPG, PNG oder HEIC werden unterstützt.")
    rohdaten = datei.read()
    if not rohdaten:
        return _fehler("Die Datei ist leer.")
    if len(rohdaten) > _FOTO_MAX_BYTES:
        return _fehler("Das Foto ist zu groß (maximal 8 MB).")

    try:
        rezept = _rezept_per_ki_bild(user["id"], mime, base64.b64encode(rohdaten).decode())
    except KiLimitError:
        return _fehler(
            "Monatliches KI-Kontingent aufgebraucht – bitte manuell eintragen "
            "oder später erneut versuchen.")
    except Exception:
        return _fehler(
            "Auf dem Foto konnte kein Rezept erkannt werden – bitte manuell eintragen.")

    return render_template("rezept_neu.html",
        user=user, token=token, farbe=user["farbe"], vorbelegt=rezept, kategorien=KATEGORIEN)


@bp.route("/a/rezepte/importieren", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/rezepte/<token>/importieren", methods=["GET", "POST"])
def importieren(token):
    """Rezept per URL importieren: JSON-LD zuerst, KI-Extraktion als Fallback.
    Ergebnis landet nur vorausgefüllt im Neu-Formular, nie direkt gespeichert."""
    user = _user(token)
    if request.method == "GET":
        return render_template("rezept_importieren.html",
            user=user, token=token, farbe=user["farbe"], fehler=None)

    def _fehler(text):
        return render_template("rezept_importieren.html",
            user=user, token=token, farbe=user["farbe"], fehler=text)

    url = request.form.get("url", "").strip()
    if not url:
        return _fehler("Bitte eine URL eingeben.")
    if not _ist_oeffentliche_url(url):
        return _fehler("Diese URL kann nicht abgerufen werden.")

    try:
        html = _seite_abrufen(url)
    except Exception:
        return _fehler("Die Seite konnte nicht abgerufen werden. Ist die URL korrekt?")

    rezept = _rezept_aus_jsonld(html)
    if not rezept:
        try:
            rezept = _rezept_per_ki(user["id"], html, url)
        except KiLimitError:
            return _fehler(
                "Monatliches KI-Kontingent aufgebraucht – bitte manuell eintragen "
                "oder nächsten Monat erneut versuchen.")
        except Exception:
            return _fehler(
                "Auf dieser Seite konnte kein Rezept erkannt werden – bitte manuell eintragen.")

    rezept["quelle_url"] = url

    return render_template("rezept_neu.html",
        user=user, token=token, farbe=user["farbe"], vorbelegt=rezept, kategorien=KATEGORIEN)


@bp.route("/a/rezepte/<int:rid>", defaults={"token": None})
@bp.route("/a/rezepte/<token>/<int:rid>")
def detail(token, rid):
    user   = _user(token)
    db     = get_db()
    bereinige_erfuellte_rezeptwuensche(db)
    rezept = db.execute("SELECT * FROM rezepte WHERE id=?", (rid,)).fetchone()
    if not rezept:
        abort(404)
    zutaten = db.execute(
        "SELECT id, name FROM rezept_zutaten WHERE rezept_id=? ORDER BY position",
        (rid,),
    ).fetchall()
    schritte = db.execute(
        "SELECT id, text FROM rezept_schritte WHERE rezept_id=? ORDER BY position",
        (rid,),
    ).fetchall()
    bewertung = db.execute(
        "SELECT AVG(sterne) AS schnitt, COUNT(*) AS anzahl FROM rezept_bewertungen WHERE rezept_id=?",
        (rid,),
    ).fetchone()
    eigene = db.execute(
        "SELECT sterne FROM rezept_bewertungen WHERE rezept_id=? AND user_id=?",
        (rid, user["id"]),
    ).fetchone()
    # Wunsch #165: Wann stand das Gericht zuletzt auf dem Tisch? Die Daten
    # legt Wunsch #162 an; hier werden sie nur gelesen. Sortiert nach dem TAG
    # des Essensplans, nicht nach dem Zeitpunkt des Anhakens - gefragt ist
    # "wann gab es das", nicht "wann hat es jemand vermerkt". Wer vier Wochen
    # spaeter nachtraegt, soll den Verlauf nicht durcheinanderbringen.
    gekocht = db.execute("""
        SELECT g.tag, g.mahlzeit, g.markiert_am, u.name AS wer
        FROM   rezept_gekocht g
        LEFT   JOIN users u ON u.id = g.markiert_von
        WHERE  g.rezept_id = ?
        ORDER  BY g.tag DESC, g.mahlzeit DESC
    """, (rid,)).fetchall()

    wunsch_anzahl = db.execute(
        "SELECT COUNT(*) FROM rezept_wuensche WHERE rezept_id=?", (rid,)
    ).fetchone()[0]
    eigener_wunsch = db.execute(
        "SELECT 1 FROM rezept_wuensche WHERE rezept_id=? AND user_id=?", (rid, user["id"])
    ).fetchone() is not None
    return render_template("rezept_detail.html",
        user=user, token=token, farbe=user["farbe"], rezept=rezept, zutaten=zutaten, schritte=schritte,
        durchschnitt=bewertung["schnitt"], anzahl_bewertungen=bewertung["anzahl"],
        eigene_bewertung=eigene["sterne"] if eigene else 0, kategorien=KATEGORIEN,
        wunsch_anzahl=wunsch_anzahl, eigener_wunsch=eigener_wunsch,
        gekocht=gekocht, mahlzeit_labels={"mittag": "mittags", "abend": "abends"})


@bp.route("/a/rezepte/<int:rid>/bearbeiten", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/rezepte/<token>/<int:rid>/bearbeiten", methods=["GET", "POST"])
def bearbeiten(token, rid):
    """Rezept nachträglich bearbeiten – dasselbe Formular wie /neu (rezept_neu.html),
    nur vorausgefüllt mit den aktuellen Werten und Ziel-Route für UPDATE statt INSERT.
    Zutaten/Schritte werden beim Speichern komplett ersetzt (löschen + neu einfügen),
    kein Zeilen-Diffing nötig."""
    user   = _user(token)
    db     = get_db()
    rezept = db.execute("SELECT * FROM rezepte WHERE id=?", (rid,)).fetchone()
    if not rezept:
        abort(404)

    if request.method == "GET":
        zutaten = db.execute(
            "SELECT name FROM rezept_zutaten WHERE rezept_id=? ORDER BY position", (rid,)
        ).fetchall()
        schritte = db.execute(
            "SELECT text FROM rezept_schritte WHERE rezept_id=? ORDER BY position", (rid,)
        ).fetchall()
        vorbelegt = {
            "name": rezept["name"],
            "portionen": rezept["portionen"],
            "kategorie": rezept["kategorie"],
            "zutaten": [z["name"] for z in zutaten],
            "schritte": [s["text"] for s in schritte],
        }
        return render_template("rezept_neu.html",
            user=user, token=token, farbe=user["farbe"], vorbelegt=vorbelegt, bearbeiten=rid,
            kategorien=KATEGORIEN)

    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("rezepte_app.bearbeiten", token=token, rid=rid))
    portionen = request.form.get("portionen", "").strip() or None
    kategorie = _clean_kategorie(request.form.get("kategorie"))
    schritte  = [z.strip() for z in request.form.get("anleitung", "").splitlines() if z.strip()]
    zutaten   = [z.strip() for z in request.form.get("zutaten", "").splitlines() if z.strip()]

    db.execute("UPDATE rezepte SET name=?, portionen=?, kategorie=? WHERE id=?",
               (name, portionen, kategorie, rid))
    db.execute("DELETE FROM rezept_zutaten WHERE rezept_id=?", (rid,))
    db.execute("DELETE FROM rezept_schritte WHERE rezept_id=?", (rid,))
    for position, zutat_name in enumerate(zutaten):
        db.execute(
            "INSERT INTO rezept_zutaten(rezept_id, name, position) VALUES(?,?,?)",
            (rid, zutat_name, position),
        )
    for position, schritt_text in enumerate(schritte):
        db.execute(
            "INSERT INTO rezept_schritte(rezept_id, text, position) VALUES(?,?,?)",
            (rid, schritt_text, position),
        )
    db.commit()
    return redirect(url_for("rezepte_app.detail", token=token, rid=rid))


@bp.route("/a/rezepte/<int:rid>/bewerten", defaults={"token": None}, methods=["POST"])
@bp.route("/a/rezepte/<token>/<int:rid>/bewerten", methods=["POST"])
def bewerten(token, rid):
    """Wunsch #52: 1-5 Sterne pro Nutzer und Rezept, editierbar (UPSERT über
    UNIQUE(rezept_id, user_id)). Gibt den neuen Durchschnitt als JSON zurück,
    damit die Sterne-Anzeige ohne vollen Seiten-Reload aktualisiert werden kann."""
    user = _user(token)
    db   = get_db()
    if not db.execute("SELECT 1 FROM rezepte WHERE id=?", (rid,)).fetchone():
        abort(404)
    data   = request.get_json(silent=True) or {}
    sterne = to_int(data.get("sterne"))
    if sterne is None or sterne < 1 or sterne > 5:
        return jsonify(ok=False), 400
    db.execute("""
        INSERT INTO rezept_bewertungen(rezept_id, user_id, sterne) VALUES(?,?,?)
        ON CONFLICT(rezept_id, user_id) DO UPDATE SET sterne=excluded.sterne
    """, (rid, user["id"], sterne))
    db.commit()
    bewertung = db.execute(
        "SELECT AVG(sterne) AS schnitt, COUNT(*) AS anzahl FROM rezept_bewertungen WHERE rezept_id=?",
        (rid,),
    ).fetchone()
    return jsonify(ok=True, sterne=sterne,
        durchschnitt=round(bewertung["schnitt"], 1), anzahl=bewertung["anzahl"])


@bp.route("/a/rezepte/<int:rid>/wunsch/toggle", defaults={"token": None}, methods=["POST"])
@bp.route("/a/rezepte/<token>/<int:rid>/wunsch/toggle", methods=["POST"])
def wunsch_toggle(token, rid):
    """Wunsch #65: bis zu 5 Rezepte pro Nutzer gleichzeitig als "wünsch ich
    mir" markieren, für die Essensplan-Wunschliste. Erfüllte Wünsche werden
    automatisch entfernt, siehe bereinige_erfuellte_rezeptwuensche()."""
    user = _user(token)
    db   = get_db()
    if not db.execute("SELECT 1 FROM rezepte WHERE id=?", (rid,)).fetchone():
        abort(404)
    bereinige_erfuellte_rezeptwuensche(db)
    vorhanden = db.execute(
        "SELECT 1 FROM rezept_wuensche WHERE rezept_id=? AND user_id=?", (rid, user["id"])
    ).fetchone()
    if vorhanden:
        db.execute(
            "DELETE FROM rezept_wuensche WHERE rezept_id=? AND user_id=?", (rid, user["id"])
        )
        db.commit()
        markiert = False
    else:
        anzahl_eigene = db.execute(
            "SELECT COUNT(*) FROM rezept_wuensche WHERE user_id=?", (user["id"],)
        ).fetchone()[0]
        if anzahl_eigene >= MAX_REZEPT_WUENSCHE:
            return jsonify(ok=False, grund="limit"), 400
        db.execute(
            "INSERT INTO rezept_wuensche(rezept_id, user_id) VALUES(?,?)", (rid, user["id"])
        )
        db.commit()
        markiert = True
    anzahl = db.execute(
        "SELECT COUNT(*) FROM rezept_wuensche WHERE rezept_id=?", (rid,)
    ).fetchone()[0]
    return jsonify(ok=True, markiert=markiert, anzahl=anzahl)


@bp.route("/a/rezepte/<int:rid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/rezepte/<token>/<int:rid>/loeschen", methods=["POST"])
def loeschen(token, rid):
    _user(token)
    db = get_db()
    db.execute("DELETE FROM rezepte WHERE id=?", (rid,))
    db.commit()
    return redirect(url_for("rezepte_app.index", token=token))


@bp.route("/a/rezepte/zutat/<int:zid>/einkaufen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/rezepte/<token>/zutat/<int:zid>/einkaufen", methods=["POST"])
def zutat_einkaufen(token, zid):
    """Eine Zutat auf die Einkaufsliste setzen.

    Wunsch #164: Wurde die Portionszahl auf der Rezeptseite umgestellt, schickt
    das Frontend die UMGERECHNETE Zeile als `text` mit. Ohne das landete
    stillschweigend die Originalmenge auf der Liste - man sieht "750 g Mehl"
    und bekommt "500 g Mehl", und zwar ohne jeden Hinweis.

    Der mitgeschickte Text wird bewusst nur als ANZEIGETEXT uebernommen und
    nicht ausgewertet; die strukturierte Zerlegung in Menge/Einheit/Name ist
    Wunsch #51 und bleibt zurueckgestellt.
    """
    user  = _user(token)
    db    = get_db()
    zutat = db.execute("SELECT name FROM rezept_zutaten WHERE id=?", (zid,)).fetchone()
    if not zutat:
        abort(404)

    daten = request.get_json(silent=True) or {}
    text  = (daten.get("text") or "").strip()[:200]
    # Leerer oder fehlender Text -> Originalzeile. So funktioniert der Knopf
    # auch dann noch, wenn das Javascript nichts mitschickt (alte PWA im Cache).
    name = text or zutat["name"]

    db.execute(
        "INSERT INTO einkauf_eintraege(name, kategorie, erstellt_von) VALUES(?,?,?)",
        (name, "Sonstiges", user["id"]),
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
