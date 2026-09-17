"""
Morning Briefing auf der Startseite (Wunsch #272).

Beim ersten Öffnen des Portals am Tag steht oben auf der Startseite eine
Karte mit dem, was heute ansteht: der Essensplan (Mittag, Abend) und die
Geburtstage von heute und morgen. Ein Tipp auf „Gelesen" bestätigt das
Briefing - die Karte verschwindet, an ihrer Stelle bleibt ein kleiner Link,
mit dem man es jederzeit wieder aufrufen kann (`/p/briefing`).

Wer es bis zum Morgen nicht bestätigt hat, bekommt eine Push-Nachricht:
werktags ab 07:30, am Wochenende ab 09:00 Familienzeit. Nur an Nutzer mit
Push-Abo, nur einmal am Tag, und nur bis 12:00 - ein Container-Neustart am
Nachmittag soll keinen „Guten Morgen" nachschicken.

Alles hängt an EINER Tabelle, `briefing_status` (user_id, tag): wann
bestätigt, wann gepusht. Kein Eintrag heißt: weder noch. Der Tag ist der
Kalendertag in Familienzeit - `heute_lokal()`, nicht `date.today()`, denn
der Container läuft in UTC und liegt zwischen Mitternacht und 02:00 sonst
einen Tag zurück.

Die Daten kommen aus den bestehenden Apps und deren Modulen, nicht aus einer
Kopie: Mahlzeiten-Konstanten aus `teile.essensplan`, Datumslogik (Tage bis
zum Geburtstag, Alter, 29. Februar) aus `teile.geburtstage`, der
Startseiten-Nutzer aus `teile.start_token`. Die Ausblend-Einstellung der
Geburtstags-App gilt auch hier - wen jemand dort ausgeblendet hat, den will
er auch morgens nicht sehen.

Warum der Push-Lauf hier im Portal läuft und nicht im `util`-Container,
steht ausführlich in `23_geburtstage.py`: `push_send()` und die VAPID-
Schlüssel liegen hier, und Gunicorn läuft mit einem Worker.
"""
import logging
import threading
import time
from datetime import date, datetime
from datetime import time as uhrzeit

from flask import Blueprint, abort, render_template, url_for

from teile.essensplan import MAHLZEIT_LABELS, MAHLZEITEN
from teile.geburtstage import MONATE, _alter_am_geburtstag, _tage_bis
from teile.kern import (
    LOKAL_TZ,
    antwort_oder_weiter,
    get_db,
    hat_grant,
    new_db,
    push_send,
)
from teile.rezepte import kategorie_symbol
from teile.start_token import _home_user

bp = Blueprint("briefing", __name__)
log = logging.getLogger("teile.briefing")

# Wann die Erinnerung frühestens rausgeht - so steht es im Wunsch.
SENDEZEIT_WERKTAG    = uhrzeit(7, 30)
SENDEZEIT_WOCHENENDE = uhrzeit(9, 0)
# Und wann nicht mehr: Wer bis mittags nicht hineingesehen hat, bekommt
# keinen "Guten Morgen" um 15 Uhr, nur weil der Container neu gestartet ist.
SENDESCHLUSS = uhrzeit(12, 0)
# Minutentakt: 07:30 soll 07:30 sein, nicht "irgendwann bis 07:40". Die
# Prüfung ist eine Abfrage auf eine kleine Tabelle, das kostet nichts.
PRUEFTAKT_SEKUNDEN = 60

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
              "Samstag", "Sonntag"]
STARTSEITE_URL = "https://portal.16schwaben.de/start"


def jetzt_lokal() -> datetime:
    """Aktuelle Familienzeit. Eigene Funktion, damit Tests sie ersetzen
    koennen, ohne an der Uhr des Rechners zu drehen."""
    return datetime.now(LOKAL_TZ)


def gruss(jetzt: datetime) -> str:
    """Die Karte bleibt den ganzen Tag stehen, bis sie bestaetigt ist - ein
    "Guten Morgen" um 20 Uhr wirkt dann wie eine stehengebliebene Uhr."""
    if jetzt.hour < 11:
        return "Guten Morgen"
    if jetzt.hour < 18:
        return "Hallo"
    return "Guten Abend"


def sendezeit(tag: date) -> uhrzeit:
    return SENDEZEIT_WOCHENENDE if tag.weekday() >= 5 else SENDEZEIT_WERKTAG


