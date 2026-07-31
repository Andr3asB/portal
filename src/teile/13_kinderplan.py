"""
Aufgabenplan (intern "kinderplan") – rollierende 14-Tage-Liste (aktuelle +
nächste Woche), analog zum Essensplan (Wunsch #92, vorher ein abstraktes
Wochentag-Raster ohne echte Daten). Zeigt für jeden der 14 Kalendertage:
  - Geholfen-Aufgaben aus einer weiterhin wöchentlich wiederkehrenden Regel
    (kinderplan_eintraege.wochentag, UNVERÄNDERT gegenüber vorher – bewusste
    Entscheidung: bestehende Wochenroutinen bleiben automatisch bestehen,
    nur die Darstellung wird zur Datumsliste statt Wochentag-Raster)
  - Aus dem Todo-Pool eingesetzte Instanzen (Wunsch #90), jetzt an ein
    echtes Kalenderdatum gebunden (todos.plan_tag), nicht mehr an einen
    abstrakten Wochentag – jede Einsortierung ist ein einmaliges Ereignis,
    kein wiederkehrendes Muster wie bei den Geholfen-Aufgaben.
URL-Präfix: /a/kinderplan/<token>/

Abhaken einer Geholfen-Aufgabe schreibt direkt in geholfen_eintraege
(dieselbe Tabelle wie die Geholfen-App) – kein doppelter Zustand, der
Erledigt-Status je Tag wird daraus abgeleitet statt separat gespeichert.
Abhaken einer Todo-Pool-Instanz schreibt direkt in todos (siehe
serie_erledigen) – ebenfalls kein separates Tracking.

Berechtigung (Wunsch #36, Rollen-Kreis um Eltern erweitert per Wunsch #91):
  Ansehen    – jedes Kind/Elternteil sieht alle Kind-/Eltern-Pläne
  Editieren  – nur den eigenen Plan; Eltern/Admin dürfen jeden Plan editieren
  Sperre     – ab 20 Uhr ist der jeweils NÄCHSTE Kalendertag für Kinder
               gesperrt (echtes Datum, nicht mehr eine abstrakte Wochentag-
               Nummer – sonst wäre z. B. IMMER "nächsten Montag" gesperrt,
               nicht nur der eine konkrete kommende Montag). Eltern/Admin
               sind über _darf_verwalten() ohnehin ausgenommen, auch am
               eigenen Plan.

Wunsch #90 (Pool wiederkehrender Aufgaben): die Vorlagen selbst werden in
der Todo-App verwaltet (teile.todo, importiert über den Alias aus
teile/__init__.py), hier passiert nur das Einsortieren einer Pool-Vorlage
auf einen Kalendertag für eine Person - erzeugt ein ganz normales
todos-Row (serie_id+plan_tag gesetzt), keine eigene Datenhaltung dafür.

Bewusst NICHT gebaut: Drag & Drop zwischen Tagen (anders als beim
Essensplan) - für Geholfen-Aufgaben ergibt das keinen Sinn (eine einzelne
Karte verschieben würde die GANZE wöchentliche Regel verschieben, nicht
nur diesen einen Tag), für Todo-Pool-Instanzen wäre es technisch möglich,
aber für einen ersten Wurf zurückgestellt.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int
from teile.todo import serien_pool_liste, serie_einsortieren

bp  = Blueprint("kinderplan_app", __name__)
APP = "kinderplan"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
_TZ = ZoneInfo("Europe/Berlin")


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _darf_verwalten(user) -> bool:
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _heute():
    """Container laeuft in UTC, "heute"/"20 Uhr" muss aber deutsche Ortszeit
    meinen (wie in 14_sportschau.py) - sonst verschiebt sich Mitternacht und
    die 20-Uhr-Sperre um 1-2 Stunden gegenueber dem, was die Familie sieht."""
    return datetime.now(_TZ).date()


def _gesperrter_tag_datum():
    """Ab 20 Uhr (deutsche Ortszeit) ist der naechste Kalendertag fuer Kinder gesperrt."""
    now = datetime.now(_TZ)
    if now.hour >= 20:
        return now.date() + timedelta(days=1)
    return None


@bp.route("/a/kinderplan/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()

    kinder = db.execute(
        "SELECT id, name, farbe FROM users WHERE rolle IN ('kind','eltern') ORDER BY rolle='eltern', name"
    ).fetchall()

    ziel_id = to_int(request.args.get("fuer"))
    ziel = None
    if ziel_id is not None:
        ziel = db.execute(
            "SELECT id, name, farbe FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)
        ).fetchone()
    if not ziel:
        if user["rolle"] in ("kind", "eltern"):
            ziel = db.execute("SELECT id, name, farbe FROM users WHERE id=?", (user["id"],)).fetchone()
        elif kinder:
            ziel = kinder[0]

    darf_editieren = bool(ziel and (user["id"] == ziel["id"] or _darf_verwalten(user)))
    gesperrter_tag = _gesperrter_tag_datum()

    aufgaben = db.execute(
        "SELECT id, name, emoji FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()

    serien_pool = serien_pool_liste(db) if (ziel and darf_editieren) else []

    heute  = _heute()
    montag = heute - timedelta(days=heute.weekday())
    tage_daten = [montag + timedelta(days=i) for i in range(14)]  # aktuelle + folgende Woche, wie Essensplan

    plan = []
    if ziel:
        # Geholfen: bestehende woechentliche Regel (unveraendert gespeichert,
        # gilt weiter fuer JEDEN passenden Wochentag in der 14-Tage-Liste).
        regeln = db.execute("""
            SELECT k.aufgabe_id, k.wochentag, a.name, a.emoji
            FROM   kinderplan_eintraege k
            JOIN   geholfen_aufgaben a ON a.id = k.aufgabe_id
            WHERE  k.user_id=?
            ORDER  BY k.wochentag, k.position
        """, (ziel["id"],)).fetchall()

        # Erledigt-Status je Tag im 14-Tage-Fenster (nicht mehr nur "heute").
        erledigt_rows = db.execute("""
            SELECT aufgabe_id, date(zeitstempel) AS tag FROM geholfen_eintraege
            WHERE  user_id=? AND date(zeitstempel) BETWEEN ? AND ?
        """, (ziel["id"], tage_daten[0].isoformat(), tage_daten[-1].isoformat())).fetchall()
        erledigt_set = {(r["aufgabe_id"], r["tag"]) for r in erledigt_rows}

        # Wunsch #90/#92: aus dem Pool eingesetzte Todo-Instanzen fuer diese
        # Person, jetzt an ein echtes Datum gebunden (plan_tag), nicht mehr
        # an einen abstrakten Wochentag.
        serien_rows = db.execute("""
            SELECT id, inhalt, plan_tag, erledigt
            FROM   todos
            WHERE  zugewiesen_an=? AND serie_id IS NOT NULL
              AND  plan_tag BETWEEN ? AND ?
            ORDER  BY plan_tag, id
        """, (ziel["id"], tage_daten[0].isoformat(), tage_daten[-1].isoformat())).fetchall()
        serien_map = {}
        for r in serien_rows:
            serien_map.setdefault(r["plan_tag"], []).append(dict(r))

        for d in tage_daten:
            iso = d.isoformat()
            wd  = d.weekday()
            if d < heute:
                status = "vergangen"
            elif d == heute:
                status = "heute"
            else:
                status = "zukunft"

            eintraege = []
            for r in regeln:
                if r["wochentag"] != wd:
                    continue
                e = dict(r)
                e["erledigt"] = (r["aufgabe_id"], iso) in erledigt_set
                eintraege.append(e)

            plan.append({
                "iso":              iso,
                "datum":            d,
                "wochentag_name":   WOCHENTAGE[wd],
                "status":           status,
                "eintraege":        eintraege,
                "serien_eintraege": serien_map.get(iso, []),
                "gesperrt":         (d == gesperrter_tag) and not _darf_verwalten(user),
            })

    # Wunsch #92: gleiche Gliederung wie der Essensplan - eigene
    # Wochenkopfzeilen, vergangene Tage einklappbar.
    aktuelle_woche  = plan[:7]
    naechste_woche  = plan[7:]
    vergangene_tage = [t for t in aktuelle_woche if t["status"] == "vergangen"]
    aktuelle_rest   = [t for t in aktuelle_woche if t["status"] != "vergangen"]

    return render_template("kinderplan.html",
        user=user, token=token, farbe=user["farbe"],
        kinder=kinder, ziel=ziel, darf_editieren=darf_editieren,
        aufgaben=aufgaben, serien_pool=serien_pool,
        vergangene_tage=vergangene_tage, aktuelle_rest=aktuelle_rest, naechste_woche=naechste_woche,
    )


@bp.route("/a/kinderplan/<token>/zuweisen", methods=["POST"])
def zuweisen(token):
    """Tippen auf einen Aufgaben-Chip weist zu bzw. entfernt wieder (Toggle).
    Schreibt weiterhin auf die woechentliche Regel (kinderplan_eintraege),
    nicht auf einen einzelnen Tag - gilt also fuer JEDEN Kalendertag mit
    diesem Wochentag, nicht nur die eine Karte, auf der geklickt wurde."""
    user = _user(token)
    db   = get_db()
    ziel_id    = to_int(request.form.get("ziel_id"))
    aufgabe_id = to_int(request.form.get("aufgabe_id"))
    tag_iso    = request.form.get("tag", "").strip()
    try:
        tag_datum = date.fromisoformat(tag_iso)
    except ValueError:
        abort(400)
    wochentag = tag_datum.weekday()
    if ziel_id is None or aufgabe_id is None:
        abort(400)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)).fetchone():
        abort(404)
    if not (user["id"] == ziel_id or _darf_verwalten(user)):
        abort(403)
    if tag_datum == _gesperrter_tag_datum() and not _darf_verwalten(user):
        abort(403)
    if not db.execute("SELECT 1 FROM geholfen_aufgaben WHERE id=? AND aktiv=1", (aufgabe_id,)).fetchone():
        abort(404)

    exists = db.execute(
        "SELECT 1 FROM kinderplan_eintraege WHERE user_id=? AND aufgabe_id=? AND wochentag=?",
        (ziel_id, aufgabe_id, wochentag),
    ).fetchone()
    if exists:
        db.execute(
            "DELETE FROM kinderplan_eintraege WHERE user_id=? AND aufgabe_id=? AND wochentag=?",
            (ziel_id, aufgabe_id, wochentag),
        )
    else:
        db.execute(
            "INSERT INTO kinderplan_eintraege(user_id, aufgabe_id, wochentag) VALUES(?,?,?)",
            (ziel_id, aufgabe_id, wochentag),
        )
    db.commit()
    return redirect(url_for("kinderplan_app.index", token=token, fuer=ziel_id))


@bp.route("/a/kinderplan/<token>/abhaken", methods=["POST"])
def abhaken(token):
    """Abhaken registriert direkt in geholfen_eintraege - dieselbe Quelle,
    aus der die Geholfen-App und ihre Statistik lesen (Wunsch #36)."""
    user = _user(token)
    db   = get_db()
    data = request.get_json(silent=True) or {}
    ziel_id    = to_int(data.get("ziel_id"))
    aufgabe_id = to_int(data.get("aufgabe_id"))
    if ziel_id is None or aufgabe_id is None:
        abort(400)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)).fetchone():
        abort(404)
    if not (user["id"] == ziel_id or _darf_verwalten(user)):
        abort(403)
    aufg = db.execute(
        "SELECT name, emoji FROM geholfen_aufgaben WHERE id=? AND aktiv=1", (aufgabe_id,)
    ).fetchone()
    if not aufg:
        abort(404)
    db.execute(
        "INSERT INTO geholfen_eintraege(aufgabe_id, user_id) VALUES(?,?)",
        (aufgabe_id, ziel_id),
    )
    db.commit()
    return jsonify(ok=True, aufgabe=aufg["name"], emoji=aufg["emoji"])


