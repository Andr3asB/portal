"""
Vokabeln-App - eigene Vokabeln erfassen, in Sprachen und Kapiteln
organisieren und per Trainer lernen (Wunsch #73, ersetzt den Fehlversuch
aus Wunsch #67 komplett).
URL-Praefix: /a/vokabeln/<token>/

Sprachen sind global (Standard: Englisch, Latein - neue Sprachen kommen
bei Bedarf per Wunsch dazu), jeder Nutzer aktiviert die fuer ihn
relevanten selbst auf einer eigenen Unterseite. Kapitel gehoeren jeweils
einem Nutzer und gruppieren seine Vokabeln (eine Vokabel kann mehreren
Kapiteln oder keinem angehoeren). Der Trainer fragt eine gewaehlte
Sprache/Kapitel-Auswahl zufaellig ab: richtig beantwortete Vokabeln
kommen in der laufenden Session nicht noch mal dran, falsch beantwortete
werden ans Ende der Warteschlange gehaengt und so spaeter erneut gefragt.
Jeder Versuch wird protokolliert, Sessions haben Start- und Endzeitpunkt.

Wunsch #80: Vokabelpaare per Fotoupload + KI-OCR importieren - Ergebnis
landet zur Kontrolle/Korrektur in einem Formular, nie direkt gespeichert
(gleiches Prinzip wie der Rezept-URL-Import in 11_rezepte.py). Der Datei-
Input in vokabel_foto_import.html hat seit Wunsch #106 KEIN
capture="environment" mehr - zwang iOS Safari sonst, direkt die Kamera zu
oeffnen ohne Mediathek-Option in der nativen Auswahl (siehe 11_rezepte.py,
gleicher Fix dort fuer den analogen Rezept-Foto-Import aus Wunsch #97).

Wunsch #81: Aussprache der Fremdsprache im Trainer per KI-TTS, Ergebnis
wird als Datei im Datenordner gecacht (siehe _audio_pfad) statt bei jeder
Wiedergabe neu erzeugt zu werden.
"""
import base64
import hashlib
import json
import os
import random
from flask import (
    Blueprint, render_template, request, redirect, url_for, jsonify, abort,
    current_app, send_file,
)
from teile.kern import (
    get_db, grant as check_grant, to_int,
    ki_anfrage, ki_text_zu_sprache, KiLimitError, KiFehler,
)

_FOTO_MAX_BYTES = 8 * 1024 * 1024  # 8 MB - Handyfotos passen bequem, schuetzt vor Ausreissern
_FOTO_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic"}
_MAX_OCR_PAARE = 60

bp  = Blueprint("vokabeln_app", __name__)
APP = "vokabeln"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _darf_andere_sehen(user):
    return bool(user["is_admin"] or user["rolle"] == "eltern")


def _aktive_sprachen_sicherstellen(db, user_id):
    """Beim allerersten Kontakt: alle Standardsprachen fuer den Nutzer
    aktivieren, damit die App nicht komplett leer startet. Wer danach
    gezielt abwaehlt (Unterseite "Sprachen"), bleibt dabei - dieser
    Automatismus greift nur, solange noch keine einzige Zeile existiert."""
    hat_schon = db.execute(
        "SELECT 1 FROM vokabel_sprachen_nutzer WHERE user_id=?", (user_id,)
    ).fetchone()
    if hat_schon:
        return
    for (sid,) in db.execute("SELECT id FROM vokabel_sprachen WHERE aktiv=1").fetchall():
        db.execute(
            "INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
            (user_id, sid),
        )
    db.commit()


def _eigene_sprachen(db, user_id):
    return db.execute("""
        SELECT s.id, s.name FROM vokabel_sprachen s
        JOIN vokabel_sprachen_nutzer n ON n.sprache_id = s.id
        WHERE n.user_id=? AND s.aktiv=1
        ORDER BY s.name COLLATE NOCASE
    """, (user_id,)).fetchall()


