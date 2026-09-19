"""
Geholfen-App – Kinder tippen auf Kacheln wenn sie geholfen haben.
URL-Präfix: /a/geholfen/<token>/

Design: große Kacheln, auch als Küchen-Tablet-Daueranzeige geeignet.

Wunsch #276: Unter den Kacheln stehen zwei Auswertungen der letzten zehn
Tage, beide aus demselben Ereignis-Log (`geholfen_eintraege`, ein Eintrag je
Erledigung) und beide reine Aggregation beim Rendern - nichts wird
vorberechnet gespeichert:

  A) Punktmatrix - eine Zeile je Aufgabe, eine Spalte je Tag, je Erledigung
     ein Punkt in der Farbe der Person (ab fuenf: vier Punkte plus "+n").
     Zeilen absteigend nach Gesamtzahl, Gleichstand alphabetisch; die
     Reihenfolge kommt aus dem UNGEFILTERTEN Datensatz, der Personenfilter
     dimmt Punkte nur (Deckkraft), er entfernt sie nicht - sonst zentrieren
     sich die uebrigen Punkte neu und der Vergleich vorher/nachher ist weg.
  B) Personenstreifen - eine Zeile je Person, dieselben Spalten, je Tag ein
     Quadrat, dessen Kantenlaenge die Anzahl erledigter Aufgaben codiert
     (18/26/34/40 px, bewusst diskrete Stufen statt Flaechenskalierung).

Beide Komponenten teilen sich die Spaltendefinition (`.mx-zeile` in
geholfen.html), damit sie untereinander fluchten. Die Tage sind Kalendertage
in Familienzeit (`utc_zu_lokal_datum`), nicht UTC-Tage wie die alte Heatmap -
ein Eintrag um 23:30 gehoert zum heutigen Tag, nicht zu morgen.

`matrix_daten()` ist eine reine Funktion (Ereignisse rein, Zeilen raus) und
deshalb ohne Datenbank testbar.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from teile.kern import (
    emoji_grafik_vorhanden,
    farbe_kontrast,
    farbe_kontrast_hell,
    get_db,
    heute_lokal,
    to_int,
    utc_zu_lokal_datum,
)
from teile.kern import grant as check_grant

bp  = Blueprint("geholfen_app", __name__)
APP = "geholfen"

MATRIX_TAGE = 10
WOCHENTAG_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
WOCHENTAG_LANG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                  "Samstag", "Sonntag"]
MONAT_LANG = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
              "August", "September", "Oktober", "November", "Dezember"]
# Wunsch #276: hoechstens vier Punkte je Zelle, der Rest als "+n".
PUNKTE_MAX = 4
# Kantenlaenge des Quadrats im Personenstreifen je Anzahl (Stufe 4 = Deckel).
QUADRAT_STUFEN = {1: 18, 2: 26, 3: 34, 4: 40}


def _kann_fuer_andere(user):
    return user["is_admin"] or user["rolle"] == "eltern"


def _spalten(tage):
    """Spaltenkoepfe: Wochentag plus Tageszahl ("Mo 1."), Wochenende markiert.
    Wunsch #278: `wt`/`tz` getrennt, damit der Kopf auf dem Handy zweizeilig
    passt; `datum_lang` fuer das Detail-Blatt."""
    heute = tage[-1]
    return [{
        "iso": t.isoformat(),
        "label": f"{WOCHENTAG_KURZ[t.weekday()]} {t.day}.",
        "wt": WOCHENTAG_KURZ[t.weekday()],
        "tz": f"{t.day}.",
        "datum_lang": f"{WOCHENTAG_LANG[t.weekday()]}, {t.day}. {MONAT_LANG[t.month - 1]}",
        "wochenende": t.weekday() >= 5,
        "heute": t == heute,
    } for t in tage]


def matrix_daten(ereignisse, tage, aufgaben, personen):
    """Wunsch #276: Aggregation fuer beide Komponenten.

    ereignisse: Iterable von (tag_iso, user_id, aufgabe_id)
    tage:       Liste von date, aelteste zuerst (10 Stueck)
    aufgaben:   Iterable von Rows/Dicts mit id, name, emoji, aktiv
    personen:   Iterable von Rows/Dicts mit id, name, farbe (Anzeigereihenfolge)

    Liefert {"spalten", "zeilen", "personen"}. Aufgaben ohne Erledigung im
    Zeitraum bleiben als leere Zeile stehen, solange sie aktiv sind;
    deaktivierte Aufgaben erscheinen nur, wenn sie im Zeitraum vorkommen."""
    spalten = _spalten(tage)
    tag_isos = [s["iso"] for s in spalten]
    personen = [dict(p) for p in personen]
    je_person = {p["id"]: p for p in personen}
    aufgaben = [dict(a) for a in aufgaben]
    je_aufgabe = {a["id"]: a for a in aufgaben}

    # (aufgabe, tag) -> [user_id, ...] in Reihenfolge des Eintreffens;
    # (person, tag) -> Anzahl. Ereignisse ausserhalb des Fensters oder von
    # Unbekannten (geloeschte Aufgabe/Person) fallen weg.
    zellen = {}
    person_tag = {}
    for tag_iso, uid, aid in ereignisse:
        if tag_iso not in tag_isos or aid not in je_aufgabe or uid not in je_person:
            continue
        zellen.setdefault((aid, tag_iso), []).append(uid)
        person_tag[(uid, tag_iso)] = person_tag.get((uid, tag_iso), 0) + 1

    gesamt = {}
    for (aid, _tag), uids in zellen.items():
        gesamt[aid] = gesamt.get(aid, 0) + len(uids)

    def _farben(p):
        return {"dunkel": farbe_kontrast(p["farbe"]), "hell": farbe_kontrast_hell(p["farbe"])}

    zeilen = []
    for a in aufgaben:
        if not a.get("aktiv", 1) and not gesamt.get(a["id"]):
            continue
        z_zellen = []
        for s in spalten:
            uids = zellen.get((a["id"], s["iso"]), [])
            je_uid = {}
            for uid in uids:
                je_uid[uid] = je_uid.get(uid, 0) + 1
            punkte = [{"uid": uid, "name": je_person[uid]["name"], **_farben(je_person[uid])}
                      for uid in uids[:PUNKTE_MAX]]
            tooltip = ""
            anteile = [f"{je_person[uid]['name']} {n}x" for uid, n in je_uid.items()]
            if uids:
                tooltip = f"{a['name']}, {s['label']} – {', '.join(anteile)}"
            z_zellen.append({
                "iso": s["iso"], "wochenende": s["wochenende"],
                "datum_lang": s["datum_lang"],
                "punkte": punkte, "mehr": max(0, len(uids) - PUNKTE_MAX),
                "anzahl": len(uids), "tooltip": tooltip, "anteile": anteile,
            })
        zeilen.append({"id": a["id"], "name": a["name"], "emoji": a["emoji"],
                       "gesamt": gesamt.get(a["id"], 0), "zellen": z_zellen})
    # Absteigend nach Haeufigkeit, Gleichstand alphabetisch - stabil, damit
    # die Reihenfolge nicht bei jedem Rendern springt.
    zeilen.sort(key=lambda z: (-z["gesamt"], z["name"].casefold()))

    personen_zeilen = []
    for p in personen:
        p_zellen = []
        for s in spalten:
            n = person_tag.get((p["id"], s["iso"]), 0)
            stufe = min(n, 4)
            p_zellen.append({
                "iso": s["iso"], "wochenende": s["wochenende"], "anzahl": n, "stufe": stufe,
                "tooltip": (f"{p['name']}, {s['label']}: {n} "
                            f"{'Aufgabe' if n == 1 else 'Aufgaben'}") if n else "",
            })
        personen_zeilen.append({"id": p["id"], "name": p["name"],
                                "vorname": p["name"].split()[0] if p["name"].split() else p["name"],
                                **_farben(p), "zellen": p_zellen})

    return {"spalten": spalten, "zeilen": zeilen, "personen": personen_zeilen}


def _matrix_fuer(db):
    """Ereignisse der letzten zehn Familientage aus der Datenbank holen und
    an matrix_daten() geben."""
    heute = date.fromisoformat(heute_lokal())
    tage = [heute - timedelta(days=i) for i in range(MATRIX_TAGE - 1, -1, -1)]
    # Erst Eltern, dann Kinder (Wunsch #44), innerhalb der Gruppe alphabetisch.
    personen = db.execute("""
        SELECT id, name, farbe FROM users WHERE rolle IN ('eltern','kind')
        ORDER BY CASE rolle WHEN 'eltern' THEN 0 ELSE 1 END, name COLLATE NOCASE
    """).fetchall()
    aufgaben = db.execute("SELECT id, name, emoji, aktiv FROM geholfen_aufgaben ORDER BY id").fetchall()
    # Einen Tag mehr holen als noetig: die Grenze liegt in UTC, der Tag in
    # Familienzeit - was um 23:30 lokal am aeltesten Tag passiert ist, steht
    # in UTC schon am Vortag.
    #
    # Wunsch #296: Die Grenze kommt aus DERSELBEN Kalenderquelle wie die
    # Spalten (`heute_lokal()`), nicht aus `datetime('now')` der SQLite-Uhr.
    # Vorher liefen hier zwei Kalender nebeneinander - unsichtbar im Betrieb
    # (beide zeigen heute), aber ein Test, der `heute_lokal` auf einen festen
    # Tag setzt, kippte elf Tage spaeter, weil die SQL-Grenze weiterwanderte.
    grenze = (tage[0] - timedelta(days=1)).isoformat() + " 00:00:00"
    rows = db.execute("""
        SELECT zeitstempel, user_id, aufgabe_id FROM geholfen_eintraege
        WHERE  zeitstempel >= ?
        ORDER  BY zeitstempel
    """, (grenze,)).fetchall()
    ereignisse = [(utc_zu_lokal_datum(r["zeitstempel"]), r["user_id"], r["aufgabe_id"]) for r in rows]
    return matrix_daten(ereignisse, tage, aufgaben, personen)


@bp.route("/a/geholfen/", defaults={"token": None})
@bp.route("/a/geholfen/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db       = get_db()
    aufgaben = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()
    alle_nutzer = None
    if _kann_fuer_andere(user):
        alle_nutzer = db.execute(
            "SELECT id, name, farbe FROM users ORDER BY name"
        ).fetchall()

    matrix = _matrix_fuer(db)
    # Fuer den Sofort-Punkt nach dem Antippen (ohne Neuladen) braucht das
    # Skript Name und Farben je Person.
    personen_js = {str(p["id"]): {"name": p["name"], "dunkel": p["dunkel"], "hell": p["hell"]}
                   for p in matrix["personen"]}

    return render_template("geholfen.html",
        user=user, token=token, farbe=user["farbe"],
        aufgaben=aufgaben, alle_nutzer=alle_nutzer,
        matrix=matrix, personen_js=personen_js, quadrat_stufen=QUADRAT_STUFEN,
    )


@bp.route("/a/geholfen/tippen/<int:aufgabe_id>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geholfen/<token>/tippen/<int:aufgabe_id>", methods=["POST"])
def tippen(token, aufgabe_id):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db = get_db()
    aufg = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE id=? AND aktiv=1", (aufgabe_id,)
    ).fetchone()
    if not aufg:
        abort(404)
    ziel_user_id = user["id"]
    if _kann_fuer_andere(user):
        data = request.get_json(silent=True) or {}
        fuer = to_int(data.get("fuer_user_id") or request.form.get("fuer_user_id"))
        if fuer is not None:
            exists = db.execute("SELECT id FROM users WHERE id=?", (fuer,)).fetchone()
            if exists:
                ziel_user_id = fuer
    db.execute(
        "INSERT INTO geholfen_eintraege(aufgabe_id, user_id) VALUES(?,?)",
        (aufgabe_id, ziel_user_id),
    )
    db.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        # Wunsch #276: der Tag in Familienzeit - die Matrix-Spalte, in die
        # der neue Punkt gehoert.
        return jsonify(
            ok=True, aufgabe=aufg["name"], emoji=aufg["emoji"],
            fuer_user_id=ziel_user_id, tag=heute_lokal(),
        )
    return redirect(url_for("geholfen_app.index", token=token))


@bp.route("/a/geholfen/verlauf", defaults={"token": None})
@bp.route("/a/geholfen/<token>/verlauf")
def verlauf(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    letzte = db.execute("""
        SELECT e.id, e.zeitstempel, e.user_id, e.aufgabe_id,
               u.name, u.farbe, a.emoji, a.name AS aufgabe
        FROM   geholfen_eintraege e
        JOIN   users              u ON u.id = e.user_id
        JOIN   geholfen_aufgaben  a ON a.id = e.aufgabe_id
        ORDER  BY e.zeitstempel DESC LIMIT 50
    """).fetchall()
    darf_bearbeiten = _kann_fuer_andere(user)
    alle_nutzer = alle_aufgaben = None
    if darf_bearbeiten:
        alle_nutzer   = db.execute("SELECT id, name FROM users ORDER BY name").fetchall()
        alle_aufgaben = db.execute("SELECT id, name, emoji FROM geholfen_aufgaben ORDER BY id").fetchall()
    return render_template("geholfen_verlauf.html",
        user=user, token=token, farbe=user["farbe"], letzte=letzte,
        darf_bearbeiten=darf_bearbeiten, alle_nutzer=alle_nutzer, alle_aufgaben=alle_aufgaben)


@bp.route("/a/geholfen/eintrag/<int:eid>/bearbeiten", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geholfen/<token>/eintrag/<int:eid>/bearbeiten", methods=["POST"])
def eintrag_bearbeiten(token, eid):
    user = check_grant(token, APP)
    if not user or not _kann_fuer_andere(user):
        abort(403)
    db  = get_db()
    row = db.execute("SELECT id FROM geholfen_eintraege WHERE id=?", (eid,)).fetchone()
    if not row:
        abort(404)
    user_id     = to_int(request.form.get("user_id"))
    aufgabe_id  = to_int(request.form.get("aufgabe_id"))
    zeitstempel = request.form.get("zeitstempel", "").strip()
    if (user_id is None or aufgabe_id is None or not zeitstempel
            or not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone()
            or not db.execute("SELECT 1 FROM geholfen_aufgaben WHERE id=?", (aufgabe_id,)).fetchone()):
        return redirect(url_for("geholfen_app.verlauf", token=token))
    # <input type="datetime-local"> liefert "YYYY-MM-DDTHH:MM" - SQLite braucht
    # ein Leerzeichen statt "T" und optional die Sekunden.
    zeitstempel_sql = zeitstempel.replace("T", " ")
    if len(zeitstempel_sql) == 16:
        zeitstempel_sql += ":00"
    db.execute(
        "UPDATE geholfen_eintraege SET user_id=?, aufgabe_id=?, zeitstempel=? WHERE id=?",
        (user_id, aufgabe_id, zeitstempel_sql, eid),
    )
    db.commit()
    return redirect(url_for("geholfen_app.verlauf", token=token))


@bp.route("/a/geholfen/eintrag/<int:eid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/geholfen/<token>/eintrag/<int:eid>/loeschen", methods=["POST"])
def eintrag_loeschen(token, eid):
    user = check_grant(token, APP)
    if not user or not _kann_fuer_andere(user):
        abort(403)
    db = get_db()
    db.execute("DELETE FROM geholfen_eintraege WHERE id=?", (eid,))
    db.commit()
    return redirect(url_for("geholfen_app.verlauf", token=token))


@bp.route("/a/geholfen/uebersicht", defaults={"token": None})
@bp.route("/a/geholfen/<token>/uebersicht")
def uebersicht(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    users    = db.execute("SELECT id, name, farbe FROM users ORDER BY name").fetchall()
    aufgaben = db.execute(
        "SELECT * FROM geholfen_aufgaben WHERE aktiv=1 ORDER BY id"
    ).fetchall()
    # Punkte/Counts letzte 7 Tage
    eintraege = db.execute("""
        SELECT e.user_id, e.aufgabe_id, a.gewichtung
        FROM   geholfen_eintraege e
        JOIN   geholfen_aufgaben  a ON a.id = e.aufgabe_id
        WHERE  e.zeitstempel >= datetime('now', '-7 days')
    """).fetchall()
    counts = {}
    punkte = {}
    for e in eintraege:
        uid, aid = e["user_id"], e["aufgabe_id"]
        counts.setdefault(uid, {}).setdefault(aid, 0)
        counts[uid][aid] += 1
        punkte[uid] = punkte.get(uid, 0.0) + e["gewichtung"]
    # Kalender: letzte 30 Tage – welcher Nutzer hat an welchem Tag geholfen
    tage = [(date.today() - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    kal_rows = db.execute("""
        SELECT date(zeitstempel) AS tag, user_id
        FROM   geholfen_eintraege
        WHERE  zeitstempel >= datetime('now', '-30 days')
        GROUP  BY date(zeitstempel), user_id
    """).fetchall()
    kalender = {}
    for r in kal_rows:
        kalender.setdefault(r["tag"], set()).add(r["user_id"])
    return render_template("geholfen_uebersicht.html",
        user=user, token=token, farbe=user["farbe"],
        users=users, aufgaben=aufgaben,
        counts=counts, punkte=punkte,
        tage=tage, kalender=kalender,
    )


@bp.route("/a/geholfen/aufgaben", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/geholfen/<token>/aufgaben", methods=["GET", "POST"])
def aufgaben_verwalten(token):
    user = check_grant(token, APP)
    if not user or not user["is_admin"]:
        abort(403)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            emoji = request.form.get("emoji", "").strip() or "👍"
            try:
                gew = float(request.form.get("gewichtung", 1.0))
            except (TypeError, ValueError):
                gew = 1.0
            # Wunsch #275: Ein Emoji ohne lokale Grafik bliebe auf Rechnern
            # ohne Emoji-Schrift leer (so kam "Staubwischen" 🪄 zustande).
            # Lieber jetzt ablehnen als spaeter eine leere Kachel.
            if name and not emoji_grafik_vorhanden(emoji):
                return redirect(url_for("geholfen_app.aufgaben_verwalten",
                                        token=token, fehler="emoji", emoji=emoji, name=name))
            if name:
                db.execute(
                    "INSERT INTO geholfen_aufgaben(name,emoji,gewichtung) VALUES(?,?,?)",
                    (name, emoji, gew),
                )
                db.commit()
        elif action == "toggle":
            aid = to_int(request.form.get("id"), 0)
            row = db.execute("SELECT aktiv FROM geholfen_aufgaben WHERE id=?", (aid,)).fetchone()
            if row:
                db.execute("UPDATE geholfen_aufgaben SET aktiv=? WHERE id=?",
                           (0 if row["aktiv"] else 1, aid))
                db.commit()
        elif action == "umbenennen":
            # Wunsch #96: Aufgaben umbenennen war bisher nur per Code-Migration
            # moeglich - jetzt genau wie bei einkauf_kategorien.html direkt in
            # der Verwaltung, damit sowas kuenftig ohne Deploy geht.
            aid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name:
                db.execute("UPDATE geholfen_aufgaben SET name=? WHERE id=?", (name, aid))
                db.commit()
        return redirect(url_for("geholfen_app.aufgaben_verwalten", token=token))
    aufgaben = db.execute("SELECT * FROM geholfen_aufgaben ORDER BY aktiv DESC, id").fetchall()
    # Wunsch #275: bestehende Aufgaben ohne Grafik sichtbar machen, statt zu
    # warten, bis jemand am PC eine leere Kachel meldet.
    ohne_grafik = {a["id"] for a in aufgaben if not emoji_grafik_vorhanden(a["emoji"])}
    return render_template("geholfen_aufgaben.html",
        user=user, token=token, farbe=user["farbe"], aufgaben=aufgaben,
        ohne_grafik=ohne_grafik,
        fehler=request.args.get("fehler", ""),
        vorbelegt={"emoji": request.args.get("emoji", ""), "name": request.args.get("name", "")})


def init_app(app):
    app.register_blueprint(bp)
