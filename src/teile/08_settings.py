from flask import Blueprint, request, jsonify, abort, make_response
from teile.kern import get_db

bp = Blueprint("settings", __name__)


@bp.route("/manifest/<token>.json")
def manifest_json(token):
    db  = get_db()
    row = db.execute(
        "SELECT u.farbe FROM users u"
        " JOIN grants g ON g.user_id=u.id"
        " JOIN apps   a ON a.id=g.app_id"
        " WHERE g.token=? AND a.slug='home'",
        (token,),
    ).fetchone()
    if not row:
        abort(404)
    data = jsonify({
        "name":             "Familienportal",
        "short_name":       "Portal",
        "start_url":        f"/p/{token}",
        "scope":            "/",
        "display":          "standalone",
        "background_color": "#f5f5f7",
        "theme_color":      row["farbe"],
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })
    data.headers["Content-Type"] = "application/manifest+json"
    return data


@bp.route("/settings/darkmode", methods=["POST"])
def toggle_darkmode():
    data  = request.get_json(silent=True) or {}
    token = data.get("token", "")
    if not token:
        abort(400)
    db  = get_db()
    row = db.execute(
        "SELECT u.id, u.dark_mode FROM users u JOIN grants g ON g.user_id=u.id WHERE g.token=?",
        (token,),
    ).fetchone()
    if not row:
        abort(403)
    new_val = 0 if row["dark_mode"] else 1
    db.execute("UPDATE users SET dark_mode=? WHERE id=?", (new_val, row["id"]))
    db.commit()
    return jsonify(ok=True, dark=bool(new_val))


def init_app(app):
    app.register_blueprint(bp)
