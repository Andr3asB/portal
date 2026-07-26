"""
Werkstatt-App – Übersicht und Verwaltung aller Verbesserungswünsche.
URL-Präfix: /a/werkstatt/<token>/

Die Erfassung selbst läuft über 02_werkstatt.py (POST /wunsch).
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant

bp  = Blueprint("werkstatt_app", __name__)
APP = "werkstatt"


@bp.route("/a/werkstatt/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    wuensche = db.execute("""
        SELECT w.*, u.name AS urheber_name, u.farbe AS urheber_farbe
        FROM   wuensche w
        LEFT JOIN users u ON u.id = w.user_id
        ORDER  BY w.erledigt ASC, w.erstellt DESC
    """).fetchall()
    return render_template("werkstatt_app.html",
        user=user, token=token, farbe=user["farbe"],
        wuensche=wuensche,
    )


@bp.route("/a/werkstatt/<token>/erledigt/<int:wid>", methods=["POST"])
def erledigt(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    row = db.execute("SELECT erledigt FROM wuensche WHERE id=?", (wid,)).fetchone()
    if not row:
        abort(404)
    db.execute("UPDATE wuensche SET erledigt=? WHERE id=?",
               (0 if row["erledigt"] else 1, wid))
    db.commit()
    return redirect(url_for("werkstatt_app.index", token=token))


@bp.route("/a/werkstatt/<token>/loeschen/<int:wid>", methods=["POST"])
def loeschen(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM wuensche WHERE id=?", (wid,))
    db.commit()
    return redirect(url_for("werkstatt_app.index", token=token))


def init_app(app):
    app.register_blueprint(bp)