def _sprache_erlaubt(db, user_id, sprache_id):
    return db.execute("""
        SELECT 1 FROM vokabel_sprachen_nutzer n
        JOIN vokabel_sprachen s ON s.id = n.sprache_id
        WHERE n.user_id=? AND n.sprache_id=? AND s.aktiv=1
    """, (user_id, sprache_id)).fetchone() is not None


def _eigene_kapitel(db, user_id, nur_aktive=True):
    sql = "SELECT * FROM vokabel_kapitel WHERE user_id=?"
    if nur_aktive:
        sql += " AND aktiv=1"
    sql += " ORDER BY name COLLATE NOCASE"
    return db.execute(sql, (user_id,)).fetchall()


def _kapitel_gehoert_nutzer(db, user_id, kapitel_id):
    return db.execute(
        "SELECT 1 FROM vokabel_kapitel WHERE id=? AND user_id=?", (kapitel_id, user_id)
    ).fetchone() is not None


def _kapitel_ids_setzen(db, vokabel_id, user_id, kapitel_ids):
    db.execute("DELETE FROM vokabel_kapitel_zuordnung WHERE vokabel_id=?", (vokabel_id,))
    for kid in kapitel_ids:
        if kid is not None and _kapitel_gehoert_nutzer(db, user_id, kid):
            db.execute(
                "INSERT OR IGNORE INTO vokabel_kapitel_zuordnung(vokabel_id, kapitel_id) VALUES(?,?)",
                (vokabel_id, kid),
            )


def _audio_pfad(sprache_id, text):
    """Dateipfad fuers TTS-Cache (Wunsch #81) - ein Wort wird pro Sprache
    genau einmal erzeugt; Schluessel ist der normalisierte Text, nicht die
    vokabel_id, damit identische Woerter (auch ueber mehrere Vokabel-Zeilen
    hinweg) sich die Audiodatei teilen. Endung bewusst neutral (.audio):
    ki_text_zu_sprache() liefert je nach Modell MP3 oder WAV zurueck
    (siehe _audio_mimetype fuers Erkennen beim Ausliefern)."""
    h = hashlib.sha256(f"{sprache_id}:{text.strip().lower()}".encode()).hexdigest()
    data_dir = current_app.config["DATA_DIR"]
    return os.path.join(data_dir, "vokabel_audio", str(sprache_id), f"{h}.audio")


def _audio_mimetype(pfad):
    with open(pfad, "rb") as f:
        kopf = f.read(4)
    return "audio/wav" if kopf == b"RIFF" else "audio/mpeg"


def _vokabeln_per_ki(user_id, sprache_name, mime, bild_b64):
    """OCR-Extraktion von Vokabelpaaren aus einem Foto (Wunsch #80) ueber
    ki_anfrage() mit Bildeingabe. Wirft KiLimitError/KiFehler/ValueError,
    der Aufrufer faengt sie ab und zeigt eine freundliche Fehlermeldung."""
    system = (
        "Du liest ein Foto einer handschriftlichen oder gedruckten Vokabelliste "
        "(Schulheft, Buchseite) und extrahierst die Vokabelpaare. Antworte "
        'AUSSCHLIESSLICH mit einem JSON-Array der Form '
        '[{"fremd": "...", "deutsch": "..."}, ...]. "fremd" ist das '
        f'fremdsprachige Wort in der Sprache {sprache_name}, "deutsch" die '
        "deutsche Übersetzung. Ignoriere alles, was keine Vokabel ist "
        "(Überschriften, Seitenzahlen, Kapitelnamen, Datum). Keine Erklärung, "
        "kein Markdown, kein Codeblock."
    )
    antwort = ki_anfrage(
        user_id, "vokabeln_ocr", system,
        "Extrahiere alle Vokabelpaare von diesem Foto.",
        max_tokens=4000, bilder=[(mime, bild_b64)],
    )
    bereinigt = antwort.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.strip("`")
        if bereinigt.lower().startswith("json"):
            bereinigt = bereinigt[4:]
    daten = json.loads(bereinigt)
    if not isinstance(daten, list):
        raise ValueError("KI hat kein Array geliefert")
    paare = []
    for eintrag in daten[:_MAX_OCR_PAARE]:
        fremd   = str((eintrag or {}).get("fremd") or "").strip()
        deutsch = str((eintrag or {}).get("deutsch") or "").strip()
        if fremd and deutsch:
            paare.append({"fremd": fremd, "deutsch": deutsch})
    if not paare:
        raise ValueError("KI hat keine Vokabelpaare erkannt")
    return paare


