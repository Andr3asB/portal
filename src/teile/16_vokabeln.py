"""
Vokabeln-App - eigene Vokabeln erfassen, in Sprachen und Kapiteln
organisieren und per Trainer lernen (Wunsch #73, ersetzt den Fehlversuch
aus Wunsch #67 komplett).
URL-Praefix: /a/vokabeln/<token>/

Sprachen sind global (Standard: Englisch, Latein - neue Sprachen kommen
bei Bedarf per Wunsch dazu), jeder Nutzer aktiviert die fuer ihn
relevanten selbst auf einer eigenen Unterseite. Kapitel gehoeren jeweils
einem Nutzer und gruppieren seine Vokabeln (eine Vokabel kann mehreren
Kapiteln oder keinem angehoeren). Der Trainer fragt eine gewaehlte
Sprache/Kapitel-Auswahl zufaellig ab: richtig beantwortete Vokabeln
kommen in der laufenden Session nicht noch mal dran, falsch beantwortete
werden ans Ende der Warteschlange gehaengt und so spaeter erneut gefragt.
Jeder Versuch wird protokolliert, Sessions haben Start- und Endzeitpunkt.
"""
import random
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, abort
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("vokabeln_app", __name__)
APP = "vokabeln"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _aktive_sprachen_sicherstellen(db, user_id):
    """Beim allerersten Kontakt: alle Standardsprachen fuer den Nutzer
    aktivieren, damit die App nicht komplett leer startet. Wer danach
    gezielt abwaehlt (Unterseite "Sprachen"), bleibt dabei - dieser
    Automatismus greift nur, solange noch keine einzige Zeile existiert."""
    hat_schon = db.execute(
        "SELECT 1 FROM vokabel_sprachen_nutzer WHERE user_id=?", (user_id,)
    ).fetchone()
    if hat_schon:
        return
    for (sid,) in db.execute("SELECT id FROM vokabel_sprachen WHERE aktiv=1").fetchall():
        db.execute(
            "INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
            (user_id, sid),
        )
    db.commit()


def _eigene_sprachen(db, user_id):
    return db.execute("""
        SELECT s.id, s.name FROM vokabel_sprachen s
        JOIN vokabel_sprachen_nutzer n ON n.sprache_id = s.id
        WHERE n.user_id=? AND s.aktiv=1
        ORDER BY s.name COLLATE NOCASE
    """, (user_id,)).fetchall()


def _sprache_erlaubt(db, user_id, sprache_id):
    return db.execute("""
        SELECT 1 FROM vokabel_sprachen_nutzer n
        JOIN vokabel_sprachen s ON s.id = n.sprache_id
        WHERE n.user_id=? AND n.sprache_id=? AND s.aktiv=1
    """, (user_id, sprache_id)).fetchone() is not None


def _eigene_kapitel(db, user_id, nur_aktive=True):
    sql = "SELECT * FROM vokabel_kapitel WHERE user_id=?"
    if nur_aktive:
        sql += " AND aktiv=1"
    sql += " ORDER BY name COLLATE NOCASE"
    return db.execute(sql, (user_id,)).fetchall()


def _kapitel_gehoert_nutzer(db, user_id, kapitel_id):
    return db.execute(
        "SELECT 1 FROM vokabel_kapitel WHERE id=? AND user_id=?", (kapitel_id, user_id)
    ).fetchone() is not None


def _kapitel_ids_setzen(db, vokabel_id, user_id, kapitel_ids):
    db.execute("DELETE FROM vokabel_kapitel_zuordnung WHERE vokabel_id=?", (vokabel_id,))
    for kid in kapitel_ids:
        if kid is not None and _kapitel_gehoert_nutzer(db, user_id, kid):
            db.execute(
                "INSERT OR IGNORE INTO vokabel_kapitel_zuordnung(vokabel_id, kapitel_id) VALUES(?,?)",
                (vokabel_id, kid),
            )


@bp.route("/a/vokabeln/<token>/")
def index(token):
    user = _user(token)
    db = get_db()
    _aktive_sprachen_sicherstellen(db, user["id"])
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])
    vokabeln = db.execute("""
        SELECT v.id, v.fremd, v.deutsch, v.sprache_id, s.name AS sprache_name,
               (SELECT GROUP_CONCAT(z.kapitel_id) FROM vokabel_kapitel_zuordnung z
                WHERE z.vokabel_id = v.id) AS kapitel_ids,
               (SELECT GROUP_CONCAT(k.name, ', ') FROM vokabel_kapitel_zuordnung z
                JOIN vokabel_kapitel k ON k.id = z.kapitel_id
                WHERE z.vokabel_id = v.id) AS kapitel_namen
        FROM   vokabeln v
        JOIN   vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  v.user_id=?
        ORDER  BY v.erstellt DESC
    """, (user["id"],)).fetchall()
    return render_template("vokabeln.html",
        user=user, token=token, farbe=user["farbe"],
        sprachen=sprachen, kapitel=kapitel, vokabeln=vokabeln)


