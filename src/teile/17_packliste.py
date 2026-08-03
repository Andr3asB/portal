"""
Packliste – gemeinsame Packlisten für Reisen/Ausflüge, sehr ähnlich zur
Einkaufsliste (10_einkauf.py), mit drei Unterschieden (Wunsch #111):

1. Statt Märkten gibt es Ziele (Reisen/Ausflüge) - genau wie Märkte per
   Admin anlegbar/deaktivierbar (packlisten_ziele), aber OHNE Umbenennen
   (Andi nannte es explizit "wie ein Markt", Läden unterstützen ebenfalls
   kein Umbenennen - nur Kategorien tun das, siehe Wunsch #37).
2. Ein Eintrag gehört zu GENAU EINEM Ziel (nicht wie Angebote bei mehreren
   Märkten) - die Übersicht zeigt deshalb immer nur EIN aktives Ziel
   gleichzeitig (?ziel=<id> in der URL, Default: erstes aktives Ziel).
   Anders als die Einkaufsliste (eine einzige Dauer-Liste) ist eine
   Packliste zeitlich an eine Reise gebunden - ein Ziel-Mix in einer
   gemeinsamen Liste wäre unübersichtlich.
3. Ein Eintrag kann zusätzlich einer Person zugeordnet sein (person_id,
   NULL = "allgemein"/für alle). Der Packmodus (analog zu Einkaufs
   "Einkauf starten") filtert nach einer gewählten Person: zeigt deren
   private Einträge PLUS alle allgemeinen; "Allgemein" zeigt NUR die
   allgemeinen Einträge.

Alle drei Design-Entscheidungen wurden vorab mit Andi per Rückfrage
geklärt (2026-08-02), bevor die App gebaut wurde.

Bewusst NICHT übernommen (kein Teil des Wunsches, spätere separate
Wünsche bei Einkauf): Offline-Fähigkeit, automatische Synchronisierung
(Wunsch #100), "Filtern"-Knopf (Wunsch #87). Kann bei Bedarf per eigenem
Folge-Wunsch nachgezogen werden, analog zur Einkaufsliste.

Wunsch #116: das zuletzt geöffnete Ziel wird pro Nutzer gemerkt
(packlisten_nutzer_ziel, server-seitig statt sessionStorage - anders als
z. B. Einkaufs Wunsch #58, weil hier "von einem Benutzer" gemeint ist,
nicht "in diesem Browser-Tab"). _aktives_ziel_fuer_index() UPSERTet bei
explizitem ?ziel= die neue Merkung, sonst wird die zuletzt gemerkte
verwendet (falls noch aktiv), sonst das erste aktive Ziel.

Wunsch #117/#118: Ziele UND Kategorien dürfen jetzt Eltern UND Admin
verwalten (_darf_verwalten()), nicht mehr nur Admin - Menü-Sichtbarkeit
in base.html entsprechend angepasst.
"""
from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("packliste_app", __name__)
APP = "packliste"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _darf_verwalten(user) -> bool:
    """Wunsch #117/#118: Ziele und Kategorien duerfen Eltern UND Admin
    anlegen/aendern/deaktivieren, nicht mehr nur Admin - gleiches Muster
    wie in 13_kinderplan.py."""
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _kategorien_aktiv(db):
    return db.execute(
        "SELECT id, name FROM packlisten_kategorien WHERE aktiv=1 ORDER BY position, name COLLATE NOCASE"
    ).fetchall()


def _clean_kategorie_id(db, kategorie_id):
    """Fällt auf 'Sonstiges' zurück, wenn die ID fehlt/ungültig/inaktiv ist
    (gleiche Logik wie bei Einkauf)."""
    if kategorie_id is not None and db.execute(
        "SELECT 1 FROM packlisten_kategorien WHERE id=? AND aktiv=1", (kategorie_id,)
    ).fetchone():
        return kategorie_id
    row = db.execute("SELECT id FROM packlisten_kategorien WHERE name='Sonstiges'").fetchone()
    return row["id"] if row else kategorie_id


def _ziele_aktiv(db):
    return db.execute(
        "SELECT id, name FROM packlisten_ziele WHERE aktiv=1 ORDER BY name COLLATE NOCASE"
    ).fetchall()


def _aktives_ziel(db, ziele, ziel_id_roh):
    """Wunsch #111: genau EIN Ziel ist je Aufruf aktiv - aus ?ziel= oder das
    erste aktive Ziel, falls fehlend/ungültig/deaktiviert. Wird auch von
    add() aufgerufen (dort ohne Nutzerbezug - deshalb kein Merken hier,
    siehe _aktives_ziel_fuer_index() für die Index-spezifische Variante
    mit Wunsch #111 zuletzt-geöffnet-Logik)."""
    ziel_id = to_int(ziel_id_roh)
    if ziel_id is not None and any(z["id"] == ziel_id for z in ziele):
        return ziel_id
    return ziele[0]["id"] if ziele else None


