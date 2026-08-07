"""
Einkaufsliste – gemeinsam von allen Nutzern befüllt.
URL-Präfix: /a/einkauf/<token>/

Wunsch #100: Damit parallele Einträge/Änderungen anderer Nutzer sichtbar
werden, ohne dass man manuell neu lädt, pollt das Frontend regelmäßig und
bei jedem Wiederöffnen der App /stand - ein kompakter Fingerabdruck der
Liste (siehe _stand()). Ändert er sich, lädt die Seite neu (wie schon beim
erfolgreichen Abarbeiten der Offline-Warteschlange), aber nur wenn gerade
nichts Ungespeichertes im Weg steht (Name-Feld leer, kein offenes
Bearbeiten-Panel) - sonst wird der nächste Sync-Versuch abgewartet.
"""
import io
import json
import re
import urllib.error
import urllib.request

from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import (
    get_db, grant as check_grant, to_int, ki_anfrage, KiLimitError, KiFehler,
)

bp  = Blueprint("einkauf_app", __name__)
APP = "einkauf"

# Wunsch #143: Barcode-Erfassung.
#
# Gelesen wird SERVERSEITIG aus einem Foto, nicht im Browser. Grund: Die
# Browser-Schnittstelle `BarcodeDetector` gibt es weder auf iOS noch in Chrome
# unter Windows (beides nachgemessen) - sie fehlt also ausgerechnet auf den
# Geraeten, mit denen tatsaechlich eingekauft wird. Die Alternative waere eine
# mitgelieferte Javascript-Bibliothek von einigen hundert Kilobyte gewesen.
#
# Der Foto-Weg nutzt stattdessen das im Projekt schon etablierte Muster
# (Rezept- und Vokabel-Foto-Import): ein <input type="file" accept="image/*">.
# Das funktioniert auf jedem Geraet, ohne Fremdcode im Browser.
#
# Bewusst OHNE capture="environment" - das Attribut zwingt iOS Safari, direkt
# die Kamera zu oeffnen, ohne die Auswahl "Mediathek" anzubieten (Wunsch #106,
# dort schon einmal zurueckgebaut).
_BARCODE_MAX_BYTES = 8 * 1024 * 1024
_BARCODE_MIME = {"jpg", "jpeg", "png", "heic", "webp"}

# Nur Ziffern - der Code landet in einer URL. Ohne diese Pruefung koennte ein
# praeparierter "Barcode" den Pfad der Abfrage veraendern.
#
# `\Z` und NICHT `$`: In Python passt `$` auch VOR einem abschliessenden
# Zeilenumbruch. "4008400401621\n" waere also durch die Pruefung gerutscht und
# mitsamt Umbruch in die Adresse geraten. Beim Schreiben des Tests aufgefallen,
# nicht beim Schreiben des Codes.
_NUR_ZIFFERN = re.compile(r"\A[0-9]{6,14}\Z")

_OFF_TIMEOUT = 12


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _kategorien_aktiv(db):
    return db.execute(
        "SELECT id, name FROM einkauf_kategorien WHERE aktiv=1 ORDER BY position, name COLLATE NOCASE"
    ).fetchall()


def _clean_kategorie_id(db, kategorie_id):
    """Fällt auf 'Sonstiges' zurück, wenn die ID fehlt/ungültig/inaktiv ist."""
    if kategorie_id is not None and db.execute(
        "SELECT 1 FROM einkauf_kategorien WHERE id=? AND aktiv=1", (kategorie_id,)
    ).fetchone():
        return kategorie_id
    row = db.execute("SELECT id FROM einkauf_kategorien WHERE name='Sonstiges'").fetchone()
    return row["id"] if row else kategorie_id


def _clean_angebot_laeden(db, angebot, laden_ids):
    """Nur eine gültige Kombination durchlassen – sonst konsequent beides aus,
    statt einer Markierung ohne Markt (führte früher zu kaputten Zwischenzuständen).
    Wunsch #86: mehrere Märkte gleichzeitig möglich, statt nur einem."""
    if not angebot:
        return 0, []
    gueltige = [lid for lid in laden_ids if db.execute(
        "SELECT 1 FROM einkauf_laeden WHERE id=?", (lid,)
    ).fetchone()]
    if not gueltige:
        return 0, []
    return 1, gueltige


