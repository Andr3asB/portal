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

Rezept-Import per Foto (Wunsch #97): Kamera oder Mediathek, OCR+Extraktion
über ki_anfrage() mit Bildeingabe (eigener KI-Zweck "rezepte_foto_import",
unabhängig vom URL-Import konfigurierbar). Liefert dieselbe Datenform wie
_rezept_aus_jsonld()/_rezept_per_ki() (name/portionen/zutaten/schritte) und
landet deshalb genau wie der URL-Import nur vorausgefüllt im bestehenden
Neu-Formular - keine eigene Prüf-Seite nötig, anders als beim Vokabeln-
Foto-Import (Wunsch #80), wo ein Foto mehrere Vokabelpaare gleichzeitig
liefert und deshalb eine eigene Zeilen-Prüf-Ansicht braucht.

Bearbeiten (bearbeiten()) nutzt dasselbe Formular (rezept_neu.html) wie
Neuanlegen und Import-Vorschau, unterschieden nur über den bearbeiten-Parameter
(Ziel-Route, Titel, Speichern-Button-Text). Zutaten/Schritte werden beim
Speichern komplett ersetzt, kein Zeilen-Diffing.
"""
import base64
import ipaddress
import json
import re
import socket
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import (
    get_db, grant as check_grant, to_int, ki_anfrage, KiLimitError, KiFehler,
    bereinige_erfuellte_rezeptwuensche,
)

MAX_REZEPT_WUENSCHE = 5

bp  = Blueprint("rezepte_app", __name__)
APP = "rezepte"

KATEGORIEN = {"kochen": "🍳 Kochen", "backen": "🍰 Backen"}

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
    _IGNORE_TAGS = {"script", "style", "nav", "header", "footer", "noscript"}

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


def _ist_oeffentliche_url(url: str) -> bool:
    """SSRF-Schutz: nur http/https, und die Ziel-IP darf nicht intern/privat sein."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _seite_abrufen(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FamilienportalRezeptImport/1.0)",
    })
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
        raw = resp.read(_MAX_FETCH_BYTES + 1)
        if len(raw) > _MAX_FETCH_BYTES:
            raise ValueError("Seite zu groß")
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


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

    bereinigt = antwort.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.strip("`")
        if bereinigt.lower().startswith("json"):
            bereinigt = bereinigt[4:]
    daten = json.loads(bereinigt)
    zutaten  = daten.get("zutaten") or []
    schritte = daten.get("schritte") or []
    name = str(daten.get("name") or "").strip()
    if not name:
        raise ValueError("KI hat keinen Rezeptnamen erkannt")
    return {
        "name": name,
        "portionen": str(daten.get("portionen") or "").strip() or None,
        "zutaten": [str(z).strip() for z in zutaten if str(z).strip()],
        "schritte": [str(s).strip() for s in schritte if str(s).strip()],
    }


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
        user=user, token=token, farbe=user["farbe"], rezepte=rezepte, kategorien=KATEGORIEN)


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
    bereinigt = antwort.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.strip("`")
        if bereinigt.lower().startswith("json"):
            bereinigt = bereinigt[4:]
    daten = json.loads(bereinigt)
    zutaten  = daten.get("zutaten") or []
    schritte = daten.get("schritte") or []
    name = str(daten.get("name") or "").strip()
    if not name:
        raise ValueError("KI hat keinen Rezeptnamen erkannt")
    return {
        "name": name,
        "portionen": str(daten.get("portionen") or "").strip() or None,
        "zutaten": [str(z).strip() for z in zutaten if str(z).strip()],
        "schritte": [str(s).strip() for s in schritte if str(s).strip()],
    }


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
        wunsch_anzahl=wunsch_anzahl, eigener_wunsch=eigener_wunsch)


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


@bp.route("/a/rezepte/<token>/<int:rid>/loeschen", methods=["POST"])
def loeschen(token, rid):
    _user(token)
    db = get_db()
    db.execute("DELETE FROM rezepte WHERE id=?", (rid,))
    db.commit()
    return redirect(url_for("rezepte_app.index", token=token))


@bp.route("/a/rezepte/<token>/zutat/<int:zid>/einkaufen", methods=["POST"])
def zutat_einkaufen(token, zid):
    user  = _user(token)
    db    = get_db()
    zutat = db.execute("SELECT name FROM rezept_zutaten WHERE id=?", (zid,)).fetchone()
    if not zutat:
        abort(404)
    db.execute(
        "INSERT INTO einkauf_eintraege(name, kategorie, erstellt_von) VALUES(?,?,?)",
        (zutat["name"], "Sonstiges", user["id"]),
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
