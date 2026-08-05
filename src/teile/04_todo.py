"""
Todo-App – Aufgaben anlegen, zuweisen, abhaken.
URL-Präfix: /a/todo/<token>/

Andere Module können todos_neu() aufrufen, um programmatisch Todos zu erstellen.

Berechtigungen (Wunsch #10):
  Erstellen  – alle Nutzer
  Abhaken    – Eltern/Admin: jedes Todo; Kind/Gast: nur eigene (erstellt oder zugewiesen),
               oder ein an ihre Rolle (bzw. "alle") adressiertes Todo (Wunsch #39)
  Löschen    – nur Eltern/Admin

Zuweisung (Wunsch #39): eine Aufgabe geht entweder an eine konkrete Person
(zugewiesen_an, wie bisher – inkl. des Leerwerts "für mich"/niemand Bestimmtes,
unverändertes Alt-Verhalten) ODER an eine/mehrere Rollen bzw. explizit "alle"
(neue Spalte zugewiesen_rollen, kommagetrennt, Sentinel "alle" = alle Rollen).
Nur die neue Rollen/Alle-Zuweisung landet initial im Backlog statt in Offen –
eine direkte Personen-Zuweisung (auch der Leerwert) verhält sich wie zuvor.

Wiederkehrende Aufgaben-Vorlagen / Pool (Wunsch #90): eine todo_serien-Zeile
ist eine Vorlage mit Wiederkehr-Regel (entweder "intervall" – X Tage nach
Erledigung wieder verfügbar – oder "wochentag" – an einem festen Wochentag
wieder verfügbar, jeweils pro Vorlage gewählt), verwaltet hier unter
/serien. Die eigentliche Einsortierung in einen Kalendertag passiert NICHT
hier, sondern in der Aufgabenplanung (kinderplan, seit Wunsch #92 eine
rollierende 14-Tage-Liste wie der Essensplan) – deshalb sind
serien_pool_fuer_tag()/serie_einsortieren() als Schnittstelle für andere
Module gedacht (importierbar über den Alias 'teile.todo', siehe
teile/__init__.py). Eine einsortierte Instanz ist ein ganz normales
todos-Row mit gesetztem serie_id+plan_tag (ISO-Datum) – nutzt die
komplette bestehende Todo-Mechanik (Status, Historie, Löschen) mit, kein
separates Tracking.

Wunsch #112: "wochentag"-Vorlagen können jetzt mehrere Wochentage
gleichzeitig haben (`feste_wochentage`, kommagetrennt, z.B. "1,3,5" für
Di+Do+Sa) statt nur einem (`fester_wochentag`, totes Altfeld ab jetzt,
siehe Migrations-Kommentar in 00_kern.py).

Wunsch #113: die Pool-Verfügbarkeit ist jetzt PRO KALENDERTAG zu
berechnen statt einmal global, und für "intervall"-Vorlagen periodisch
statt einmalig-ab-Erreichen-der-Frist: `serie_verfuegbar_am(db, serie,
tag_iso)` ersetzt das alte `_serie_ist_im_pool()`. Zwei wesentliche
Verhaltensänderungen gegenüber vorher:
  1. Der Anker für "intervall" ist jetzt der zuletzt EINGEPLANTE Tag
     (MAX(plan_tag) über alle Instanzen dieser Serie), nicht mehr der
     zuletzt ERLEDIGT-Zeitpunkt - dadurch lässt sich eine Serie mehrere
     Tage im Voraus einplanen, ohne auf das Erledigen der vorherigen
     Instanz warten zu müssen.
  2. Verfügbarkeit ist periodisch (Differenz zum Anker muss ein positives
     Vielfaches von intervall_tage sein), nicht mehr "einmal Schwelle
     erreicht, für immer verfügbar" - Beispiel (Alle 2 Tage, zuletzt
     Montag eingeplant): Mittwoch (Differenz 2) und Freitag (Differenz 4)
     sind verfügbar, Dienstag/Donnerstag/Samstag nicht.
Eine Serie, die an einem bestimmten Tag schon eine eigene Instanz hat,
wird für GENAU diesen Tag nicht nochmal angeboten (unabhängig vom
Intervall/Wochentag) - Doppel-Einträge am selben Tag bleiben ausgeschlossen.
"""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, new_token, push_send, to_int, token_entschluesseln