def _barcode_aus_bild(rohdaten: bytes):
    """Erster erkannter Barcode aus einem Foto, sonst None.

    `zxing-cpp` liefert alle gefundenen Codes; auf einer Packung ist meist nur
    einer, gelegentlich aber auch ein QR-Code daneben. Bevorzugt wird deshalb
    ein Produktcode (EAN/UPC), erst danach irgendein anderer."""
    from PIL import Image
    import zxingcpp

    bild = Image.open(io.BytesIO(rohdaten))
    # Manche Handy-Fotos kommen als RGBA oder mit Palette - zxing-cpp will
    # etwas Handfestes.
    if bild.mode not in ("L", "RGB"):
        bild = bild.convert("RGB")
    treffer = zxingcpp.read_barcodes(bild)
    if not treffer:
        return None
    produktcodes = [t for t in treffer if "EAN" in str(t.format) or "UPC" in str(t.format)]
    gewaehlt = (produktcodes or treffer)[0]
    text = (gewaehlt.text or "").strip()
    return text if _NUR_ZIFFERN.match(text) else None


def _produkt_zu_barcode(code: str):
    """Produktdaten von Open Food Facts, oder None.

    Feste Adresse mit geprüftem Ziffern-Code - deshalb ist hier KEINE
    SSRF-Prüfung wie beim Rezept-Import nötig (dort gibt der Nutzer die
    komplette Adresse vor, hier nur Ziffern in einem festen Pfad).

    Ein unbekannter Code beantwortet Open Food Facts mit HTTP 404, nicht mit
    einem leeren Ergebnis - das ist kein Fehler, sondern der Normalfall bei
    Nicht-Lebensmitteln."""
    if not _NUR_ZIFFERN.match(code or ""):
        return None
    url = (f"https://world.openfoodfacts.org/api/v2/product/{code}.json"
           "?fields=product_name,product_name_de,brands,quantity")
    req = urllib.request.Request(url, headers={
        # Open Food Facts bittet in seiner Doku ausdrücklich um eine
        # erkennbare Kennung statt eines anonymen Aufrufs.
        "User-Agent": "Familienportal/1.0 (privates Familienprojekt)",
    })
    try:
        with urllib.request.urlopen(req, timeout=_OFF_TIMEOUT) as resp:
            daten = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if daten.get("status") != 1:
        return None
    p = daten.get("product") or {}
    name = (p.get("product_name_de") or p.get("product_name") or "").strip()
    if not name:
        return None
    marke = (p.get("brands") or "").split(",")[0].strip()
    menge = (p.get("quantity") or "").strip()
    return {"name": name[:80], "marke": marke[:40], "menge": menge[:30]}


def _kategorie_per_ki(user_id: int, produkt: dict, kategorien) -> int:
    """Ordnet ein Produkt einer der VORHANDENEN Kategorien zu.

    Die Auswahl wird der KI vorgegeben und die Antwort gegen sie geprüft -
    ein frei erfundener Kategoriename wäre wertlos, weil er zu keiner Zeile in
    `einkauf_kategorien` passt. Bei Unsicherheit oder Fehler bleibt es bei
    `None`; `_clean_kategorie_id()` setzt dann 'Sonstiges'."""
    namen = [k["name"] for k in kategorien]
    system = (
        "Du ordnest ein Lebensmittel oder Drogerieprodukt genau EINER Kategorie "
        "einer Einkaufsliste zu. Antworte AUSSCHLIESSLICH mit dem exakten "
        "Kategorienamen aus der vorgegebenen Liste, ohne Anführungszeichen, "
        "ohne Erklärung. Passt nichts eindeutig, antworte: Sonstiges"
    )
    beschreibung = " ".join(x for x in (produkt.get("marke"), produkt["name"]) if x)
    prompt = f"Kategorien: {', '.join(namen)}\n\nProdukt: {beschreibung}"
    antwort = ki_anfrage(user_id, "einkauf_barcode", system, prompt, max_tokens=30)
    gewaehlt = (antwort or "").strip().strip('"').strip()
    for k in kategorien:
        if k["name"].lower() == gewaehlt.lower():
            return k["id"]
    return None


