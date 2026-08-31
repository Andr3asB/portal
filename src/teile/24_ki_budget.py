"""
KI-Verbrauch und OpenRouter-Guthaben (Wunsch #183).
URL-Präfix: /a/admin/<token>/ki

Zwei Dinge auf einer Seite:

1. **Wer verbraucht wie viel.** Die Zahlen liegen längst in `ki_nutzung`
   (Tokens je Anfrage und Nutzer) und `ki_tts_nutzung` (Zeichen fürs Vorlesen,
   Wunsch #136) – sichtbar waren sie bisher nirgends. `ki_anfrage()` prüft das
   Monatskontingent (`users.ki_token_limit`) gegen den Verbrauch **seit
   Monatsanfang**; genau diese Zahl steht deshalb hier vorne, nicht die
   Gesamtsumme.
2. **Wie viel Guthaben noch da ist**, direkt von OpenRouter.

WÄHRUNG: OpenRouter rechnet in **US-Dollar**, nicht in Euro. Der Wunsch nennt
"ein Euro" als Schwelle; hier steht 1,00 USD. Der Unterschied ist bei dieser
Größenordnung belanglos, aber er soll benannt sein statt stillschweigend
umgedeutet – eine Zahl, die anders heißt als sie ist, führt irgendwann in die
Irre.

ZWEI ARTEN VON "GUTHABEN": `/api/v1/credits` nennt das Konto-Guthaben (gekaufte
Credits minus Gesamtverbrauch), `/api/v1/key` zusätzlich ein Limit des
verwendeten Schlüssels, das sich monatlich zurücksetzt. Ausschlaggebend für
"kann das Portal noch KI benutzen" ist der KLEINERE von beiden – ist eines leer,
geht keine Anfrage mehr durch. Gewarnt wird deshalb auf den kleineren Wert,
nicht auf das Konto-Guthaben allein. Beide stehen auf der Seite, damit man
sieht, welcher gerade klemmt.

Der Wächter läuft als Hintergrund-Thread (Muster wie `23_geburtstage.py`) und
legt bei Unterschreitung EINE Aufgabe für den Admin an, die per Push zugestellt
wird. Ist bereits eine offene Aufgabe dieser Art da, passiert nichts weiter –
sonst stünden nach einer Woche sieben identische Aufgaben in der Liste.
"""
import json
import logging
import threading
import time
import urllib.request

from flask import Blueprint, abort, current_app, render_template

from teile.kern import get_db, new_db, push_send
from teile.kern import grant as check_grant

bp  = Blueprint("ki_budget", __name__)
APP = "admin"
log = logging.getLogger("teile.ki_budget")

SCHWELLE_USD       = 1.00
PRUEFTAKT_SEKUNDEN = 3600          # stündlich; das Guthaben ändert sich langsam
AUFGABEN_MARKE     = "🤖 OpenRouter-Guthaben aufladen"
TODO_URL           = "https://portal.16schwaben.de/a/todo/"

# OpenRouter liefert den Rhythmus englisch ("monthly"). Unbekannte Werte gehen
# unübersetzt durch - lieber ein englisches Wort als gar keine Angabe.
RESET_TEXT = {"daily": "jeden Tag", "weekly": "jede Woche",
              "monthly": "jeden Monat"}


