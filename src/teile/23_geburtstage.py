"""
Geburtstage – gemeinsame Geburtstagsliste der Familie (Wunsch #145).
URL-Präfix: /a/geburtstage/<token>/

Jeder trägt ein, alle sehen es (Auto-Grant wie hilfe/einkauf). Was NICHT
gemeinsam ist, sind die Einstellungen: Ausblenden und Erinnerungen gelten
jeweils nur für den Nutzer, der sie setzt – so verlangt es der Wunsch
ausdrücklich.

Zwei getrennte Erinnerungen, ebenfalls laut Wunsch:
  * `erinnerung`   – am Tag selbst ("heute hat X Geburtstag")
  * `vorlauf_tage` – einige Tage vorher, um z. B. nach Geschenkwünschen zu
                     fragen. Unabhängig einstellbar: man kann nur den Vorlauf
                     wollen, nur den Tag, beides oder nichts.

`tag`/`monat` stehen als Zahlen in der Datenbank (siehe Schema-Kommentar in
`00_kern.py`): Ein Geburtstag wiederholt sich jährlich, und das Geburtsjahr
ist oft unbekannt.

**Wo der tägliche Lauf sitzt und warum:**
Der `util`-Container ist eigentlich der Ort für Zeitgesteuertes (Snapshots,
Backup, Zertifikate). Die Erinnerungen laufen trotzdem HIER, in einem
Hintergrund-Thread des Portals - aus einem einfachen Grund: `push_send()` und
die VAPID-Schlüssel liegen im Portal. Läge der Lauf in `util`, müssten
entweder die Schlüssel dorthin dupliziert werden (zwei Orte für dasselbe
Geheimnis) oder es bräuchte einen zusätzlichen, abgesicherten HTTP-Endpunkt
zwischen den Containern. Beides sind mehr bewegliche Teile als ein Thread -
und jedes bewegliche Teil kann still ausfallen.

Der Thread ist gefahrlos, weil Gunicorn hier mit **einem** Worker läuft (siehe
`server.md`): Es gibt genau einen Thread, keine Doppelversendung durch
mehrere Prozesse. Gegen Doppelversendung nach einem Neustart schützt
zusätzlich die Tabelle `geburtstag_gesendet` - verschickt wird nur, was für
den heutigen Tag noch nicht vermerkt ist.
"""
import threading
import time
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, to_int, new_db, push_send

bp  = Blueprint("geburtstage_app", __name__)
APP = "geburtstage"

# Wann die Erinnerungen rausgehen. Früher wäre unhöflich, später wäre der
# halbe Tag vorbei.
SENDESTUNDE = 8
# Wie oft der Thread nachschaut. Fein genug, um die Sendestunde sicher zu
# treffen, grob genug, um nichts zu kosten.
PRUEFTAKT_SEKUNDEN = 600

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _tage_bis(tag: int, monat: int, heute: date = None) -> int:
    """Tage bis zum nächsten Vorkommen dieses Tag/Monat-Paares.

    0 = heute. Über den Jahreswechsel hinweg korrekt, weil bei einem bereits
    vergangenen Datum aufs Folgejahr gerechnet wird.

    Der 29. Februar ist der Sonderfall: In einem Nicht-Schaltjahr gibt es ihn
    nicht. Gefeiert wird dann am 1. März - das ist die in Deutschland übliche
    Handhabung und besser als "faellt dieses Jahr aus"."""
    heute = heute or date.today()
    for jahr in (heute.year, heute.year + 1):
        try:
            ziel = date(jahr, monat, tag)
        except ValueError:
            if monat == 2 and tag == 29:
                ziel = date(jahr, 3, 1)
            else:
                continue
        if ziel >= heute:
            return (ziel - heute).days
    return 999


def _alter_am_geburtstag(jahr, tag, monat, heute: date = None):
    """Wie alt die Person am nächsten Geburtstag wird - None ohne Jahresangabe.

    Rechnet über `_tage_bis()` statt selbst am Kalender: Damit gilt hier
    automatisch dieselbe Schaltjahr- und Jahreswechsel-Behandlung, statt einer
    zweiten, leicht abweichenden Kopie davon."""
    if not jahr:
        return None
    heute = heute or date.today()
    ziel = heute + timedelta(days=_tage_bis(tag, monat, heute))
    return ziel.year - jahr