def _aktives_ziel_fuer_index(db, ziele, ziel_id_roh, user_id):
    """Wunsch #116: ohne explizites ?ziel= wird das zuletzt von DIESEM Nutzer
    geöffnete Ziel geladen (packlisten_nutzer_ziel), nicht einfach das erste
    aktive. Ein explizit angeklicktes Ziel (?ziel=) wird als neue Merkung
    gespeichert (UPSERT)."""
    ziel_id_explizit = to_int(ziel_id_roh)
    if ziel_id_explizit is not None and any(z["id"] == ziel_id_explizit for z in ziele):
        db.execute(
            "INSERT INTO packlisten_nutzer_ziel(user_id, ziel_id) VALUES(?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET ziel_id=excluded.ziel_id",
            (user_id, ziel_id_explizit),
        )
        db.commit()
        return ziel_id_explizit

    gemerkt = db.execute(
        "SELECT ziel_id FROM packlisten_nutzer_ziel WHERE user_id=?", (user_id,)
    ).fetchone()
    if gemerkt and any(z["id"] == gemerkt["ziel_id"] for z in ziele):
        return gemerkt["ziel_id"]

    return ziele[0]["id"] if ziele else None


def _personen(db):
    return db.execute("SELECT id, name, farbe FROM users ORDER BY name COLLATE NOCASE").fetchall()


@bp.route("/a/packliste/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()
    ziele      = _ziele_aktiv(db)
    kategorien = _kategorien_aktiv(db)
    personen   = _personen(db)
    aktives_ziel_id = _aktives_ziel_fuer_index(db, ziele, request.args.get("ziel"), user["id"])

    offene = gepackte = []
    if aktives_ziel_id is not None:
        offene = db.execute("""
            SELECT e.id, e.name, e.kategorie_id, e.person_id, e.gepackt, e.gepackt_am,
                   u.name AS person_name, u.farbe AS person_farbe
            FROM   packlisten_eintraege e
            LEFT JOIN users u ON u.id = e.person_id
            WHERE  e.ziel_id = ? AND e.gepackt = 0
            ORDER  BY e.name COLLATE NOCASE ASC
        """, (aktives_ziel_id,)).fetchall()
        gepackte = db.execute("""
            SELECT e.id, e.name, e.kategorie_id, e.person_id, e.gepackt, e.gepackt_am,
                   u.name AS person_name, u.farbe AS person_farbe
            FROM   packlisten_eintraege e
            LEFT JOIN users u ON u.id = e.person_id
            WHERE  e.ziel_id = ? AND e.gepackt = 1
            ORDER  BY e.gepackt_am DESC
        """, (aktives_ziel_id,)).fetchall()

    gruppen = {k["id"]: [] for k in kategorien}
    unsortiert = []
    for r in offene:
        if r["kategorie_id"] in gruppen:
            gruppen[r["kategorie_id"]].append(r)
        else:
            unsortiert.append(r)

    return render_template("packliste.html",
        user=user, token=token, farbe=user["farbe"],
        ziele=ziele, aktives_ziel_id=aktives_ziel_id,
        kategorien=kategorien, gruppen=gruppen, unsortiert=unsortiert,
        gepackte=gepackte, personen=personen,
    )


@bp.route("/a/packliste/<token>/add", methods=["POST"])
def add(token):
    user = _user(token)
    db   = get_db()
    ziele = _ziele_aktiv(db)
    ziel_id = _aktives_ziel(db, ziele, request.form.get("ziel_id"))
    if ziel_id is None:
        return redirect(url_for("packliste_app.index", token=token))
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("packliste_app.index", token=token, ziel=ziel_id))
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    person_id = to_int(request.form.get("person_id"))
    if person_id is not None and not db.execute("SELECT 1 FROM users WHERE id=?", (person_id,)).fetchone():
        person_id = None
    db.execute(
        "INSERT INTO packlisten_eintraege(name,ziel_id,kategorie_id,person_id,erstellt_von) VALUES(?,?,?,?,?)",
        (name, ziel_id, kategorie_id, person_id, user["id"]),
    )
    db.commit()
    return redirect(url_for("packliste_app.index", token=token, ziel=ziel_id))