bp  = Blueprint("todo_app", __name__)
APP = "todo"

STATUS_ORDER  = ["backlog", "offen", "in_arbeit", "erledigt"]
STATUS_LABELS = {"backlog": "Backlog", "offen": "Offen", "in_arbeit": "In Arbeit", "erledigt": "Erledigt"}
ROLLEN        = ["eltern", "kind", "gast"]
ROLLEN_LABELS = {"eltern": "Eltern", "kind": "Kind", "gast": "Gast"}
WOCHENTAGE    = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _darf_loeschen(user) -> bool:
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _rolle_passt(row, user) -> bool:
    """Wunsch #39: Rollen-/Alle-Zuweisung – passt die Rolle des Nutzers?"""
    rollen = row["zugewiesen_rollen"]
    if not rollen:
        return False
    return rollen == "alle" or user["rolle"] in rollen.split(",")


def _darf_erledigen(user, row) -> bool:
    if user["is_admin"] or user["rolle"] == "eltern":
        return True
    if row["erstellt_von"] == user["id"] or row["zugewiesen_an"] == user["id"]:
        return True
    return row["zugewiesen_an"] is None and _rolle_passt(row, user)


def _todo_url(db, user_id: int) -> str:
    row = db.execute("""
        SELECT g.token_enc FROM grants g JOIN apps a ON a.id=g.app_id
        WHERE g.user_id=? AND a.slug='todo'
    """, (user_id,)).fetchone()
    return f"https://portal.16schwaben.de/a/todo/{token_entschluesseln(row['token_enc'])}/" if row else ""


def todos_neu(inhalt: str, erstellt_von: int, zugewiesen_an: int = None,
              privat: bool = False, zugewiesen_rollen: str = None):
    """Programmatische Schnittstelle für andere Apps (z. B. Geholfen, Scanner).

    Ohne konkrete Personen-Zuweisung, aber mit Rollen/Alle-Ziel (Wunsch #39)
    landet die Aufgabe im Backlog statt in Offen."""
    db = get_db()
    status = "backlog" if (zugewiesen_an is None and zugewiesen_rollen) else "offen"
    db.execute(
        "INSERT INTO todos(inhalt,erstellt_von,zugewiesen_an,privat,zugewiesen_rollen,status) "
        "VALUES(?,?,?,?,?,?)",
        (inhalt, erstellt_von, zugewiesen_an, 1 if privat else 0, zugewiesen_rollen, status),
    )
    db.commit()
    if zugewiesen_an and zugewiesen_an != erstellt_von:
        push_send(zugewiesen_an, "Neue Aufgabe 📋", inhalt[:80], "todo",
                  _todo_url(db, zugewiesen_an))