@bp.route("/a/vokabeln/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    db = get_db()
    fremd      = request.form.get("fremd", "").strip()
    deutsch    = request.form.get("deutsch", "").strip()
    sprache_id = to_int(request.form.get("sprache_id"))
    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        cur = db.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,?,?)",
            (user["id"], sprache_id, fremd, deutsch),
        )
        _kapitel_ids_setzen(db, cur.lastrowid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/<int:vid>/bearbeiten", methods=["POST"])
def bearbeiten(token, vid):
    user = _user(token)
    db = get_db()
    if not db.execute(
        "SELECT 1 FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"])
    ).fetchone():
        abort(404)

    fremd      = request.form.get("fremd", "").strip()
    deutsch    = request.form.get("deutsch", "").strip()
    sprache_id = to_int(request.form.get("sprache_id"))
    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        db.execute(
            "UPDATE vokabeln SET fremd=?, deutsch=?, sprache_id=? WHERE id=?",
            (fremd, deutsch, sprache_id, vid),
        )
        _kapitel_ids_setzen(db, vid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/<int:vid>/loeschen", methods=["POST"])
def loeschen(token, vid):
    user = _user(token)
    db = get_db()
    db.execute("DELETE FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"]))
    db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/sprachen", methods=["GET", "POST"])
def sprachen_verwalten(token):
    user = _user(token)
    db = get_db()
    if request.method == "POST":
        gewaehlt = {to_int(x) for x in request.form.getlist("sprache_ids")}
        gewaehlt.discard(None)
        for (sid,) in db.execute("SELECT id FROM vokabel_sprachen WHERE aktiv=1").fetchall():
            if sid in gewaehlt:
                db.execute(
                    "INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
                    (user["id"], sid),
                )
            else:
                db.execute(
                    "DELETE FROM vokabel_sprachen_nutzer WHERE user_id=? AND sprache_id=?",
                    (user["id"], sid),
                )
        db.commit()
        return redirect(url_for("vokabeln_app.sprachen_verwalten", token=token))

    _aktive_sprachen_sicherstellen(db, user["id"])
    alle_sprachen = db.execute(
        "SELECT * FROM vokabel_sprachen WHERE aktiv=1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    aktive_ids = {r[0] for r in db.execute(
        "SELECT sprache_id FROM vokabel_sprachen_nutzer WHERE user_id=?", (user["id"],)
    ).fetchall()}
    return render_template("vokabel_sprachen.html",
        user=user, token=token, farbe=user["farbe"],
        sprachen=alle_sprachen, aktive_ids=aktive_ids)


@bp.route("/a/vokabeln/<token>/kapitel", methods=["GET", "POST"])
def kapitel_verwalten(token):
    user = _user(token)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                db.execute(
                    "INSERT INTO vokabel_kapitel(user_id, name) VALUES(?,?)", (user["id"], name)
                )
                db.commit()
        elif action == "umbenennen":
            kid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name and _kapitel_gehoert_nutzer(db, user["id"], kid):
                db.execute("UPDATE vokabel_kapitel SET name=? WHERE id=?", (name, kid))
                db.commit()
        elif action == "toggle":
            kid = to_int(request.form.get("id"), 0)
            row = db.execute(
                "SELECT aktiv FROM vokabel_kapitel WHERE id=? AND user_id=?", (kid, user["id"])
            ).fetchone()
            if row:
                db.execute("UPDATE vokabel_kapitel SET aktiv=? WHERE id=?",
                           (0 if row[0] else 1, kid))
                db.commit()
        return redirect(url_for("vokabeln_app.kapitel_verwalten", token=token))

    kapitel = db.execute(
        "SELECT * FROM vokabel_kapitel WHERE user_id=? ORDER BY name COLLATE NOCASE", (user["id"],)
    ).fetchall()
    return render_template("vokabel_kapitel.html",
        user=user, token=token, farbe=user["farbe"], kapitel=kapitel)


@bp.route("/a/vokabeln/<token>/lernen")
def lernen(token):
    user = _user(token)
    db = get_db()
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])
    return render_template("vokabel_lernen.html",
        user=user, token=token, farbe=user["farbe"], sprachen=sprachen, kapitel=kapitel)


