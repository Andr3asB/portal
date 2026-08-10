"""
Werkstatt-App – Übersicht und Verwaltung aller Verbesserungswünsche.
URL-Präfix: /a/werkstatt/<token>/

Die Erfassung selbst läuft über 02_werkstatt.py (POST /wunsch).

WICHTIGE REGEL (Wunsch #61): Wünsche mit prioritaet='zurueckgestellt'
dürfen NIEMALS automatisiert umgesetzt werden – auch nicht, wenn die
Anweisung lautet "implementiere alle Wünsche" oder ähnlich pauschal
formuliert ist. Diese Regel gilt uneingeschränkt für jede KI, die an
diesem Projekt arbeitet. Ein Admin muss die Priorität eines
zurückgestellten Wunsches erst ändern, bevor er umgesetzt werden darf.

Wunsch #101: `wuensche.umsetzung` dokumentiert, was bei der Implementierung
genau gemacht wurde - wird über `manage.py wunsch_erledigt <id> "Text"`
gesetzt (siehe manage.py), nicht über die Web-UI. Klickt man in der
Werkstatt-App auf einen Wunsch, klappt eine Detailansicht mit Wunsch,
Benutzer, Wunsch-/Implementierungsdatum und dieser Umsetzung auf.
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import (get_db, grant as check_grant, to_int, push_send,
                        antwort_oder_weiter, WUNSCH_PRIORITAETEN)
# Wunsch #187: Ersatz-Ueberschrift aus dem Wunschtext. Sie steht in
# 02_werkstatt.py, wo auch der KI-Titel entsteht - zwei Regeln fuer dieselbe
# Ueberschrift an zwei Orten waeren genau das Duplikat, das auseinanderlaeuft.
from teile.werkstatt import ersatz_titel

bp  = Blueprint("werkstatt_app", __name__)
APP = "werkstatt"

_PRIORITAETEN = WUNSCH_PRIORITAETEN   # Wunsch #152: eine Liste, im Kern

# Wunsch #141: lesbare Beschriftung für die Filter-Chips. "" = Wunsch ohne
# gesetzte Priorität (kommt bei frisch eingereichten Wünschen vor).
_PRIO_LABELS = {
    "sehr_hoch":       "Sehr hoch",
    "hoch":            "Hoch",
    "mittel":          "Mittel",
    "niedrig":         "Niedrig",
    "zurueckgestellt": "Zurückgestellt",
    "":                "Ohne Priorität",
}

_PRIO_ORDER = """
    CASE w.prioritaet
        WHEN 'sehr_hoch'       THEN 1
        WHEN 'hoch'            THEN 2
        WHEN 'mittel'          THEN 3
        WHEN 'niedrig'         THEN 4
        WHEN 'zurueckgestellt' THEN 6
        ELSE 5
    END ASC, w.erstellt DESC
"""

_SELECT = """
    SELECT w.id, w.text, w.titel, w.prioritaet, w.app_slug, w.ansicht,
           w.erstellt, w.erledigt, w.erledigt_am, w.umsetzung,
           u.name AS urheber_name, u.farbe AS urheber_farbe
    FROM   wuensche w
    LEFT JOIN users u ON u.id = w.user_id
