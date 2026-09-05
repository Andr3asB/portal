"""
Essensplan – aktuelle und folgende Woche, zwei Mahlzeiten pro Tag.
URL-Präfix: /a/essensplan/<token>/

Jeder Tag hat einen Mittag- und einen Abend-Slot: entweder ein Verweis auf
ein bestehendes Rezept (teile.11_rezepte) oder freier Text. Einträge lassen
sich per Drag & Drop auf einen beliebigen anderen Slot verschieben – anderer
Tag, andere Mahlzeit oder beides (Wunsch #35, überarbeitet). Aktuelle und
nächste Woche haben eigene Überschriften (Wunsch #40/#41), vergangene Tage
sind zu einem Block einklappbar (Wunsch #42).
"""
import re
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from teile.kern import antwort_oder_weiter, get_db, to_int
from teile.kern import grant as check_grant

# Wunsch #184: Das Symbol vor einem Rezept haengt an dessen Kategorie. Der
# Essensplan zeigt dieselben Rezepte - stuende hier weiter ein fester Topf,
# haette dasselbe Rezept je nach Seite ein anderes Zeichen.
from teile.rezepte import kategorie_symbol

bp  = Blueprint("essensplan_app", __name__)
APP = "essensplan"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MAHLZEITEN = ["mittag", "abend"]
MAHLZEIT_LABELS = {"mittag": "Mittag", "abend": "Abend"}


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


@bp.route("/a/essensplan/", defaults={"token": None})
@bp.route("/a/essensplan/<token>/")
def index(token):
    user  = _user(token)
    heute = date.today()
    montag = heute - timedelta(days=heute.weekday())
    tage_daten = [montag + timedelta(days=i) for i in range(14)]  # aktuelle + folgende Woche

    db   = get_db()
    rows = db.execute("""
        SELECT e.tag, e.mahlzeit, e.text, r.id AS rezept_id, r.name AS rezept_name,
               r.kategorie AS rezept_kategorie
        FROM   essensplan_eintraege e
        LEFT JOIN rezepte r ON r.id = e.rezept_id
        WHERE  e.tag BETWEEN ? AND ?
    """, (tage_daten[0].isoformat(), tage_daten[-1].isoformat())).fetchall()
    # Wunsch #162: Welche Slots sind als gekocht markiert? Eine Abfrage fuer
    # die ganzen zwei Wochen statt einer je Slot (das waeren 28).
    gekocht = {
        (g["tag"], g["mahlzeit"])
        for g in db.execute(
            "SELECT tag, mahlzeit FROM rezept_gekocht WHERE tag BETWEEN ? AND ?",
            (tage_daten[0].isoformat(), tage_daten[-1].isoformat()))
    }
    eintraege_map = {}
    for r in rows:
        zeile = dict(r)
        zeile["gekocht"] = (r["tag"], r["mahlzeit"]) in gekocht
        eintraege_map.setdefault(r["tag"], {})[r["mahlzeit"]] = zeile

    rezepte = db.execute(
        "SELECT id, name FROM rezepte ORDER BY name COLLATE NOCASE"
    ).fetchall()

    tage = []
    for d in tage_daten:
        iso = d.isoformat()
        if d < heute:
            status = "vergangen"
        elif d == heute:
            status = "heute"
        else:
            status = "zukunft"
        tage.append({
            "iso": iso, "datum": d, "wochentag_name": WOCHENTAGE[d.weekday()],
            "status": status, "eintraege": eintraege_map.get(iso, {}),
        })

    # Wunsch #40/#41: eigene Überschriften je Woche. Wunsch #42: vergangene
    # Tage (immer ein zusammenhängender Block am Anfang der aktuellen Woche)
    # einklappbar statt einzeln in der Liste.
    aktuelle_woche  = tage[:7]
    naechste_woche  = tage[7:]
    vergangene_tage = [t for t in aktuelle_woche if t["status"] == "vergangen"]
    aktuelle_rest   = [t for t in aktuelle_woche if t["status"] != "vergangen"]

    return render_template("essensplan.html",
        user=user, token=token, farbe=user["farbe"],
        tage=tage, vergangene_tage=vergangene_tage, aktuelle_rest=aktuelle_rest,
        naechste_woche=naechste_woche,
        rezepte=rezepte, mahlzeiten=MAHLZEITEN, mahlzeit_labels=MAHLZEIT_LABELS,
        symbol=kategorie_symbol,
    )


@bp.route("/a/essensplan/eintrag", defaults={"token": None}, methods=["POST"])
@bp.route("/a/essensplan/<token>/eintrag", methods=["POST"])
def eintrag_speichern(token):
    user     = _user(token)
    tag      = request.form.get("tag", "").strip()
    mahlzeit = request.form.get("mahlzeit", "").strip()
    if not tag or mahlzeit not in MAHLZEITEN:
        return redirect(url_for("essensplan_app.index", token=token))

    db        = get_db()
    rezept_id = to_int(request.form.get("rezept_id"))
    if rezept_id is not None and not db.execute(
        "SELECT 1 FROM rezepte WHERE id=?", (rezept_id,)
    ).fetchone():
        rezept_id = None
    text = "" if rezept_id else request.form.get("text", "").strip()

    if not rezept_id and not text:
        db.execute("DELETE FROM essensplan_eintraege WHERE tag=? AND mahlzeit=?", (tag, mahlzeit))
    else:
        db.execute("""
            INSERT INTO essensplan_eintraege(tag, mahlzeit, rezept_id, text, erstellt_von)
            VALUES(?,?,?,?,?)
            ON CONFLICT(tag, mahlzeit) DO UPDATE SET
                rezept_id=excluded.rezept_id,
                text=excluded.text,
                erstellt_von=excluded.erstellt_von
        """, (tag, mahlzeit, rezept_id, text, user["id"]))
    db.commit()
    # Wunsch #257: zurueck an die bearbeitete Stelle statt an den
    # Seitenanfang - Weiterleitung mit #anker auf den Slot (dieselbe
    # Konvention wie bei den Umschaltern, die die Reihenfolge aendern).
    # Der Anker entsteht nur aus geprueften Werten: mahlzeit ist oben
    # gegen MAHLZEITEN geprueft, tag muss ein ISO-Datum sein.
    ziel = url_for("essensplan_app.index", token=token)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tag):
        ziel += f"#slot-{tag}_{mahlzeit}"
    return redirect(ziel)