@bp.route("/a/vokabeln/<token>/lernen/start", methods=["POST"])
def lernen_start(token):
    user = _user(token)
    db = get_db()
    sprache_id = to_int(request.form.get("sprache_id"))
    if not sprache_id or not _sprache_erlaubt(db, user["id"], sprache_id):
        return redirect(url_for("vokabeln_app.lernen", token=token))

    auswahl = request.form.getlist("kapitel_ids")  # kann "alle" und/oder "ohne" enthalten
    alle_gewaehlt = "alle" in auswahl or not auswahl
    ohne_gewaehlt = "ohne" in auswahl
    kapitel_ids   = {to_int(k) for k in auswahl if k not in ("alle", "ohne")}
    kapitel_ids.discard(None)

    if alle_gewaehlt:
        vokabeln = db.execute(
            "SELECT id, fremd, deutsch FROM vokabeln WHERE user_id=? AND sprache_id=?",
            (user["id"], sprache_id),
        ).fetchall()
    else:
        gefunden = {}
        if ohne_gewaehlt:
            for r in db.execute("""
                SELECT v.id, v.fremd, v.deutsch FROM vokabeln v
                WHERE v.user_id=? AND v.sprache_id=?
                  AND NOT EXISTS (SELECT 1 FROM vokabel_kapitel_zuordnung z WHERE z.vokabel_id=v.id)
            """, (user["id"], sprache_id)).fetchall():
                gefunden[r[0]] = r
        for kid in kapitel_ids:
            if not _kapitel_gehoert_nutzer(db, user["id"], kid):
                continue
            for r in db.execute("""
                SELECT v.id, v.fremd, v.deutsch FROM vokabeln v
                JOIN vokabel_kapitel_zuordnung z ON z.vokabel_id = v.id
                WHERE v.user_id=? AND v.sprache_id=? AND z.kapitel_id=?
            """, (user["id"], sprache_id, kid)).fetchall():
                gefunden[r[0]] = r
        vokabeln = list(gefunden.values())

    # Nur eine offene Session je Nutzer: eine vorherige, nicht sauber
    # beendete Session (Tab geschlossen statt "Training beenden") wird
    # beim naechsten Start automatisch abgeschlossen.
    db.execute(
        "UPDATE vokabel_sessions SET beendet=datetime('now') WHERE user_id=? AND beendet IS NULL",
        (user["id"],),
    )
    cur = db.execute(
        "INSERT INTO vokabel_sessions(user_id, sprache_id) VALUES(?,?)",
        (user["id"], sprache_id),
    )
    session_id = cur.lastrowid

    if not vokabeln:
        db.execute("UPDATE vokabel_sessions SET beendet=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        return render_template("vokabel_training.html",
            user=user, token=token, farbe=user["farbe"], session_id=session_id, vokabeln=[])

    db.commit()
    aufgaben = [{"id": v[0], "fremd": v[1], "deutsch": v[2]} for v in vokabeln]
    random.shuffle(aufgaben)
    return render_template("vokabel_training.html",
        user=user, token=token, farbe=user["farbe"],
        session_id=session_id, vokabeln=aufgaben)


@bp.route("/a/vokabeln/<token>/versuch", methods=["POST"])
def versuch(token):
    user = _user(token)
    db = get_db()
    data       = request.get_json(silent=True) or {}
    session_id = to_int(data.get("session_id"))
    vokabel_id = to_int(data.get("vokabel_id"))
    richtig    = bool(data.get("richtig"))

    session_ok = session_id and db.execute(
        "SELECT 1 FROM vokabel_sessions WHERE id=? AND user_id=? AND beendet IS NULL",
        (session_id, user["id"]),
    ).fetchone()
    vokabel_ok = vokabel_id and db.execute(
        "SELECT 1 FROM vokabeln WHERE id=? AND user_id=?", (vokabel_id, user["id"])
    ).fetchone()
    if not (session_ok and vokabel_ok):
        return jsonify(ok=False), 400

    db.execute(
        "INSERT INTO vokabel_versuche(session_id, vokabel_id, richtig) VALUES(?,?,?)",
        (session_id, vokabel_id, 1 if richtig else 0),
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/a/vokabeln/<token>/session/<int:sid>/beenden", methods=["POST"])
def session_beenden(token, sid):
    user = _user(token)
    db = get_db()
    db.execute(
        "UPDATE vokabel_sessions SET beendet=datetime('now') WHERE id=? AND user_id=? AND beendet IS NULL",
        (sid, user["id"]),
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
