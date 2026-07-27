"""
Rezepte-App – Lieblingsrezepte mit Zutaten und Zubereitung.
URL-Präfix: /a/rezepte/<token>/
Fehlende Zutaten lassen sich mit einem Klick auf die Einkaufsliste setzen.
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant

bp  = Blueprint("rezepte_app", __name__)
APP = "rezepte"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


@bp.route("/a/rezepte/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()
    rezepte = db.execute("""
        SELECT r.id, r.name,
               (SELECT COUNT(*) FROM rezept_zutaten z WHERE z.rezept_id = r.id) AS anzahl_zutaten
        FROM   rezepte r
        ORDER  BY r.name COLLATE NOCASE
    """).fetchall()
    return render_template("rezepte.html",
        user=user, token=token, farbe=user["farbe"], rezepte=rezepte)


@bp.route("/a/rezepte/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("rezepte_app.index", token=token))
    anleitung = request.form.get("anleitung", "").strip()
    zutaten   = [z.strip() for z in request.form.get("zutaten", "").splitlines() if z.strip()]

    db  = get_db()
    cur = db.execute(
        "INSERT INTO rezepte(name, anleitung, erstellt_von) VALUES(?,?,?)",
        (name, anleitung, user["id"]),
    )
    rezept_id = cur.lastrowid
    for position, zutat_name in enumerate(zutaten):
        db.execute(
            "INSERT INTO rezept_zutaten(rezept_id, name, position) VALUES(?,?,?)",
            (rezept_id, zutat_name, position),
        )
    db.commit()
    return redirect(url_for("rezepte_app.detail", token=token, rid=rezept_id))


@bp.route("/a/rezepte/<token>/<int:rid>")
def detail(token, rid):
    user   = _user(token)
    db     = get_db()
    rezept = db.execute("SELECT * FROM rezepte WHERE id=?", (rid,)).fetchone()
    if not rezept:
        abort(404)
    zutaten = db.execute(
        "SELECT id, name FROM rezept_zutaten WHERE rezept_id=? ORDER BY position",
        (rid,),
    ).fetchall()
    return render_template("rezept_detail.html",
        user=user, token=token, farbe=user["farbe"], rezept=rezept, zutaten=zutaten)


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
