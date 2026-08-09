from flask import Blueprint, request, jsonify, abort, make_response
from teile.kern import get_db, token_lookup, aktueller_nutzer, start_pfad

bp = Blueprint("settings", __name__)


@bp.route("/manifest.json", defaults={"token": None})
@bp.route("/manifest/<token>.json")
def manifest_json(token):
    """Wunsch #140, Stufe 4: `/manifest.json` ohne Token in der Adresse.

    Das Manifest ist pro Nutzer personalisiert (Farbe, Startadresse), hängt
    token-frei also am Sitzungs-Cookie. Der Haken: Der Browser holt das
    Manifest standardmäßig OHNE Cookies - ohne
    `crossorigin="use-credentials"` am <link> in base.html käme hier ein 404
    an und die PWA verlöre Namen, Farbe und Startadresse."""
    db = get_db()
    if token:
        row = db.execute(
            "SELECT u.farbe FROM users u"
            " JOIN grants g ON g.user_id=u.id"
            " JOIN apps   a ON a.id=g.app_id"
            " WHERE g.token_lookup=? AND a.slug='home'",
            (token_lookup(token),),
        ).fetchone()
    else:
        row = aktueller_nutzer()
    if not row:
        abort(404)
    data = jsonify({
        "name":             "Familienportal",
        "short_name":       "Portal",
        # `/start` (Cookie) oder `/p/<token>` - entscheidet der Schalter
        # TOKENFREIE_URLS, dieselbe Quelle wie für alle anderen Adressen.
        # Steht er auf 0, bekommt auch eine schon installierte PWA wieder
        # ihren alten, personalisierten Einstieg.
        "start_url":        start_pfad(token),
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
    data = request.get_json(silent=True) or {}
    # Wunsch #140, Stufe 4: Auf token-freien Seiten ist `TOKEN` im Javascript
    # leer - dann zählt das Sitzungs-Cookie. Deshalb hier KEIN abort(400) mehr
    # bei fehlendem Token; das würde den Dark-Mode-Schalter still lahmlegen.
    row = aktueller_nutzer(data.get("token", ""))
    if not row:
        abort(403)
    db = get_db()
    # Wunsch #172: drei Zustaende im Kreis - 2 (wie das Geraet) -> 0 (immer
    # hell) -> 1 (immer dunkel) -> 2. Die Automatik steht bewusst am Anfang
    # des Kreises: Sie ist der Normalfall, die beiden anderen sind bewusste
    # Uebersteuerungen.
    naechster = {2: 0, 0: 1, 1: 2}
    neu = naechster.get(row["dark_mode"], 0)
    db.execute("UPDATE users SET dark_mode=? WHERE id=?", (neu, row["id"]))
    db.commit()
    # `dark` bleibt fuer aeltere PWA-Staende im Cache erhalten, die noch das
    # alte Feld auswerten - fuer sie sieht "wie das Geraet" wie "hell" aus,
    # was der harmlosere der beiden moeglichen Irrtuemer ist.
    return jsonify(ok=True, modus=neu, dark=(neu == 1))


def init_app(app):
    app.register_blueprint(bp)
