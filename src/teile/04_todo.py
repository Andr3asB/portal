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
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, new_token, push_send, to_int

bp  = Blueprint("todo_app", __name__)
APP = "todo"

STATUS_ORDER  = ["backlog", "offen", "in_arbeit", "erledigt"]
STATUS_LABELS = {"backlog": "Backlog", "offen": "Offen", "in_arbeit": "In Arbeit", "erledigt": "Erledigt"}
ROLLEN        = ["eltern", "kind", "gast"]
ROLLEN_LABELS = {"eltern": "Eltern", "kind": "Kind", "gast": "Gast"}


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
        SELECT g.token FROM grants g JOIN apps a ON a.id=g.app_id
        WHERE g.user_id=? AND a.slug='todo'
    """, (user_id,)).fetchone()
    return f"https://portal.16schwaben.de/a/todo/{row['token']}/" if row else ""


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


def init_app(app):
    app.register_blueprint(bp)