@bp.route("/a/kinderplan/<token>/serie_einsortieren", methods=["POST"])
def serie_einsortieren_route(token):
    """Holt eine Pool-Vorlage und legt sie fuer eine Person auf einen
    echten Kalendertag (Wunsch #90/#92) - erzeugt ein ganz normales
    todos-Row, einmalig, kein wiederkehrendes Muster."""
    user = _user(token)
    db   = get_db()
    ziel_id  = to_int(request.form.get("ziel_id"))
    serie_id = to_int(request.form.get("serie_id"))
    tag_iso  = request.form.get("tag", "").strip()
    try:
        tag_datum = date.fromisoformat(tag_iso)
    except ValueError:
        abort(400)
    if ziel_id is None or serie_id is None:
        abort(400)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)).fetchone():
        abort(404)
    if not (user["id"] == ziel_id or _darf_verwalten(user)):
        abort(403)
    if tag_datum == _gesperrter_tag_datum() and not _darf_verwalten(user):
        abort(403)
    serie_einsortieren(db, serie_id, ziel_id, tag_iso, user["id"])
    return redirect(url_for("kinderplan_app.index", token=token, fuer=ziel_id))


@bp.route("/a/kinderplan/<token>/serie_erledigen/<int:tid>", methods=["POST"])
def serie_erledigen(token, tid):
    """Abhaken/Zurücknehmen einer aus dem Pool eingesetzten Todo-Instanz
    (Wunsch #90) - schreibt direkt in todos, dieselbe Tabelle wie die
    Todo-App selbst, kein separates Tracking."""
    user = _user(token)
    db   = get_db()
    row = db.execute(
        "SELECT id, zugewiesen_an, erledigt FROM todos WHERE id=? AND serie_id IS NOT NULL", (tid,)
    ).fetchone()
    if not row:
        abort(404)
    if not (user["id"] == row["zugewiesen_an"] or _darf_verwalten(user)):
        abort(403)
    neu = 0 if row["erledigt"] else 1
    db.execute(
        "UPDATE todos SET status=?, erledigt=?, "
        "erledigt_am=CASE WHEN ?=1 THEN datetime('now') ELSE NULL END WHERE id=?",
        ("erledigt" if neu else "offen", neu, neu, tid),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, erledigt=bool(neu))
    return redirect(url_for("kinderplan_app.index", token=token, fuer=row["zugewiesen_an"]))


def init_app(app):
    app.register_blueprint(bp)
