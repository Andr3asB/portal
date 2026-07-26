"""
✨ Verbesserungswünsche – gemeinsamer Endpunkt für alle Apps.

POST /wunsch  { text, app, token }
  → Speichert Wunsch; token identifiziert den Nutzer (beliebige App).
  → Ohne gültigen Token: anonymer Eintrag.
"""
from flask import Blueprint, request, jsonify
from teile.kern import get_db

bp = Blueprint("werkstatt", __name__)


@bp.route("/wunsch", methods=["POST"])
def wunsch():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="Kein Text"), 400

    token    = (data.get("token") or "").strip()
    app_slug = (data.get("app")   or "").strip() or None

    db = get_db()

    # Nutzer über beliebiges gültiges Token ermitteln
    user_id = None
    if token:
        row = db.execute("""
            SELECT u.id FROM grants g JOIN users u ON u.id = g.user_id
            WHERE g.token = ?
        """, (token,)).fetchone()
        if row:
            user_id = row["id"]

    db.execute(
        "INSERT INTO wuensche(text, user_id, app_slug) VALUES(?,?,?)",
        (text, user_id, app_slug),
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
