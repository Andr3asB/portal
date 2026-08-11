"""
✨ Verbesserungswünsche – gemeinsamer Endpunkt für alle Apps.

POST /wunsch  { text, app, token, pfad, prioritaet }
  → Speichert Wunsch; token identifiziert den Nutzer (beliebige App), oder -
    auf token-freien Seiten - das Sitzungs-Cookie.
  → Wunsch #204 (Sicherheitsaudit 11.08.2026): Vorher wurde OHNE erkennbare
    Identität (weder Token noch Cookie) trotzdem gespeichert, nur ohne
    Urheber ("ein anonymer Wunsch ist besser als ein verlorener"). Das gibt
    es nicht mehr - seither 403 ohne Identität, und jeder gespeicherte Wunsch
    hat damit IMMER einen echten Urheber. Die ✨-Schaltfläche steht nur
    Nutzern zur Verfügung, die grant() für IRGENDEINE App bereits durchlaufen
    haben - und die haben spätestens dann ein Sitzungs-Cookie (Wunsch #140,
    Stufe 1 stellt es bei jeder erfolgreichen Token-Auflösung aus). Für sie
    ändert sich nichts. Betroffen ist nur der Fall, den es vorher gab: jeder
    Aufrufer im Internet, ganz ohne Anmeldeversuch - "/" liefert öffentlich
    denied.html mit Status 200 aus, von dort liess sich der Endpunkt ohne
    jede Hürde erreichen.
  → Wunsch #207: zusätzlich auf 8 Anfragen/Minute je Adresse begrenzt.
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
                        ki_anfrage, WUNSCH_PRIORITAETEN, rate_ueberschritten)

bp = Blueprint("werkstatt", __name__)

_PFAD_RE = re.compile(r"^/a/([a-z0-9_-]+)/[^/]+(/.*)?$")


_TITEL_SYSTEM = (
    "Du formulierst aus einem Verbesserungswunsch fuer eine private "
    "Familien-Web-App eine kurze Ueberschrift auf Deutsch. Antworte "
    "AUSSCHLIESSLICH mit der Ueberschrift, ohne Anfuehrungszeichen, ohne "
    "Punkt am Ende, hoechstens 60 Zeichen."
)
_TITEL_MAX = 80
_ERSATZ_MAX = 60


def ersatz_titel(text: str) -> str:
    """Wunsch #187: Eine Überschrift aus dem Text selbst, ohne KI.

    Der KI-Titel ist besser, aber er ist nicht garantiert: Er entsteht in
    einem Hintergrund-Thread, braucht ein bekanntes Konto (anonyme Wünsche
    haben keins), ein Kontingent und eine erreichbare Gegenstelle. Fällt
    davon etwas aus, stand die Karte bisher ganz ohne Überschrift da.

    Deshalb ist dies KEINE gespeicherte Zweitüberschrift, sondern ein
    Anzeigewert: Trägt die KI später doch einen Titel nach, gewinnt er
    sofort, ohne dass irgendwo ein Provisorium aufzuräumen wäre.

    Genommen wird der erste Satz - er ist bei einem Wunsch fast immer die
    Kernaussage; der Rest ist Begründung.

    Der Doppelpunkt trennt hier bewusst NICHT: Wünsche beginnen oft mit einer
    Einordnung ("UI: Die Knöpfe hängen am Header"), und "UI" wäre als
    Überschrift schlechter als gar keine.
    """
    text = " ".join((text or "").split())
    if not text:
        return ""
    satz = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if len(satz) > _ERSATZ_MAX:
        # Nicht mitten im Wort abschneiden - sonst steht da "Die Ansicht sieht
        # nach der Feldanpa…".
        gekuerzt = satz[:_ERSATZ_MAX].rsplit(" ", 1)[0] or satz[:_ERSATZ_MAX]
        return gekuerzt.rstrip(" ,;-") + " …"
    return satz.rstrip(" .")


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
    # Wunsch #207 (Sicherheitsaudit 11.08.2026): eng gefasst, weil die Route
    # bis zur naechsten Zeile noch fuer JEDEN ohne jede Identitaet erreichbar
    # ist. 8 Anfragen/Minute je Adresse laesst normalem Gebrauch (auch
    # mehrere schnell hintereinander eingetragene Wuensche) Luft, haelt aber
    # eine Flut in Grenzen.
    if rate_ueberschritten("wunsch-anlegen", max_anfragen=8, fenster_sekunden=60):
        return jsonify(ok=False, error="Zu viele Anfragen"), 429

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="Kein Text"), 400

    token    = (data.get("token") or "").strip()
    app_slug = (data.get("app")   or "").strip() or None
    ansicht  = _ansicht_aus_pfad((data.get("pfad") or "").strip()) or app_slug

    db = get_db()

    # Nutzer über beliebiges gültiges Token ermitteln - oder, auf token-freien
    # Seiten (Wunsch #140, Stufe 4), über das Sitzungs-Cookie.
    row = aktueller_nutzer(token)
    # Wunsch #204: OHNE jede erkennbare Identitaet (weder Token noch Cookie)
    # kein Eintrag mehr - siehe Docstring oben. Damit gibt es die vorherige
    # echte Anonymitaet (user_id NULL) nicht mehr: Wer den Wunsch abschickt,
    # ist ab jetzt IMMER jemand, der schon einmal erfolgreich eine App
    # geoeffnet hat, also immer bekannt.
    if not row:
        return jsonify(ok=False, error="Nicht angemeldet"), 403
    user_id = row["id"]

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
