"""
Aufgabenplan (intern "kinderplan") – ordnet wiederkehrende Aufgaben
(aus geholfen_aufgaben) Wochentagen zu, ursprünglich nur für Kinder,
seit Wunsch #91 auch für Eltern (eigener Plan, nicht nur Verwalten fremder
Pläne).
URL-Präfix: /a/kinderplan/<token>/

Abhaken schreibt direkt in geholfen_eintraege (dieselbe Tabelle wie die
Geholfen-App) – kein doppelter Zustand, "erledigt heute" wird daraus
abgeleitet statt separat gespeichert.

Berechtigung (Wunsch #36, Rollen-Kreis um Eltern erweitert per Wunsch #91):
  Ansehen    – jedes Kind/Elternteil sieht alle Kind-/Eltern-Pläne
  Editieren  – nur den eigenen Plan; Eltern/Admin dürfen jeden Plan editieren
  Sperre     – ab 20 Uhr ist der Plan für morgen für Kinder gesperrt (Eltern/
               Admin sind über _darf_verwalten() ohnehin von der Sperre
               ausgenommen, auch beim eigenen Plan)

Wunsch #90 (Pool wiederkehrender Aufgaben): die Vorlagen selbst werden in
der Todo-App verwaltet (teile.todo, importiert über den Alias aus
teile/__init__.py), hier passiert nur das Einsortieren einer Pool-Vorlage
in einen Wochentag für eine Person - erzeugt ein ganz normales todos-Row
(serie_id+wochentag gesetzt), keine eigene Datenhaltung dafür.
"""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int
from teile.todo import serien_pool_liste, serie_einsortieren

bp  = Blueprint("kinderplan_app", __name__)
APP = "kinderplan"

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _darf_verwalten(user) -> bool:
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _gesperrter_wochentag():
    """Ab 20 Uhr ist der Wochentag von morgen für Kinder gesperrt."""
    now = datetime.now()
    if now.hour >= 20:
        return (now.date() + timedelta(days=1)).weekday()
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
    gesperrter_tag = _gesperrter_wochentag()

    aufgaben = db.execute(
        "SELECT id, name, emoji FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()

    serien_pool = serien_pool_liste(db) if (ziel and darf_editieren) else []

    plan = []
    if ziel:
        rows = db.execute("""
            SELECT k.aufgabe_id, k.wochentag, a.name, a.emoji
            FROM   kinderplan_eintraege k
            JOIN   geholfen_aufgaben a ON a.id = k.aufgabe_id
            WHERE  k.user_id=?
            ORDER  BY k.wochentag, k.position
        """, (ziel["id"],)).fetchall()

        erledigt_heute = {r["aufgabe_id"] for r in db.execute("""
            SELECT aufgabe_id FROM geholfen_eintraege
            WHERE user_id=? AND date(zeitstempel) = date('now')
        """, (ziel["id"],)).fetchall()}

        # Wunsch #90: aus dem Pool eingesetzte Todo-Instanzen fuer diese
        # Person, gruppiert nach Wochentag - ganz normale todos-Rows mit
        # gesetztem serie_id, unerledigte UND heute erledigte (fuer den
        # Haken-Status), aeltere erledigte bleiben stehen bis die Vorlage
        # per Wiederkehr-Regel wieder im Pool verfuegbar ist.
        serien_rows = db.execute("""
            SELECT id, inhalt, wochentag, erledigt
            FROM   todos
            WHERE  zugewiesen_an=? AND serie_id IS NOT NULL
            ORDER  BY wochentag, id
        """, (ziel["id"],)).fetchall()

        heute_wd = date.today().weekday()
        for wd in range(7):
            eintraege = []
            for r in rows:
                if r["wochentag"] != wd:
                    continue
                e = dict(r)
                e["erledigt_heute"] = (wd == heute_wd and e["aufgabe_id"] in erledigt_heute)
                eintraege.append(e)
            serien_eintraege = [dict(r) for r in serien_rows if r["wochentag"] == wd]
            plan.append({
                "wochentag":        wd,
                "name":             WOCHENTAGE[wd],
                "eintraege":        eintraege,
                "serien_eintraege": serien_eintraege,
                "ist_heute":        wd == heute_wd,
                "gesperrt":         (wd == gesperrter_tag) and not _darf_verwalten(user),
            })

    return render_template("kinderplan.html",
        user=user, token=token, farbe=user["farbe"],
        kinder=kinder, ziel=ziel, darf_editieren=darf_editieren,
        aufgaben=aufgaben, plan=plan, serien_pool=serien_pool,
    )


@bp.route("/a/kinderplan/<token>/zuweisen", methods=["POST"])
def zuweisen(token):
    """Tippen auf einen Aufgaben-Chip weist zu bzw. entfernt wieder (Toggle)."""
    user = _user(token)
    db   = get_db()
    ziel_id    = to_int(request.form.get("ziel_id"))
    aufgabe_id = to_int(request.form.get("aufgabe_id"))
    wochentag  = to_int(request.form.get("wochentag"))
    if ziel_id is None or aufgabe_id is None or wochentag is None or not (0 <= wochentag <= 6):
        abort(400)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)).fetchone():
        abort(404)
    if not (user["id"] == ziel_id or _darf_verwalten(user)):
        abort(403)
    if wochentag == _gesperrter_wochentag() and not _darf_verwalten(user):
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
    Wochentag (Wunsch #90) - erzeugt ein ganz normales todos-Row."""
    user = _user(token)
    db   = get_db()
    ziel_id   = to_int(request.form.get("ziel_id"))
    serie_id  = to_int(request.form.get("serie_id"))
    wochentag = to_int(request.form.get("wochentag"))
    if ziel_id is None or serie_id is None or wochentag is None or not (0 <= wochentag <= 6):
        abort(400)
    if not db.execute("SELECT 1 FROM users WHERE id=? AND rolle IN ('kind','eltern')", (ziel_id,)).fetchone():
        abort(404)
    if not (user["id"] == ziel_id or _darf_verwalten(user)):
        abort(403)
    if wochentag == _gesperrter_wochentag() and not _darf_verwalten(user):
        abort(403)
    serie_einsortieren(db, serie_id, ziel_id, wochentag, user["id"])
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
