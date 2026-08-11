"""
Push-Benachrichtigungen – Subscription-Management.

GET  /push/vapid-public-key  → {"key": "<base64url>"}
POST /push/subscribe         → {"subscription":{...}, "token":"...", "geraet":"iPhone"}
POST /push/unsubscribe       → {"endpoint":"...", "token":"..."}
"""
from flask import Blueprint, jsonify, request, current_app, abort
from teile.kern import (get_db, grant as check_grant, token_lookup, aktueller_nutzer,
                        ist_oeffentliche_url)

bp = Blueprint("push", __name__)


@bp.route("/push/vapid-public-key")
def vapid_public_key():
    key = current_app.config.get("VAPID_PUBLIC_KEY", "")
    if not key:
        return jsonify(key=None), 503
    return jsonify(key=key)


@bp.route("/push/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    sub   = data.get("subscription") or {}
    geraet = (data.get("geraet") or "").strip()[:80]

    endpoint = (sub.get("endpoint") or "").strip()
    p256dh   = ((sub.get("keys") or {}).get("p256dh") or "").strip()
    auth     = ((sub.get("keys") or {}).get("auth")   or "").strip()

    # Wunsch #140, Stufe 4: Der Token darf fehlen (token-freie Seite), die
    # Abo-Daten nicht - ohne sie gäbe es nichts zu speichern.
    if not (endpoint and p256dh and auth):
        return jsonify(ok=False, error="Ungültige Anfrage"), 400

    # Wunsch #203 (Sicherheitsaudit 11.08.2026): `endpoint` kommt vollstaendig
    # vom Client - ohne diese Pruefung koennte er auf eine interne Adresse
    # zeigen (z. B. einen anderen Container im Bridge-Netz), und push_send()
    # wuerde spaeter serverseitig dorthin POSTen, ausgeloest durch ein ganz
    # gewoehnliches Ereignis (neue Aufgabe, Rueckfrage, Geburtstag). Dieselbe
    # Pruefung wie beim Rezept-Import (Wunsch #127), nur hier ohne DNS-
    # Rebinding-Pinning: Push-Zustellungen laufen ausschliesslich ueber die
    # `pywebpush`-Bibliothek, die die IP selbst zum Zeitpunkt des Versands
    # aufloest - das Pinning aus 11_rezepte.py laesst sich hier nicht
    # wiederverwenden, ohne pywebpush selbst zu veraendern. Die Pruefung HIER,
    # beim Registrieren, schliesst trotzdem den eigentlichen Weg: ohne sie
    # kaeme eine interne Adresse gar nicht erst in die Datenbank.
    if not ist_oeffentliche_url(endpoint):
        return jsonify(ok=False, error="Ungültige Anfrage"), 400

    # Nutzer über irgendein gültiges Token oder das Sitzungs-Cookie
    db  = get_db()
    row = aktueller_nutzer(token)
    if not row:
        abort(403)
    user_id = row["id"]

    db.execute("""
        INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet)
        VALUES (?,?,?,?,?)
        ON CONFLICT(endpoint) DO UPDATE
          SET p256dh=excluded.p256dh, auth=excluded.auth, geraet=excluded.geraet
    """, (user_id, endpoint, p256dh, auth, geraet))
    db.commit()
    return jsonify(ok=True)


@bp.route("/push/unsubscribe", methods=["POST"])
def unsubscribe():
    data     = request.get_json(silent=True) or {}
    token    = (data.get("token")    or "").strip()
    endpoint = (data.get("endpoint") or "").strip()

    if not endpoint:
        return jsonify(ok=False), 400

    db  = get_db()
    row = aktueller_nutzer(token)
    if not row:
        abort(403)

    db.execute("DELETE FROM push_abos WHERE endpoint=? AND user_id=?",
               (endpoint, row["id"]))
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