"""


def _de_datum(ts):
    """Wunsch #101: 'YYYY-MM-DD HH:MM:SS' -> 'DD.MM.YYYY, HH:MM Uhr' fuer die
    gut lesbare Detailansicht - die Rohwerte aus SQLite sind sonst nur als
    ISO-Zeichenkette abgelegt, kein echtes datetime-Objekt."""
    if not ts or len(ts) < 16:
        return ts or ""
    return f"{ts[8:10]}.{ts[5:7]}.{ts[0:4]}, {ts[11:16]} Uhr"


@bp.route("/a/werkstatt/", defaults={"token": None})
@bp.route("/a/werkstatt/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    offen = db.execute(
        _SELECT + " WHERE w.erledigt = 0 ORDER BY " + _PRIO_ORDER
    ).fetchall()
    erledigt = db.execute(
        _SELECT + " WHERE w.erledigt = 1 ORDER BY COALESCE(w.erledigt_am, w.erstellt) DESC"
    ).fetchall()

    # Wunsch #141: Filterkriterien. Bewusst NUR aus den tatsächlich
    # vorkommenden Werten gebaut statt aus festen Listen - eine App oder ein
    # Urheber ohne Wünsche liefert sonst einen Knopf, der nie etwas trifft.
    # Gefiltert wird dann im Browser (gleiches Muster wie die Aufgaben-App),
    # deshalb reichen hier die Auswahlwerte.
    alle = list(offen) + list(erledigt)
    prios_vorhanden = [p for p in _PRIORITAETEN
                       if any((w["prioritaet"] or "") == p for w in alle)]
    if any(not w["prioritaet"] for w in alle):
        prios_vorhanden.append("")          # "ohne Priorität"
    apps_vorhanden = sorted({w["app_slug"] for w in alle if w["app_slug"]})
    urheber_vorhanden = sorted({w["urheber_name"] for w in alle if w["urheber_name"]})

    return render_template("werkstatt_app.html",
        user=user, token=token, farbe=user["farbe"],
        offen=offen, erledigt=erledigt,
        aktionen=_aktionen_je_wunsch(db), aktions_arten=AKTIONS_ARTEN,
        urheber_ids=_urheber_ids(db),
        prios_vorhanden=prios_vorhanden, prio_labels=_PRIO_LABELS,
        apps_vorhanden=apps_vorhanden, urheber_vorhanden=urheber_vorhanden,
        ersatz_titel=ersatz_titel,
    )


@bp.route("/a/werkstatt/erledigt/<int:wid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/werkstatt/<token>/erledigt/<int:wid>", methods=["POST"])
def toggle_erledigt(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    row = db.execute("SELECT erledigt FROM wuensche WHERE id=?", (wid,)).fetchone()
    if not row:
        abort(404)
    if row["erledigt"]:
        db.execute("UPDATE wuensche SET erledigt=0, erledigt_am=NULL WHERE id=?", (wid,))
    else:
        db.execute(
            "UPDATE wuensche SET erledigt=1, erledigt_am=CURRENT_TIMESTAMP WHERE id=?", (wid,)
        )
    db.commit()
    # Wunsch #171: bei 170 Wuenschen sprang die Seite nach jedem Haken an den
    # Anfang zurueck - man verlor die Stelle, an der man gerade war.
    # Wunsch #171: Anker statt Seitenanfang. Ein fetch waere hier falsch: Der
    # Haken verschiebt den Wunsch zwischen "offen" und "erledigt", die Liste
    # muss also ohnehin neu sortiert werden. Eine Karte, die an Ort und Stelle
    # umspringt, zeigte eine veraltete Reihenfolge - schlimmer als ein Sprung.
    return redirect(url_for("werkstatt_app.index", token=token) + f"#wunsch-{wid}")


@bp.route("/a/werkstatt/loeschen/<int:wid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/werkstatt/<token>/loeschen/<int:wid>", methods=["POST"])
def loeschen(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    db.execute("DELETE FROM wuensche WHERE id=?", (wid,))
    db.commit()
    return redirect(url_for("werkstatt_app.index", token=token))


@bp.route("/a/werkstatt/prioritaet/<int:wid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/werkstatt/<token>/prioritaet/<int:wid>", methods=["POST"])
def prioritaet(token, wid):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    prio = request.form.get("prioritaet", "")
    if prio not in _PRIORITAETEN:
        prio = None
    db = get_db()
    if not db.execute("SELECT id FROM wuensche WHERE id=?", (wid,)).fetchone():
        abort(404)
    db.execute("UPDATE wuensche SET prioritaet=? WHERE id=?", (prio, wid))
    db.commit()
    # Wunsch #171: Anker statt Seitenanfang - die Prioritaet bestimmt die
    # Sortierung, die Liste muss neu gebaut werden (siehe toggle_erledigt).
    return redirect(url_for("werkstatt_app.index", token=token) + f"#wunsch-{wid}")


# Wunsch #161: Die Werkstatt wird zum Ticketsystem. Jede Handlung an einem
# Wunsch - Plan, Rueckfrage, Antwort, Umsetzung - ist eine eigene Zeile mit
# Zeitpunkt und Urheber, statt in einem einzigen Freitextfeld zu verschwinden.
AKTIONS_ARTEN = {
    "frage":     ("❓", "Rückfrage"),
    "antwort":   ("💬", "Antwort"),
    "plan":      ("📋", "Plan"),
    "umsetzung": ("🔨", "Umsetzung"),
    "notiz":     ("📝", "Notiz"),
}


def _aktionen_je_wunsch(db):
    """{wunsch_id: [aktion, ...]} - alle auf einmal statt je Wunsch einzeln.

    Die Werkstatt zeigt gut 160 Wuensche auf einer Seite; eine Abfrage je
    Wunsch waeren 160 Abfragen fuer eine Liste, in der die meisten gar keine
    Aktionen haben."""
    aus = {}
    for r in db.execute("""
        SELECT a.id, a.wunsch_id, a.art, a.text, a.erstellt,
               u.name AS wer, u.farbe AS wer_farbe
        FROM   wunsch_aktionen a
        LEFT   JOIN users u ON u.id = a.user_id
        ORDER  BY a.erstellt ASC, a.id ASC
    """):
        aus.setdefault(r["wunsch_id"], []).append(dict(r))
    return aus


def _urheber_ids(db):
    """{wunsch_id: user_id} - fuer die Frage, wer eine Aktion anlegen darf."""
    return {r["id"]: r["user_id"]
            for r in db.execute("SELECT id, user_id FROM wuensche")}


@bp.route("/a/werkstatt/aktion/<int:wid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/werkstatt/<token>/aktion/<int:wid>", methods=["POST"])
def aktion_neu(token, wid):
    """Eine Aktion an einen Wunsch haengen - z.B. eine Rueckfrage beantworten.

    Erlaubt fuer Admins UND fuer den Urheber des Wunsches. Genau darum geht es
    im Wunsch: Wer etwas eingetragen hat, soll auf Rueckfragen antworten
    koennen, ohne dafuer Admin sein zu muessen. Alle uebrigen duerfen die
    Werkstatt lesen, aber nicht in fremde Vorgaenge hineinschreiben.
    """
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute("SELECT user_id FROM wuensche WHERE id=?", (wid,)).fetchone()
    if not row:
        abort(404)
    if not (user["is_admin"] or row["user_id"] == user["id"]):
        abort(403)

    art  = (request.form.get("art") or "antwort").strip()
    text = (request.form.get("text") or "").strip()[:2000]
    if art not in AKTIONS_ARTEN or not text:
        return redirect(url_for("werkstatt_app.index", token=token) + f"#wunsch-{wid}")

    db.execute(
        "INSERT INTO wunsch_aktionen(wunsch_id, art, text, user_id) VALUES(?,?,?,?)",
        (wid, art, text, user["id"]))
    db.commit()

    if art == "frage":
        _admins_benachrichtigen(db, user, wid, text)

    return redirect(url_for("werkstatt_app.index", token=token) + f"#wunsch-{wid}")


def _admins_benachrichtigen(db, absender, wid, text):
    """Wunsch #166: Eine Rueckfrage soll nicht unbemerkt liegen bleiben.

    Nur bei art='frage' - eine Antwort oder Notiz zu melden wuerde die
    Meldungen entwerten, und dann schaut irgendwann niemand mehr hin.

    Wer die Frage selbst gestellt hat, bekommt sie nicht zugestellt (sonst
    meldet sich Andis Handy bei jeder eigenen Rueckfrage). Verschickt wird an
    ALLE Admins, nicht an "den Admin": Es koennen mehrere sein, und ein fest
    verdrahteter Empfaenger waere still kaputt, sobald sich das aendert.

    `push_send()` arbeitet selbst in einem Thread und mit eigener Verbindung -
    ein nicht erreichbarer Push-Dienst darf das Speichern der Aktion nicht
    mitreissen, die ist zu diesem Zeitpunkt bereits committet.
    """
    zeile = db.execute("SELECT titel, text FROM wuensche WHERE id=?", (wid,)).fetchone()
    betreff = (zeile["titel"] or zeile["text"] or "").strip() if zeile else ""
    for admin in db.execute(
            "SELECT id FROM users WHERE is_admin=1 AND id != ?", (absender["id"],)):
        push_send(
            admin["id"],
            f"❓ Rückfrage zu #{wid}",
            f"{absender['name']}: {text[:120]}" if betreff == "" else
            f"{betreff[:60]} – {text[:100]}",
            "werkstatt",
            f"https://portal.16schwaben.de/a/werkstatt/#wunsch-{wid}",
        )


@bp.route("/a/werkstatt/titel/<int:wid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/werkstatt/<token>/titel/<int:wid>", methods=["POST"])
def titel_setzen(token, wid):
    """Endpunkt für Claude: setzt einen KI-generierten Titel (max. 80 Zeichen)."""
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    data = request.get_json(silent=True) or {}
    titel = str(data.get("titel", "")).strip()[:80]
    if not titel:
        abort(400)
    db = get_db()
    if not db.execute("SELECT id FROM wuensche WHERE id=?", (wid,)).fetchone():
        abort(404)
    db.execute("UPDATE wuensche SET titel=? WHERE id=?", (titel, wid))
    db.commit()
    return {"ok": True}


def init_app(app):
    app.register_blueprint(bp)
    app.jinja_env.filters["de_datum"] = _de_datum