def _visible_todos(db, user):
    uid   = user["id"]
    rolle = user["rolle"]
    if user["is_admin"] or rolle == "eltern":
        return db.execute("""
            SELECT t.*,
                   u1.name  AS von_name,  u1.farbe AS von_farbe,
                   u2.name  AS fuer_name, u2.farbe AS fuer_farbe
            FROM   todos t
            LEFT JOIN users u1 ON u1.id = t.erstellt_von
            LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
            ORDER BY t.erledigt ASC, t.erstellt DESC
        """).fetchall()
    rows = db.execute("""
        SELECT t.*,
               u1.name  AS von_name,  u1.farbe AS von_farbe,
               u2.name  AS fuer_name, u2.farbe AS fuer_farbe
        FROM   todos t
        LEFT JOIN users u1 ON u1.id = t.erstellt_von
        LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
        WHERE (t.zugewiesen_an = :uid OR t.erstellt_von = :uid
               OR (t.zugewiesen_an IS NULL AND t.zugewiesen_rollen IS NULL AND t.privat = 0))
          AND (t.privat = 0
               OR t.erstellt_von = :uid
               OR t.zugewiesen_an = :uid)
        ORDER BY t.erledigt ASC, t.erstellt DESC
    """, {"uid": uid}).fetchall()
    # Rollen-/Alle-Zuweisung (Wunsch #39) lässt sich nicht sauber in SQL mit
    # einer kommagetrennten Spalte matchen -- deshalb hier in Python filtern
    # und zur bereits geladenen Liste hinzufügen.
    rollen_rows = db.execute("""
        SELECT t.*,
               u1.name  AS von_name,  u1.farbe AS von_farbe,
               u2.name  AS fuer_name, u2.farbe AS fuer_farbe
        FROM   todos t
        LEFT JOIN users u1 ON u1.id = t.erstellt_von
        LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
        WHERE  t.zugewiesen_an IS NULL AND t.zugewiesen_rollen IS NOT NULL
               AND t.privat = 0 AND t.erstellt_von != :uid
    """, {"uid": uid}).fetchall()
    rows = list(rows)
    vorhandene_ids = {r["id"] for r in rows}
    for r in rollen_rows:
        if r["id"] not in vorhandene_ids and _rolle_passt(r, user):
            rows.append(r)
    # Zwei stabile Sortierungen statt ORDER BY in SQL, weil die Rollen-Zeilen
    # erst nachträglich in Python dazugemischt werden: erst nach erstellt
    # absteigend, dann nach erledigt aufsteigend (stabil -> Reihenfolge
    # innerhalb gleicher erledigt-Gruppen bleibt erhalten).
    rows.sort(key=lambda r: r["erstellt"], reverse=True)
    rows.sort(key=lambda r: r["erledigt"])
    return rows


def _historie_map(db, todo_ids):
    """Editierhistorie je Todo-ID, neueste zuerst (Wunsch #19)."""
    if not todo_ids:
        return {}
    platzhalter = ",".join("?" * len(todo_ids))
    rows = db.execute(f"""
        SELECT h.todo_id, h.alter_inhalt, h.geaendert_am, u.name AS geaendert_von_name
        FROM   todo_historie h
        LEFT JOIN users u ON u.id = h.geaendert_von
        WHERE  h.todo_id IN ({platzhalter})
        ORDER  BY h.geaendert_am DESC
    """, todo_ids).fetchall()
    historie = {}
    for r in rows:
        historie.setdefault(r["todo_id"], []).append(r)
    return historie


