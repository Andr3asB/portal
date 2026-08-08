"""
✨ Verbesserungswünsche – gemeinsamer Endpunkt für alle Apps.

POST /wunsch  { text, app, token, pfad, prioritaet }
  → Speichert Wunsch; token identifiziert den Nutzer (beliebige App).
  → Ohne gültigen Token: anonymer Eintrag.
  → prioritaet (Wunsch #152) wird NUR von einem Admin übernommen und nur,
    wenn sie in WUNSCH_PRIORITAETEN steht. Bei allen anderen bleibt sie NULL
    wie bisher – die Prüfung steht hier serverseitig und nicht bloß im
    Template, sonst genügte ein selbstgebauter POST, um einen fremden Wunsch
    an die Spitze der Liste zu setzen.
  → pfad (window.location.pathname) wird zu "app_slug/unterseite" verdichtet
    und token-frei als ansicht gespeichert (Wunsch #47: merken, in welcher
    Ansicht ein Vorschlag eingegeben wurde – ohne das Token in der für
    Admins sichtbaren Werkstatt-Liste zu leaken).
"""
import re
import threading

from flask import Blueprint, current_app, request, jsonify
from teile.kern import (get_db, token_lookup, aktueller_nutzer, new_db,
                        ki_anfrage, WUNSCH_PRIORITAETEN)

bp = Blueprint("werkstatt", __name__)

_PFAD_RE = re.compile(r"^/a/([a-z0-9_-]+)/[^/]+(/.*)?$")


_TITEL_SYSTEM = (
    "Du formulierst aus einem Verbesserungswunsch fuer eine private "
    "Familien-Web-App eine kurze Ueberschrift auf Deutsch. Antworte "
    "AUSSCHLIESSLICH mit der Ueberschrift, ohne Anfuehrungszeichen, ohne "
    "Punkt am Ende, hoechstens 60 Zeichen."
)
_TITEL_MAX = 80


def _titel_nachtragen(app, wunsch_id: int, user_id: int, text: str):
    """Wunsch #161: Ueberschrift per KI - im Hintergrund.

    Laeuft bewusst in einem eigenen Thread mit eigener Verbindung (`new_db`),
    aus zwei Gruenden:

    1. Der Wunsch ist bereits gespeichert, wenn dieser Thread startet. Faellt
       OpenRouter aus, ist das Kontingent leer oder antwortet das Modell
       Unsinn, bleibt der Wunsch einfach ohne Titel - genau wie vorher. Ein
       KI-Ausfall darf das Eintragen nie mitreissen; der Wunsch selbst ist das
       Wertvolle, der Titel ist Beiwerk.
    2. Der Nutzer wartet nicht auf die KI. Der ✨-Dialog schliesst sofort.

    `g.db` aus einem Thread anzufassen gaebe "Cannot operate on a closed
    database" - dieselbe Lehre wie bei push_send().
    """
    def arbeiten():
        with app.app_context():
            try:
                titel = ki_anfrage(user_id, "wunsch_titel", _TITEL_SYSTEM,
                                   text[:2000], max_tokens=40)
            except Exception as fehler:            # KiLimitError, KiFehler, Netz
                app.logger.info("Kein KI-Titel fuer Wunsch %s: %s", wunsch_id, fehler)
                return
            # Modelle liefern die Ueberschrift gern in Anfuehrungszeichen und
            # manchmal mit Zeilenumbruch - beides hier abraeumen.
            titel = " ".join((titel or "").split())
            titel = titel.strip("\"'„“»« ")[:_TITEL_MAX]
            if not titel:
                return
            with new_db() as db:
                # Nur setzen, wenn immer noch keiner da ist: In der Zwischenzeit
                # kann ein Admin von Hand einen Titel vergeben haben, und der
                # hat Vorrang vor der Maschine.
                db.execute(
                    "UPDATE wuensche SET titel=? WHERE id=? AND (titel IS NULL OR titel='')",
                    (titel, wunsch_id))
                db.commit()

    threading.Thread(target=arbeiten, daemon=True).start()


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

    # Wunsch #152: Nur Admins duerfen beim Anlegen priorisieren. Ein
    # unbekannter oder unerlaubter Wert wird still zu NULL - der Wunsch geht
    # dabei NICHT verloren, denn ein verworfener Vorschlag waere der
    # schlechtere Ausgang als eine fehlende Priorität.
    prio = (data.get("prioritaet") or "").strip()
    if not (row and row["is_admin"] and prio in WUNSCH_PRIORITAETEN):
        prio = None

    zeile = db.execute(
        "INSERT INTO wuensche(text, user_id, app_slug, ansicht, prioritaet) "
        "VALUES(?,?,?,?,?) RETURNING id",
        (text, user_id, app_slug, ansicht, prio),
    ).fetchone()
    db.commit()

    # Wunsch #161: Ueberschrift nachtragen lassen. Erst NACH dem commit, damit
    # der Thread den Wunsch auch findet, und nur mit bekanntem Nutzer - das
    # KI-Kontingent haengt an einer Person.
    if user_id and current_app.config.get("OPENROUTER_API_KEY"):
        _titel_nachtragen(current_app._get_current_object(), zeile["id"], user_id, text)

    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