@bp.route("/a/vokabeln/<token>/")
def index(token):
    user = _user(token)
    db = get_db()
    _aktive_sprachen_sicherstellen(db, user["id"])
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])
    vokabeln = db.execute("""
        SELECT v.id, v.fremd, v.deutsch, v.sprache_id, s.name AS sprache_name,
               (SELECT GROUP_CONCAT(z.kapitel_id) FROM vokabel_kapitel_zuordnung z
                WHERE z.vokabel_id = v.id) AS kapitel_ids,
               (SELECT GROUP_CONCAT(k.name, ', ') FROM vokabel_kapitel_zuordnung z
                JOIN vokabel_kapitel k ON k.id = z.kapitel_id
                WHERE z.vokabel_id = v.id) AS kapitel_namen
        FROM   vokabeln v
        JOIN   vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  v.user_id=?
        ORDER  BY v.erstellt DESC
    """, (user["id"],)).fetchall()
    return render_template("vokabeln.html",
        user=user, token=token, farbe=user["farbe"],
        sprachen=sprachen, kapitel=kapitel, vokabeln=vokabeln)


@bp.route("/a/vokabeln/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    db = get_db()
    fremd      = request.form.get("fremd", "").strip()
    deutsch    = request.form.get("deutsch", "").strip()
    sprache_id = to_int(request.form.get("sprache_id"))
    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        cur = db.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,?,?)",
            (user["id"], sprache_id, fremd, deutsch),
        )
        _kapitel_ids_setzen(db, cur.lastrowid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/<int:vid>/bearbeiten", methods=["POST"])
def bearbeiten(token, vid):
    user = _user(token)
    db = get_db()
    if not db.execute(
        "SELECT 1 FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"])
    ).fetchone():
        abort(404)

    fremd      = request.form.get("fremd", "").strip()
    deutsch    = request.form.get("deutsch", "").strip()
    sprache_id = to_int(request.form.get("sprache_id"))
    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        db.execute(
            "UPDATE vokabeln SET fremd=?, deutsch=?, sprache_id=? WHERE id=?",
            (fremd, deutsch, sprache_id, vid),
        )
        _kapitel_ids_setzen(db, vid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/<int:vid>/loeschen", methods=["POST"])
def loeschen(token, vid):
    user = _user(token)
    db = get_db()
    db.execute("DELETE FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"]))
    db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/sprachen", methods=["GET", "POST"])
def sprachen_verwalten(token):
    user = _user(token)
    db = get_db()
    if request.method == "POST":
        gewaehlt = {to_int(x) for x in request.form.getlist("sprache_ids")}
        gewaehlt.discard(None)
        for (sid,) in db.execute("SELECT id FROM vokabel_sprachen WHERE aktiv=1").fetchall():
            if sid in gewaehlt:
                db.execute(
                    "INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
                    (user["id"], sid),
                )
            else:
                db.execute(
                    "DELETE FROM vokabel_sprachen_nutzer WHERE user_id=? AND sprache_id=?",
                    (user["id"], sid),
                )
        db.commit()
        return redirect(url_for("vokabeln_app.sprachen_verwalten", token=token))

    _aktive_sprachen_sicherstellen(db, user["id"])
    alle_sprachen = db.execute(
        "SELECT * FROM vokabel_sprachen WHERE aktiv=1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    aktive_ids = {r[0] for r in db.execute(
        "SELECT sprache_id FROM vokabel_sprachen_nutzer WHERE user_id=?", (user["id"],)
    ).fetchall()}
    return render_template("vokabel_sprachen.html",
        user=user, token=token, farbe=user["farbe"],
        sprachen=alle_sprachen, aktive_ids=aktive_ids)


