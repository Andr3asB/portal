"""
Ausfallprotokoll (Wunsch #222) - Aussetzer des Infotainments im Škoda Enyaq
dokumentieren, damit die Werkstatt Zahlen statt Erinnerungen bekommt.
URL-Praefix: /a/ausfaelle/<token>/

Die eine Anforderung, die den ganzen Aufbau bestimmt, steht woertlich im
Wunsch: **"Wichtig waere das die GPS Position und die Uhrzeit vom ersten
Knopfdruck gezogen wird und nicht erst mal speichern der Notiz."**

Daraus folgt ein Ablauf in drei Schritten statt eines Formulars:

1. `melden()` - der Knopfdruck. Der Eintrag entsteht SOFORT, mit
   `datetime('now')` und dem Nutzer. Kein Formular, keine Bestaetigung,
   nichts, was schiefgehen kann.
2. `position()` - die Ortung trudelt Sekunden spaeter ein und wird an den
   eben angelegten Eintrag gehaengt. Kommt sie nie (abgelehnt, Tiefgarage,
   altes Geraet), bleibt der Eintrag trotzdem stehen - nur ohne Ort.
3. `notiz()` - was der Ausfall angerichtet hat, in Ruhe hinterher getippt.

Warum nicht alles in einem Rutsch: Ein Formular, das erst beim Absenden
speichert, verliert den Eintrag, sobald jemand im Auto abgelenkt wird - und
genau dann passieren diese Ausfaelle. Ausserdem waere der Zeitstempel dann
der des Abschickens, also je nach Tipptempo Minuten daneben.

Die Zeit setzt der SERVER, nicht der Browser. Der Knopfdruck loest die
Anfrage unmittelbar aus, der Unterschied liegt im Millisekundenbereich - und
eine falsch gestellte Handy-Uhr kann so kein Protokoll verfaelschen, das
spaeter jemand in der Werkstatt vorlegt.
"""
import math

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from teile.kern import get_db, utc_zu_lokal
from teile.kern import grant as check_grant

bp  = Blueprint("ausfaelle_app", __name__)
APP = "ausfaelle"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _darf_aendern(user, zeile) -> bool:
    """Notiz aendern und loeschen darf, wer den Eintrag gemeldet hat - oder
    ein Admin. Das Protokoll ist gemeinsam einsehbar (der Wunsch verlangt
    ausdruecklich, alle Eintraege inklusive des Benutzers zu sehen), aber
    fremde Beobachtungen umschreibt man nicht."""
    return bool(user["is_admin"] or zeile["user_id"] == user["id"])


def _koordinate(wert, grenze):
    """Zahl aus dem Browser, oder None.

    Bewusst streng: Ausserhalb des gueltigen Bereichs (oder gar keine Zahl)
    wird verworfen statt gespeichert. Eine unmoegliche Koordinate im
    Protokoll waere schlimmer als gar keine - sie sieht aus wie eine Angabe."""
    try:
        zahl = float(wert)
    except (TypeError, ValueError):
        return None
    if math.isnan(zahl) or abs(zahl) > grenze:
        return None
    return zahl


@bp.route("/a/ausfaelle/", defaults={"token": None})
@bp.route("/a/ausfaelle/<token>/")
def index(token):
    user = _user(token)
    db = get_db()
    # Wunsch #241: Standard sind die letzten 20 - mit 71 Eintraegen war die
    # Seite 7.500px hoch. ?alle=1 holt weiterhin die komplette Liste.
    zeige_alle = request.args.get("alle") == "1"
    sql = """
        SELECT a.id, a.user_id, a.zeitpunkt, a.lat, a.lon, a.genauigkeit, a.notiz,
               u.name AS melder, u.farbe AS melder_farbe
        FROM   ausfaelle a
        LEFT   JOIN users u ON u.id = a.user_id
        ORDER  BY a.zeitpunkt DESC, a.id DESC
    """
    if not zeige_alle:
        sql += " LIMIT 20"
    zeilen = db.execute(sql).fetchall()

    eintraege = []
    for z in zeilen:
        d = dict(z)
        d["zeit_lokal"] = utc_zu_lokal(z["zeitpunkt"])
        d["darf_aendern"] = _darf_aendern(user, z)
        eintraege.append(d)

    # Zahlen fuer die Werkstatt: "wie oft" ist die erste Frage, die dort
    # gestellt wird - die soll nicht jeder selbst abzaehlen muessen.
    gesamt = db.execute("SELECT COUNT(*) FROM ausfaelle").fetchone()[0]
    letzte_30 = db.execute(
        "SELECT COUNT(*) FROM ausfaelle WHERE zeitpunkt >= datetime('now','-30 days')"
    ).fetchone()[0]

    return render_template("ausfaelle.html",
        user=user, token=token, farbe=user["farbe"],
        eintraege=eintraege, gesamt=gesamt, letzte_30=letzte_30)


