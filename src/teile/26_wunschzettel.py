"""
Wunschzettel (Wunsch #251) - Geschenkwuensche der Familie, als Vorbereitung
auf Weihnachten und Geburtstage. URL-Praefix: /a/wunschzettel/<token>/

Der Wunsch verlangt zwei Dinge: sehr einfaches Erfassen, und dass die
anderen die Wuensche sehen. Dazu kommt die eine Regel, ohne die eine
Familien-Wunschliste ihren Zweck verfehlt:

**Der Wuenschende erfaehrt NICHT, ob und von wem ein Wunsch reserviert ist.**
Sonst weiss er vor Heiligabend, was er bekommt. Alle ANDEREN sehen die
Reservierung - genau dafuer ist sie da: verhindern, dass zwei Leute dasselbe
kaufen. Durchgesetzt wird das hier in den Routen (die Daten verlassen den
Server fuer den Wuenschenden gar nicht erst), nicht per if in der Vorlage.

Reservieren ist ein reversibler Umschalter (kein confirm, Konvention):
freigeben kann nur, wer reserviert hat - oder ein Admin, falls jemand die
Familie verlaesst oder ein Handy verloren geht.
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for

from teile.kern import antwort_oder_weiter, get_db, utc_zu_lokal_datum
from teile.kern import grant as check_grant

bp  = Blueprint("wunschzettel_app", __name__)
APP = "wunschzettel"

MAX_TEXT = 300


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _link_ok(wert):
    """Nur echte Web-Adressen - alles andere (auch javascript:) wird
    verworfen statt gespeichert. Ein leerer Link ist einfach keiner."""
    wert = (wert or "").strip()
    if wert.startswith(("http://", "https://")) and len(wert) <= 500:
        return wert
    return None


@bp.route("/a/wunschzettel/", defaults={"token": None})
@bp.route("/a/wunschzettel/<token>/")
def index(token):
    user = _user(token)
    db = get_db()
    zeilen = db.execute("""
        SELECT w.id, w.user_id, w.text, w.link, w.erstellt, w.reserviert_von,
               u.name AS wuenscher, u.farbe AS wuenscher_farbe,
               r.name AS reserviert_name
        FROM   wunschzettel w
        JOIN   users u ON u.id = w.user_id
        LEFT   JOIN users r ON r.id = w.reserviert_von
        ORDER  BY u.name COLLATE NOCASE, w.erstellt DESC, w.id DESC
    """).fetchall()

    meine, fremde = [], {}
    for z in zeilen:
        d = {
            "id": z["id"], "text": z["text"], "link": z["link"],
            "datum": utc_zu_lokal_datum(z["erstellt"]),
        }
        if z["user_id"] == user["id"]:
            # Die Ueberraschungs-Regel: KEINE Reservierungsfelder. Was hier
            # nicht ins dict kommt, kann keine Vorlage verraten.
            meine.append(d)
        else:
            d["reserviert"] = z["reserviert_von"] is not None
            d["von_mir_reserviert"] = z["reserviert_von"] == user["id"]
            d["reserviert_name"] = z["reserviert_name"]
            d["darf_loeschen"] = bool(user["is_admin"])
            gruppe = fremde.setdefault(z["user_id"], {
                "name": z["wuenscher"], "farbe": z["wuenscher_farbe"],
                "wuensche": [],
            })
            gruppe["wuensche"].append(d)

    return render_template("wunschzettel.html",
        user=user, token=token, farbe=user["farbe"],
        meine=meine, fremde=list(fremde.values()))


@bp.route("/a/wunschzettel/neu", defaults={"token": None}, methods=["POST"])
@bp.route("/a/wunschzettel/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    text = (request.form.get("text") or "").strip()[:MAX_TEXT]
    if text:
        db = get_db()
        db.execute(
            "INSERT INTO wunschzettel(user_id, text, link) VALUES(?,?,?)",
            (user["id"], text, _link_ok(request.form.get("link"))))
        db.commit()
    return redirect(url_for("wunschzettel_app.index", token=token))


@bp.route("/a/wunschzettel/<int:wid>/bearbeiten", defaults={"token": None}, methods=["POST"])
@bp.route("/a/wunschzettel/<token>/<int:wid>/bearbeiten", methods=["POST"])
def bearbeiten(token, wid):
    user = _user(token)
    db = get_db()
    zeile = db.execute("SELECT user_id FROM wunschzettel WHERE id=?", (wid,)).fetchone()
    if not zeile:
        abort(404)
    # Bearbeiten nur der Wuenschende selbst - auch kein Admin: Auf einem
    # fremden Zettel hat niemand Wuensche umzuformulieren.
    if zeile["user_id"] != user["id"]:
        abort(403)
    text = (request.form.get("text") or "").strip()[:MAX_TEXT]
    if text:
        db.execute("UPDATE wunschzettel SET text=?, link=? WHERE id=?",
                   (text, _link_ok(request.form.get("link")), wid))
        db.commit()
    return redirect(url_for("wunschzettel_app.index", token=token) + f"#wz-{wid}")


@bp.route("/a/wunschzettel/<int:wid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/wunschzettel/<token>/<int:wid>/loeschen", methods=["POST"])
def loeschen(token, wid):
    user = _user(token)
    db = get_db()
    zeile = db.execute("SELECT user_id FROM wunschzettel WHERE id=?", (wid,)).fetchone()
    if not zeile:
        abort(404)
    if zeile["user_id"] != user["id"] and not user["is_admin"]:
        abort(403)
    db.execute("DELETE FROM wunschzettel WHERE id=?", (wid,))
    db.commit()
    return redirect(url_for("wunschzettel_app.index", token=token))


@bp.route("/a/wunschzettel/<int:wid>/reservieren", defaults={"token": None}, methods=["POST"])
@bp.route("/a/wunschzettel/<token>/<int:wid>/reservieren", methods=["POST"])
def reservieren(token, wid):
    """Umschalter: reservieren bzw. wieder freigeben.

    - Der Wuenschende selbst darf NIE (403) - sonst koennte er per Antwort
      auch nur erfahren, dass es diese Route fuer ihn gibt.
    - Reservieren geht nur, wenn frei; freigeben nur, wer selbst reserviert
      hat (oder Admin). Wer fremde Reservierungen umwerfen koennte, machte
      die Absprache wertlos.
    """
    user = _user(token)
    db = get_db()
    zeile = db.execute(
        "SELECT user_id, reserviert_von FROM wunschzettel WHERE id=?", (wid,)
    ).fetchone()
    if not zeile:
        abort(404)
    if zeile["user_id"] == user["id"]:
        abort(403)

    if zeile["reserviert_von"] is None:
        db.execute("UPDATE wunschzettel SET reserviert_von=? WHERE id=?",
                   (user["id"], wid))
        reserviert, von_mir = True, True
    elif zeile["reserviert_von"] == user["id"] or user["is_admin"]:
        db.execute("UPDATE wunschzettel SET reserviert_von=NULL WHERE id=?", (wid,))
        reserviert, von_mir = False, False
    else:
        abort(403)
    db.commit()
    ziel = url_for("wunschzettel_app.index", token=token) + f"#wz-{wid}"
    return antwort_oder_weiter(ziel, id=wid, reserviert=reserviert, von_mir=von_mir)


def init_app(app):
    app.register_blueprint(bp)
