from flask import Blueprint, request, jsonify, abort
from teile.kern import get_db

bp = Blueprint("settings", __name__)


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