@bp.route("/a/ausfaelle/druck", defaults={"token": None})
@bp.route("/a/ausfaelle/<token>/druck")
def druck(token):
    """Wunsch #250: Das Protokoll als Ausdruck fuer die Werkstatt.

    Die Ortsangaben werden HIER gerundet, nicht erst in der Vorlage - die
    Druckseite bekommt die vollen Koordinaten gar nicht zu sehen und kann
    sie damit auch nicht versehentlich ausgeben.

    Gewaehlte Kuerzung: zwei Nachkommastellen. Das ist ein Raster von rund
    1,1 km (Breite) x 0,75 km (Laenge, auf unserer Hoehe) - grob eine
    Ortslage. Man erkennt, dass die Ausfaelle wirklich unterwegs und an
    verschiedenen Orten passiert sind (Echtheit), aber weder Wohnadresse
    noch Fahrstrecke lassen sich daraus ablesen. Eine Stelle mehr (~110 m)
    waere wieder ein Bewegungsprofil, eine weniger (~11 km) saehe aus wie
    ausgedacht. Die Genauigkeit (+-x m) bleibt im Ausdruck ganz weg - neben
    einem 1-km-Raster ist sie bedeutungslos.

    Melder-Namen stehen ebenfalls nicht im Ausdruck: Die Werkstatt braucht
    Zeitpunkte und Zahlen, nicht die Familienmitglieder dahinter."""
    user = _user(token)
    db = get_db()
    zeilen = db.execute("""
        SELECT zeitpunkt, lat, lon, notiz
        FROM   ausfaelle
        ORDER  BY zeitpunkt ASC, id ASC
    """).fetchall()

    eintraege = []
    for z in zeilen:
        d = {"zeit_lokal": utc_zu_lokal(z["zeitpunkt"]), "notiz": z["notiz"]}
        if z["lat"] is not None and z["lon"] is not None:
            d["ort_kurz"] = f"{z['lat']:.2f}, {z['lon']:.2f}"
        else:
            d["ort_kurz"] = None
        eintraege.append(d)

    gesamt = len(eintraege)
    letzte_30 = db.execute(
        "SELECT COUNT(*) FROM ausfaelle WHERE zeitpunkt >= datetime('now','-30 days')"
    ).fetchone()[0]
    stand = utc_zu_lokal(db.execute("SELECT datetime('now')").fetchone()[0])

    return render_template("ausfaelle_druck.html",
        user=user, token=token, farbe=user["farbe"],
        eintraege=eintraege, gesamt=gesamt, letzte_30=letzte_30, stand=stand)


@bp.route("/a/ausfaelle/melden", defaults={"token": None}, methods=["POST"])
@bp.route("/a/ausfaelle/<token>/melden", methods=["POST"])
def melden(token):
    """Der Knopfdruck. Legt den Eintrag SOFORT an - ohne Ort, ohne Notiz."""
    user = _user(token)
    db = get_db()
    cur = db.execute("INSERT INTO ausfaelle(user_id) VALUES(?)", (user["id"],))
    db.commit()
    zeile = db.execute("SELECT zeitpunkt FROM ausfaelle WHERE id=?",
                       (cur.lastrowid,)).fetchone()
    return jsonify(ok=True, id=cur.lastrowid,
                   zeit=utc_zu_lokal(zeile["zeitpunkt"]))


@bp.route("/a/ausfaelle/<int:aid>/position", defaults={"token": None}, methods=["POST"])
@bp.route("/a/ausfaelle/<token>/<int:aid>/position", methods=["POST"])
def position(token, aid):
    """Haengt die Ortung an einen eben gemeldeten Ausfall.

    Nur einmal: Steht schon eine Position drin, bleibt sie. Sonst koennte ein
    spaeterer, ungenauerer Messwert (oder ein zweiter Tab) den ersten
    ueberschreiben - und der erste ist der, der zum Knopfdruck gehoert."""
    user = _user(token)
    db = get_db()
    zeile = db.execute("SELECT user_id, lat FROM ausfaelle WHERE id=?", (aid,)).fetchone()
    if not zeile:
        abort(404)
    if not _darf_aendern(user, zeile):
        abort(403)
    if zeile["lat"] is not None:
        return jsonify(ok=True, schon_da=True)

    daten = request.get_json(silent=True) or {}
    lat = _koordinate(daten.get("lat"), 90)
    lon = _koordinate(daten.get("lon"), 180)
    if lat is None or lon is None:
        return jsonify(ok=False, grund="ungueltige Koordinate"), 400

    genauigkeit = _koordinate(daten.get("genauigkeit"), 100000)
    db.execute("UPDATE ausfaelle SET lat=?, lon=?, genauigkeit=? WHERE id=?",
               (lat, lon, genauigkeit, aid))
    db.commit()
    return jsonify(ok=True)


@bp.route("/a/ausfaelle/<int:aid>/notiz", defaults={"token": None}, methods=["POST"])
@bp.route("/a/ausfaelle/<token>/<int:aid>/notiz", methods=["POST"])
def notiz(token, aid):
    user = _user(token)
    db = get_db()
    zeile = db.execute("SELECT user_id FROM ausfaelle WHERE id=?", (aid,)).fetchone()
    if not zeile:
        abort(404)
    if not _darf_aendern(user, zeile):
        abort(403)

    text = (request.form.get("notiz") or "").strip()
    db.execute("UPDATE ausfaelle SET notiz=? WHERE id=?", (text or None, aid))
    db.commit()
    return redirect(url_for("ausfaelle_app.index", token=token) + f"#eintrag-{aid}")


@bp.route("/a/ausfaelle/<int:aid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/ausfaelle/<token>/<int:aid>/loeschen", methods=["POST"])
def loeschen(token, aid):
    user = _user(token)
    db = get_db()
    zeile = db.execute("SELECT user_id FROM ausfaelle WHERE id=?", (aid,)).fetchone()
    if not zeile:
        abort(404)
    if not _darf_aendern(user, zeile):
        abort(403)
    db.execute("DELETE FROM ausfaelle WHERE id=?", (aid,))
    db.commit()
    return redirect(url_for("ausfaelle_app.index", token=token))


def init_app(app):
    app.register_blueprint(bp)
