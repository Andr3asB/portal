"""
✨ Verbesserungswünsche – gemeinsamer Endpunkt für alle Apps.

POST /wunsch  { text, app, token, pfad }
  → Speichert Wunsch; token identifiziert den Nutzer (beliebige App).
  → Ohne gültigen Token: anonymer Eintrag.
  → pfad (window.location.pathname) wird zu "app_slug/unterseite" verdichtet
    und token-frei als ansicht gespeichert (Wunsch #47: merken, in welcher
    Ansicht ein Vorschlag eingegeben wurde – ohne das Token in der für
    Admins sichtbaren Werkstatt-Liste zu leaken).
"""
import re
from flask import Blueprint, request, jsonify
from teile.kern import get_db, token_lookup, aktueller_nutzer

bp = Blueprint("werkstatt", __name__)

_PFAD_RE = re.compile(r"^/a/([a-z0-9_-]+)/[^/]+(/.*)?$")


def _ansicht_aus_pfad(pfad):
    if not pfad:
        return None
    m = _PFAD_RE.match(pfad)
    if not m:
        return None
    slug, rest = m.group(1), (m.group(2) or "").strip("/")
    return f"{slug}/{rest}" if rest else slug


@bp.route("/wunsch", methods=["POST"])
def wunsch():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="Kein Text"), 400

    token    = (data.get("token") or "").strip()
    app_slug = (data.get("app")   or "").strip() or None
    ansicht  = _ansicht_aus_pfad((data.get("pfad") or "").strip()) or app_slug

    db = get_db()

    # Nutzer über beliebiges gültiges Token ermitteln - oder, auf token-freien
    # Seiten (Wunsch #140, Stufe 4), über das Sitzungs-Cookie. Ohne Nutzer wird
    # der Wunsch bewusst trotzdem gespeichert, nur ohne Urheber: ein anonymer
    # Wunsch ist besser als ein verlorener.
    row = aktueller_nutzer(token)
    user_id = row["id"] if row else None

    db.execute(
        "INSERT INTO wuensche(text, user_id, app_slug, ansicht) VALUES(?,?,?,?)",
        (text, user_id, app_slug, ansicht),
    )
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