def _liste_fuer(db, user_id):
    """Alle Geburtstage mit den Einstellungen DIESES Nutzers, sortiert nach
    Nähe zum heutigen Tag."""
    rows = db.execute("""
        SELECT g.id, g.name, g.tag, g.monat, g.jahr, g.notiz,
               g.erstellt_von, u.name AS ersteller,
               COALESCE(e.ausgeblendet, 0) AS ausgeblendet,
               COALESCE(e.erinnerung, 0)   AS erinnerung,
               e.vorlauf_tage
        FROM   geburtstage g
        LEFT   JOIN users u ON u.id = g.erstellt_von
        LEFT   JOIN geburtstag_einstellungen e
               ON e.geburtstag_id = g.id AND e.user_id = ?
        ORDER  BY g.monat, g.tag, g.name COLLATE NOCASE
    """, (user_id,)).fetchall()

    heute = date.today()
    liste = []
    for r in rows:
        eintrag = dict(r)
        eintrag["tage_bis"] = _tage_bis(r["tag"], r["monat"], heute)
        eintrag["wird_alt"] = _alter_am_geburtstag(r["jahr"], r["tag"], r["monat"], heute)
        eintrag["datum_text"] = f"{r['tag']}. {MONATE[r['monat'] - 1]}"
        liste.append(eintrag)
    liste.sort(key=lambda e: e["tage_bis"])
    return liste


