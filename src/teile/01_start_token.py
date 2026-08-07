from flask import (
    Blueprint, render_template, abort, request, jsonify, redirect, url_for,
)
from teile.kern import (
    get_db, to_int, token_lookup, sitzung_vormerken,
    sitzung_nutzer_id, sitzung_konsumieren_an, _nutzer_aufbereiten,
    tokenfreie_urls_an,
)

bp = Blueprint("start", __name__)


# Wunsch #140, Stufe 6: Die Unterabfragen auf die Navigations-Tokens sind
# entfallen - es gibt keinen Klartext mehr, und seit Stufe 4 braucht ihn auch
# niemand (alle Adressen sind token-frei).
_HOME_SELECT = """
    SELECT u.id, u.name, u.farbe, u.is_admin, u.dark_mode, u.rolle
    FROM   users u
"""


def _home_user(token):
    """Gibt User-Daten für gültigen Home-Token zurück, sonst None.

    Wunsch #129: Suche über token_lookup, die Token-Felder kommen
    verschlüsselt aus der DB. Wunsch #140 Stufe 3: ohne Token in der Adresse
    zählt ersatzweise das Sitzungs-Cookie – dieselbe Reihenfolge und dieselbe
    Begründung wie in grant() (Pfad-Token hat immer Vorrang, ein angegebener
    aber ungültiger Token fällt NICHT aufs Cookie zurück)."""
    db = get_db()

    if token:
        row = db.execute(_HOME_SELECT + """
            JOIN   grants g ON g.user_id = u.id
            JOIN   apps  a ON a.id = g.app_id
            WHERE  g.token_lookup = ? AND a.slug = 'home'
        """, (token_lookup(token),)).fetchone()
        if not row:
            return None
        daten = _nutzer_aufbereiten(row)
        sitzung_vormerken(daten["id"])   # Wunsch #140, Stufe 1
        return daten

    if not sitzung_konsumieren_an():
        return None
    user_id = sitzung_nutzer_id(db)
    if user_id is None:
        return None
    row = db.execute(_HOME_SELECT + """
        WHERE  u.id = ?
          AND  EXISTS (SELECT 1 FROM grants g JOIN apps a ON a.id = g.app_id
                       WHERE g.user_id = u.id AND a.slug = 'home')
    """, (user_id,)).fetchone()
    return _nutzer_aufbereiten(row) if row else None


@bp.route("/")
def index():
    """Landing ohne Token."""
    return render_template("denied.html", reason="landing"), 200


# Wunsch #140, Stufe 3: `/start` ist derselbe Einstieg ohne Token in der
# Adresse - der Nutzer kommt dann aus dem Sitzungs-Cookie. `/p/<token>` bleibt
# unverändert gültig und hat Vorrang; er ist der Ersteinstieg (QR-Code) und
# die Rückfallebene.
@bp.route("/start", defaults={"token": None})
@bp.route("/p/<token>")
def startseite(token):
    db  = get_db()
    row = _home_user(token)
    if not row:
        return render_template("denied.html", reason="invalid"), 403

    # Wunsch #140, Stufe 4: Den Token aus der Adresszeile nehmen - aber erst,
    # wenn dieses Gerät bewiesen hat, dass es das Cookie annimmt und
    # zurückschickt.
    #
    # Der naheliegende Weg (jeder Aufruf von /p/<token> leitet sofort auf
    # /start um) hat ein Aussperr-Fenster: Nimmt der Browser das Cookie nicht
    # an - Privatmodus, aufgebrauchter Speicher, strenge Einstellungen -,
    # landet man auf /start ohne Sitzung, bekommt denied.html, und der erneute
    # Scan des QR-Codes führt in dieselbe Weiterleitung. Der Link wäre für
    # dieses Gerät dauerhaft tot, obwohl der Token gilt.
    #
    # Deshalb: Beim ERSTEN Besuch wird die Seite ganz normal ausgeliefert (mit
    # Token in der Adresse, wie bisher) und das Cookie gesetzt. Kommt es beim
    # nächsten Aufruf zurück und zeigt auf denselben Nutzer, ist bewiesen, dass
    # Cookies auf diesem Gerät tragen - dann erst wird umgeleitet. Ein Gerät
    # ohne funktionierende Cookies behält für immer den Token-Link und
    # funktioniert unverändert weiter.
    if token and tokenfreie_urls_an() and sitzung_nutzer_id(db) == row["id"]:
        return redirect(url_for("start.startseite"))

    gruppen_rows = db.execute("""
        SELECT id, name, position FROM home_gruppen
        WHERE user_id = ? ORDER BY position
    """, (row["id"],)).fetchall()

    apps_rows = db.execute("""
        SELECT a.slug, a.name, a.emoji, a.offline_faehig,
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
        # Wunsch #140, Stufe 6: Kein app_token mehr - die Kacheln verlinken
        # seit Stufe 4 token-frei (app_pfad() in startseite.html).
        app = dict(app_row)
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
        # Wunsch #140, Stufe 4: Hier stand bis Stufe 3 `token or
        # row["home_token"]` - eine Brücke, damit Menü und fetch-Aufrufe auf
        # `/start` nicht ohne Token dastehen. Die ist jetzt weg und muss weg
        # sein: Sie hätte den Home-Token in `const TOKEN` und damit in jede
        # ausgelieferte Seite geschrieben, obwohl er in keiner Adresse mehr
        # vorkommt. Die Links kommen inzwischen aus `tp`/`app_pfad()`, die
        # Menü-Sichtbarkeit hängt an `user`, und die vier Endpunkte mit Token
        # im Body fallen über `aktueller_nutzer()` aufs Sitzungs-Cookie zurück.
        token=token,
        farbe=row["farbe"],
        greeting="Hallo",
    )


@bp.route("/p/reorder", defaults={"token": None}, methods=["POST"])
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


@bp.route("/p/gruppe/reorder", defaults={"token": None}, methods=["POST"])
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


@bp.route("/p/gruppe/neu", defaults={"token": None}, methods=["POST"])
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


@bp.route("/p/gruppe/<int:gid>/umbenennen", defaults={"token": None}, methods=["POST"])
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


@bp.route("/p/gruppe/<int:gid>/loeschen", defaults={"token": None}, methods=["POST"])
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
