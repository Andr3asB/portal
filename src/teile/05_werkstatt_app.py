"""
Werkstatt-App – Übersicht und Verwaltung aller Verbesserungswünsche.
URL-Präfix: /a/werkstatt/<token>/

Die Erfassung selbst läuft über 02_werkstatt.py (POST /wunsch).

WICHTIGE REGEL (Wunsch #61): Wünsche mit prioritaet='zurueckgestellt'
dürfen NIEMALS automatisiert umgesetzt werden – auch nicht, wenn die
Anweisung lautet "implementiere alle Wünsche" oder ähnlich pauschal
formuliert ist. Diese Regel gilt uneingeschränkt für jede KI, die an
diesem Projekt arbeitet. Ein Admin muss die Priorität eines
zurückgestellten Wunsches erst ändern, bevor er umgesetzt werden darf.
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant

bp  = Blueprint("werkstatt_app", __name__)
APP = "werkstatt"

_PRIORITAETEN = ("niedrig", "mittel", "hoch", "sehr_hoch", "zurueckgestellt")

_PRIO_ORDER = """
    CASE w.prioritaet
        WHEN 'sehr_hoch'       THEN 1
        WHEN 'hoch'            THEN 2
        WHEN 'mittel'          THEN 3
        WHEN 'niedrig'         THEN 4
        WHEN 'zurueckgestellt' THEN 6
        ELSE 5
    END ASC, w.erstellt DESC
"""

_SELECT = """
    SELECT w.id, w.text, w.titel, w.prioritaet, w.app_slug, w.ansicht,
           w.erstellt, w.erledigt, w.erledigt_am,
           u.name AS urheber_name, u.farbe AS urheber_farbe
    FROM   wuensche w
    LEFT JOIN users u ON u.id = w.user_id
"""


@bp.route("/a/werkstatt/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    offen = db.execute(
        _SELECT + " WHERE w.erledigt = 0 ORDER BY " + _PRIO_ORDER
    ).fetchall()
    erledigt = db.execute(
        _SELECT + " WHERE w.erledigt = 1 ORDER BY COALESCE(w.erledigt_am, w.erstellt) DESC"
    ).fetchall()
    return render_template("werkstatt_app.html",
        user=user, token=token, farbe=user["farbe"],
        offen=offen, erledigt=erledigt,
    )


@bp.route("/a/werkstatt/<token>/erledigt/<int:wid>", methods=["POST"])
def toggle_erledigt(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    row = db.execute("SELECT erledigt FROM wuensche WHERE id=?", (wid,)).fetchone()
    if not row:
        abort(404)
    if row["erledigt"]:
        db.execute("UPDATE wuensche SET erledigt=0, erledigt_am=NULL WHERE id=?", (wid,))
    else:
        db.execute(
            "UPDATE wuensche SET erledigt=1, erledigt_am=CURRENT_TIMESTAMP WHERE id=?", (wid,)
        )
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


@bp.route("/a/werkstatt/<token>/prioritaet/<int:wid>", methods=["POST"])
def prioritaet(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    prio = request.form.get("prioritaet", "")
    if prio not in _PRIORITAETEN:
        prio = None
    db = get_db()
    if not db.execute("SELECT id FROM wuensche WHERE id=?", (wid,)).fetchone():
        abort(404)
    db.execute("UPDATE wuensche SET prioritaet=? WHERE id=?", (prio, wid))
    db.commit()
    return redirect(url_for("werkstatt_app.index", token=token))


@bp.route("/a/werkstatt/<token>/titel/<int:wid>", methods=["POST"])
def titel_setzen(token, wid):
    """Endpunkt für Claude: setzt einen KI-generierten Titel (max. 80 Zeichen)."""
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    data = request.get_json(silent=True) or {}
    titel = str(data.get("titel", "")).strip()[:80]
    if not titel:
        abort(400)
    db = get_db()
    if not db.execute("SELECT id FROM wuensche WHERE id=?", (wid,)).fetchone():
        abort(404)
    db.execute("UPDATE wuensche SET titel=? WHERE id=?", (titel, wid))
    db.commit()
    return {"ok": True}


def init_app(app):
    app.register_blueprint(bp)
