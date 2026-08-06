"""
CSRF-Riegel – Wunsch #140, Stufe 2.

Heute braucht das Portal keinen CSRF-Schutz, und das ist kein Versäumnis:
Jede ändernde Anfrage muss den Zugangstoken mittragen (im Pfad oder im
JSON-Body). Ein fremder Server kennt ihn nicht und kann die Anfrage deshalb
gar nicht bilden. Das ist exakt das Synchronizer-Token-Muster, nur im Pfad
statt im Formularfeld.

Sobald aber ab Stufe 3 ein Cookie autorisiert, entsteht „ambient authority":
Der Browser schickt das Cookie bei jeder Anfrage automatisch mit, auch bei
einer, die eine fremde Seite ausgelöst hat. Ab dann ist CSRF-Schutz Pflicht.

**Reihenfolge mit Absicht:** Dieser Riegel geht scharf, BEVOR das Cookie
autorisiert. In diesem Moment kann er nichts kaputtmachen, was nicht ohnehin
kaputt wäre – jede Anfrage trägt noch ihren Pfad-Token. Falsch-Positive
fallen dadurch im Protokoll auf und nicht später im Betrieb.

Verfahren: Header-Prüfung, kein verstecktes Formularfeld. Ein
Synchronizer-Token müsste in 57 Formulare und 27 fetch()-Aufrufe eingebaut
werden; jedes vergessene bricht still. Der Header-Riegel ist eine einzige
Funktion und braucht null Template-Änderungen. Er hätte zudem ein Problem mit
der Offline-Warteschlange der Einkaufsliste, die POSTs stundenlang aufhebt und
später nachspielt – ein rotierendes Token wäre dann längst abgelaufen.

Zwei Fallen, die den Aufbau erklären:

1. `Referrer-Policy: no-referrer` (Caddyfile) kann den `Origin`-Header auf
   `null` setzen. Wer nur `Origin` prüft, lehnt womöglich alles ab. Deshalb
   steht `Sec-Fetch-Site` an erster Stelle – dieser Header ist von der
   Referrer-Policy unberührt.
2. `Sec-Fetch-Site: same-site` muss ABGELEHNT werden. Home Assistant läuft
   unter derselben Domain (`wir4` bzw. `portal` unter `16schwaben.de`); ein
   POST aus einer HA-Seite wäre damit same-site, aber nicht same-origin –
   genau der Fall, den wir nicht wollen. Der Kiosk ist davon nicht betroffen:
   die Seite IM iFrame hat Portal-Origin, ihre Formulare sind same-origin.
"""
from urllib.parse import urlparse

from flask import abort, current_app, request

UNSICHERE_METHODEN = {"POST", "PUT", "PATCH", "DELETE"}


def _modus() -> str:
    """'aus' | 'beobachten' | 'scharf'"""
    wert = str(current_app.config.get("CSRF_MODUS", "aus")).strip().lower()
    return wert if wert in ("aus", "beobachten", "scharf") else "aus"


def _erwartete_origin() -> str:
    """Die eigene Herkunft. Konfigurierbar, sonst aus der Anfrage abgeleitet
    (die geht durch Caddy, das nur die eine Site bedient)."""
    fest = str(current_app.config.get("PORTAL_ORIGIN", "")).strip()
    if fest:
        return fest.rstrip("/")
    teile = urlparse(request.url_root)
    return f"{teile.scheme}://{teile.netloc}"


def _ist_eigene_anfrage() -> tuple[bool, str]:
    """(ok, begruendung) – die Begründung landet im Protokoll."""
    site = request.headers.get("Sec-Fetch-Site")
    if site:
        # Nur same-origin ist in Ordnung. 'same-site' bewusst nicht, siehe
        # Docstring. 'none' kommt bei Adresszeilen-Navigation vor und sollte
        # bei einer ändernden Anfrage gar nicht auftreten.
        if site == "same-origin":
            return True, ""
        return False, f"Sec-Fetch-Site={site}"

    # Kein Sec-Fetch-Site: älterer Browser. Dann ersatzweise Origin.
    herkunft = request.headers.get("Origin")
    if herkunft and herkunft == _erwartete_origin():
        return True, ""
    if herkunft:
        return False, f"Origin={herkunft}"
    return False, "weder Sec-Fetch-Site noch Origin vorhanden"


def init_app(app):
    @app.before_request
    def csrf_pruefen():
        if request.method not in UNSICHERE_METHODEN:
            return None
        modus = _modus()
        if modus == "aus":
            return None

        ok, grund = _ist_eigene_anfrage()
        if ok:
            return None

        # Ein Wort, nach dem sich greppen lässt: "CSRF-Verdacht".
        current_app.logger.warning(
            "CSRF-Verdacht (%s): %s %s – %s – UA=%s",
            modus, request.method, request.path, grund,
            (request.headers.get("User-Agent") or "")[:60],
        )
        if modus == "beobachten":
            return None          # protokollieren, aber durchlassen
        abort(403)