@bp.route("/a/vokabeln/<token>/kapitel", methods=["GET", "POST"])
def kapitel_verwalten(token):
    user = _user(token)
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "neu":
            name = request.form.get("name", "").strip()
            if name:
                db.execute(
                    "INSERT INTO vokabel_kapitel(user_id, name) VALUES(?,?)", (user["id"], name)
                )
                db.commit()
        elif action == "umbenennen":
            kid  = to_int(request.form.get("id"), 0)
            name = request.form.get("name", "").strip()
            if name and _kapitel_gehoert_nutzer(db, user["id"], kid):
                db.execute("UPDATE vokabel_kapitel SET name=? WHERE id=?", (name, kid))
                db.commit()
        elif action == "toggle":
            kid = to_int(request.form.get("id"), 0)
            row = db.execute(
                "SELECT aktiv FROM vokabel_kapitel WHERE id=? AND user_id=?", (kid, user["id"])
            ).fetchone()
            if row:
                db.execute("UPDATE vokabel_kapitel SET aktiv=? WHERE id=?",
                           (0 if row[0] else 1, kid))
                db.commit()
        return redirect(url_for("vokabeln_app.kapitel_verwalten", token=token))

    kapitel = db.execute(
        "SELECT * FROM vokabel_kapitel WHERE user_id=? ORDER BY name COLLATE NOCASE", (user["id"],)
    ).fetchall()
    return render_template("vokabel_kapitel.html",
        user=user, token=token, farbe=user["farbe"], kapitel=kapitel)


@bp.route("/a/vokabeln/<token>/lernen")
def lernen(token):
    user = _user(token)
    db = get_db()
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])
    return render_template("vokabel_lernen.html",
        user=user, token=token, farbe=user["farbe"], sprachen=sprachen, kapitel=kapitel)


@bp.route("/a/vokabeln/<token>/lernen/start", methods=["POST"])
def lernen_start(token):
    user = _user(token)
    db = get_db()
    sprache_id = to_int(request.form.get("sprache_id"))
    if not sprache_id or not _sprache_erlaubt(db, user["id"], sprache_id):
        return redirect(url_for("vokabeln_app.lernen", token=token))

    auswahl = request.form.getlist("kapitel_ids")  # kann "alle" und/oder "ohne" enthalten
    alle_gewaehlt = "alle" in auswahl or not auswahl
    ohne_gewaehlt = "ohne" in auswahl
    kapitel_ids   = {to_int(k) for k in auswahl if k not in ("alle", "ohne")}
    kapitel_ids.discard(None)

    if alle_gewaehlt:
        vokabeln = db.execute(
            "SELECT id, fremd, deutsch FROM vokabeln WHERE user_id=? AND sprache_id=?",
            (user["id"], sprache_id),
        ).fetchall()
    else:
        gefunden = {}
        if ohne_gewaehlt:
            for r in db.execute("""
                SELECT v.id, v.fremd, v.deutsch FROM vokabeln v
                WHERE v.user_id=? AND v.sprache_id=?
                  AND NOT EXISTS (SELECT 1 FROM vokabel_kapitel_zuordnung z WHERE z.vokabel_id=v.id)
            """, (user["id"], sprache_id)).fetchall():
                gefunden[r[0]] = r
        for kid in kapitel_ids:
            if not _kapitel_gehoert_nutzer(db, user["id"], kid):
                continue
            for r in db.execute("""
                SELECT v.id, v.fremd, v.deutsch FROM vokabeln v
                JOIN vokabel_kapitel_zuordnung z ON z.vokabel_id = v.id
                WHERE v.user_id=? AND v.sprache_id=? AND z.kapitel_id=?
            """, (user["id"], sprache_id, kid)).fetchall():
                gefunden[r[0]] = r
        vokabeln = list(gefunden.values())

    # Nur eine offene Session je Nutzer: eine vorherige, nicht sauber
    # beendete Session (Tab geschlossen statt "Training beenden") wird
    # beim naechsten Start automatisch abgeschlossen.
    db.execute(
        "UPDATE vokabel_sessions SET beendet=datetime('now') WHERE user_id=? AND beendet IS NULL",
        (user["id"],),
    )
    cur = db.execute(
        "INSERT INTO vokabel_sessions(user_id, sprache_id) VALUES(?,?)",
        (user["id"], sprache_id),
    )
    session_id = cur.lastrowid

    if not vokabeln:
        db.execute("UPDATE vokabel_sessions SET beendet=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        return render_template("vokabel_training.html",
            user=user, token=token, farbe=user["farbe"], session_id=session_id, vokabeln=[])

    db.commit()
    aufgaben = [{"id": v[0], "fremd": v[1], "deutsch": v[2]} for v in vokabeln]
    random.shuffle(aufgaben)
    return render_template("vokabel_training.html",
        user=user, token=token, farbe=user["farbe"],
        session_id=session_id, vokabeln=aufgaben)


