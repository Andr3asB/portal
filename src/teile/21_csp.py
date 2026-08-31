"""
Content-Security-Policy mit Nonce – Wunsch #142, Stufe 5 des Umbaus.

Ausgangslage: Die CSP stand im `Caddyfile` und musste `script-src
'unsafe-inline'` erlauben, weil 59 `onclick`/`onsubmit`-Attribute in 27
Vorlagen daran hingen. Mit `'unsafe-inline'` läuft eingeschleuster Code
genauso selbstverständlich wie unser eigener – die Regel stand da, schützte
aber genau vor dem nicht, wogegen sie gedacht ist.

Nachdem die Inline-Handler auf den Verteiler in `base.html` umgestellt sind,
bleiben nur noch unsere eigenen `<script>`-Blöcke. Die bekommen ein Nonce,
und `'unsafe-inline'` kann weg.

**Warum die CSP jetzt in Flask liegt und nicht mehr in Caddy:** Das Nonce muss
je Anfrage neu erzeugt und in dieselbe Antwort geschrieben werden, in der es
auch in den `<script>`-Tags steht. Caddy sieht die Vorlage nicht. Ein festes
Nonce im Caddyfile wäre wertlos – ein Angreifer könnte es abschreiben.

**`style-src` behält `'unsafe-inline'`.** Im Projekt stehen rund 200
`style="…"`-Attribute; die alle umzubauen wäre ein Vielfaches des Aufwands bei
einem Bruchteil des Nutzens. Über Style-Injektion lässt sich Layout
verunstalten und in Grenzen Inhalt ausspähen – über Script-Injektion lässt
sich alles tun, was der angemeldete Nutzer darf. Die beiden Risiken sind nicht
vergleichbar, und eine halbe Maßnahme bei `script-src` wäre schlechter als
eine ganze bei `script-src` und keine bei `style-src`.

Drei Modi, wie beim CSRF-Riegel (Wunsch #140, Stufe 2) – dasselbe Muster, weil
es sich dort bewährt hat:

  aus         – die alte, freizügige Regel mit 'unsafe-inline'. Der Zustand
                von vorher, der Notausstieg.
  beobachten  – die alte Regel gilt weiterhin (blockiert also nichts Neues),
                zusätzlich geht die STRENGE Regel als `Report-Only` mit. Jeder
                Verstoß wird gemeldet und protokolliert, ohne dass irgendetwas
                kaputtgeht. So findet man ein übersehenes Inline-Skript, bevor
                es jemandem den Knopf lahmlegt.
  scharf      – die strenge Regel gilt.

Der Beobachtungsmodus ist hier mehr wert als beim CSRF-Riegel: Ein übersehener
Inline-Handler fällt sonst erst auf, wenn jemand den betreffenden Knopf
drückt – und das kann Wochen dauern.
"""
import re
import secrets

from flask import Blueprint, current_app, g, request

# Flask 3 reicht Markup nicht mehr durch - es kommt aus markupsafe.
from markupsafe import Markup

from teile.kern import rate_ueberschritten

# Wunsch #205 (Sicherheitsaudit 11.08.2026): Steuerzeichen aus den drei
# gemeldeten Feldern entfernen, bevor sie in eine Log-Zeile eingesetzt
# werden - siehe bericht() weiter unten.
_STEUERZEICHEN = re.compile(r"[\r\n\x00-\x1f]+")

bp = Blueprint("csp", __name__)

# Was das Portal wirklich braucht. Keine fremden Hosts: JS-Bibliotheken sind
# lokal gebündelt (Projektkonvention), Bilder und Schriften kommen von uns.
_BASIS = (
    "default-src 'self'; "
    "img-src 'self' data:; "
    # `blob:` ist Pflicht, nicht Bequemlichkeit: Die Vokabel-Aussprache wird
    # per fetch() geholt (um ein aufgebrauchtes Kontingent, HTTP 429, sauber
    # melden zu koennen) und dann als Blob abgespielt. Ohne eigenes
    # `media-src` greift `default-src 'self'`, und eine blob:-Adresse ist
    # davon NICHT gedeckt - das Audio-Element scheitert dann mit Fehlercode 4.
    #
    # Genau so ist es passiert: Die strenge CSP kam in v125, die Umstellung
    # auf Blob-Wiedergabe in v126. Seither wurde die Datei zwar erzeugt und
    # ausgeliefert, aber nie abgespielt - auf ALLEN Geraeten, ohne sichtbare
    # Fehlermeldung. Wer hier etwas aendert: erst pruefen, ob eine Ressource
    # ueber blob:/data: laeuft, sonst bricht sie lautlos weg.
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    # Der Esszimmerbildschirm zeigt das Portal im Home-Assistant-iFrame.
    # Ohne diese Zeile wäre er schwarz.
    "frame-ancestors https://wir4.16schwaben.de"
)

# style-src bleibt bewusst freizügig – Begründung im Modul-Docstring.
_STYLE = "style-src 'self' 'unsafe-inline'"