@bp.route("/a/einkauf/barcode", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/barcode", methods=["POST"])
def barcode(token):
    """Foto -> Barcode -> Produktname + Kategorievorschlag.

    Gibt JSON zurück und speichert NICHTS: Das Ergebnis füllt nur das
    bestehende Formular vor, der Nutzer prüft und speichert selbst - genau wie
    beim Rezept-Import und wie im Wunsch beschrieben."""
    user = _user(token)

    datei = request.files.get("foto")
    if not datei or not datei.filename:
        return jsonify(ok=False, fehler="Kein Foto erhalten."), 400
    endung = datei.filename.rsplit(".", 1)[-1].lower() if "." in datei.filename else ""
    if endung not in _BARCODE_MIME:
        return jsonify(ok=False, fehler="Nur JPG, PNG, HEIC oder WEBP."), 400
    rohdaten = datei.read()
    if not rohdaten:
        return jsonify(ok=False, fehler="Die Datei ist leer."), 400
    if len(rohdaten) > _BARCODE_MAX_BYTES:
        return jsonify(ok=False, fehler="Das Foto ist zu groß (maximal 8 MB)."), 400

    try:
        code = _barcode_aus_bild(rohdaten)
    except Exception:
        return jsonify(ok=False, fehler="Das Foto konnte nicht gelesen werden."), 400
    if not code:
        return jsonify(
            ok=False,
            fehler="Kein Barcode erkannt. Nochmal näher und gerader fotografieren?"), 200

    try:
        produkt = _produkt_zu_barcode(code)
    except Exception:
        return jsonify(ok=False, code=code,
                       fehler="Die Produktdatenbank ist gerade nicht erreichbar."), 200
    if not produkt:
        # Der Code wird trotzdem zurückgegeben - dann kann der Nutzer den
        # Namen selbst eintippen, statt ganz von vorn anzufangen.
        return jsonify(ok=False, code=code,
                       fehler="Barcode erkannt, aber das Produkt ist nicht "
                              "in der Datenbank. Bitte den Namen eintragen."), 200

    db = get_db()
    kategorien = _kategorien_aktiv(db)
    kategorie_id = None
    try:
        kategorie_id = _kategorie_per_ki(user["id"], produkt, kategorien)
    except KiLimitError:
        pass          # Kontingent aufgebraucht - Name reicht, Kategorie waehlt der Nutzer
    except KiFehler:
        pass          # KI nicht erreichbar - dito, kein Grund die Erfassung abzubrechen
    except Exception:
        pass

    anzeige = produkt["name"]
    if produkt.get("menge"):
        anzeige = f"{anzeige} ({produkt['menge']})"
    return jsonify(ok=True, code=code, name=anzeige[:80],
                   kategorie_id=kategorie_id)


def _stand(db):
    """Wunsch #100: Kompakter Sync-Fingerabdruck der Liste - Anzahl + jüngster
    geaendert-Zeitstempel deckt Einfügen (Anzahl steigt), Löschen (Anzahl
    sinkt) und Ändern/Abhaken (Zeitstempel steigt) ab, ohne die komplette
    Liste zu übertragen. Frontend vergleicht das regelmäßig gegen den beim
    Laden eingebetteten Wert (siehe /stand-Route unten)."""
    row = db.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(geaendert), '') AS g FROM einkauf_eintraege"
    ).fetchone()
    return f"{row['n']}:{row['g']}"


def _laden_ids_aus_form(form):
    roh = form.get("laden_ids", "")
    ids = []
    for teil in roh.split(","):
        lid = to_int(teil.strip())
        if lid is not None and lid not in ids:
            ids.append(lid)
    return ids