@bp.route("/a/vokabeln/<token>/versuch", methods=["POST"])
def versuch(token):
    user = _user(token)
    db = get_db()
    data       = request.get_json(silent=True) or {}
    session_id = to_int(data.get("session_id"))
    vokabel_id = to_int(data.get("vokabel_id"))
    richtig    = bool(data.get("richtig"))

    session_ok = session_id and db.execute(
        "SELECT 1 FROM vokabel_sessions WHERE id=? AND user_id=? AND beendet IS NULL",
        (session_id, user["id"]),
    ).fetchone()
    vokabel_ok = vokabel_id and db.execute(
        "SELECT 1 FROM vokabeln WHERE id=? AND user_id=?", (vokabel_id, user["id"])
    ).fetchone()
    if not (session_ok and vokabel_ok):
        return jsonify(ok=False), 400

    db.execute(
        "INSERT INTO vokabel_versuche(session_id, vokabel_id, richtig) VALUES(?,?,?)",
        (session_id, vokabel_id, 1 if richtig else 0),
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/a/vokabeln/<token>/session/<int:sid>/beenden", methods=["POST"])
def session_beenden(token, sid):
    user = _user(token)
    db = get_db()
    db.execute(
        "UPDATE vokabel_sessions SET beendet=datetime('now') WHERE id=? AND user_id=? AND beendet IS NULL",
        (sid, user["id"]),
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/a/vokabeln/<token>/auswertung")
def auswertung(token):
    """Wunsch #79: Trainingszeit je Sprache + richtig/falsch-Auswertung
    je Kapitel. Kinder sehen nur die eigene Auswertung; Eltern/Admin
    koennen per ?fuer=<user_id> einen anderen Nutzer ansehen.

    vokabel_sessions speichert nur sprache_id, kein kapitel_id (eine
    Session kann mehrere/alle Kapitel umfassen) - Trainingsdauer ist
    deshalb nur sauber je SPRACHE aggregierbar. Richtig/Falsch-Zaehlung
    dagegen ist je Kapitel sauber moeglich, weil sie an der Vokabel haengt
    (ueber vokabel_kapitel_zuordnung), nicht an der Session."""
    user = _user(token)
    db = get_db()

    ziel_id = to_int(request.args.get("fuer"))
    ziel = None
    if ziel_id is not None and _darf_andere_sehen(user):
        ziel = db.execute("SELECT id, name, farbe FROM users WHERE id=?", (ziel_id,)).fetchone()
    if not ziel:
        ziel = db.execute("SELECT id, name, farbe FROM users WHERE id=?", (user["id"],)).fetchone()

    alle_nutzer = db.execute(
        "SELECT id, name FROM users ORDER BY name COLLATE NOCASE"
    ).fetchall() if _darf_andere_sehen(user) else []

    trainingszeit = db.execute("""
        SELECT s.id AS sprache_id, s.name AS sprache, COUNT(*) AS anzahl,
               SUM((julianday(vs.beendet) - julianday(vs.gestartet)) * 1440.0) AS minuten
        FROM   vokabel_sessions vs
        JOIN   vokabel_sprachen s ON s.id = vs.sprache_id
        WHERE  vs.user_id=? AND vs.beendet IS NOT NULL
          AND  EXISTS (SELECT 1 FROM vokabel_versuche ver WHERE ver.session_id = vs.id)
        GROUP  BY s.id
        ORDER  BY minuten DESC
    """, (ziel["id"],)).fetchall()
    max_minuten = max((t["minuten"] or 0) for t in trainingszeit) if trainingszeit else 0

    sprachen = db.execute("""
        SELECT DISTINCT s.id, s.name FROM vokabeln v
        JOIN   vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  v.user_id=?
        ORDER  BY s.name COLLATE NOCASE
    """, (ziel["id"],)).fetchall()

    sprache_id = to_int(request.args.get("sprache")) or (sprachen[0]["id"] if sprachen else None)

    kapitel_auswertung = []
    if sprache_id:
        vokabeln = db.execute(
            "SELECT id, fremd, deutsch FROM vokabeln WHERE user_id=? AND sprache_id=?",
            (ziel["id"], sprache_id),
        ).fetchall()
        vokabel_ids = [v["id"] for v in vokabeln]

        versuche_je_vokabel = {}
        kapitel_je_vokabel = {}
        if vokabel_ids:
            platzhalter = ",".join("?" * len(vokabel_ids))
            for row in db.execute(
                f"SELECT vokabel_id, richtig FROM vokabel_versuche "
                f"WHERE vokabel_id IN ({platzhalter}) ORDER BY id", vokabel_ids,
            ).fetchall():
                versuche_je_vokabel.setdefault(row["vokabel_id"], []).append(row["richtig"])
            for row in db.execute(f"""
                SELECT z.vokabel_id, k.id AS kapitel_id, k.name AS kapitel_name
                FROM   vokabel_kapitel_zuordnung z
                JOIN   vokabel_kapitel k ON k.id = z.kapitel_id
                WHERE  z.vokabel_id IN ({platzhalter})
            """, vokabel_ids).fetchall():
                kapitel_je_vokabel.setdefault(row["vokabel_id"], []).append(
                    (row["kapitel_id"], row["kapitel_name"])
                )

        eimer = {}
        for v in vokabeln:
            versuche  = versuche_je_vokabel.get(v["id"], [])
            richtig_n = sum(1 for r in versuche if r)
            falsch_n  = len(versuche) - richtig_n
            wort = f"{v['fremd']} – {v['deutsch']}"
            if not versuche:
                status = "ungeuebt"
            elif versuche[-1]:
                status = "gelernt"
            else:
                status = "schwierig"

            for kid, kname in (kapitel_je_vokabel.get(v["id"]) or [(None, "Ohne Kapitel")]):
                eintrag = eimer.setdefault(kid, {
                    "name": kname, "richtig": 0, "falsch": 0,
                    "gelernt": [], "schwierig": [], "ungeuebt": [],
                })
                eintrag["richtig"] += richtig_n
                eintrag["falsch"]  += falsch_n
                eintrag[status].append(wort)

        kapitel_auswertung = sorted(eimer.values(), key=lambda e: e["name"])

    return render_template("vokabel_auswertung.html",
        user=user, token=token, farbe=user["farbe"],
        ziel=ziel, alle_nutzer=alle_nutzer, darf_andere_sehen=_darf_andere_sehen(user),
        trainingszeit=trainingszeit, max_minuten=max_minuten,
        sprachen=sprachen, sprache_id=sprache_id,
        kapitel_auswertung=kapitel_auswertung,
    )


@bp.route("/a/vokabeln/<token>/foto-import", methods=["GET", "POST"])
def foto_import(token):
    """Wunsch #80: Vokabelpaare per Foto + KI-OCR erfassen. Ergebnis landet
    nur zur Kontrolle/Korrektur in vokabel_foto_pruefen.html, nie direkt in
    der DB - Speichern passiert erst ueber foto_import_speichern()."""
    user = _user(token)
    db = get_db()
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])

    if request.method == "GET":
        return render_template("vokabel_foto_import.html",
            user=user, token=token, farbe=user["farbe"],
            sprachen=sprachen, fehler=None)

    def _fehler(text):
        return render_template("vokabel_foto_import.html",
            user=user, token=token, farbe=user["farbe"],
            sprachen=sprachen, fehler=text)

    sprache_id = to_int(request.form.get("sprache_id"))
    sprache = next((s for s in sprachen if s["id"] == sprache_id), None)
    if not sprache:
        return _fehler("Bitte eine Sprache auswählen.")

    datei = request.files.get("foto")
    if not datei or not datei.filename:
        return _fehler("Bitte ein Foto auswählen.")
    endung = datei.filename.rsplit(".", 1)[-1].lower() if "." in datei.filename else ""
    mime = _FOTO_MIME.get(endung)
    if not mime:
        return _fehler("Nur JPG, PNG oder HEIC werden unterstützt.")
    rohdaten = datei.read()
    if not rohdaten:
        return _fehler("Die Datei ist leer.")
    if len(rohdaten) > _FOTO_MAX_BYTES:
        return _fehler("Das Foto ist zu groß (maximal 8 MB).")

    try:
        paare = _vokabeln_per_ki(user["id"], sprache["name"], mime, base64.b64encode(rohdaten).decode())
    except KiLimitError:
        return _fehler(
            "Monatliches KI-Kontingent aufgebraucht – bitte später erneut versuchen "
            "oder die Vokabeln manuell eintragen.")
    except Exception:
        return _fehler("Auf dem Foto konnten keine Vokabeln erkannt werden.")

    return render_template("vokabel_foto_pruefen.html",
        user=user, token=token, farbe=user["farbe"],
        sprache=sprache, kapitel=kapitel, paare=paare)


