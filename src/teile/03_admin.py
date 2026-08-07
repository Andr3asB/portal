"""
Admin-App – Nutzerverwaltung, App-Freischaltungen, QR-Codes.
URL-Präfix: /a/admin/<token>/

Wunsch #140, Stufe 6: In der Datenbank steht nur noch der HMAC eines Tokens,
nicht mehr der Klartext. Diese Seite kann einen Zugangslink deshalb NICHT mehr
nachschlagen - sie zeigt ihn ausschliesslich in dem einen Moment an, in dem er
entsteht (`zugang_zeigen()`): beim Anlegen eines Nutzers und bei "Zugänge neu
erzeugen" (Wunsch #131). Wer seinen Link verliert, bekommt einen neuen; ein
alter lässt sich nicht mehr hervorholen. Genau das war das Ziel - vorher
rendete diese Seite alle Zugänge der ganzen Familie im Klartext, und der
Service Worker cachte sie mit.
"""
import base64
import io
import re
import segno
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, to_int, grant_anlegen, token_lookup, new_token

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
    """Gibt {user_id: set(app_id)} zurück - WELCHE Apps freigeschaltet sind.

    Wunsch #140, Stufe 6: früher stand hier {user_id: {app_id: token}} und die
    Seite rendete jeden Zugangslink der ganzen Familie im Klartext. Den Token
    gibt es nicht mehr zurückzugewinnen, und die Oberfläche braucht ihn auch
    nicht: für die Grant-Chips zählt nur, OB ein Grant existiert."""
    result = {}
    for row in db.execute("SELECT user_id, app_id FROM grants"):
        result.setdefault(row["user_id"], set()).add(row["app_id"])
    return result


def _zugang_anzeigen(user, token, kind_name: str, klartext: str, hinweis: str):
    """Die einzige Stelle, an der ein Zugangslink je zu sehen ist.

    Wunsch #140, Stufe 6: Der Klartext existiert nur in diesem Request. Der
    QR-Code wird deshalb direkt hier erzeugt und als `data:`-URI eingebettet -
    eine eigene `/qr.svg`-Route (wie bis Stufe 5) müsste den Token erneut aus
    der Datenbank holen, und genau das geht nicht mehr. Die CSP erlaubt
    `img-src 'self' data:` (siehe 21_csp.py), das Bild trägt also.

    Bewusst KEIN Redirect danach: Ein Redirect müsste den Token weiterreichen -
    über die Adresszeile (landet im Verlauf, das wollten wir gerade abschaffen)
    oder über die Flask-Session (schriebe ihn in ein Cookie). Die Antwort auf
    den POST selbst ist der einzige Ort, an dem er niemandem sonst begegnet."""
    url = f"https://portal.16schwaben.de/p/{klartext}"
    puffer = io.BytesIO()
    segno.make(url, error="M").save(
        puffer, kind="svg", scale=6, border=2, xmldecl=False, nl=False)
    qr_data_uri = "data:image/svg+xml;base64," + \
        base64.b64encode(puffer.getvalue()).decode()
    return render_template("admin_zugang.html",
        user=user, token=token, farbe=user["farbe"],
        kind_name=kind_name, url=url, qr_data_uri=qr_data_uri, hinweis=hinweis)


def _push_counts(db):
    """Gibt {user_id: Anzahl Push-Abos} zurück."""
    result = {}
    for row in db.execute("SELECT user_id, COUNT(*) AS n FROM push_abos GROUP BY user_id"):
        result[row["user_id"]] = row["n"]
    return result


@bp.route("/a/admin/", defaults={"token": None})
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


@bp.route("/a/admin/user/neu", defaults={"token": None}, methods=["GET", "POST"])
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
        ki_tts_zeichen_limit = _clean_ki_limit(request.form.get("ki_tts_zeichen_limit"), 50000)
        if not name:
            return redirect(url_for("admin_app.user_neu", token=token))
        db = get_db()
        uid = db.execute(
            "INSERT INTO users(name,farbe,is_admin,rolle,ki_token_limit,ki_tts_zeichen_limit) "
            "VALUES(?,?,?,?,?,?) RETURNING id",
            (name, farbe, is_admin, rolle, ki_token_limit, ki_tts_zeichen_limit),
        ).fetchone()["id"]
        home_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
        klartext = grant_anlegen(db, uid, home_id)
        db.commit()
        # Wunsch #140, Stufe 6: Der Link des neuen Nutzers ist JETZT zu sehen -
        # oder nie wieder. Deshalb kein Redirect auf die Übersicht.
        return _zugang_anzeigen(
            user, token, name, klartext,
            f"{name} wurde angelegt. Das ist der persönliche Zugang – "
            "jetzt weitergeben oder scannen lassen.")
    return render_template("admin_user_form.html",
        user=user, token=token, farbe=user["farbe"], edit=None)


