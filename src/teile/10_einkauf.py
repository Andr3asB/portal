"""
Einkaufsliste – gemeinsam von allen Nutzern befüllt.
URL-Präfix: /a/einkauf/<token>/
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("einkauf_app", __name__)
APP = "einkauf"

KATEGORIEN = [
    "Obst & Gemüse",
    "Kühlregal",
    "Wurst & Käse",
    "Trockenvorrat",
    "TK",
    "Convenience",
    "Sonstiges",
]


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


@bp.route("/a/einkauf/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()
    laeden = db.execute(
        "SELECT id, name FROM einkauf_laeden WHERE aktiv=1 ORDER BY name"
    ).fetchall()
    vorschlaege = [r["name"] for r in db.execute(
        "SELECT name, COUNT(*) AS n FROM einkauf_eintraege "
        "GROUP BY lower(name) ORDER BY n DESC LIMIT 40"
    ).fetchall()]
    rows = db.execute("""
        SELECT e.id, e.name, e.kategorie, e.angebot, e.erledigt,
               e.erledigt_am, l.name AS laden_name
        FROM   einkauf_eintraege e
        LEFT JOIN einkauf_laeden l ON l.id = e.laden_id
        WHERE  e.erledigt = 0
           OR  (e.erledigt = 1 AND e.erledigt_am >= datetime('now', '-6 hours'))
        ORDER  BY e.erledigt ASC, e.erstellt DESC
    """).fetchall()
    # Gruppierung
    gruppen = {k: [] for k in KATEGORIEN}
    erledigt = []
    for r in rows:
        if r["erledigt"]:
            erledigt.append(r)
        else:
            kat = r["kategorie"] if r["kategorie"] in gruppen else "Sonstiges"
            gruppen[kat].append(r)
    return render_template("einkauf.html",
        user=user, token=token, farbe=user["farbe"],
        kategorien=KATEGORIEN, gruppen=gruppen, erledigt=erledigt,
        laeden=laeden, vorschlaege=vorschlaege,
    )


@bp.route("/a/einkauf/<token>/add", methods=["POST"])
def add(token):
    user = _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("einkauf_app.index", token=token))
    kat = request.form.get("kategorie", "Sonstiges")
    if kat not in KATEGORIEN:
        kat = "Sonstiges"
    angebot  = 1 if request.form.get("angebot") == "1" else 0
    laden_id = to_int(request.form.get("laden_id"))
    db = get_db()
    if not angebot or laden_id is None or not db.execute(
        "SELECT 1 FROM einkauf_laeden WHERE id=?", (laden_id,)
    ).fetchone():
        laden_id = None
    db.execute(
        "INSERT INTO einkauf_eintraege(name,kategorie,angebot,laden_id,erstellt_von) VALUES(?,?,?,?,?)",
        (name, kat, angebot, laden_id, user["id"]),
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


@bp.route("/a/einkauf/<token>/angebot/<int:eid>", methods=["POST"])
def set_angebot(token, eid):
    _user(token)
    db      = get_db()
    angebot = 1 if request.form.get("angebot") == "1" else 0
    laden_id = to_int(request.form.get("laden_id"))
    if not angebot or laden_id is None or not db.execute(
        "SELECT 1 FROM einkauf_laeden WHERE id=?", (laden_id,)
    ).fetchone():
        laden_id = None
    db.execute(
        "UPDATE einkauf_eintraege SET angebot=?, laden_id=? WHERE id=?",
        (angebot, laden_id, eid),
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


def init_app(app):
    app.register_blueprint(bp)