@bp.route("/a/vokabeln/<token>/foto-import/speichern", methods=["POST"])
def foto_import_speichern(token):
    user = _user(token)
    db = get_db()
    sprache_id = to_int(request.form.get("sprache_id"))
    if not sprache_id or not _sprache_erlaubt(db, user["id"], sprache_id):
        return redirect(url_for("vokabeln_app.foto_import", token=token))

    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]
    fremde   = request.form.getlist("fremd")
    deutsche = request.form.getlist("deutsch")
    behalten = {to_int(i) for i in request.form.getlist("behalten")}

    for i, (fremd, deutsch) in enumerate(zip(fremde, deutsche)):
        if i not in behalten:
            continue
        fremd, deutsch = fremd.strip(), deutsch.strip()
        if not fremd or not deutsch:
            continue
        cur = db.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,?,?)",
            (user["id"], sprache_id, fremd, deutsch),
        )
        _kapitel_ids_setzen(db, cur.lastrowid, user["id"], kapitel_ids)
    db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<token>/wort/<int:vid>/audio")
def wort_audio(token, vid):
    """Wunsch #81: liest das fremdsprachige Wort per KI-TTS vor, einmalig
    erzeugt und dauerhaft im Datenordner gecacht (siehe _audio_pfad)."""
    user = _user(token)
    db = get_db()
    row = db.execute(
        "SELECT fremd, sprache_id FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"])
    ).fetchone()
    if not row:
        abort(404)

    pfad = _audio_pfad(row["sprache_id"], row["fremd"])
    if not os.path.exists(pfad):
        try:
            audio, _mime = ki_text_zu_sprache(row["fremd"], row["sprache_id"])
        except KiFehler:
            abort(502)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "wb") as f:
            f.write(audio)

    mimetype = _audio_mimetype(pfad)
    # iOS/Safari verlaesst sich beim Erkennen des Audioformats teils auf die
    # Dateiendung im Content-Disposition-Header, nicht nur auf Content-Type -
    # die generische ".audio"-Endung der Cache-Datei fuehrte dort zu
    # stummer Wiedergabe. download_name gibt daher explizit die passende
    # Endung vor, ohne die Datei selbst umbenennen zu muessen.
    endung = "wav" if mimetype == "audio/wav" else "mp3"
    return send_file(
        pfad, mimetype=mimetype, conditional=True,
        download_name=f"aussprache.{endung}",
    )


def init_app(app):
    app.register_blueprint(bp)