@bp.route("/a/einkauf/", defaults={"token": None})
@bp.route("/a/einkauf/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()
    laeden = db.execute(
        "SELECT id, name FROM einkauf_laeden WHERE aktiv=1 ORDER BY name"
    ).fetchall()
    kategorien = _kategorien_aktiv(db)
    vorschlaege = [r["name"] for r in db.execute(
        "SELECT name, COUNT(*) AS n FROM einkauf_eintraege "
        "GROUP BY lower(name) ORDER BY n DESC LIMIT 40"
    ).fetchall()]

    # Offen: nach Kategorie gruppiert (Reihenfolge der Kategorien-Tabelle), innerhalb alphabetisch.
    offene = db.execute("""
        SELECT e.id, e.name, e.kategorie_id, e.angebot, e.erledigt, e.erledigt_am,
               GROUP_CONCAT(l.name, ', ') AS laden_namen,
               GROUP_CONCAT(l.id, ',') AS laden_ids
        FROM   einkauf_eintraege e
        LEFT JOIN einkauf_eintrag_laeden el ON el.eintrag_id = e.id
        LEFT JOIN einkauf_laeden l ON l.id = el.laden_id
        WHERE  e.erledigt = 0
        GROUP  BY e.id
        ORDER  BY e.name COLLATE NOCASE ASC
    """).fetchall()
    gruppen  = {k["id"]: [] for k in kategorien}
    unsortiert = []
    for r in offene:
        if r["kategorie_id"] in gruppen:
            gruppen[r["kategorie_id"]].append(r)
        else:
            unsortiert.append(r)

    # Erledigt: zuletzt abgehakt zuerst.
    erledigt = db.execute("""
        SELECT e.id, e.name, e.kategorie_id, e.angebot, e.erledigt, e.erledigt_am,
               GROUP_CONCAT(l.name, ', ') AS laden_namen,
               GROUP_CONCAT(l.id, ',') AS laden_ids
        FROM   einkauf_eintraege e
        LEFT JOIN einkauf_eintrag_laeden el ON el.eintrag_id = e.id
        LEFT JOIN einkauf_laeden l ON l.id = el.laden_id
        WHERE  e.erledigt = 1 AND e.erledigt_am >= datetime('now', '-6 hours')
        GROUP  BY e.id
        ORDER  BY e.erledigt_am DESC
    """).fetchall()
    return render_template("einkauf.html",
        user=user, token=token, farbe=user["farbe"],
        kategorien=kategorien, gruppen=gruppen, unsortiert=unsortiert, erledigt=erledigt,
        laeden=laeden, vorschlaege=vorschlaege, stand=_stand(db),
    )


@bp.route("/a/einkauf/stand", defaults={"token": None})
@bp.route("/a/einkauf/<token>/stand")
def stand(token):
    """Wunsch #100: leichtgewichtiger Sync-Check, den das Frontend regelmäßig
    und bei jedem Wiederöffnen der App abfragt, um Änderungen anderer
    Nutzer zu erkennen (siehe _stand())."""
    _user(token)
    return jsonify(stand=_stand(get_db()))


@bp.route("/a/einkauf/add", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/add", methods=["POST"])
def add(token):
    user = _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("einkauf_app.index", token=token))
    db = get_db()
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    angebot, laden_ids = _clean_angebot_laeden(
        db,
        1 if request.form.get("angebot") == "1" else 0,
        _laden_ids_aus_form(request.form),
    )
    cur = db.execute(
        "INSERT INTO einkauf_eintraege(name,kategorie_id,angebot,erstellt_von,geaendert) "
        "VALUES(?,?,?,?,datetime('now'))",
        (name, kategorie_id, angebot, user["id"]),
    )
    eid = cur.lastrowid
    for lid in laden_ids:
        db.execute("INSERT OR IGNORE INTO einkauf_eintrag_laeden(eintrag_id,laden_id) VALUES(?,?)", (eid, lid))
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/erledigt/<int:eid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/erledigt/<int:eid>", methods=["POST"])
def toggle_erledigt(token, eid):
    """Wunsch: Einkauf offline-faehig. ziel wird jetzt explizit mitgeschickt
    (statt reinem Toggle) und macht die Route idempotent - noetig, damit ein
    aus der Offline-Warteschlange wiederholter Request nicht versehentlich
    ein zwischenzeitlich schon erfolgreich uebertragenes Toggle nochmal
    umdreht. ziel fehlt nur bei sehr altem, gecachtem Frontend-Code -
    faellt dann auf den alten Toggle zurueck."""
    _user(token)
    db  = get_db()
    row = db.execute("SELECT erledigt FROM einkauf_eintraege WHERE id=?", (eid,)).fetchone()
    if not row:
        abort(404)
    ziel_roh = request.form.get("ziel")
    neu = (1 if ziel_roh == "1" else 0) if ziel_roh is not None else (0 if row["erledigt"] else 1)
    db.execute(
        "UPDATE einkauf_eintraege SET erledigt=?, "
        "erledigt_am=CASE WHEN ?=1 THEN datetime('now') ELSE NULL END, "
        "geaendert=datetime('now') WHERE id=?",
        (neu, neu, eid),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, erledigt=bool(neu))
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/loeschen/<int:eid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/loeschen/<int:eid>", methods=["POST"])
def loeschen(token, eid):
    _user(token)
    db = get_db()
    db.execute("DELETE FROM einkauf_eintraege WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/bearbeiten/<int:eid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/bearbeiten/<int:eid>", methods=["POST"])
def bearbeiten(token, eid):
    _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("einkauf_app.index", token=token))
    db = get_db()
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    angebot, laden_ids = _clean_angebot_laeden(
        db,
        1 if request.form.get("angebot") == "1" else 0,
        _laden_ids_aus_form(request.form),
    )
    db.execute(
        "UPDATE einkauf_eintraege SET name=?, kategorie_id=?, angebot=?, geaendert=datetime('now') WHERE id=?",
        (name, kategorie_id, angebot, eid),
    )
    db.execute("DELETE FROM einkauf_eintrag_laeden WHERE eintrag_id=?", (eid,))
    for lid in laden_ids:
        db.execute("INSERT OR IGNORE INTO einkauf_eintrag_laeden(eintrag_id,laden_id) VALUES(?,?)", (eid, lid))
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/laeden", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/einkauf/<token>/laeden", methods=["GET", "POST"])
def laeden_verwalten(token):
    user = _user(token)
    if not user["is_admin"]:
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                db.execute("INSERT OR IGNORE INTO einkauf_laeden(name) VALUES(?)", (name,))
                db.commit()
        elif action == "toggle":
            lid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM einkauf_laeden WHERE id=?", (lid,)).fetchone()
            if row:
                db.execute("UPDATE einkauf_laeden SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, lid))
                db.commit()
        return redirect(url_for("einkauf_app.laeden_verwalten", token=token))
    laeden = db.execute("SELECT * FROM einkauf_laeden ORDER BY aktiv DESC, name").fetchall()
    return render_template("einkauf_laeden.html",
        user=user, token=token, farbe=user["farbe"], laeden=laeden)


@bp.route("/a/einkauf/kategorien", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/einkauf/<token>/kategorien", methods=["GET", "POST"])
def kategorien_verwalten(token):
    """Wunsch #37: Kategorien anlegen, umbenennen, deaktivieren – wie Läden,
    aber mit Umbenennen, weil der Wunsch das ausdrücklich als "editierbar" nannte."""
    user = _user(token)
    if not user["is_admin"]:
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                max_pos = db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM einkauf_kategorien"
                ).fetchone()[0]
                db.execute(
                    "INSERT OR IGNORE INTO einkauf_kategorien(name, position) VALUES(?,?)",
                    (name, max_pos + 1),
                )
                db.commit()
        elif action == "umbenennen":
            kid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name:
                db.execute("UPDATE einkauf_kategorien SET name=? WHERE id=?", (name, kid))
                db.commit()
        elif action == "toggle":
            kid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM einkauf_kategorien WHERE id=?", (kid,)).fetchone()
            if row:
                db.execute("UPDATE einkauf_kategorien SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, kid))
                db.commit()
        return redirect(url_for("einkauf_app.kategorien_verwalten", token=token))
    kategorien = db.execute(
        "SELECT * FROM einkauf_kategorien ORDER BY position, name COLLATE NOCASE"
    ).fetchall()
    return render_template("einkauf_kategorien.html",
        user=user, token=token, farbe=user["farbe"], kategorien=kategorien)


@bp.route("/a/einkauf/kategorien/reorder", defaults={"token": None}, methods=["POST"])
@bp.route("/a/einkauf/<token>/kategorien/reorder", methods=["POST"])
def kategorien_reorder(token):
    """Wunsch #38: Sortierreihenfolge der Kategorien per Drag & Drop änderbar."""
    user = _user(token)
    if not user["is_admin"]:
        abort(403)
    data  = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if not isinstance(order, list):
        abort(400)
    db = get_db()
    for position, kid in enumerate(order):
        kid = to_int(kid)
        if kid is None:
            continue
        db.execute("UPDATE einkauf_kategorien SET position=? WHERE id=?", (position, kid))
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