def _mahlzeiten(db, tag: date) -> list[dict]:
    """Die beiden Slots des Tages, immer beide - auch leer. "Nichts geplant"
    ist eine Information, ein fehlender Slot waere eine Luecke."""
    rows = db.execute("""
        SELECT e.mahlzeit, e.text, r.name AS rezept_name, r.kategorie
        FROM   essensplan_eintraege e
        LEFT JOIN rezepte r ON r.id = e.rezept_id
        WHERE  e.tag = ?
    """, (tag.isoformat(),)).fetchall()
    je_slot = {r["mahlzeit"]: r for r in rows}
    liste = []
    for m in MAHLZEITEN:
        r = je_slot.get(m)
        text = symbol = ""
        if r:
            if r["rezept_name"]:
                text, symbol = r["rezept_name"], kategorie_symbol(r["kategorie"])
            else:
                text = (r["text"] or "").strip()
        liste.append({"slot": m, "label": MAHLZEIT_LABELS[m],
                      "text": text, "symbol": symbol})
    return liste


def _geburtstage(db, user_id: int, tag: date) -> list[dict]:
    """Heute und morgen, mit den Ausblendungen DIESES Nutzers."""
    rows = db.execute("""
        SELECT g.name, g.tag, g.monat, g.jahr
        FROM   geburtstage g
        LEFT JOIN geburtstag_einstellungen e
               ON e.geburtstag_id = g.id AND e.user_id = ?
        WHERE  COALESCE(e.ausgeblendet, 0) = 0
        ORDER  BY g.name COLLATE NOCASE
    """, (user_id,)).fetchall()
    liste = []
    for r in rows:
        bis = _tage_bis(r["tag"], r["monat"], tag)
        if bis > 1:
            continue
        liste.append({
            "name": r["name"],
            "wann": "heute" if bis == 0 else "morgen",
            "tage_bis": bis,
            "wird_alt": _alter_am_geburtstag(r["jahr"], r["tag"], r["monat"], tag),
        })
    liste.sort(key=lambda e: (e["tage_bis"], e["name"].casefold()))
    return liste


def briefing_fuer(db, user_id: int, jetzt: datetime | None = None) -> dict:
    """Alles, was die Karte zeigt. Reine Daten, keine Flask-Abhaengigkeit -
    der Push-Lauf benutzt dieselbe Funktion fuer seinen Text."""
    jetzt = jetzt or jetzt_lokal()
    tag = jetzt.date()
    # Wunsch #292 (Sicherheitsaudit 16.09.2026, Befund N-14): Der Essensplan
    # gehoert nur ins Briefing, wenn der Nutzer die Essensplan-App auch hat.
    # Vorher las _mahlzeiten() ohne Grant-Pruefung - ein Nutzer (auch Rolle
    # gast), dem Andi die App bewusst nicht gegeben hatte, sah Mittag und
    # Abend trotzdem auf der Startseite. Geburtstage sind an alle vergeben
    # (00_kern._auto_grant_all), dort stellt sich die Frage nicht.
    essensplan = hat_grant(db, user_id, "essensplan")
    return {
        "tag": tag.isoformat(),
        "datum_text": f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE[tag.month - 1]}",
        "gruss": gruss(jetzt),
        "essensplan": essensplan,
        "mahlzeiten": _mahlzeiten(db, tag) if essensplan else [],
        "geburtstage": _geburtstage(db, user_id, tag),
    }


def push_text(briefing: dict) -> str:
    """Eine Zeile fuer die Push-Nachricht: das Wesentliche, nicht die Karte."""
    teile = []
    for m in briefing["mahlzeiten"]:
        if m["text"]:
            teile.append(f"{m['label']}: {m['text']}")
    for g in briefing["geburtstage"]:
        teile.append(f"🎂 {g['name']} hat {g['wann']} Geburtstag")
    if not teile:
        return "Dein Briefing für heute wartet auf dich."
    return " · ".join(teile)


def ist_bestaetigt(db, user_id: int, tag: date) -> bool:
    row = db.execute(
        "SELECT bestaetigt_am FROM briefing_status WHERE user_id=? AND tag=?",
        (user_id, tag.isoformat())).fetchone()
    return bool(row and row["bestaetigt_am"])


