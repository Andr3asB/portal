from flask import Blueprint, render_template, abort, request, jsonify
from teile.kern import (
    get_db, to_int, token_lookup, token_entschluesseln, sitzung_vormerken,
)

bp = Blueprint("start", __name__)


def _home_user(token):
    """Gibt User-Daten für gültigen Home-Token zurück, sonst None.

    Wunsch #129: Suche über token_lookup, die beiden Token-Felder kommen
    verschlüsselt aus der DB und werden hier entschlüsselt (dict statt Row,
    wie bei grant() in 00_kern.py)."""
    db = get_db()
    row = db.execute("""
        SELECT u.id, u.name, u.farbe, u.is_admin, u.dark_mode, u.rolle,
               g.token_enc AS home_enc,
               (SELECT g2.token_enc FROM grants g2
                JOIN apps a2 ON a2.id = g2.app_id
                WHERE g2.user_id = u.id AND a2.slug = 'hilfe') AS hilfe_enc
        FROM   grants g
        JOIN   users u ON u.id = g.user_id
        JOIN   apps  a ON a.id = g.app_id
        WHERE  g.token_lookup = ? AND a.slug = 'home'
    """, (token_lookup(token),)).fetchone()
    if not row:
        return None
    daten = dict(row)
    daten["home_token"]  = token_entschluesseln(daten.pop("home_enc"))
    daten["hilfe_token"] = token_entschluesseln(daten.pop("hilfe_enc"))
    sitzung_vormerken(daten["id"])   # Wunsch #140, Stufe 1
    return daten


@bp.route("/")
def index():
    """Landing ohne Token."""
    return render_template("denied.html", reason="landing"), 200


@bp.route("/p/<token>")
def startseite(token):
    db  = get_db()
    row = _home_user(token)
    if not row:
        return render_template("denied.html", reason="invalid"), 403

    gruppen_rows = db.execute("""
        SELECT id, name, position FROM home_gruppen
        WHERE user_id = ? ORDER BY position
    """, (row["id"],)).fetchall()

    apps_rows = db.execute("""
        SELECT a.slug, a.name, a.emoji, a.offline_faehig, g.token_enc AS app_enc,
               g.id AS grant_id, g.gruppe_id, g.position,
               COALESCE(hg.position, 9999) AS gruppe_pos
        FROM   grants g
        JOIN   apps   a  ON a.id  = g.app_id
        LEFT JOIN home_gruppen hg ON hg.id = g.gruppe_id
        WHERE  g.user_id = ? AND a.slug NOT IN ('home', 'hilfe')
        ORDER  BY (g.gruppe_id IS NULL), gruppe_pos, g.gruppe_id, g.position, a.id
    """, (row["id"],)).fetchall()

    gruppen_map = {g["id"]: {"info": dict(g), "apps": []} for g in gruppen_rows}
    allgemein   = []
    for app_row in apps_rows:
        # Wunsch #129: Kachel-Links brauchen den Klartext-Token
        app = dict(app_row)
        app["app_token"] = token_entschluesseln(app.pop("app_enc"))
        gid = app["gruppe_id"]
        if gid is not None and gid in gruppen_map:
            gruppen_map[gid]["apps"].append(app)
        else:
            allgemein.append(app)
    gruppen_list = [gruppen_map[g["id"]] for g in gruppen_rows]

    return render_template(
        "startseite.html",
        user=row,
        gruppen=gruppen_list,
        allgemein=allgemein,
        token=token,
        farbe=row["farbe"],
        greeting="Hallo",
    )


@bp.route("/p/<token>/reorder", methods=["POST"])
def reorder(token):
    row = _home_user(token)
    if not row:
        abort(403)
    data  = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if not isinstance(order, list):
        abort(400)
    db = get_db()
    for item in order:
        grant_id  = to_int(item.get("grant_id"))
        gruppe_id = to_int(item.get("gruppe_id"))
        position  = to_int(item.get("position"), 0)
        if grant_id is None:
            continue
        if gruppe_id is not None:
            grp = db.execute(
                "SELECT id FROM home_gruppen WHERE id=? AND user_id=?",
                (gruppe_id, row["id"])
            ).fetchone()
            if not grp:
                gruppe_id = None
        g = db.execute(
            "SELECT id FROM grants WHERE id=? AND user_id=?",
            (grant_id, row["id"])
        ).fetchone()
        if g:
            db.execute(
                "UPDATE grants SET position=?, gruppe_id=? WHERE id=?",
                (position, gruppe_id, grant_id)
            )
    db.commit()
    return jsonify(ok=True)


@bp.route("/p/<token>/gruppe/reorder", methods=["POST"])
def gruppe_reorder(token):
    """Wunsch #21: die Gruppen selbst umsortieren (nicht nur Apps innerhalb)."""
    row = _home_user(token)
    if not row:
        abort(403)
    data  = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if not isinstance(order, list):
        abort(400)
    db = get_db()
    for position, gid in enumerate(order):
        gid = to_int(gid)
        if gid is None:
            continue
        db.execute(
            "UPDATE home_gruppen SET position=? WHERE id=? AND user_id=?",
            (position, gid, row["id"])
        )
    db.commit()
    return jsonify(ok=True)


@bp.route("/p/<token>/gruppe/neu", methods=["POST"])
def gruppe_neu(token):
    row = _home_user(token)
    if not row:
        abort(403)
    data = request.get_json(silent=True) or {}
    name = (request.form.get("name") or data.get("name", "")).strip()
    if not name:
        return jsonify(ok=False, error="name required"), 400
    db      = get_db()
    max_pos = db.execute(
        "SELECT COALESCE(MAX(position), -1) FROM home_gruppen WHERE user_id=?",
        (row["id"],)
    ).fetchone()[0]
    result = db.execute(
        "INSERT INTO home_gruppen(user_id, name, position) VALUES(?,?,?) RETURNING id",
        (row["id"], name, max_pos + 1)
    ).fetchone()
    db.commit()
    return jsonify(ok=True, id=result["id"], name=name)


@bp.route("/p/<token>/gruppe/<int:gid>/umbenennen", methods=["POST"])
def gruppe_umbenennen(token, gid):
    row = _home_user(token)
    if not row:
        abort(403)
    data = request.get_json(silent=True) or {}
    name = (request.form.get("name") or data.get("name", "")).strip()
    if not name:
        return jsonify(ok=False), 400
    db = get_db()
    db.execute(
        "UPDATE home_gruppen SET name=? WHERE id=? AND user_id=?",
        (name, gid, row["id"])
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/p/<token>/gruppe/<int:gid>/loeschen", methods=["POST"])
def gruppe_loeschen(token, gid):
    row = _home_user(token)
    if not row:
        abort(403)
    db = get_db()
    db.execute(
        "UPDATE grants SET gruppe_id=NULL WHERE gruppe_id=? AND user_id=?",
        (gid, row["id"])
    )
    db.execute(
        "DELETE FROM home_gruppen WHERE id=? AND user_id=?",
        (gid, row["id"])
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
