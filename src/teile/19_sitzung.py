"""
Sitzungen – Wunsch #140, Stufe 1.

Ziel des Gesamtumbaus: Der Zugangstoken soll aus der Adresszeile verschwinden.
Er ist dort heute Name, Passwort und Sitzung in einem und landet damit im
Browserverlauf, in synchronisierten Lesezeichen, in Screenshots und in
weitergeleiteten Links.

**Diese Stufe stellt nur aus.** Das Cookie wird angelegt und mitgegeben, aber
von NICHTS ausgewertet – die Anmeldung läuft weiterhin ausschließlich über den
Pfad-Token. Damit kann diese Stufe per Definition nichts kaputtmachen, und der
Cookie-Mechanismus lässt sich im echten Betrieb beobachten, bevor irgendetwas
davon abhängt (Stufe 3).

Warum eine eigene Tabelle statt Flasks signiertem Cookie: ein signiertes
Cookie ist nicht widerrufbar. Die Aktion „Zugänge neu erzeugen" (Wunsch #131)
wäre sonst wirkungslos – und das fiele erst im Ernstfall auf, wenn ein Gerät
verloren gegangen ist. Mit Tabelle lässt sich jede Sitzung einzeln beenden.

Der Cookie-Wert steht NICHT im Klartext in der Datenbank: gespeichert wird
`token_lookup(wert)`, also derselbe HMAC, den auch die Zugangstokens seit
Wunsch #129 benutzen. Ein `_enc`-Gegenstück braucht es hier nicht, weil der
Wert nie zurückgelesen werden muss – das ist nebenbei genau das echte Hashing,
das bei #129 an der Navigation gescheitert ist.

Cookie-Attribute und ihre Begründung:
  Secure     – HTTPS-only; HSTS steht bereits (Wunsch #134)
  HttpOnly   – die CSP erlaubt bewusst `unsafe-inline` bei script-src
               (59 Inline-Handler, Wunsch #142); bei XSS ist HttpOnly die
               verbleibende Bremse
  SameSite=Lax – `wir4` und `portal` sind Subdomains von `16schwaben.de`,
               also same-site: das Cookie geht auch im Home-Assistant-iFrame
               auf dem Esszimmerbildschirm mit. `Strict` würde beim ersten
               Aufruf über einen Link von aussen cookielos ankommen.
  kein Domain – sonst ginge das Cookie an Home Assistant mit. Das soll es nie.
  Max-Age 1 Jahr – der heutige Link läuft NIE ab. Eine kurze Sitzung wäre ein
               Komfortrückschritt ohne Sicherheitsgewinn und würde die Familie
               zurück auf die Links zwingen.
"""
import secrets

from flask import current_app, g, request

from teile.kern import get_db, token_lookup, SITZUNG_COOKIE

# Der Name liegt im Kern, weil grant() das Cookie ab Stufe 3 selbst liest -
# ein Import in die andere Richtung waere ein Ringschluss.
COOKIE_NAME = SITZUNG_COOKIE
_MAX_AGE = 365 * 24 * 3600
_GERAET_MAX = 80


def _schalter_an() -> bool:
    return str(current_app.config.get("SITZUNG_AUSSTELLEN", "")).strip() in ("1", "true", "ja")


def sitzung_aus_cookie(db):
    """Die Sitzungszeile zum mitgesendeten Cookie, oder None.

    Wird in Stufe 1 NUR benutzt, um zu erkennen, ob schon eine Sitzung
    existiert – nicht zum Autorisieren. Das kommt erst in Stufe 3."""
    wert = request.cookies.get(COOKIE_NAME)
    if not wert:
        return None
    return db.execute(
        "SELECT * FROM sitzungen WHERE kennung_lookup = ?", (token_lookup(wert),)
    ).fetchone()


def _sitzung_anlegen(db, user_id: int, quelle: str) -> str:
    """Legt eine Sitzung an und gibt den Cookie-Wert im Klartext zurück –
    der existiert nur hier und geht direkt an den Browser."""
    wert = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sitzungen(user_id, kennung_lookup, quelle, geraet, gesehen) "
        "VALUES(?,?,?,?, datetime('now'))",
        (user_id, token_lookup(wert), quelle,
         (request.headers.get("User-Agent") or "")[:_GERAET_MAX]),
    )
    db.commit()
    return wert


def init_app(app):
    @app.after_request
    def sitzung_ausstellen(antwort):
        # `g.sitzung_fuer` setzt kern.sitzung_vormerken(), sobald ein
        # Pfad-Token erfolgreich zu einer Identität aufgelöst wurde.
        user_id = getattr(g, "sitzung_fuer", None)
        if user_id is None or not _schalter_an():
            return antwort

        # Fehlerantworten bekommen kein Cookie. Weiterleitungen dagegen schon –
        # der erste Kontakt nach einem POST ist oft ein 302, und dort schon
        # auszustellen spart einen Umlauf. (Der Kommentar behauptete früher
        # das Gegenteil, der Code tat es nie – beim Prüfen von Stufe 3
        # aufgefallen.)
        if antwort.status_code >= 400:
            return antwort

        try:
            db = get_db()
            vorhanden = sitzung_aus_cookie(db)
            if vorhanden is not None and vorhanden["user_id"] == user_id:
                return antwort          # passende Sitzung liegt schon vor

            # Wunsch #140, Stufe 4: Gehört die vorhandene Sitzung einem ANDEREN
            # Nutzer, wird sie ersetzt. Das ist der Fall "geteiltes Gerät":
            # Simone öffnet auf dem Familien-iPad ihren QR-Link, während das
            # Cookie noch Andi gehört.
            #
            # Bis Stufe 3 war das harmlos - jede Kachel trug Simones Token, die
            # Navigation folgte also dem Link. Token-frei ist `/a/einkauf/` für
            # alle dieselbe Adresse: Simone sähe ihre Startseite, und beim
            # ersten Tippen Andis Einkaufsliste. Der Vorrang des Pfad-Tokens
            # hielte genau eine Seite lang.
            #
            # Deshalb: Wer seinen Link öffnet, übernimmt das Gerät. Die alte
            # Sitzung wird dabei gelöscht und nicht bloß überschrieben, sonst
            # bliebe für jeden Wechsel eine verwaiste, gültige Zeile zurück -
            # und "Zugänge neu erzeugen" räumt nur die des eigenen Nutzers weg.
            if vorhanden is not None:
                db.execute("DELETE FROM sitzungen WHERE id = ?", (vorhanden["id"],))
                db.commit()

            wert = _sitzung_anlegen(db, user_id, "token")
            antwort.set_cookie(
                COOKIE_NAME, wert,
                max_age=_MAX_AGE, secure=True, httponly=True, samesite="Lax",
                path="/",               # kein domain= – siehe Docstring
            )
        except Exception:
            # Eine kaputte Sitzungslogik darf niemals eine funktionierende
            # Seite zerstören. In dieser Stufe hängt ohnehin nichts daran.
            current_app.logger.exception("Sitzung konnte nicht ausgestellt werden")

        return antwort
