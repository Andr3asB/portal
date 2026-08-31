"""
Geholfen-App – Kinder tippen auf Kacheln wenn sie geholfen haben.
URL-Präfix: /a/geholfen/<token>/

Design: große Kacheln, auch als Küchen-Tablet-Daueranzeige geeignet.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from teile.kern import get_db, to_int
from teile.kern import grant as check_grant

bp  = Blueprint("geholfen_app", __name__)
APP = "geholfen"


def _kann_fuer_andere(user):
    return user["is_admin"] or user["rolle"] == "eltern"


@bp.route("/a/geholfen/", defaults={"token": None})
@bp.route("/a/geholfen/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db       = get_db()
    aufgaben = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()
    alle_nutzer = None
    if _kann_fuer_andere(user):
        alle_nutzer = db.execute(
            "SELECT id, name, farbe FROM users ORDER BY name"
        ).fetchall()

    # Heatmap: letzte 10 Tage, wer hat wann geholfen (Wunsch #29).
    # Erst Eltern, dann Kinder (Wunsch #44), innerhalb der Gruppe alphabetisch.
    heatmap_nutzer = db.execute("""
        SELECT id, name, farbe FROM users WHERE rolle IN ('eltern','kind')
        ORDER BY CASE rolle WHEN 'eltern' THEN 0 ELSE 1 END, name COLLATE NOCASE
    """).fetchall()
    tage = [(date.today() - timedelta(days=i)).isoformat() for i in range(9, -1, -1)]
    heat_rows = db.execute("""
        SELECT date(zeitstempel) AS tag, user_id
        FROM   geholfen_eintraege
        WHERE  zeitstempel >= datetime('now', '-10 days')
        GROUP  BY date(zeitstempel), user_id
    """).fetchall()
    geholfen_tage = {}
    for r in heat_rows:
        geholfen_tage.setdefault(r["user_id"], set()).add(r["tag"])

    return render_template("geholfen.html",
        user=user, token=token, farbe=user["farbe"],
        aufgaben=aufgaben, alle_nutzer=alle_nutzer,
        heatmap_nutzer=heatmap_nutzer, tage=tage, geholfen_tage=geholfen_tage,
    )


@bp.route("/a/geholfen/tippen/<int:aufgabe_id>", defaults={"token": None}, methods=["POST"])
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
        return jsonify(
            ok=True, aufgabe=aufg["name"], emoji=aufg["emoji"],
            fuer_user_id=ziel_user_id, tag=date.today().isoformat(),
        )
    return redirect(url_for("geholfen_app.index", token=token))


@bp.route("/a/geholfen/verlauf", defaults={"token": None})
@bp.route("/a/geholfen/<token>/verlauf")
def verlauf(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    letzte = db.execute("""
        SELECT e.id, e.zeitstempel, e.user_id, e.aufgabe_id,
               u.name, u.farbe, a.emoji, a.name AS aufgabe
        FROM   geholfen_eintraege e
        JOIN   users              u ON u.id = e.user_id
        JOIN   geholfen_aufgaben  a ON a.id = e.aufgabe_id
        ORDER  BY e.zeitstempel DESC LIMIT 50
    """).fetchall()
    darf_bearbeiten = _kann_fuer_andere(user)
    alle_nutzer = alle_aufgaben = None
    if darf_bearbeiten:
        alle_nutzer   = db.execute("SELECT id, name FROM users ORDER BY name").fetchall()
        alle_aufgaben = db.execute("SELECT id, name, emoji FROM geholfen_aufgaben ORDER BY id").fetchall()
    return render_template("geholfen_verlauf.html",
        user=user, token=token, farbe=user["farbe"], letzte=letzte,
        darf_bearbeiten=darf_bearbeiten, alle_nutzer=alle_nutzer, alle_aufgaben=alle_aufgaben)


@bp.route("/a/geholfen/eintrag/<int:eid>/bearbeiten", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geholfen/<token>/eintrag/<int:eid>/bearbeiten", methods=["POST"])
def eintrag_bearbeiten(token, eid):
    user = check_grant(token, APP)
    if not user or not _kann_fuer_andere(user):
        abort(403)
    db  = get_db()
    row = db.execute("SELECT id FROM geholfen_eintraege WHERE id=?", (eid,)).fetchone()
    if not row:
        abort(404)
    user_id     = to_int(request.form.get("user_id"))
    aufgabe_id  = to_int(request.form.get("aufgabe_id"))
    zeitstempel = request.form.get("zeitstempel", "").strip()
    if (user_id is None or aufgabe_id is None or not zeitstempel
            or not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
            or not db.execute("SELECT 1 FROM geholfen_aufgaben WHERE id=?", (aufgabe_id,)).fetchone()):
        return redirect(url_for("geholfen_app.verlauf", token=token))
    # <input type="datetime-local"> liefert "YYYY-MM-DDTHH:MM" - SQLite braucht
    # ein Leerzeichen statt "T" und optional die Sekunden.
    zeitstempel_sql = zeitstempel.replace("T", " ")
    if len(zeitstempel_sql) == 16:
        zeitstempel_sql += ":00"
    db.execute(
        "UPDATE geholfen_eintraege SET user_id=?, aufgabe_id=?, zeitstempel=? WHERE id=?",
        (user_id, aufgabe_id, zeitstempel_sql, eid),
    )
    db.commit()
    return redirect(url_for("geholfen_app.verlauf", token=token))


@bp.route("/a/geholfen/eintrag/<int:eid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geholfen/<token>/eintrag/<int:eid>/loeschen", methods=["POST"])
def eintrag_loeschen(token, eid):
    user = check_grant(token, APP)
    if not user or not _kann_fuer_andere(user):
        abort(403)
    db = get_db()
    db.execute("DELETE FROM geholfen_eintraege WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("geholfen_app.verlauf", token=token))


@bp.route("/a/geholfen/uebersicht", defaults={"token": None})
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


@bp.route("/a/geholfen/aufgaben", defaults={"token": None}, methods=["GET", "POST"])
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
        elif action == "umbenennen":
            # Wunsch #96: Aufgaben umbenennen war bisher nur per Code-Migration
            # moeglich - jetzt genau wie bei einkauf_kategorien.html direkt in
            # der Verwaltung, damit sowas kuenftig ohne Deploy geht.
            aid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name:
                db.execute("UPDATE geholfen_aufgaben SET name=? WHERE id=?", (name, aid))
                db.commit()
        return redirect(url_for("geholfen_app.aufgaben_verwalten", token=token))
    aufgaben = db.execute("SELECT * FROM geholfen_aufgaben ORDER BY aktiv DESC, id").fetchall()
    return render_template("geholfen_aufgaben.html",
        user=user, token=token, farbe=user["farbe"], aufgaben=aufgaben)


def init_app(app):
    app.register_blueprint(bp)