@bp.route("/a/admin/user/<int:uid>/bearbeiten", defaults={"token": None}, methods=["GET", "POST"])
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
        ki_tts_zeichen_limit = _clean_ki_limit(
            request.form.get("ki_tts_zeichen_limit"), edit["ki_tts_zeichen_limit"])
        if uid == user["id"]:
            is_admin = 1
        db.execute(
            "UPDATE users SET name=?,farbe=?,is_admin=?,rolle=?,ki_token_limit=?,"
            "ki_tts_zeichen_limit=? WHERE id=?",
            (name, farbe, is_admin, rolle, ki_token_limit, ki_tts_zeichen_limit, uid))
        db.commit()
        return redirect(url_for("admin_app.index", token=token))
    return render_template("admin_user_form.html",
        user=user, token=token, farbe=user["farbe"], edit=edit)


@bp.route("/a/admin/user/<int:uid>/grant/<app_slug>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/admin/<token>/user/<int:uid>/grant/<app_slug>", methods=["POST"])
def grant_app(token, uid, app_slug):
    _admin(token)
    db  = get_db()
    app = db.execute("SELECT id FROM apps WHERE slug=?", (app_slug,)).fetchone()
    if app:
        # Der Klartext wird bewusst verworfen: Seit Stufe 4 verlinkt nichts
        # mehr auf eine App-eigene Adresse - der Nutzer kommt über seinen
        # Home-Zugang bzw. das Sitzungs-Cookie in jede freigeschaltete App.
        grant_anlegen(db, uid, app["id"])
        db.commit()
    return redirect(url_for("admin_app.index", token=token))


@bp.route("/a/admin/user/<int:uid>/revoke/<app_slug>", defaults={"token": None}, methods=["POST"])
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


@bp.route("/a/admin/user/<int:uid>/neue_tokens", defaults={"token": None}, methods=["POST"])
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

    ziel = db.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    if not ziel:
        abort(404)

    # Wunsch #140, Stufe 6: Jeder Grant bekommt einen neuen Token; nur der des
    # HOME-Grants wird aufgehoben, denn nur der wird als Link/QR gebraucht.
    home_id = db.execute("SELECT id FROM apps WHERE slug='home'").fetchone()["id"]
    neuer_home_token = None
    for g in db.execute("SELECT id, app_id FROM grants WHERE user_id=?", (uid,)).fetchall():
        klartext = new_token()
        db.execute("UPDATE grants SET token_lookup=? WHERE id=?",
                   (token_lookup(klartext), g["id"]))
        if g["app_id"] == home_id:
            neuer_home_token = klartext
    # Wunsch #140: Ohne diese Zeile wäre der Widerruf ab Stufe 3 wirkungslos -
    # das alte Gerät käme über sein Sitzungs-Cookie weiter rein, obwohl der
    # Token erneuert wurde. Steht hier schon ab Stufe 1, damit es nicht
    # vergessen wird, wenn es zählt.
    db.execute("DELETE FROM sitzungen WHERE user_id=?", (uid,))
    db.commit()

    # Hat der Nutzer (aus welchem Grund auch immer) keinen Home-Grant, gibt es
    # auch keinen Link zu zeigen - dann zurück zur Übersicht statt einer
    # leeren Zugangsseite.
    if not neuer_home_token:
        return redirect(url_for("admin_app.index", token=token) + f"#user-{uid}")

    # Sonderfall eigener Zugang: Die eigene Sitzung wurde eben gelöscht. Das
    # ist unkritisch - `grant()` hat zu Beginn dieses Requests bereits
    # `sitzung_vormerken()` aufgerufen, `19_sitzung.py` stellt am Ende der
    # Antwort also ein frisches Cookie aus. Dieses Gerät bleibt drin, alle
    # anderen sind draußen. Genau das soll der Notfallknopf leisten.
    hinweis = (
        "Alle bisherigen Links und QR-Codes sind ab sofort ungültig. "
        f"Das hier ist der neue Zugang für {ziel['name']}."
    )
    if uid == admin["id"]:
        hinweis += (" Dieses Gerät bleibt angemeldet – alle anderen Geräte "
                    "müssen den neuen Zugang einmal öffnen.")
    return _zugang_anzeigen(admin, token, ziel["name"], neuer_home_token, hinweis)


def init_app(app):
    app.register_blueprint(bp)