def bestaetigen(db, user_id: int, tag: date) -> None:
    """Idempotent: die erste Bestaetigung zaehlt, eine zweite (zweiter Tab,
    Zurueck-Taste) aendert nichts mehr."""
    db.execute("""
        INSERT INTO briefing_status (user_id, tag, bestaetigt_am)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(user_id, tag) DO UPDATE SET bestaetigt_am = excluded.bestaetigt_am
        WHERE briefing_status.bestaetigt_am IS NULL
    """, (user_id, tag.isoformat()))
    db.commit()


# --- Routen ------------------------------------------------------------------

def _nutzer(token):
    row = _home_user(token)
    if not row:
        abort(403)
    return row


@bp.route("/p/briefing", defaults={"token": None})
@bp.route("/p/<token>/briefing")
def seite(token):
    """Das Briefing als eigene Seite - der Weg zurueck, nachdem die Karte auf
    der Startseite bestaetigt und damit eingeklappt ist."""
    row = _home_user(token)
    if not row:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    jetzt = jetzt_lokal()
    return render_template(
        "briefing.html", user=row, token=token, farbe=row["farbe"],
        briefing=briefing_fuer(db, row["id"], jetzt),
        bestaetigt=ist_bestaetigt(db, row["id"], jetzt.date()),
    )


@bp.route("/p/briefing/bestaetigen", defaults={"token": None}, methods=["POST"])
@bp.route("/p/<token>/briefing/bestaetigen", methods=["POST"])
def bestaetigen_route(token):
    row = _nutzer(token)
    bestaetigen(get_db(), row["id"], jetzt_lokal().date())
    # Wunsch #171: per fetch von der Startseite aus JSON, sonst zurueck zur
    # Startseite (mit oder ohne Token, je nachdem, wie man gekommen ist).
    return antwort_oder_weiter(url_for("start.startseite", token=token), bestaetigt=True)


# --- Erinnerung per Push -----------------------------------------------------

def faellige_pushes(db, jetzt: datetime) -> list[int]:
    """Nutzer-IDs, die JETZT eine Erinnerung bekommen: Sendezeit erreicht,
    Sendeschluss nicht, mindestens ein Push-Abo, heute weder bestaetigt noch
    schon erinnert. Ohne Thread testbar - die Auswahl ist das Schwierige, der
    Versand drumherum ist trivial."""
    tag = jetzt.date()
    if not (sendezeit(tag) <= jetzt.time() < SENDESCHLUSS):
        return []
    rows = db.execute("""
        SELECT DISTINCT p.user_id
        FROM   push_abos p
        LEFT JOIN briefing_status s ON s.user_id = p.user_id AND s.tag = ?
        WHERE  s.bestaetigt_am IS NULL AND s.push_am IS NULL
        ORDER  BY p.user_id
    """, (tag.isoformat(),)).fetchall()
    return [r["user_id"] for r in rows]


def pushes_verschicken(app, jetzt: datetime | None = None) -> int:
    """Ein Durchlauf. Gibt die Zahl der verschickten Erinnerungen zurueck."""
    jetzt = jetzt or jetzt_lokal()
    with app.app_context(), new_db() as db:
        faellig = faellige_pushes(db, jetzt)
        for user_id in faellig:
            briefing = briefing_fuer(db, user_id, jetzt)
            push_send(user_id, "☀️ Dein Briefing für heute", push_text(briefing),
                      "home", STARTSEITE_URL, dedup_key=f"briefing-{briefing['tag']}")
            db.execute("""
                INSERT INTO briefing_status (user_id, tag, push_am)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(user_id, tag) DO UPDATE SET push_am = excluded.push_am
            """, (user_id, jetzt.date().isoformat()))
        db.commit()
    return len(faellig)


def _push_schleife(app):
    while True:
        try:
            anzahl = pushes_verschicken(app)
            if anzahl:
                log.info("Briefing-Erinnerungen verschickt: %d", anzahl)
        except Exception:
            # Ein Fehler darf die Schleife nicht beenden - sonst gaebe es bis
            # zum naechsten Neustart still keine Erinnerung mehr.
            log.exception("Briefing-Erinnerung fehlgeschlagen")
        time.sleep(PRUEFTAKT_SEKUNDEN)


def init_app(app):
    app.register_blueprint(bp)
    if str(app.config.get("BRIEFING_PUSH", "1")).strip() in ("1", "true", "ja"):
        threading.Thread(target=_push_schleife, args=(app,), daemon=True).start()
