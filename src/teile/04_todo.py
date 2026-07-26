"""
Todo-App – Aufgaben anlegen, zuweisen, abhaken.
URL-Präfix: /a/todo/<token>/

Andere Module können todos_neu() aufrufen, um programmatisch Todos zu erstellen.
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import get_db, grant as check_grant, new_token, push_send

bp  = Blueprint("todo_app", __name__)
APP = "todo"


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
        push_send(zugewiesen_an, "Neues Todo 📋", inhalt[:80], "todo",
                  _todo_url(db, zugewiesen_an))


def _visible_todos(db, user_id):
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
    """, {"uid": user_id}).fetchall()


@bp.route("/a/todo/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db    = get_db()
    todos = _visible_todos(db, user["id"])
    users = db.execute(
        "SELECT id, name, farbe FROM users ORDER BY name"
    ).fetchall()
    return render_template("todo.html",
        user=user, token=token, farbe=user["farbe"],
        todos=todos, users=users,
    )


@bp.route("/a/todo/<token>/neu", methods=["POST"])
def neu(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    inhalt = request.form.get("inhalt", "").strip()
    if not inhalt:
        return redirect(url_for("todo_app.index", token=token))
    zugewiesen_an = request.form.get("zugewiesen_an") or None
    if zugewiesen_an:
        zugewiesen_an = int(zugewiesen_an)
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
    # Nur Besitzer oder Zugewiesener darf abhaken
    if row["erstellt_von"] != user["id"] and row["zugewiesen_an"] != user["id"]:
        if not user["is_admin"]:
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
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute("SELECT erstellt_von FROM todos WHERE id=?", (tid,)).fetchone()
    if not row:
        abort(404)
    if row["erstellt_von"] != user["id"] and not user["is_admin"]:
        abort(403)
    db.execute("DELETE FROM todos WHERE id=?", (tid,))
    db.commit()
    return redirect(url_for("todo_app.index", token=token))


def init_app(app):
    app.register_blueprint(bp)
