"""
Admin-App – Nutzerverwaltung, App-Freischaltungen, QR-Codes.
URL-Präfix: /a/admin/<token>/
"""
import io
import re
import segno
from flask import Blueprint, render_template, request, redirect, url_for, abort, Response
from teile.kern import get_db, grant as check_grant, new_token, to_int, grant_werte, token_entschluesseln

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_farbe(value, fallback="#4a90d9"):
    value = (value or "").strip()
    return value if _HEX_RE.match(value) else fallback


def _clean_ki_limit(value, fallback=100000):
    parsed = to_int(value)
    return parsed if parsed is not None and parsed >= 0 else fallback

bp = Blueprint("admin_app", __name__)
APP = "admin"


def _admin(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    return user


def _grants_by_user(db):
    """Gibt {user_id: {app_id: token}} zurück.

    Wunsch #129: In der DB steht nur noch der verschlüsselte Token; für die
    Anzeige von Link und QR-Code wird er hier zurückgewonnen."""
    result = {}
    for row in db.execute("SELECT user_id, app_id, token_enc FROM grants"):
        result.setdefault(row["user_id"], {})[row["app_id"]] = \
            token_entschluesseln(row["token_enc"])
    return result


def _push_counts(db):
    """Gibt {user_id: Anzahl Push-Abos} zurück."""
    result = {}
    for row in db.execute("SELECT user_id, COUNT(*) AS n FROM push_abos GROUP BY user_id"):
        result[row["user_id"]] = row["n"]
    return result


@bp.route("/a/admin/<token>/")
def index(token):
    user = _admin(token)
    db   = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    apps  = db.execute("SELECT * FROM apps WHERE slug != 'home' ORDER BY id").fetchall()
    home_app_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
    grants = _grants_by_user(db)
    push_counts = _push_counts(db)
    return render_template("admin.html",
        user=user, token=token, farbe=user["farbe"],
        all_users=users, apps=apps, grants=grants,
        home_app_id=home_app_id, push_counts=push_counts,
    )


@bp.route("/a/admin/<token>/user/neu", methods=["GET", "POST"])
def user_neu(token):
    user = _admin(token)
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        farbe    = _clean_farbe(request.form.get("farbe"))
        is_admin = 1 if request.form.get("is_admin") else 0
        rolle    = request.form.get("rolle", "gast")
        if rolle not in ("eltern", "kind", "gast"):
            rolle = "gast"
        ki_token_limit = _clean_ki_limit(request.form.get("ki_token_limit"))
        if not name:
            return redirect(url_for("admin_app.user_neu", token=token))
        db = get_db()
        uid = db.execute(
            "INSERT INTO users(name,farbe,is_admin,rolle,ki_token_limit) VALUES(?,?,?,?,?) RETURNING id",
            (name, farbe, is_admin, rolle, ki_token_limit),
        ).fetchone()["id"]
        home_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
        lookup, enc = grant_werte(new_token())
        db.execute("INSERT OR IGNORE INTO grants(user_id,app_id,token_lookup,token_enc) VALUES(?,?,?,?)",
                   (uid, home_id, lookup, enc))
        db.commit()
        return redirect(url_for("admin_app.index", token=token))
    return render_template("admin_user_form.html",
        user=user, token=token, farbe=user["farbe"], edit=None)


@bp.route("/a/admin/<token>/user/<int:uid>/bearbeiten", methods=["GET", "POST"])
def user_bearbeiten(token, uid):
    user = _admin(token)
    db   = get_db()
    edit = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not edit:
        abort(404)
    if request.method == "POST":
        name     = request.form.get("name", "").strip() or edit["name"]
        farbe    = _clean_farbe(request.form.get("farbe"), edit["farbe"])
        is_admin = 1 if request.form.get("is_admin") else 0
        rolle    = request.form.get("rolle", edit["rolle"] if edit["rolle"] else "gast")
        if rolle not in ("eltern", "kind", "gast"):
            rolle = "gast"
        ki_token_limit = _clean_ki_limit(request.form.get("ki_token_limit"), edit["ki_token_limit"])
        if uid == user["id"]:
            is_admin = 1
        db.execute("UPDATE users SET name=?,farbe=?,is_admin=?,rolle=?,ki_token_limit=? WHERE id=?",
                   (name, farbe, is_admin, rolle, ki_token_limit, uid))
        db.commit()
        return redirect(url_for("admin_app.index", token=token))
    return render_template("admin_user_form.html",
        user=user, token=token, farbe=user["farbe"], edit=edit)


@bp.route("/a/admin/<token>/user/<int:uid>/grant/<app_slug>", methods=["POST"])
def grant_app(token, uid, app_slug):
    _admin(token)
    db  = get_db()
    app = db.execute("SELECT id FROM apps WHERE slug=?", (app_slug,)).fetchone()
    if app:
        lookup, enc = grant_werte(new_token())
        db.execute("INSERT OR IGNORE INTO grants(user_id,app_id,token_lookup,token_enc) VALUES(?,?,?,?)",
                   (uid, app["id"], lookup, enc))
        db.commit()
    return redirect(url_for("admin_app.index", token=token))


@bp.route("/a/admin/<token>/user/<int:uid>/revoke/<app_slug>", methods=["POST"])
def revoke_app(token, uid, app_slug):
    admin = _admin(token)
    # Nicht den eigenen admin-Grant entziehen
    if uid == admin["id"] and app_slug == "admin":
        return redirect(url_for("admin_app.index", token=token))
    db = get_db()
    db.execute("""
        DELETE FROM grants
        WHERE user_id=? AND app_id=(SELECT id FROM apps WHERE slug=?)
    """, (uid, app_slug))
    db.commit()
    return redirect(url_for("admin_app.index", token=token))


@bp.route("/a/admin/<token>/user/<int:uid>/neue_tokens", methods=["POST"])
def neue_tokens(token, uid):
    """Wunsch #131: Alle Zugänge eines Nutzers in einem Rutsch neu erzeugen.

    Der Notfallknopf für "Handy weg" oder "Link versehentlich weitergegeben".
    Vorher musste man je App einzeln entziehen und neu vergeben - bei zehn
    Apps zehn Klickpaare, und man übersah leicht eine. Alle alten Adressen
    dieses Nutzers sind danach sofort ungültig; er braucht einen neuen Link
    bzw. QR-Code.

    Bewusst NUR für die Grants dieses einen Nutzers - andere Familien-
    mitglieder behalten ihre Zugänge."""
    admin = _admin(token)
    db = get_db()

    grants = db.execute("SELECT id FROM grants WHERE user_id=?", (uid,)).fetchall()
    for g in grants:
        lookup, enc = grant_werte(new_token())
        db.execute("UPDATE grants SET token_lookup=?, token_enc=? WHERE id=?",
                   (lookup, enc, g["id"]))
    db.commit()

    # Erneuert der Admin seine EIGENEN Zugänge, ist der Token in der aktuellen
    # Adresszeile mit erneuert worden - eine Weiterleitung dorthin liefe ins
    # Leere (403). Deshalb auf die neue Admin-Adresse umleiten.
    if uid == admin["id"]:
        neuer_admin_token = token_entschluesseln(db.execute("""
            SELECT g.token_enc FROM grants g JOIN apps a ON a.id = g.app_id
            WHERE g.user_id=? AND a.slug='admin'
        """, (uid,)).fetchone()["token_enc"])
        return redirect(url_for("admin_app.index", token=neuer_admin_token))

    return redirect(url_for("admin_app.index", token=token) + f"#user-{uid}")


@bp.route("/a/admin/<token>/user/<int:uid>/qr.svg")
def qr_svg(token, uid):
    _admin(token)
    db = get_db()
    row = db.execute("""
        SELECT g.token_enc FROM grants g
        JOIN apps a ON a.id = g.app_id
        WHERE g.user_id=? AND a.slug='home'
    """, (uid,)).fetchone()
    if not row:
        abort(404)
    url = f"https://portal.16schwaben.de/p/{token_entschluesseln(row['token_enc'])}"
    qr  = segno.make(url, error="M")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", omitsize=True, border=2,
            svgclass=None, lineclass=None, xmldecl=False, nl=False)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


def init_app(app):
    app.register_blueprint(bp)
