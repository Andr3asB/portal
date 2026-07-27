"""
Geholfen-App – Kinder tippen auf Kacheln wenn sie geholfen haben.
URL-Präfix: /a/geholfen/<token>/

Design: große Kacheln, auch als Küchen-Tablet-Daueranzeige geeignet.
"""
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("geholfen_app", __name__)
APP = "geholfen"


def _kann_fuer_andere(user):
    return user["is_admin"] or user["rolle"] == "eltern"


@bp.route("/a/geholfen/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db       = get_db()
    aufgaben = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()
    letzte = db.execute("""
        SELECT e.zeitstempel, u.name, a.emoji, a.name AS aufgabe
        FROM   geholfen_eintraege e
        JOIN   users              u ON u.id = e.user_id
        JOIN   geholfen_aufgaben  a ON a.id = e.aufgabe_id
        ORDER  BY e.zeitstempel DESC LIMIT 10
    """).fetchall()
    alle_nutzer = None
    if _kann_fuer_andere(user):
        alle_nutzer = db.execute(
            "SELECT id, name, farbe FROM users ORDER BY name"
        ).fetchall()
    return render_template("geholfen.html",
        user=user, token=token, farbe=user["farbe"],
        aufgaben=aufgaben, letzte=letzte, alle_nutzer=alle_nutzer,
    )


@bp.route("/a/geholfen/<token>/tippen/<int:aufgabe_id>", methods=["POST"])
def tippen(token, aufgabe_id):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db = get_db()
    aufg = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE id=? AND aktiv=1", (aufgabe_id,)
    ).fetchone()
    if not aufg:
        abort(404)
    ziel_user_id = user["id"]
    if _kann_fuer_andere(user):
        data = request.get_json(silent=True) or {}
        fuer = to_int(data.get("fuer_user_id") or request.form.get("fuer_user_id"))
        if fuer is not None:
            exists = db.execute("SELECT id FROM users WHERE id=?", (fuer,)).fetchone()
            if exists:
                ziel_user_id = fuer
    db.execute(
        "INSERT INTO geholfen_eintraege(aufgabe_id, user_id) VALUES(?,?)",
        (aufgabe_id, ziel_user_id),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        letzte = db.execute("""
            SELECT e.zeitstempel, u.name, a.emoji, a.name AS aufgabe
            FROM   geholfen_eintraege e
            JOIN   users             u ON u.id = e.user_id
            JOIN   geholfen_aufgaben a ON a.id = e.aufgabe_id
            ORDER  BY e.zeitstempel DESC LIMIT 10
        """).fetchall()
        return jsonify(
            ok=True, aufgabe=aufg["name"], emoji=aufg["emoji"],
            letzte=[{"name": r["name"], "aufgabe": r["aufgabe"],
                     "emoji": r["emoji"], "zeit": r["zeitstempel"][11:16]}
                    for r in letzte],
        )
    return redirect(url_for("geholfen_app.index", token=token))


@bp.route("/a/geholfen/<token>/uebersicht")
def uebersicht(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    users    = db.execute("SELECT id, name, farbe FROM users ORDER BY name").fetchall()
    aufgaben = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()
    # Punkte/Counts letzte 7 Tage
    eintraege = db.execute("""
        SELECT e.user_id, e.aufgabe_id, a.gewichtung
        FROM   geholfen_eintraege e
        JOIN   geholfen_aufgaben  a ON a.id = e.aufgabe_id
        WHERE  e.zeitstempel >= datetime('now', '-7 days')
    """).fetchall()
    counts = {}
    punkte = {}
    for e in eintraege:
        uid, aid = e["user_id"], e["aufgabe_id"]
        counts.setdefault(uid, {}).setdefault(aid, 0)
        counts[uid][aid] += 1
        punkte[uid] = punkte.get(uid, 0.0) + e["gewichtung"]
    # Kalender: letzte 30 Tage – welcher Nutzer hat an welchem Tag geholfen
    tage = [(date.today() - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    kal_rows = db.execute("""
        SELECT date(zeitstempel) AS tag, user_id
        FROM   geholfen_eintraege
        WHERE  zeitstempel >= datetime('now', '-30 days')
        GROUP  BY date(zeitstempel), user_id
    """).fetchall()
    kalender = {}
    for r in kal_rows:
        kalender.setdefault(r["tag"], set()).add(r["user_id"])
    return render_template("geholfen_uebersicht.html",
        user=user, token=token, farbe=user["farbe"],
        users=users, aufgaben=aufgaben,
        counts=counts, punkte=punkte,
        tage=tage, kalender=kalender,
    )


@bp.route("/a/geholfen/<token>/aufgaben", methods=["GET", "POST"])
def aufgaben_verwalten(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            emoji = request.form.get("emoji", "👍").strip()
            try:
                gew = float(request.form.get("gewichtung", 1.0))
            except (TypeError, ValueError):
                gew = 1.0
            if name:
                db.execute(
                    "INSERT INTO geholfen_aufgaben(name,emoji,gewichtung) VALUES(?,?,?)",
                    (name, emoji, gew),
                )
                db.commit()
        elif action == "toggle":
            aid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM geholfen_aufgaben WHERE id=?", (aid,)).fetchone()
            if row:
                db.execute("UPDATE geholfen_aufgaben SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, aid))
                db.commit()
        return redirect(url_for("geholfen_app.aufgaben_verwalten", token=token))
    aufgaben = db.execute("SELECT * FROM geholfen_aufgaben ORDER BY aktiv DESC, id").fetchall()
    return render_template("geholfen_aufgaben.html",
        user=user, token=token, farbe=user["farbe"], aufgaben=aufgaben)


def init_app(app):
    app.register_blueprint(bp)