@bp.route("/a/packliste/<token>/gepackt/<int:eid>", methods=["POST"])
def toggle_gepackt(token, eid):
    """Idempotent per explizitem `wert` (0/1) - gleiches Muster wie Einkaufs
    toggle_erledigt(), notwendig fuer eine spaeter moegliche Offline-
    Warteschlange (noch nicht Teil dieses Wunsches, aber die Route ist
    schon darauf vorbereitet)."""
    _user(token)
    db  = get_db()
    row = db.execute("SELECT gepackt FROM packlisten_eintraege WHERE id=?", (eid,)).fetchone()
    if not row:
        abort(404)
    wert_roh = request.form.get("wert")
    neu = (1 if wert_roh == "1" else 0) if wert_roh is not None else (0 if row["gepackt"] else 1)
    db.execute(
        "UPDATE packlisten_eintraege SET gepackt=?, gepackt_am=CASE WHEN ?=1 THEN datetime('now') ELSE NULL END WHERE id=?",
        (neu, neu, eid),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(ok=True, gepackt=bool(neu))
    return redirect(url_for("packliste_app.index", token=token))


@bp.route("/a/packliste/<token>/loeschen/<int:eid>", methods=["POST"])
def loeschen(token, eid):
    _user(token)
    db = get_db()
    db.execute("DELETE FROM packlisten_eintraege WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("packliste_app.index", token=token))


@bp.route("/a/packliste/<token>/bearbeiten/<int:eid>", methods=["POST"])
def bearbeiten(token, eid):
    _user(token)
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(url_for("packliste_app.index", token=token))
    db = get_db()
    kategorie_id = _clean_kategorie_id(db, to_int(request.form.get("kategorie_id")))
    person_id = to_int(request.form.get("person_id"))
    if person_id is not None and not db.execute("SELECT 1 FROM users WHERE id=?", (person_id,)).fetchone():
        person_id = None
    db.execute(
        "UPDATE packlisten_eintraege SET name=?, kategorie_id=?, person_id=? WHERE id=?",
        (name, kategorie_id, person_id, eid),
    )
    db.commit()
    return redirect(url_for("packliste_app.index", token=token))


@bp.route("/a/packliste/<token>/ziele", methods=["GET", "POST"])
def ziele_verwalten(token):
    user = _user(token)
    if not _darf_verwalten(user):
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                db.execute("INSERT OR IGNORE INTO packlisten_ziele(name) VALUES(?)", (name,))
                db.commit()
        elif action == "toggle":
            zid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM packlisten_ziele WHERE id=?", (zid,)).fetchone()
            if row:
                db.execute("UPDATE packlisten_ziele SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, zid))
                db.commit()
        return redirect(url_for("packliste_app.ziele_verwalten", token=token))
    ziele = db.execute("SELECT * FROM packlisten_ziele ORDER BY aktiv DESC, name COLLATE NOCASE").fetchall()
    return render_template("packliste_ziele.html",
        user=user, token=token, farbe=user["farbe"], ziele=ziele)


@bp.route("/a/packliste/<token>/kategorien", methods=["GET", "POST"])
def kategorien_verwalten(token):
    user = _user(token)
    if not _darf_verwalten(user):
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                max_pos = db.execute(
                    "SELECT COALESCE(MAX(position), -1) FROM packlisten_kategorien"
                ).fetchone()[0]
                db.execute(
                    "INSERT OR IGNORE INTO packlisten_kategorien(name, position) VALUES(?,?)",
                    (name, max_pos + 1),
                )
                db.commit()
        elif action == "umbenennen":
            kid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name:
                db.execute("UPDATE packlisten_kategorien SET name=? WHERE id=?", (name, kid))
                db.commit()
        elif action == "toggle":
            kid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM packlisten_kategorien WHERE id=?", (kid,)).fetchone()
            if row:
                db.execute("UPDATE packlisten_kategorien SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, kid))
                db.commit()
        return redirect(url_for("packliste_app.kategorien_verwalten", token=token))
    kategorien = db.execute(
        "SELECT * FROM packlisten_kategorien ORDER BY position, name COLLATE NOCASE"
    ).fetchall()
    return render_template("packliste_kategorien.html",
        user=user, token=token, farbe=user["farbe"], kategorien=kategorien)


@bp.route("/a/packliste/<token>/kategorien/reorder", methods=["POST"])
def kategorien_reorder(token):
    user = _user(token)
    if not _darf_verwalten(user):
        abort(403)
    data  = request.get_json(silent=True) or {}
    order = data.get("order", [])
    if not isinstance(order, list):
        abort(400)
    db = get_db()
    for position, kid in enumerate(order):
        kid = to_int(kid)
        if kid is None:
            continue
        db.execute("UPDATE packlisten_kategorien SET position=? WHERE id=?", (position, kid))
    db.commit()
    return jsonify(ok=True)


def init_app(app):
    app.register_blueprint(bp)
