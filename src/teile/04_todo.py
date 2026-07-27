"""
Todo-App – Aufgaben anlegen, zuweisen, abhaken.
URL-Präfix: /a/todo/<token>/

Andere Module können todos_neu() aufrufen, um programmatisch Todos zu erstellen.

Berechtigungen (Wunsch #10):
  Erstellen  – alle Nutzer
  Abhaken    – Eltern/Admin: jedes Todo; Kind/Gast: nur eigene (erstellt oder zugewiesen)
  Löschen    – nur Eltern/Admin
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, new_token, push_send, to_int

bp  = Blueprint("todo_app", __name__)
APP = "todo"


def _darf_loeschen(user) -> bool:
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _darf_erledigen(user, row) -> bool:
    if user["is_admin"] or user["rolle"] == "eltern":
        return True
    return row["erstellt_von"] == user["id"] or row["zugewiesen_an"] == user["id"]


def _todo_url(db, user_id: int) -> str:
    row = db.execute("""
        SELECT g.token FROM grants g JOIN apps a ON a.id=g.app_id
        WHERE g.user_id=? AND a.slug='todo'
    """, (user_id,)).fetchone()
    return f"https://portal.16schwaben.de/a/todo/{row['token']}/" if row else ""


def todos_neu(inhalt: str, erstellt_von: int, zugewiesen_an: int = None,
              privat: bool = False):
    """Programmatische Schnittstelle für andere Apps (z. B. Geholfen, Scanner)."""
    db = get_db()
    db.execute(
        "INSERT INTO todos(inhalt,erstellt_von,zugewiesen_an,privat) VALUES(?,?,?,?)",
        (inhalt, erstellt_von, zugewiesen_an, 1 if privat else 0),
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
    return db.execute("""
        SELECT t.*,
               u1.name  AS von_name,  u1.farbe AS von_farbe,
               u2.name  AS fuer_name, u2.farbe AS fuer_farbe
        FROM   todos t
        LEFT JOIN users u1 ON u1.id = t.erstellt_von
        LEFT JOIN users u2 ON u2.id = t.zugewiesen_an
        WHERE (t.zugewiesen_an = :uid OR t.erstellt_von = :uid
               OR (t.zugewiesen_an IS NULL AND t.privat = 0))
          AND (t.privat = 0
               OR t.erstellt_von = :uid
               OR t.zugewiesen_an = :uid)
        ORDER BY t.erledigt ASC, t.erstellt DESC
    """, {"uid": uid}).fetchall()


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
    )


@bp.route("/a/todo/<token>/neu", methods=["POST"])
def neu(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    inhalt = request.form.get("inhalt", "").strip()
    if not inhalt:
        return redirect(url_for("todo_app.index", token=token))
    zugewiesen_an = to_int(request.form.get("zugewiesen_an"))
    if zugewiesen_an is not None and not get_db().execute(
        "SELECT 1 FROM users WHERE id=?", (zugewiesen_an,)
    ).fetchone():
        zugewiesen_an = None
    privat = 1 if request.form.get("privat") else 0
    todos_neu(inhalt, user["id"], zugewiesen_an, bool(privat))
    return redirect(url_for("todo_app.index", token=token))


@bp.route("/a/todo/<token>/check/<int:tid>", methods=["POST"])
def check(token, tid):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()
    if not row:
        abort(404)
    if not _darf_erledigen(user, row):
        abort(403)
    if row["erledigt"]:
        db.execute("UPDATE todos SET erledigt=0, erledigt_am=NULL WHERE id=?", (tid,))
    else:
        db.execute("UPDATE todos SET erledigt=1, erledigt_am=datetime('now') WHERE id=?", (tid,))
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
