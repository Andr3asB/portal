"""
Admin-App – Nutzerverwaltung, App-Freischaltungen, QR-Codes.
URL-Präfix: /a/admin/<token>/
"""
import io
import segno
from flask import Blueprint, render_template, request, redirect, url_for, abort, Response
from teile.kern import get_db, grant as check_grant, new_token

bp = Blueprint("admin_app", __name__)
APP = "admin"


def _admin(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    return user


def _grants_by_user(db):
    """Gibt {user_id: {app_id: token}} zurück."""
    result = {}
    for row in db.execute("SELECT user_id, app_id, token FROM grants"):
        result.setdefault(row["user_id"], {})[row["app_id"]] = row["token"]
    return result


@bp.route("/a/admin/<token>/")
def index(token):
    user = _admin(token)
    db   = get_db()
    users = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    apps  = db.execute("SELECT * FROM apps WHERE slug != 'home' ORDER BY id").fetchall()
    home_app_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
    grants = _grants_by_user(db)
    return render_template("admin.html",
        user=user, token=token, farbe=user["farbe"],
        all_users=users, apps=apps, grants=grants,
        home_app_id=home_app_id,
    )


@bp.route("/a/admin/<token>/user/neu", methods=["GET", "POST"])
def user_neu(token):
    user = _admin(token)
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        farbe    = request.form.get("farbe", "#4a90d9").strip()
        is_admin = 1 if request.form.get("is_admin") else 0
        if not name:
            return redirect(url_for("admin_app.user_neu", token=token))
        db = get_db()
        uid = db.execute(
            "INSERT INTO users(name,farbe,is_admin) VALUES(?,?,?) RETURNING id",
            (name, farbe, is_admin),
        ).fetchone()["id"]
        home_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
        db.execute("INSERT OR IGNORE INTO grants(user_id,app_id,token) VALUES(?,?,?)",
                   (uid, home_id, new_token()))
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
        farbe    = request.form.get("farbe", edit["farbe"]).strip()
        is_admin = 1 if request.form.get("is_admin") else 0
        # Nicht den eigenen Admin-Status wegnehmen
        if uid == user["id"]:
            is_admin = 1
        db.execute("UPDATE users SET name=?,farbe=?,is_admin=? WHERE id=?",
                   (name, farbe, is_admin, uid))
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
        db.execute("INSERT OR IGNORE INTO grants(user_id,app_id,token) VALUES(?,?,?)",
                   (uid, app["id"], new_token()))
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


@bp.route("/a/admin/<token>/user/<int:uid>/qr.svg")
def qr_svg(token, uid):
    _admin(token)
    db = get_db()
    row = db.execute("""
        SELECT g.token FROM grants g
        JOIN apps a ON a.id = g.app_id
        WHERE g.user_id=? AND a.slug='home'
    """, (uid,)).fetchone()
    if not row:
        abort(404)
    url = f"https://portal.16schwaben.de/p/{row['token']}"
    qr  = segno.make(url, error="M")
    buf = io.StringIO()
    qr.save(buf, kind="svg", omitsize=True, border=2,
            svgclass=None, lineclass=None, xmldecl=False, nl=False)
    return Response(buf.getvalue(), mimetype="image/svg+xml")


def init_app(app):
    app.register_blueprint(bp)