@bp.route("/a/essensplan/gekocht", defaults={"token": None}, methods=["POST"])
@bp.route("/a/essensplan/<token>/gekocht", methods=["POST"])
def gekocht_umschalten(token):
    """Wunsch #162: Einen Planeintrag als gekocht markieren - oder doch nicht.

    Umschalter statt Einbahnstrasse: Ein Haken, den man nicht mehr wegnimmt,
    ist bei einem Versehen aergerlich. Weil die Historie am Rezept haengt und
    nicht am Plan, ist das Zuruecknehmen hier ein echtes Loeschen - anders als
    im Kassenbuch geht es nicht um Buchfuehrung, sondern um eine Notiz.

    Nur fuer Eintraege MIT Rezept: "wann ein Rezept aus der DB gekocht wurde"
    laesst sich fuer einen Freitext-Eintrag nicht fuehren. Die Oberflaeche
    zeigt den Haken deshalb auch nur dort.
    """
    user = _user(token)
    tag      = (request.form.get("tag") or "").strip()
    mahlzeit = (request.form.get("mahlzeit") or "").strip()
    if mahlzeit not in MAHLZEITEN or not tag:
        abort(400)

    db = get_db()
    eintrag = db.execute(
        "SELECT rezept_id FROM essensplan_eintraege WHERE tag=? AND mahlzeit=?",
        (tag, mahlzeit)).fetchone()
    if not eintrag or not eintrag["rezept_id"]:
        abort(404)
    rid = eintrag["rezept_id"]

    schon_da = db.execute(
        "SELECT id FROM rezept_gekocht WHERE rezept_id=? AND tag=? AND mahlzeit=?",
        (rid, tag, mahlzeit)).fetchone()
    if schon_da:
        db.execute("DELETE FROM rezept_gekocht WHERE id=?", (schon_da["id"],))
    else:
        db.execute(
            "INSERT INTO rezept_gekocht(rezept_id, tag, mahlzeit, markiert_von) "
            "VALUES(?,?,?,?)", (rid, tag, mahlzeit, user["id"]))
    db.commit()
    # Wunsch #171: ohne Seitensprung. Der neue Zustand geht zurueck, damit die
    # Seite den Knopf umschalten kann, ohne alles neu zu laden.
    return antwort_oder_weiter(url_for("essensplan_app.index", token=token),
                               gekocht=not schon_da)


@bp.route("/a/essensplan/verschieben", defaults={"token": None}, methods=["POST"])
@bp.route("/a/essensplan/<token>/verschieben", methods=["POST"])
def verschieben(token):
    """Drag & Drop: Eintrag auf einen beliebigen anderen Mahlzeit-Slot ziehen
    (anderer Tag und/oder andere Mahlzeit). Ist der Ziel-Slot schon belegt,
    werden beide getauscht."""
    _user(token)
    data          = request.get_json(silent=True) or {}
    von_tag       = (data.get("von_tag") or "").strip()
    von_mahlzeit  = (data.get("von_mahlzeit") or "").strip()
    nach_tag      = (data.get("nach_tag") or "").strip()
    nach_mahlzeit = (data.get("nach_mahlzeit") or "").strip()
    if (not von_tag or not nach_tag or von_mahlzeit not in MAHLZEITEN
            or nach_mahlzeit not in MAHLZEITEN
            or (von_tag == nach_tag and von_mahlzeit == nach_mahlzeit)):
        return jsonify(ok=False), 400

    db = get_db()
    quelle = db.execute(
        "SELECT id FROM essensplan_eintraege WHERE tag=? AND mahlzeit=?", (von_tag, von_mahlzeit)
    ).fetchone()
    if not quelle:
        return jsonify(ok=False), 404
    ziel = db.execute(
        "SELECT id FROM essensplan_eintraege WHERE tag=? AND mahlzeit=?", (nach_tag, nach_mahlzeit)
    ).fetchone()

    if ziel:
        # Platzhalter-Tag, damit die UNIQUE(tag,mahlzeit)-Regel beim Tausch
        # nicht kurzzeitig zwei Zeilen mit demselben (tag,mahlzeit) verlangt.
        db.execute("UPDATE essensplan_eintraege SET tag='__tausch__' WHERE id=?", (quelle["id"],))
        db.execute("UPDATE essensplan_eintraege SET tag=?, mahlzeit=? WHERE id=?",
                   (von_tag, von_mahlzeit, ziel["id"]))
        db.execute("UPDATE essensplan_eintraege SET tag=?, mahlzeit=? WHERE id=?",
                   (nach_tag, nach_mahlzeit, quelle["id"]))
    else:
        db.execute("UPDATE essensplan_eintraege SET tag=?, mahlzeit=? WHERE id=?",
                   (nach_tag, nach_mahlzeit, quelle["id"]))
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