_MELDEZIEL = "/csp-bericht"


def _modus() -> str:
    wert = str(current_app.config.get("CSP_MODUS", "aus")).strip().lower()
    return wert if wert in ("aus", "beobachten", "scharf") else "aus"


def _freizuegig() -> str:
    """Die Regel von vor Wunsch #142 – inhaltlich die aus dem Caddyfile."""
    return f"script-src 'self' 'unsafe-inline'; {_STYLE}; {_BASIS}"


def _streng(nonce: str, melden: bool = False) -> str:
    regel = f"script-src 'self' 'nonce-{nonce}'; {_STYLE}; {_BASIS}"
    if melden:
        regel += f"; report-uri {_MELDEZIEL}"
    return regel


def _log_sicher(wert, laenge: int) -> str:
    """Ein gemeldetes Feld log-tauglich machen.

    Wunsch #205 (Sicherheitsaudit 11.08.2026): Der Endpunkt ist absichtlich
    unauthentifiziert (siehe bericht()) - jeder kann also beliebigen Text mit
    eingebetteten Zeilenumbruechen einschicken. Ohne dieses Saeubern liesse
    sich damit eine zusaetzliche, frei erfundene Log-Zeile einschleusen, die
    wie eine ECHTE Meldung aussieht (z. B. eine gefaelschte "CSRF-Verdacht:"-
    Zeile) - Log-Faelschung durch reine Zeichenketten-Formatierung."""
    return _STEUERZEICHEN.sub(" ", str(wert if wert is not None else "?"))[:laenge]


@bp.route(_MELDEZIEL, methods=["POST"])
def bericht():
    """Nimmt die Verstoßmeldungen des Browsers entgegen.

    Bewusst ohne jede Autorisierung: Der Browser schickt diese Meldungen
    unabhängig davon, ob jemand angemeldet ist, und eine abgelehnte Meldung
    wäre eine verlorene Meldung. Geschrieben wird nichts – nur protokolliert.
    Der Endpunkt ist deshalb auch von der CSRF-Prüfung ausgenommen (siehe
    `20_csrf.py`); er ändert keine Daten, es gibt nichts zu fälschen.

    Wunsch #207 (Sicherheitsaudit 11.08.2026): Gerade WEIL unauthentifiziert
    und ohne CSRF-Schutz, braucht die Route eine eigene Bremse - sonst liesse
    sich das Log beliebig fluten. 30/Minute laesst Raum fuer eine Seite, die
    mehrere Ressourcen gleichzeitig blockiert bekommt (mehrere echte Meldungen
    auf einen Seitenaufruf), haelt aber eine gezielte Flut in Grenzen.
    """
    if rate_ueberschritten("csp-bericht", max_anfragen=30, fenster_sekunden=60):
        return "", 429

    daten = request.get_json(silent=True, force=True) or {}
    meldung = daten.get("csp-report", daten)
    current_app.logger.warning(
        # Ein Wort zum Greppen: "CSP-Verstoss".
        "CSP-Verstoss: %s in %s (Zeile %s) – Regel: %s",
        _log_sicher(meldung.get("blocked-uri"), 120),
        _log_sicher(meldung.get("document-uri"), 120),
        _log_sicher(meldung.get("line-number"), 10),
        _log_sicher(meldung.get("violated-directive"), 80),
    )
    return "", 204


def init_app(app):
    app.register_blueprint(bp)

    @app.before_request
    def nonce_erzeugen():
        # Je Anfrage neu. `secrets` und nicht `random`: ein erratbares Nonce
        # wäre dasselbe wie gar keines.
        g.csp_nonce_wert = secrets.token_urlsafe(16)

    @app.context_processor
    def nonce_bereitstellen():
        """Liefert ` nonce="…"` zum direkten Einsetzen: `<script{{ csp_nonce }}>`.

        Inklusive führendem Leerzeichen, damit die Vorlagen kein Leerzeichen
        vor dem Ausdruck brauchen – sonst stünde bei leerem Wert `<script >`.
        Im Modus `aus` bleibt es leer; das Attribut wäre dort wirkungslos.
        """
        wert = getattr(g, "csp_nonce_wert", "")
        if not wert or _modus() == "aus":
            return {"csp_nonce": Markup("")}
        return {"csp_nonce": Markup(f' nonce="{wert}"')}

    @app.after_request
    def csp_setzen(antwort):
        modus = _modus()
        nonce = getattr(g, "csp_nonce_wert", "")

        if modus == "scharf" and nonce:
            antwort.headers["Content-Security-Policy"] = _streng(nonce)
        elif modus == "beobachten" and nonce:
            antwort.headers["Content-Security-Policy"] = _freizuegig()
            antwort.headers["Content-Security-Policy-Report-Only"] = \
                _streng(nonce, melden=True)
        else:
            antwort.headers["Content-Security-Policy"] = _freizuegig()
        return antwort