@bp.route("/a/todo/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db    = get_db()
    todos = _visible_todos(db, user)
    users = db.execute(
        "SELECT id, name, farbe FROM users ORDER BY name"
    ).fetchall()
    return render_template("todo.html",
        user=user, token=token, farbe=user["farbe"],
        todos=todos, users=users,
        darf_loeschen=_darf_loeschen(user),
        historie=_historie_map(db, [t["id"] for t in todos]),
        status_order=STATUS_ORDER, status_labels=STATUS_LABELS,
        rollen=ROLLEN, rollen_labels=ROLLEN_LABELS,
    )


@bp.route("/a/todo/<token>/neu", methods=["POST"])
def neu(token):
    """Wunsch #39: Ziel ist entweder eine Person (wie bisher, inkl. Leerwert
    "für mich"/niemand Bestimmtes), oder eine/mehrere Rollen, oder "alle" –
    Letzteres landet initial im Backlog statt in Offen."""
    user = check_grant(token, APP)
    if not user:
        abort(403)
    inhalt = request.form.get("inhalt", "").strip()
    if not inhalt:
        return redirect(url_for("todo_app.index", token=token))

    ziel_typ          = request.form.get("ziel_typ", "person")
    zugewiesen_an     = None
    zugewiesen_rollen = None
    db = get_db()
    if ziel_typ == "rollen":
        gewaehlt = [r for r in request.form.getlist("rollen") if r in ROLLEN]
        if gewaehlt:
            zugewiesen_rollen = ",".join(sorted(set(gewaehlt)))
    elif ziel_typ == "alle":
        zugewiesen_rollen = "alle"
    else:
        zugewiesen_an = to_int(request.form.get("zugewiesen_an"))
        if zugewiesen_an is not None and not db.execute(
            "SELECT 1 FROM users WHERE id=?", (zugewiesen_an,)
        ).fetchone():
            zugewiesen_an = None

    privat = 1 if request.form.get("privat") else 0
    todos_neu(inhalt, user["id"], zugewiesen_an, bool(privat), zugewiesen_rollen)
    return redirect(url_for("todo_app.index", token=token))


@bp.route("/a/todo/<token>/status/<int:tid>", methods=["POST"])
def set_status(token, tid):
    """Wunsch #20: 4 Status-Stufen statt einfachem Abhaken-Toggle."""
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()
    if not row:
        abort(404)
    if not _darf_erledigen(user, row):
        abort(403)
    status = request.form.get("status", "")
    if status not in STATUS_ORDER:
        abort(400)
    erledigt = 1 if status == "erledigt" else 0
    db.execute(
        "UPDATE todos SET status=?, erledigt=?, "
        "erledigt_am=CASE WHEN ?=1 THEN datetime('now') ELSE NULL END WHERE id=?",
        (status, erledigt, erledigt, tid),
    )
    db.commit()
    return redirect(url_for("todo_app.index", token=token))


@bp.route("/a/todo/<token>/bearbeiten/<int:tid>", methods=["POST"])
def bearbeiten(token, tid):
    """Wunsch #43: alle Felder bearbeitbar, gleiche UX (Person/Rolle(n)/Alle,
    Privat) wie beim Anlegen – nicht nur der Text wie bisher. Der Status
    bleibt beim Bearbeiten unangetastet, auch wenn das Ziel wechselt (nur
    beim NEU-Anlegen landet ein Rollen/Alle-Ziel im Backlog, Wunsch #39)."""
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()
    if not row:
        abort(404)
    if not _darf_erledigen(user, row):
        abort(403)

    neuer_inhalt = request.form.get("inhalt", "").strip()
    if neuer_inhalt and neuer_inhalt != row["inhalt"]:
        db.execute(
            "INSERT INTO todo_historie(todo_id, alter_inhalt, geaendert_von) VALUES(?,?,?)",
            (tid, row["inhalt"], user["id"]),
        )
        db.execute("UPDATE todos SET inhalt=? WHERE id=?", (neuer_inhalt, tid))

    ziel_typ          = request.form.get("ziel_typ", "person")
    zugewiesen_an     = None
    zugewiesen_rollen = None
    if ziel_typ == "rollen":
        gewaehlt = [r for r in request.form.getlist("rollen") if r in ROLLEN]
        if gewaehlt:
            zugewiesen_rollen = ",".join(sorted(set(gewaehlt)))
    elif ziel_typ == "alle":
        zugewiesen_rollen = "alle"
    else:
        zugewiesen_an = to_int(request.form.get("zugewiesen_an"))
        if zugewiesen_an is not None and not db.execute(
            "SELECT 1 FROM users WHERE id=?", (zugewiesen_an,)
        ).fetchone():
            zugewiesen_an = None
    privat = 1 if request.form.get("privat") else 0

    db.execute(
        "UPDATE todos SET zugewiesen_an=?, zugewiesen_rollen=?, privat=? WHERE id=?",
        (zugewiesen_an, zugewiesen_rollen, privat, tid),
    )
    db.commit()
    return redirect(url_for("todo_app.index", token=token))


@bp.route("/a/todo/<token>/loeschen/<int:tid>", methods=["POST"])
def loeschen(token, tid):
    user = check_grant(token, APP)
    if not user or not _darf_loeschen(user):
        abort(403)
    db = get_db()
    if not db.execute("SELECT 1 FROM todos WHERE id=?", (tid,)).fetchone():
        abort(404)
    db.execute("DELETE FROM todos WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("todo_app.index", token=token))


def _wochentage_menge(serie):
    """Parst feste_wochentage ('1,3,5') zu einer Menge von int-Wochentagen
    (0=Mo..6=So). Fällt auf das alte fester_wochentag zurück, falls eine
    Serie aus der Zeit vor Wunsch #112 noch nicht migriert wurde (sollte
    durch die Backfill-Migration in 00_kern.py eigentlich nicht vorkommen,
    schadet als zusätzliche Absicherung aber nicht)."""
    roh = serie["feste_wochentage"]
    if roh is None or roh == "":
        roh = serie["fester_wochentag"]
    if roh is None:
        return set()
    return {int(w) for w in str(roh).split(",") if str(w).strip() != ""}


def serie_verfuegbar_am(db, serie, tag_iso) -> bool:
    """True, wenn diese Vorlage für GENAU diesen Kalendertag als Pool-
    Kandidat infrage kommt (Wunsch #113). Zwei Regeln:
    1. Es existiert noch keine eigene Instanz dieser Serie an GENAU diesem
       Tag (unabhängig vom Status) - kein Doppel-Eintrag am selben Tag.
    2. 'wochentag': der Tag muss einer der konfigurierten Wochentage sein
       (Wunsch #112, mehrere möglich) - kein Abstands-Anker nötig, jede
       Woche mit passendem Wochentag zählt unabhängig für sich.
       'intervall': die Differenz zum zuletzt EINGEPLANTEN Tag (nicht mehr
       zum Erledigt-Zeitpunkt, siehe Docstring am Dateianfang) muss ein
       positives Vielfaches von intervall_tage sein - periodische
       Wiederkehr statt "einmal fällig, für immer verfügbar"."""
    schon_an_diesem_tag = db.execute(
        "SELECT 1 FROM todos WHERE serie_id=? AND plan_tag=?", (serie["id"], tag_iso)
    ).fetchone()
    if schon_an_diesem_tag:
        return False

    tag_datum = date.fromisoformat(tag_iso)
    if serie["wiederkehr_typ"] == "wochentag":
        return tag_datum.weekday() in _wochentage_menge(serie)

    letzter = db.execute(
        "SELECT plan_tag FROM todos WHERE serie_id=? AND plan_tag IS NOT NULL "
        "ORDER BY plan_tag DESC LIMIT 1", (serie["id"],)
    ).fetchone()
    if not letzter or not letzter["plan_tag"]:
        return True  # noch nie eingeplant -> jeder Tag kommt als Start infrage
    differenz = (tag_datum - date.fromisoformat(letzter["plan_tag"])).days
    intervall = serie["intervall_tage"] or 1
    return differenz > 0 and differenz % intervall == 0


def serien_pool_fuer_tag(db, tag_iso, alle_serien=None):
    """Alle aktiven Vorlagen, die für GENAU diesen Kalendertag als Pool-
    Kandidat infrage kommen - Schnittstelle für die Aufgabenplanung
    (kinderplan), pro sichtbarem Tag separat aufgerufen (Wunsch #113).
    `alle_serien` optional vorab geladen übergeben, um die Serien-Tabelle
    nicht 14x (einmal je sichtbarem Tag) neu abzufragen."""
    if alle_serien is None:
        alle_serien = db.execute(
            "SELECT * FROM todo_serien WHERE aktiv=1 ORDER BY inhalt COLLATE NOCASE"
        ).fetchall()
    return [s for s in alle_serien if serie_verfuegbar_am(db, s, tag_iso)]


def serie_einsortieren(db, serie_id, ziel_user_id, plan_tag, erstellt_von_user_id):
    """Erzeugt aus einer Pool-Vorlage eine konkrete Todo-Instanz für eine
    Person an einem echten Kalendertag (Wunsch #92: plan_tag ISO-Datum,
    vorher wochentag 0-6) - Schnittstelle für die Aufgabenplanung."""
    serie = db.execute("SELECT * FROM todo_serien WHERE id=? AND aktiv=1", (serie_id,)).fetchone()
    if not serie or not serie_verfuegbar_am(db, serie, plan_tag):
        return False
    db.execute(
        "INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, serie_id, plan_tag, status) "
        "VALUES(?,?,?,?,?,'offen')",
        (serie["inhalt"], erstellt_von_user_id, ziel_user_id, serie_id, plan_tag),
    )
    db.commit()
    return True


@bp.route("/a/todo/<token>/serien", methods=["GET", "POST"])
def serien(token):
    """Verwaltung der wiederkehrenden Aufgaben-Vorlagen (Wunsch #90) - die
    Einsortierung in Wochentage passiert in der Aufgabenplanung, nicht hier."""
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            inhalt = request.form.get("inhalt", "").strip()
            typ = request.form.get("wiederkehr_typ")
            if inhalt and typ in ("intervall", "wochentag"):
                intervall_tage = to_int(request.form.get("intervall_tage")) if typ == "intervall" else None
                # Wunsch #112: mehrere Wochentage gleichzeitig moeglich -
                # kommagetrennte Liste aus dem Hidden-Feld statt eines
                # einzelnen Werts, serverseitig auf gueltige 0-6-Werte geprueft.
                wochentage_roh = request.form.get("feste_wochentage", "") if typ == "wochentag" else ""
                wochentage_liste = sorted({
                    w for w in (to_int(t) for t in wochentage_roh.split(",")) if w is not None and 0 <= w <= 6
                })
                feste_wochentage = ",".join(str(w) for w in wochentage_liste) or None
                gueltig = (typ == "intervall" and intervall_tage and intervall_tage > 0) or \
                          (typ == "wochentag" and feste_wochentage is not None)
                if gueltig:
                    db.execute(
                        "INSERT INTO todo_serien(inhalt, wiederkehr_typ, intervall_tage, feste_wochentage, erstellt_von) "
                        "VALUES(?,?,?,?,?)",
                        (inhalt, typ, intervall_tage, feste_wochentage, user["id"]),
                    )
                    db.commit()
        elif action == "toggle":
            sid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM todo_serien WHERE id=?", (sid,)).fetchone()
            if row:
                db.execute("UPDATE todo_serien SET aktiv=? WHERE id=?", (0 if row["aktiv"] else 1, sid))
                db.commit()
        elif action == "loeschen" and _darf_loeschen(user):
            sid = to_int(request.form.get("id"), 0)
            db.execute("DELETE FROM todo_serien WHERE id=?", (sid,))
            db.commit()
        return redirect(url_for("todo_app.serien", token=token))

    alle_serien = db.execute(
        "SELECT * FROM todo_serien ORDER BY aktiv DESC, inhalt COLLATE NOCASE"
    ).fetchall()
    # "im Pool"-Badge bezieht sich auf HEUTE als Referenztag (Wunsch #113:
    # Verfuegbarkeit ist jetzt pro Kalendertag, nicht mehr global) - reine
    # Anzeige-Vereinfachung fuer diese Verwaltungsseite, die eigentliche
    # Tag-fuer-Tag-Pruefung passiert in der Aufgabenplanung.
    heute_iso = date.today().isoformat()
    im_pool = {s["id"] for s in alle_serien if s["aktiv"] and serie_verfuegbar_am(db, s, heute_iso)}
    # Wunsch #112: mehrere Wochentage je Serie - Anzeige-String ("Montag,
    # Mittwoch") hier vorberechnen statt mit verschachtelten Jinja-Filtern
    # im Template zu basteln.
    serien_liste = []
    for s in alle_serien:
        s_dict = dict(s)
        if s["wiederkehr_typ"] == "wochentag":
            indices = sorted(_wochentage_menge(s))
            s_dict["wochentag_anzeige"] = ", ".join(WOCHENTAGE[i] for i in indices)
        serien_liste.append(s_dict)
    return render_template("todo_serien.html",
        user=user, token=token, farbe=user["farbe"],
        serien=serien_liste, im_pool=im_pool, darf_loeschen=_darf_loeschen(user),
        wochentage=WOCHENTAGE,
    )


def init_app(app):
    app.register_blueprint(bp)