def _admin(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    return user


def _openrouter(pfad: str, api_key: str):
    """Ein GET gegen OpenRouter. Gibt None zurück, statt zu werfen – die
    Übersicht soll auch dann etwas anzeigen, wenn OpenRouter gerade nicht
    erreichbar ist; der Verbrauch je Nutzer steht ja lokal in der Datenbank."""
    if not api_key:
        return None
    try:
        anfrage = urllib.request.Request(
            "https://openrouter.ai" + pfad,
            headers={"Authorization": "Bearer " + api_key})
        with urllib.request.urlopen(anfrage, timeout=15) as antwort:
            return json.loads(antwort.read()).get("data")
    except Exception as fehler:
        log.info("OpenRouter %s nicht abrufbar: %s", pfad, fehler)
        return None


def guthaben_lesen(api_key: str):
    """`{'rest': float, 'quelle': 'konto'|'limit', …}` oder None.

    `rest` ist der kleinere aus Konto-Guthaben und Schlüssel-Limit (siehe
    Modul-Docstring). Hat der Schlüssel kein Limit (`limit: null`), zählt
    allein das Konto-Guthaben."""
    credits = _openrouter("/api/v1/credits", api_key)
    schluessel = _openrouter("/api/v1/key", api_key)
    if not credits and not schluessel:
        return None

    werte = {}
    if credits:
        werte["konto_rest"] = round(
            (credits.get("total_credits") or 0) - (credits.get("total_usage") or 0), 4)
        werte["konto_gekauft"]  = credits.get("total_credits")
        werte["konto_verbraucht"] = credits.get("total_usage")
    if schluessel:
        if schluessel.get("limit") is not None:
            werte["limit_rest"]  = round(schluessel.get("limit_remaining") or 0, 4)
            werte["limit"]       = schluessel.get("limit")
            rhythmus = schluessel.get("limit_reset")
            werte["limit_reset"] = RESET_TEXT.get(rhythmus, rhythmus)
        werte["usage_taeglich"]  = schluessel.get("usage_daily")
        werte["usage_monatlich"] = schluessel.get("usage_monthly")

    kandidaten = [(werte[k], name) for k, name in
                  (("konto_rest", "konto"), ("limit_rest", "limit"))
                  if werte.get(k) is not None]
    if not kandidaten:
        return None
    werte["rest"], werte["quelle"] = min(kandidaten)
    return werte


def _aufgabe_schon_offen(db) -> bool:
    """Eine Aufgabe je Ebbe, nicht eine je Prüfung. Sieben gleichlautende
    Zeilen in der Liste würde man irgendwann sammelweise wegwischen – und
    die achte dann auch."""
    return db.execute(
        "SELECT 1 FROM todos WHERE status <> 'erledigt' AND inhalt LIKE ?",
        (AUFGABEN_MARKE + "%",)).fetchone() is not None


def _betrag(wert: float) -> str:
    return f"{wert:.2f}".replace(".", ",")


def guthaben_pruefen(app) -> bool:
    """Ein Durchlauf des Wächters. True, wenn eine neue Aufgabe entstanden ist."""
    with app.app_context():
        stand = guthaben_lesen(app.config.get("OPENROUTER_API_KEY", ""))
        if not stand or stand.get("rest") is None:
            return False          # OpenRouter nicht erreichbar: kein Alarm auf Verdacht
        if stand["rest"] > SCHWELLE_USD:
            return False

        with new_db() as db:
            if _aufgabe_schon_offen(db):
                return False
            admin = db.execute(
                "SELECT id FROM users WHERE is_admin=1 ORDER BY id").fetchone()
            if not admin:
                return False
            ziel = admin["id"]
            db.execute(
                "INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, status) "
                "VALUES(?,?,?,'offen')",
                (f"{AUFGABEN_MARKE} – nur noch {_betrag(stand['rest'])} USD übrig",
                 ziel, ziel))
            db.commit()

        push_send(ziel, "🤖 KI-Guthaben fast leer",
                  f"Nur noch {_betrag(stand['rest'])} USD. Ohne Guthaben fallen "
                  f"Rezept-Import, Vorlesen und Foto-Import aus.",
                  "todo", TODO_URL)
        log.info("Guthaben-Aufgabe angelegt (%.2f USD, Quelle %s)",
                 stand["rest"], stand["quelle"])
        return True


def _wacht_schleife(app):
    while True:
        try:
            guthaben_pruefen(app)
        except Exception:
            # Ein Fehler darf die Schleife nicht beenden - sonst gäbe es bis
            # zum nächsten Neustart still keine Warnung mehr.
            log.exception("Guthaben-Pruefung fehlgeschlagen")
        time.sleep(PRUEFTAKT_SEKUNDEN)


@bp.route("/a/admin/ki", defaults={"token": None})
@bp.route("/a/admin/<token>/ki")
def uebersicht(token):
    user = _admin(token)
    db   = get_db()

    nutzer = db.execute("""
        SELECT u.id, u.name, u.farbe, u.ki_token_limit, u.ki_tts_zeichen_limit,
               COALESCE(SUM(CASE WHEN k.erstellt >= date('now','start of month')
                                 THEN k.tokens END), 0) AS tokens_monat,
               COALESCE(SUM(k.tokens), 0)               AS tokens_gesamt,
               COUNT(k.id)                              AS anfragen
        FROM   users u
        LEFT   JOIN ki_nutzung k ON k.user_id = u.id
        GROUP  BY u.id
        ORDER  BY tokens_monat DESC, u.name COLLATE NOCASE
    """).fetchall()

    # Vorlesen zaehlt Zeichen, nicht Tokens (Wunsch #136) - deshalb eine eigene
    # Spalte statt einer Summe, die zwei Einheiten vermischt.
    tts = {r["user_id"]: r["zeichen"] for r in db.execute("""
        SELECT user_id, COALESCE(SUM(zeichen), 0) AS zeichen
        FROM   ki_tts_nutzung
        WHERE  erstellt >= date('now','start of month')
        GROUP  BY user_id
    """)}

    je_feature = db.execute("""
        SELECT feature, COUNT(*) AS anfragen, COALESCE(SUM(tokens), 0) AS tokens
        FROM   ki_nutzung
        WHERE  erstellt >= date('now','start of month')
        GROUP  BY feature
        ORDER  BY tokens DESC
    """).fetchall()

    return render_template("admin_ki.html",
        user=user, token=token, farbe=user["farbe"],
        nutzer=nutzer, tts=tts, je_feature=je_feature,
        guthaben=guthaben_lesen(current_app.config.get("OPENROUTER_API_KEY", "")),
        schwelle=SCHWELLE_USD,
    )


def init_app(app):
    app.register_blueprint(bp)
    if str(app.config.get("KI_GUTHABEN_WACHT", "1")).strip() in ("1", "true", "ja"):
        threading.Thread(target=_wacht_schleife, args=(app,), daemon=True).start()
