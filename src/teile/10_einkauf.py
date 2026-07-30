"""
Einkaufsliste – gemeinsam von allen Nutzern befüllt.
URL-Präfix: /a/einkauf/<token>/
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("einkauf_app", __name__)
APP = "einkauf"


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


def _clean_angebot(db, angebot, laden_id):
    """Nur eine gültige Kombination durchlassen – sonst konsequent beides aus,
    statt einer Markierung ohne Markt (führte früher zu kaputten Zwischenzuständen)."""
    if angebot and laden_id is not None and db.execute(
        "SELECT 1 FROM einkauf_laeden WHERE id=?", (laden_id,)
    ).fetchone():
        return 1, laden_id
    return 0, None


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
        SELECT e.id, e.name, e.kategorie_id, e.angebot, e.laden_id, e.erledigt,
               e.erledigt_am, l.name AS laden_name
        FROM   einkauf_eintraege e
        LEFT JOIN einkauf_laeden l ON l.id = e.laden_id
        WHERE  e.erledigt = 0
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
        SELECT e.id, e.name, e.kategorie_id, e.angebot, e.laden_id, e.erledigt,
               e.erledigt_am, l.name AS laden_name
        FROM   einkauf_eintraege e
        LEFT JOIN einkauf_laeden l ON l.id = e.laden_id
        WHERE  e.erledigt = 1 AND e.erledigt_am >= datetime('now', '-6 hours')
        ORDER  BY e.erledigt_am DESC
    """).fetchall()
    return render_template("einkauf.html",
        user=user, token=token, farbe=user["farbe"],
        kategorien=kategorien, gruppen=gruppen, unsortiert=unsortiert, erledigt=erledigt,
        laeden=laeden, vorschlaege=vorschlaege,
    )


@bp.route("/a/einkauf/<token>/add", methods=["POST"])
def add(token):
    user = _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("einkauf_app.index", token=token))
    db = get_db()
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    angebot, laden_id = _clean_angebot(
        db,
        1 if request.form.get("angebot") == "1" else 0,
        to_int(request.form.get("laden_id")),
    )
    db.execute(
        "INSERT INTO einkauf_eintraege(name,kategorie_id,angebot,laden_id,erstellt_von) VALUES(?,?,?,?,?)",
        (name, kategorie_id, angebot, laden_id, user["id"]),
    )
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/<token>/erledigt/<int:eid>", methods=["POST"])
def toggle_erledigt(token, eid):
    _user(token)
    db  = get_db()
    row = db.execute("SELECT erledigt FROM einkauf_eintraege WHERE id=?", (eid,)).fetchone()
    if not row:
        abort(404)
    neu = 0 if row["erledigt"] else 1
    db.execute(
        "UPDATE einkauf_eintraege SET erledigt=?, erledigt_am=CASE WHEN ?=1 THEN datetime('now') ELSE NULL END WHERE id=?",
        (neu, neu, eid),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, erledigt=bool(neu))
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/<token>/loeschen/<int:eid>", methods=["POST"])
def loeschen(token, eid):
    _user(token)
    db = get_db()
    db.execute("DELETE FROM einkauf_eintraege WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


@bp.route("/a/einkauf/<token>/bearbeiten/<int:eid>", methods=["POST"])
def bearbeiten(token, eid):
    _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("einkauf_app.index", token=token))
    db = get_db()
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    angebot, laden_id = _clean_angebot(
        db,
        1 if request.form.get("angebot") == "1" else 0,
        to_int(request.form.get("laden_id")),
    )
    db.execute(
        "UPDATE einkauf_eintraege SET name=?, kategorie_id=?, angebot=?, laden_id=? WHERE id=?",
        (name, kategorie_id, angebot, laden_id, eid),
    )
    db.commit()
    return redirect(url_for("einkauf_app.index", token=token))


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