@bp.route("/a/geburtstage/", defaults={"token": None})
@bp.route("/a/geburtstage/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()
    alle = _liste_fuer(db, user["id"])
    return render_template("geburtstage.html",
        user=user, token=token, farbe=user["farbe"],
        sichtbare=[e for e in alle if not e["ausgeblendet"]],
        ausgeblendete=[e for e in alle if e["ausgeblendet"]],
        monate=MONATE, heute_jahr=date.today().year)


def _eingaben_lesen():
    """Formularwerte pruefen -> (name, tag, monat, jahr, notiz) oder None.

    Wunsch #158: Anlegen und Bearbeiten teilen sich diese Pruefung. Zwei
    Kopien waeren die Bauart, bei der man eine Grenze nur an einer Stelle
    nachzieht - und dann laesst sich per Bearbeiten eintragen, was beim
    Anlegen abgelehnt wird.
    """
    name  = (request.form.get("name") or "").strip()[:80]
    tag   = to_int(request.form.get("tag"))
    monat = to_int(request.form.get("monat"))
    jahr  = to_int(request.form.get("jahr"))
    notiz = (request.form.get("notiz") or "").strip()[:200] or None

    if not name or not tag or not monat:
        return None
    if not (1 <= tag <= 31) or not (1 <= monat <= 12):
        return None
    # Ein Jahr in der Zukunft oder vor 1900 ist ein Tippfehler, kein Geburtstag.
    if jahr is not None and not (1900 <= jahr <= date.today().year):
        jahr = None
    return name, tag, monat, jahr, notiz


def _darf_aendern(user, row):
    """Ein Eintrag gilt fuer ALLE - deshalb duerfen ihn nur der Urheber sowie
    Eltern/Admin anfassen. Dieselbe Regel wie beim Loeschen; wer ihn nur fuer
    sich loswerden will, blendet ihn aus."""
    return (row["erstellt_von"] == user["id"]
            or user["is_admin"] or user["rolle"] == "eltern")


@bp.route("/a/geburtstage/neu", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geburtstage/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    werte = _eingaben_lesen()
    if werte is None:
        return redirect(url_for("geburtstage_app.index", token=token))
    name, tag, monat, jahr, notiz = werte

    db = get_db()
    db.execute(
        "INSERT INTO geburtstage(name, tag, monat, jahr, notiz, erstellt_von) "
        "VALUES(?,?,?,?,?,?)",
        (name, tag, monat, jahr, notiz, user["id"]))
    db.commit()
    return redirect(url_for("geburtstage_app.index", token=token))


@bp.route("/a/geburtstage/<int:gid>/bearbeiten", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geburtstage/<token>/<int:gid>/bearbeiten", methods=["POST"])
def bearbeiten(token, gid):
    """Wunsch #158: Eintraege korrigierbar machen.

    `erstellt_von` bleibt bewusst unangetastet - wer den Eintrag angelegt hat,
    bleibt sein Urheber, auch wenn ein Elternteil einen Tippfehler behebt.
    Sonst wanderte mit jeder Korrektur die Zustaendigkeit mit, und der
    urspruengliche Urheber koennte seinen eigenen Eintrag ploetzlich nicht
    mehr aendern.

    Die Erinnerungssperre (`geburtstag_gesendet`) wird NICHT geleert: Sie
    schluesselt auf den VERSANDTAG, nicht auf das Geburtsdatum. Eine Korrektur
    kann deshalb keine kuenftige Erinnerung unterdruecken - und eine bereits
    heute verschickte soll sich auch nicht durch eine Namensaenderung
    wiederholen lassen.
    """
    user = _user(token)
    db   = get_db()
    row  = db.execute("SELECT erstellt_von FROM geburtstage WHERE id=?", (gid,)).fetchone()
    if not row:
        abort(404)
    if not _darf_aendern(user, row):
        abort(403)

    werte = _eingaben_lesen()
    if werte is None:
        return redirect(url_for("geburtstage_app.index", token=token))
    name, tag, monat, jahr, notiz = werte

    db.execute(
        "UPDATE geburtstage SET name=?, tag=?, monat=?, jahr=?, notiz=? WHERE id=?",
        (name, tag, monat, jahr, notiz, gid))
    db.commit()
    return redirect(url_for("geburtstage_app.index", token=token))


@bp.route("/a/geburtstage/<int:gid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geburtstage/<token>/<int:gid>/loeschen", methods=["POST"])
def loeschen(token, gid):
    """Löschen betrifft ALLE - deshalb nur für den Urheber oder Eltern/Admin.
    Wer einen Eintrag nur für sich loswerden will, blendet ihn aus."""
    user = _user(token)
    db   = get_db()
    row  = db.execute("SELECT erstellt_von FROM geburtstage WHERE id=?", (gid,)).fetchone()
    if not row:
        abort(404)
    if not _darf_aendern(user, row):
        abort(403)
    db.execute("DELETE FROM geburtstage WHERE id=?", (gid,))
    db.commit()
    return redirect(url_for("geburtstage_app.index", token=token))


@bp.route("/a/geburtstage/<int:gid>/einstellung", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geburtstage/<token>/<int:gid>/einstellung", methods=["POST"])
def einstellung(token, gid):
    """Ausblenden und Erinnerungen - gilt nur für den aufrufenden Nutzer."""
    user = _user(token)
    db   = get_db()
    if not db.execute("SELECT 1 FROM geburtstage WHERE id=?", (gid,)).fetchone():
        abort(404)

    ausgeblendet = 1 if request.form.get("ausgeblendet") else 0
    erinnerung   = 1 if request.form.get("erinnerung") else 0
    vorlauf      = to_int(request.form.get("vorlauf_tage"))
    # 0 heisst "kein Vorlauf" - das waere sonst dasselbe wie die
    # Tages-Erinnerung und wuerde doppelt zustellen.
    if vorlauf is not None and not (1 <= vorlauf <= 60):
        vorlauf = None

    db.execute("""
        INSERT INTO geburtstag_einstellungen
            (user_id, geburtstag_id, ausgeblendet, erinnerung, vorlauf_tage)
        VALUES (?,?,?,?,?)
        ON CONFLICT(user_id, geburtstag_id) DO UPDATE SET
            ausgeblendet = excluded.ausgeblendet,
            erinnerung   = excluded.erinnerung,
            vorlauf_tage = excluded.vorlauf_tage
    """, (user["id"], gid, ausgeblendet, erinnerung, vorlauf))
    db.commit()
    return redirect(url_for("geburtstage_app.index", token=token))


# ---------------------------------------------------------------------------
# Erinnerungen
# ---------------------------------------------------------------------------

def faellige_erinnerungen(db, heute: date = None):
    """(user_id, geburtstag_id, art, name, tage_bis) für alles, was heute
    rausgehen muss und noch nicht vermerkt ist.

    Als eigene Funktion, damit sie sich ohne Thread und ohne Wartezeit testen
    lässt - der Versandweg drumherum ist trivial, die Auswahl ist es nicht."""
    heute = heute or date.today()
    heute_iso = heute.isoformat()
    faellig = []
    for r in db.execute("""
        SELECT e.user_id, e.geburtstag_id, e.erinnerung, e.vorlauf_tage,
               g.name, g.tag, g.monat
        FROM   geburtstag_einstellungen e
        JOIN   geburtstage g ON g.id = e.geburtstag_id
        WHERE  e.erinnerung = 1 OR e.vorlauf_tage IS NOT NULL
    """).fetchall():
        tage = _tage_bis(r["tag"], r["monat"], heute)
        arten = []
        if r["erinnerung"] and tage == 0:
            arten.append("tag")
        if r["vorlauf_tage"] is not None and tage == r["vorlauf_tage"]:
            arten.append("vorlauf")
        for art in arten:
            schon_da = db.execute("""
                SELECT 1 FROM geburtstag_gesendet
                WHERE user_id=? AND geburtstag_id=? AND art=? AND datum=?
            """, (r["user_id"], r["geburtstag_id"], art, heute_iso)).fetchone()
            if not schon_da:
                faellig.append({
                    "user_id": r["user_id"], "geburtstag_id": r["geburtstag_id"],
                    "art": art, "name": r["name"], "tage_bis": tage,
                })
    return faellig


def erinnerungen_verschicken(app, heute: date = None):
    """Ein Durchlauf. Gibt die Zahl der verschickten Erinnerungen zurück."""
    heute = heute or date.today()
    with app.app_context():
        with new_db() as db:
            faellig = faellige_erinnerungen(db, heute)
            for f in faellig:
                if f["art"] == "tag":
                    titel = "🎂 Geburtstag heute"
                    text  = f"{f['name']} hat heute Geburtstag!"
                else:
                    tage = f["tage_bis"]
                    titel = "🎁 Geburtstag in Sicht"
                    text  = (f"{f['name']} hat in {tage} "
                             f"{'Tag' if tage == 1 else 'Tagen'} Geburtstag.")
                push_send(f["user_id"], titel, text, "geburtstage",
                          "https://portal.16schwaben.de/a/geburtstage/")
                db.execute("""
                    INSERT OR IGNORE INTO geburtstag_gesendet
                        (user_id, geburtstag_id, art, datum)
                    VALUES (?,?,?,?)
                """, (f["user_id"], f["geburtstag_id"], f["art"], heute.isoformat()))
            db.commit()
    return len(faellig)


def _erinnerungs_schleife(app):
    import logging
    log = logging.getLogger("teile.geburtstage")
    zuletzt_gesendet_am = None
    while True:
        try:
            jetzt = date.today()
            import datetime as _dt
            stunde = _dt.datetime.now().hour
            if stunde >= SENDESTUNDE and zuletzt_gesendet_am != jetzt:
                anzahl = erinnerungen_verschicken(app, jetzt)
                zuletzt_gesendet_am = jetzt
                if anzahl:
                    log.info("Geburtstags-Erinnerungen verschickt: %d", anzahl)
        except Exception:
            # Ein Fehler darf die Schleife nicht beenden - sonst gäbe es bis
            # zum nächsten Neustart still keine Erinnerungen mehr.
            log.exception("Geburtstags-Erinnerungen fehlgeschlagen")
        time.sleep(PRUEFTAKT_SEKUNDEN)


def init_app(app):
    app.register_blueprint(bp)
    if str(app.config.get("GEBURTSTAGS_ERINNERUNGEN", "1")).strip() in ("1", "true", "ja"):
        threading.Thread(target=_erinnerungs_schleife, args=(app,), daemon=True).start()
