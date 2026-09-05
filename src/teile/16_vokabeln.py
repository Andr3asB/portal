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

Wunsch #258: Aussprache UEBEN - der Trainer nimmt nach der Antwort per
Mikrofon auf (MediaRecorder, ausdruecklich NICHT die Diktierfunktion des
Geraets), packt die Aufnahme im Browser zu WAV und schickt sie an
/wort/<vid>/aussprache. Bewertet wird ueber ki_anfrage() mit Audio-Eingabe
(Zweck "vokabeln_aussprache"): Voxtral von Mistral, festgenagelt auf den
EU-Endpunkt (Andis Vorgabe: EU-Hosting, nicht in China entwickelt). Die
Aufnahme wird nicht gespeichert. Latein ist ausgenommen (_OHNE_AUSSPRACHE).
"""
import base64
import hashlib
import json
import os
import random

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from teile.kern import (
    KiFehler,
    KiLimitError,
    get_db,
    ki_anfrage,
    ki_text_zu_sprache,
    to_int,
)
from teile.kern import (
    grant as check_grant,
)

_FOTO_MAX_BYTES = 8 * 1024 * 1024  # 8 MB - Handyfotos passen bequem, schuetzt vor Ausreissern
_FOTO_MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic"}
_MAX_OCR_PAARE = 60

# Wunsch #258: Aussprache ueben. Die Aufnahme kommt als WAV (16 kHz, mono,
# 16 Bit - der Browser packt sie selbst so, siehe vokabel_training.html),
# hoechstens 8 Sekunden = 256 KB. 1 MB laesst Luft, faengt aber jeden
# Ausreisser ab, BEVOR er zum kostenpflichtigen KI-Aufruf wird. Unter
# 8 KB (eine Viertelsekunde) ist es kein Wort, sondern ein Klick.
_AUSSPRACHE_MAX_BYTES = 1_000_000
_AUSSPRACHE_MIN_BYTES = 8_000
_AUSSPRACHE_MAX_ZEICHEN_VERSTANDEN = 80
_AUSSPRACHE_MAX_ZEICHEN_TIPP = 200
# Sprachen ohne Aussprache-Training. Latein wird nicht gesprochen gelernt -
# eine Bewertung waere dort geraten. Stand aus der Rueckfrage am Wunsch
# (05.09.2026): Andi hat Weg A entschieden, die Latein-Frage offen gelassen;
# umgesetzt ist die Empfehlung "Latein ausgenommen". Eine Zeile hier, wenn
# das anders sein soll.
_OHNE_AUSSPRACHE = {"Latein"}


def aussprache_moeglich(sprache_name) -> bool:
    """Gibt es fuer diese Sprache das Aussprache-Training (Wunsch #258)?"""
    return (sprache_name or "").strip() not in _OHNE_AUSSPRACHE

# Wunsch #194: Unregelmaessige Verben. Ein Eintrag IST ein unregelmaessiges
# Verb, wenn `simple_past` UND `perfect` gefuellt sind - `fremd` traegt dann
# den Infinitiv. Kein eigener Typ-Merker: Der waere eine zweite Wahrheit
# neben den Feldern und koennte von ihnen abweichen.
_IST_VERB = "COALESCE(v.simple_past,'') <> '' AND COALESCE(v.perfect,'') <> ''"

# Die waehlbaren Abfrageformen. Reihenfolge = Anzeigereihenfolge.
# Aufbau: schluessel -> (Beschriftung, Frage-Feld, [Antwort-Felder])
VERB_ABFRAGEN = {
    "deutsch_alle":      ("Deutsch → alle drei Formen",
                          "deutsch", ["fremd", "simple_past", "perfect"]),
    "infinitiv_formen":  ("Infinitiv → simple past + Perfect",
                          "fremd", ["simple_past", "perfect"]),
    "infinitiv_deutsch": ("Infinitiv → Deutsch",      "fremd",       ["deutsch"]),
    "deutsch_infinitiv": ("Deutsch → Infinitiv",      "deutsch",     ["fremd"]),
    "past_infinitiv":    ("simple past → Infinitiv",  "simple_past", ["fremd"]),
    "perfect_infinitiv": ("Perfect → Infinitiv",      "perfect",     ["fremd"]),
}
# Voreinstellung auf der Lernseite: die beiden Formen, die in der Schule
# tatsaechlich abgefragt werden.
VERB_ABFRAGEN_STANDARD = ["deutsch_alle", "infinitiv_formen"]

# Wunsch #195: Unregelmaessige Verben in diesem Sinn (drei Stammformen, die
# man auswendig lernt) gibt es nur im Englischen. In allen anderen Sprachen
# waeren die Felder Ballast - sie werden dort gar nicht erst angezeigt.
#
# Eine Namensliste und keine Datenbankspalte: Eine Spalte ohne Bedien-
# oberflaeche waere genauso unsichtbar wie diese Zeile, nur schwerer zu
# finden. Kommt eine weitere Sprache mit Stammformen dazu, ist es ein Wort
# mehr - und `test_die_sprache_gibt_es_wirklich` faellt auf, wenn "Englisch"
# umbenannt wird.
#
# Der Unterschied ist groesser als er klingt: Auf dem Server stehen (Stand
# 10.08.2026) FUENF Sprachen - Englisch, Latein, Daenisch, Italienisch,
# Franzoesisch. Bei vieren davon sind die Verbfelder jetzt weg, und in der
# Vokabelliste ist Daenisch die erste Sprache, also die Voreinstellung.
SPRACHEN_MIT_VERBFORMEN = {"Englisch"}


def sprachen_mit_verbformen(db):
    """IDs der Sprachen, bei denen die Verbfelder ueberhaupt Sinn ergeben."""
    if not SPRACHEN_MIT_VERBFORMEN:
        return []
    platzhalter = ",".join("?" * len(SPRACHEN_MIT_VERBFORMEN))
    return [r["id"] for r in db.execute(
        f"SELECT id FROM vokabel_sprachen WHERE name IN ({platzhalter})",
        tuple(SPRACHEN_MIT_VERBFORMEN))]


FELD_LABELS = {
    "fremd":       "Infinitiv",
    "simple_past": "simple past",
    "perfect":     "Perfect",
    "deutsch":     "Deutsch",
}


def verb_aufgaben(zeilen, formen):
    """Aus Verb-Zeilen und gewaehlten Abfrageformen die Trainingsaufgaben.

    Je Verb und je gewaehlter Form EINE Aufgabe - wer "Deutsch → alle drei"
    und "Infinitiv → simple past + Perfect" ankreuzt, bekommt jedes Verb
    zweimal, aus zwei Richtungen. Genau das ist der Sinn der Auswahl.

    Uebersprungen wird eine Form, deren Fragefeld leer ist - sonst stuende
    im Training eine Frage ohne Wort.
    """
    aufgaben = []
    for z in zeilen:
        for schluessel in formen:
            if schluessel not in VERB_ABFRAGEN:
                continue
            label, frage_feld, antwort_felder = VERB_ABFRAGEN[schluessel]
            frage_wort = (z[frage_feld] or "").strip()
            felder = [{"label": FELD_LABELS[f], "erwartet": (z[f] or "").strip()}
                      for f in antwort_felder if (z[f] or "").strip()]
            if not frage_wort or not felder:
                continue
            aufgaben.append({
                "id": z["id"], "form": schluessel, "richtung": label,
                "frage": frage_wort, "felder": felder,
            })
    return aufgaben

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
    """Eigentum - NICHT Sichtbarkeit. Fuer alles Aendernde (umbenennen,
    aktiv/inaktiv, teilen) ist das der richtige Massstab: Ein geteiltes
    Kapitel darf der Empfaenger benutzen, aber nicht veraendern."""
    return db.execute(
        "SELECT 1 FROM vokabel_kapitel WHERE id=? AND user_id=?", (kapitel_id, user_id)
    ).fetchone() is not None


# ---------------------------------------------------------------------------
# Wunsch #150: geteilte Kapitel
#
# Die Zugriffsregel steht bewusst an EINER Stelle. Vorher war "gehoert mir"
# an sieben Stellen einzeln als `user_id=?` ausgeschrieben - bei einer
# Erweiterung ist genau das die Bauart, bei der man eine Stelle vergisst und
# entweder zu viel preisgibt oder eine Funktion still nicht mitzieht.
#
# `:uid` als benannter Parameter, weil das Fragment in Abfragen mit
# unterschiedlicher Parameterzahl eingesetzt wird.
# ---------------------------------------------------------------------------

_VOKABEL_SICHTBAR = """
    (v.user_id = :uid
     OR EXISTS (SELECT 1
                FROM   vokabel_kapitel_zuordnung z
                JOIN   vokabel_kapitel_freigabe f ON f.kapitel_id = z.kapitel_id
                WHERE  z.vokabel_id = v.id AND f.user_id = :uid))
"""


def _vokabel_sichtbar(db, user_id, vokabel_id) -> bool:
    """Darf dieser Nutzer diese Vokabel sehen/hoeren/ueben?"""
    return db.execute(f"""
        SELECT 1 FROM vokabeln v WHERE v.id = :vid AND {_VOKABEL_SICHTBAR}
    """, {"vid": vokabel_id, "uid": user_id}).fetchone() is not None


def _kapitel_zugaenglich(db, user_id, kapitel_id) -> bool:
    """Eigenes ODER mit mir geteiltes Kapitel."""
    return db.execute("""
        SELECT 1 FROM vokabel_kapitel k
        WHERE  k.id = :kid
          AND (k.user_id = :uid
               OR EXISTS (SELECT 1 FROM vokabel_kapitel_freigabe f
                          WHERE f.kapitel_id = k.id AND f.user_id = :uid))
    """, {"kid": kapitel_id, "uid": user_id}).fetchone() is not None


def _zugaengliche_kapitel(db, user_id):
    """Eigene + geteilte Kapitel, mit Eigentuemer-Namen.

    `geteilt_von` ist NULL beim eigenen Kapitel - die Oberflaeche nutzt das,
    um fremde Kapitel als solche zu kennzeichnen. Ohne diesen Hinweis waere
    unklar, wessen Vokabeln man da gerade uebt."""
    return db.execute("""
        SELECT k.id, k.name, k.aktiv, k.user_id,
               CASE WHEN k.user_id = :uid THEN NULL ELSE u.name END AS geteilt_von
        FROM   vokabel_kapitel k
        JOIN   users u ON u.id = k.user_id
        WHERE  k.aktiv = 1
          AND (k.user_id = :uid
               OR EXISTS (SELECT 1 FROM vokabel_kapitel_freigabe f
                          WHERE f.kapitel_id = k.id AND f.user_id = :uid))
        ORDER  BY (k.user_id = :uid) DESC, u.name COLLATE NOCASE, k.name COLLATE NOCASE
    """, {"uid": user_id}).fetchall()


def _sprache_zugaenglich(db, user_id, sprache_id) -> bool:
    """Eigene aktive Sprache ODER eine, die in einem geteilten Kapitel vorkommt.

    Ohne den zweiten Teil liefe das Teilen ins Leere, sobald der Empfaenger
    die Sprache nicht selbst aktiviert hat - und er haette keinen Hinweis,
    woran es liegt."""
    if _sprache_erlaubt(db, user_id, sprache_id):
        return True
    return db.execute("""
        SELECT 1
        FROM   vokabeln v
        JOIN   vokabel_kapitel_zuordnung z ON z.vokabel_id = v.id
        JOIN   vokabel_kapitel_freigabe f  ON f.kapitel_id = z.kapitel_id
        WHERE  v.sprache_id = :sid AND f.user_id = :uid
        LIMIT  1
    """, {"sid": sprache_id, "uid": user_id}).fetchone() is not None


def _zugaengliche_sprachen(db, user_id):
    """Eigene aktive Sprachen plus die aus geteilten Kapiteln."""
    return db.execute("""
        SELECT s.id, s.name FROM vokabel_sprachen s
        WHERE  s.aktiv = 1
          AND (EXISTS (SELECT 1 FROM vokabel_sprachen_nutzer n
                       WHERE n.sprache_id = s.id AND n.user_id = :uid)
               OR EXISTS (SELECT 1 FROM vokabeln v
                          JOIN vokabel_kapitel_zuordnung z ON z.vokabel_id = v.id
                          JOIN vokabel_kapitel_freigabe f  ON f.kapitel_id = z.kapitel_id
                          WHERE v.sprache_id = s.id AND f.user_id = :uid))
        ORDER  BY s.name COLLATE NOCASE
    """, {"uid": user_id}).fetchall()


def _verbformen_lesen(db=None, sprache_id=None):
    """simple past und Perfect aus dem Formular - oder (None, None).

    Nur BEIDE zusammen ergeben ein unregelmaessiges Verb. Ein halb
    ausgefuelltes Paar wird verworfen statt halb gespeichert: Sonst gaebe es
    Eintraege, die im Verbtraining als Verb gelten und dort eine leere
    Antwort erwarten."""
    # Wunsch #195: Bei einer Sprache ohne Stammformen werden die Felder gar
    # nicht angezeigt - ein trotzdem mitgeschickter Wert (alte Seite im
    # Speicher, selbstgebauter POST) wird hier verworfen. Sonst haette eine
    # lateinische Vokabel ein "simple past".
    if db is not None and sprache_id not in sprachen_mit_verbformen(db):
        return None, None
    past    = (request.form.get("simple_past") or "").strip()
    perfect = (request.form.get("perfect") or "").strip()
    if past and perfect:
        return past, perfect
    return None, None


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
    # Wunsch #149: Das "v2:" entwertet alle vor der Sprachangabe erzeugten
    # Dateien. Sie klingen falsch (das Modell hat die Sprache geraten), sind
    # aber technisch einwandfrei - ohne Aenderung am Schluessel wuerden sie
    # ewig weiterverwendet und der Fehler bliebe unsichtbar bestehen.
    # Die alten Dateien werden nicht geloescht: Sie fallen einfach aus dem
    # Cache und kosten nur etwas Plattenplatz.
    h = hashlib.sha256(f"v2:{sprache_id}:{text.strip().lower()}".encode()).hexdigest()
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


def _verben_per_ki(user_id, mime, bild_b64):
    """Wunsch #194: OCR einer Tabelle unregelmaessiger Verben (vier Spalten).

    Eigener Aufruf statt eines Schalters in `_vokabeln_per_ki`: Der Prompt
    beschreibt eine voellig andere Vorlage (Verbtabelle statt Vokabelliste),
    und ein Modell, das beides gleichzeitig erklaert bekommt, liefert
    zuverlaessig Mischformen.
    """
    system = (
        "Du liest ein Foto einer Tabelle unregelmaessiger englischer Verben "
        "(Schulheft, Buchseite) und extrahierst die Zeilen. Antworte "
        'AUSSCHLIESSLICH mit einem JSON-Array der Form [{"fremd": "...", '
        '"simple_past": "...", "perfect": "...", "deutsch": "..."}, ...]. '
        '"fremd" ist der Infinitiv (ohne "to"), "simple_past" die zweite '
        'Form, "perfect" die dritte Form (past participle), "deutsch" die '
        "deutsche Bedeutung. Gibt es zu einer Form mehrere Varianten, nimm "
        "die erste. Ignoriere Ueberschriften, Seitenzahlen und Nummerierung. "
        "Keine Erklaerung, kein Markdown, kein Codeblock."
    )
    antwort = ki_anfrage(
        user_id, "vokabeln_ocr", system,
        "Extrahiere alle Verben mit ihren drei Formen und der Bedeutung.",
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
    verben = []
    for eintrag in daten[:_MAX_OCR_PAARE]:
        e = eintrag or {}
        zeile = {feld: str(e.get(feld) or "").strip()
                 for feld in ("fremd", "simple_past", "perfect", "deutsch")}
        # Alle vier oder gar nicht: Eine Zeile ohne dritte Form waere im
        # Verbtraining eine Frage ohne Antwort.
        if all(zeile.values()):
            verben.append(zeile)
    if not verben:
        raise ValueError("KI hat keine Verben erkannt")
    return verben


@bp.route("/a/vokabeln/", defaults={"token": None})
@bp.route("/a/vokabeln/<token>/")
def index(token):
    user = _user(token)
    db = get_db()
    _aktive_sprachen_sicherstellen(db, user["id"])
    sprachen = _eigene_sprachen(db, user["id"])
    kapitel  = _eigene_kapitel(db, user["id"])
    vokabeln = db.execute("""
        SELECT v.id, v.fremd, v.deutsch, v.simple_past, v.perfect,
               v.sprache_id, s.name AS sprache_name,
               v.user_id, (SELECT u.name FROM users u WHERE u.id = v.user_id) AS besitzer,
               (SELECT GROUP_CONCAT(z.kapitel_id) FROM vokabel_kapitel_zuordnung z
                WHERE z.vokabel_id = v.id) AS kapitel_ids,
               (SELECT GROUP_CONCAT(k.name, ', ') FROM vokabel_kapitel_zuordnung z
                JOIN vokabel_kapitel k ON k.id = z.kapitel_id
                WHERE z.vokabel_id = v.id) AS kapitel_namen
        FROM   vokabeln v
        JOIN   vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  {SICHTBAR}
        ORDER  BY (v.user_id = :uid) DESC, v.erstellt DESC
    """.replace("{SICHTBAR}", _VOKABEL_SICHTBAR), {"uid": user["id"]}).fetchall()
    # Wunsch #148: Sichtbar machen, wofuer die Aussprache schon vorliegt.
    # Geprueft wird die Datei im Cache, nicht ein Merker in der Datenbank -
    # der Cache IST die Wahrheit (er ueberlebt keinen Datenverlust und wird
    # von Wunsch #149 bewusst entwertet). Ein Datenbank-Flag koennte davon
    # abweichen und wuerde dann das Falsche anzeigen.
    vokabeln = [dict(v) for v in vokabeln]
    for v in vokabeln:
        v["audio_da"] = os.path.exists(_audio_pfad(v["sprache_id"], v["fremd"]))

    # Wunsch #220: Der Filter muss ueber ALLES gehen, was in der Liste steht -
    # also auch ueber geteilte Kapitel und deren Sprachen. `sprachen` und
    # `kapitel` daneben bleiben die EIGENEN: in ein fremdes Kapitel darf man
    # nichts eintragen, und `_sprache_erlaubt()` laesst beim Speichern ohnehin
    # nur eigene Sprachen durch. Zwei Listen mit unterschiedlichem Zweck, und
    # genau deshalb nicht dieselbe.
    return render_template("vokabeln.html",
        user=user, token=token, farbe=user["farbe"],
        sprachen=sprachen, kapitel=kapitel, vokabeln=vokabeln,
        filter_sprachen=_zugaengliche_sprachen(db, user["id"]),
        filter_kapitel=_zugaengliche_kapitel(db, user["id"]),
        verb_sprachen=sprachen_mit_verbformen(db))


@bp.route("/a/vokabeln/neu", defaults={"token": None}, methods=["POST"])
@bp.route("/a/vokabeln/<token>/neu", methods=["POST"])
def neu(token):
    user = _user(token)
    db = get_db()
    fremd      = request.form.get("fremd", "").strip()
    deutsch    = request.form.get("deutsch", "").strip()
    sprache_id = to_int(request.form.get("sprache_id"))
    kapitel_ids = [to_int(k) for k in request.form.getlist("kapitel_ids")]
    simple_past, perfect = _verbformen_lesen(db, sprache_id)

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        cur = db.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch, simple_past, perfect) "
            "VALUES(?,?,?,?,?,?)",
            (user["id"], sprache_id, fremd, deutsch, simple_past, perfect),
        )
        _kapitel_ids_setzen(db, cur.lastrowid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<int:vid>/bearbeiten", defaults={"token": None}, methods=["POST"])
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

    simple_past, perfect = _verbformen_lesen(db, sprache_id)

    if fremd and deutsch and sprache_id and _sprache_erlaubt(db, user["id"], sprache_id):
        db.execute(
            "UPDATE vokabeln SET fremd=?, deutsch=?, sprache_id=?, "
            "simple_past=?, perfect=? WHERE id=?",
            (fremd, deutsch, sprache_id, simple_past, perfect, vid),
        )
        _kapitel_ids_setzen(db, vid, user["id"], kapitel_ids)
        db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/<int:vid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/vokabeln/<token>/<int:vid>/loeschen", methods=["POST"])
def loeschen(token, vid):
    user = _user(token)
    db = get_db()
    db.execute("DELETE FROM vokabeln WHERE id=? AND user_id=?", (vid, user["id"]))
    db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/sprachen", defaults={"token": None}, methods=["GET", "POST"])
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


@bp.route("/a/vokabeln/kapitel", defaults={"token": None}, methods=["GET", "POST"])
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
        elif action == "teilen":
            # Wunsch #150: Teilen darf NUR der Eigentuemer - deshalb hier
            # _kapitel_gehoert_nutzer und nicht _kapitel_zugaenglich. Sonst
            # koennte ein Empfaenger das Kapitel weiterreichen.
            kid = to_int(request.form.get("id"), 0)
            if _kapitel_gehoert_nutzer(db, user["id"], kid):
                gewaehlt = {to_int(x) for x in request.form.getlist("mit_user_ids")}
                gewaehlt.discard(None)
                gewaehlt.discard(user["id"])          # sich selbst teilen ist sinnlos
                db.execute("DELETE FROM vokabel_kapitel_freigabe WHERE kapitel_id=?", (kid,))
                for uid in gewaehlt:
                    if db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                        db.execute(
                            "INSERT OR IGNORE INTO vokabel_kapitel_freigabe"
                            "(kapitel_id, user_id) VALUES(?,?)", (kid, uid))
                db.commit()
        return redirect(url_for("vokabeln_app.kapitel_verwalten", token=token))

    kapitel = [dict(k) for k in db.execute(
        "SELECT * FROM vokabel_kapitel WHERE user_id=? ORDER BY name COLLATE NOCASE", (user["id"],)
    ).fetchall()]
    for k in kapitel:
        k["geteilt_mit"] = [r["user_id"] for r in db.execute(
            "SELECT user_id FROM vokabel_kapitel_freigabe WHERE kapitel_id=?", (k["id"],))]
        k["anzahl"] = db.execute(
            "SELECT COUNT(*) FROM vokabel_kapitel_zuordnung WHERE kapitel_id=?", (k["id"],)
        ).fetchone()[0]

    andere = db.execute(
        "SELECT id, name, farbe FROM users WHERE id != ? ORDER BY name COLLATE NOCASE",
        (user["id"],)).fetchall()

    # Was MIR jemand geteilt hat - nur zur Ansicht, aufheben kann es der
    # Eigentuemer. Ohne diese Liste waeren fremde Kapitel zwar im Trainer
    # auswaehlbar, aber nirgends erklaert.
    geteilt_mir = db.execute("""
        SELECT k.id, k.name, u.name AS von,
               (SELECT COUNT(*) FROM vokabel_kapitel_zuordnung z WHERE z.kapitel_id = k.id) AS anzahl
        FROM   vokabel_kapitel_freigabe f
        JOIN   vokabel_kapitel k ON k.id = f.kapitel_id
        JOIN   users u ON u.id = k.user_id
        WHERE  f.user_id = ?
        ORDER  BY u.name COLLATE NOCASE, k.name COLLATE NOCASE
    """, (user["id"],)).fetchall()

    return render_template("vokabel_kapitel.html",
        user=user, token=token, farbe=user["farbe"], kapitel=kapitel,
        andere=andere, geteilt_mir=geteilt_mir)


@bp.route("/a/vokabeln/lernen", defaults={"token": None})
@bp.route("/a/vokabeln/<token>/lernen")
def lernen(token):
    user = _user(token)
    db = get_db()
    sprachen = _zugaengliche_sprachen(db, user["id"])
    kapitel  = _zugaengliche_kapitel(db, user["id"])
    return render_template("vokabel_lernen.html",
        user=user, token=token, farbe=user["farbe"], sprachen=sprachen, kapitel=kapitel,
        verb_abfragen=VERB_ABFRAGEN, verb_standard=VERB_ABFRAGEN_STANDARD,
        verb_sprachen=sprachen_mit_verbformen(db))


@bp.route("/a/vokabeln/lernen/start", defaults={"token": None}, methods=["POST"])
@bp.route("/a/vokabeln/<token>/lernen/start", methods=["POST"])
def lernen_start(token):
    user = _user(token)
    db = get_db()
    sprache_id = to_int(request.form.get("sprache_id"))
    if not sprache_id or not _sprache_zugaenglich(db, user["id"], sprache_id):
        return redirect(url_for("vokabeln_app.lernen", token=token))

    auswahl = request.form.getlist("kapitel_ids")  # kann "alle" und/oder "ohne" enthalten
    alle_gewaehlt = "alle" in auswahl or not auswahl
    ohne_gewaehlt = "ohne" in auswahl
    kapitel_ids   = {to_int(k) for k in auswahl if k not in ("alle", "ohne")}
    kapitel_ids.discard(None)

    # Wunsch #150: ueberall die gemeinsame Sichtbarkeitsregel statt user_id -
    # sonst waere ein geteiltes Kapitel zwar auswaehlbar, das Training aber
    # leer.
    # Wunsch #194: Mindestens eine angekreuzte Abfrageform schaltet das
    # Training auf unregelmaessige Verben um - der "Spezialmodus" aus dem
    # Wunsch. Ohne Kreuz bleibt alles wie bisher. Ein zusaetzlicher
    # Hauptschalter waere ein Bedienelement mehr fuer dieselbe Aussage.
    verb_formen = [f for f in request.form.getlist("verb_formen")
                   if f in VERB_ABFRAGEN]
    nur_verben = bool(verb_formen)
    # Der SQL-Filter ist eine Abkuerzung, KEINE Sicherung: Die Korrektheit
    # kommt aus verb_aufgaben(), das jede Zeile ohne beide Formen ohnehin
    # ueberspringt. Er verhindert nur, dass 500 normale Vokabeln geladen
    # werden, um sie danach wegzuwerfen. (Ihn zu entfernen aendert deshalb
    # kein Testergebnis - absichtlich geprueft.)
    verb_filter = f" AND {_IST_VERB}" if nur_verben else ""
    spalten = ("v.id, v.fremd, v.deutsch, v.simple_past, v.perfect"
               if nur_verben else "v.id, v.fremd, v.deutsch")

    p = {"uid": user["id"], "sid": sprache_id}
    if alle_gewaehlt:
        vokabeln = db.execute(f"""
            SELECT {spalten} FROM vokabeln v
            WHERE  v.sprache_id = :sid AND {_VOKABEL_SICHTBAR}{verb_filter}
        """, p).fetchall()
    else:
        gefunden = {}
        if ohne_gewaehlt:
            # "Ohne Kapitel" bleibt bewusst auf EIGENE Vokabeln beschraenkt:
            # Geteilt wird immer ein Kapitel, eine kapitellose fremde Vokabel
            # kann es also gar nicht geben.
            for r in db.execute(f"""
                SELECT {spalten} FROM vokabeln v
                WHERE v.user_id = :uid AND v.sprache_id = :sid{verb_filter}
                  AND NOT EXISTS (SELECT 1 FROM vokabel_kapitel_zuordnung z WHERE z.vokabel_id=v.id)
            """, p).fetchall():
                gefunden[r[0]] = r
        for kid in kapitel_ids:
            if not _kapitel_zugaenglich(db, user["id"], kid):
                continue
            for r in db.execute(f"""
                SELECT {spalten} FROM vokabeln v
                JOIN vokabel_kapitel_zuordnung z ON z.vokabel_id = v.id
                WHERE v.sprache_id = :sid AND z.kapitel_id = :kid{verb_filter}
            """, {"sid": sprache_id, "kid": kid}).fetchall():
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

    if nur_verben:
        aufgaben = verb_aufgaben(vokabeln, verb_formen)
    else:
        # Ohne Verbmodus bleibt die Aufgabe wie bisher: EIN Feld, Richtung
        # wuerfelt das Training selbst.
        aufgaben = [{"id": v["id"], "fremd": v["fremd"], "deutsch": v["deutsch"]}
                    for v in vokabeln]

    # Wunsch #258: Der Mikrofon-Knopf erscheint nur, wenn die Sprache ein
    # Aussprache-Training hat - serverseitig entschieden, die Vorlage kennt
    # die Sprachliste nicht.
    sprache = db.execute(
        "SELECT name FROM vokabel_sprachen WHERE id=?", (sprache_id,)).fetchone()
    aussprache = aussprache_moeglich(sprache["name"] if sprache else "")

    if not aufgaben:
        db.execute("UPDATE vokabel_sessions SET beendet=datetime('now') WHERE id=?", (session_id,))
        db.commit()
        return render_template("vokabel_training.html",
            user=user, token=token, farbe=user["farbe"], session_id=session_id,
            vokabeln=[], verbmodus=nur_verben, aussprache_moeglich=aussprache)

    db.commit()
    random.shuffle(aufgaben)
    return render_template("vokabel_training.html",
        user=user, token=token, farbe=user["farbe"],
        session_id=session_id, vokabeln=aufgaben, verbmodus=nur_verben,
        aussprache_moeglich=aussprache)


@bp.route("/a/vokabeln/versuch", defaults={"token": None}, methods=["POST"])
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
        f"SELECT 1 FROM vokabeln v WHERE v.id = :vid AND {_VOKABEL_SICHTBAR}",
        {"vid": vokabel_id, "uid": user["id"]}
    ).fetchone()
    if not (session_ok and vokabel_ok):
        return jsonify(ok=False), 400

    db.execute(
        "INSERT INTO vokabel_versuche(session_id, vokabel_id, richtig) VALUES(?,?,?)",
        (session_id, vokabel_id, 1 if richtig else 0),
    )
    db.commit()
    return jsonify(ok=True)


@bp.route("/a/vokabeln/session/<int:sid>/beenden", defaults={"token": None}, methods=["POST"])
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


@bp.route("/a/vokabeln/auswertung", defaults={"token": None})
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

    # Wunsch #150: Auch geteilte Vokabeln - der Wunsch verlangt ausdruecklich,
    # dass ALLE Trainings dokumentiert werden. Ohne das faenden sich Trainings
    # mit fremden Kapiteln in keiner Auswertung wieder.
    sprachen = db.execute(f"""
        SELECT DISTINCT s.id, s.name FROM vokabeln v
        JOIN   vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  {_VOKABEL_SICHTBAR}
        ORDER  BY s.name COLLATE NOCASE
    """, {"uid": ziel["id"]}).fetchall()

    sprache_id = to_int(request.args.get("sprache")) or (sprachen[0]["id"] if sprachen else None)

    kapitel_auswertung = []
    if sprache_id:
        vokabeln = db.execute(f"""
            SELECT v.id, v.fremd, v.deutsch FROM vokabeln v
            WHERE  v.sprache_id = :sid AND {_VOKABEL_SICHTBAR}
        """, {"uid": ziel["id"], "sid": sprache_id}).fetchall()
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


@bp.route("/a/vokabeln/foto-import", defaults={"token": None}, methods=["GET", "POST"])
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
            sprachen=sprachen, fehler=None,
            verb_sprachen=sprachen_mit_verbformen(db))

    def _fehler(text):
        return render_template("vokabel_foto_import.html",
            user=user, token=token, farbe=user["farbe"],
            sprachen=sprachen, fehler=text,
            verb_sprachen=sprachen_mit_verbformen(db))

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

    # Wunsch #194: Dieselbe Seite liest wahlweise eine Vokabelliste oder eine
    # Verbtabelle - mit zwei getrennten Prompts (siehe _verben_per_ki).
    verbmodus = bool(request.form.get("verbmodus"))
    b64 = base64.b64encode(rohdaten).decode()
    try:
        if verbmodus:
            paare = _verben_per_ki(user["id"], mime, b64)
        else:
            paare = _vokabeln_per_ki(user["id"], sprache["name"], mime, b64)
    except KiLimitError:
        return _fehler(
            "Monatliches KI-Kontingent aufgebraucht – bitte später erneut versuchen "
            "oder die Vokabeln manuell eintragen.")
    except Exception:
        return _fehler("Auf dem Foto konnten keine Verben erkannt werden."
                       if verbmodus else
                       "Auf dem Foto konnten keine Vokabeln erkannt werden.")

    return render_template("vokabel_foto_pruefen.html",
        user=user, token=token, farbe=user["farbe"],
        sprache=sprache, kapitel=kapitel, paare=paare, verbmodus=verbmodus)


@bp.route("/a/vokabeln/foto-import/speichern", defaults={"token": None}, methods=["POST"])
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
    # Wunsch #194: Im Verbmodus kommen zwei Listen mehr mit. Sie sind gleich
    # lang wie `fremde`, weil das Pruefformular je Zeile alle Felder rendert -
    # `_spalte()` faengt trotzdem ab, wenn nicht: eine zu kurze Liste soll die
    # ganze Uebernahme nicht mit einem IndexError abbrechen.
    pasts    = request.form.getlist("simple_past")
    perfects = request.form.getlist("perfect")
    verb_sprachen = sprachen_mit_verbformen(db)

    def _spalte(liste, i):
        return liste[i].strip() if i < len(liste) else ""

    for i, (fremd, deutsch) in enumerate(zip(fremde, deutsche)):
        if i not in behalten:
            continue
        fremd, deutsch = fremd.strip(), deutsch.strip()
        if not fremd or not deutsch:
            continue
        past, perfect = _spalte(pasts, i), _spalte(perfects, i)
        if not (past and perfect) or sprache_id not in verb_sprachen:
            past = perfect = None
        cur = db.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch, simple_past, perfect) "
            "VALUES(?,?,?,?,?,?)",
            (user["id"], sprache_id, fremd, deutsch, past, perfect),
        )
        _kapitel_ids_setzen(db, cur.lastrowid, user["id"], kapitel_ids)
    db.commit()
    return redirect(url_for("vokabeln_app.index", token=token))


@bp.route("/a/vokabeln/wort/<int:vid>/audio", defaults={"token": None})
@bp.route("/a/vokabeln/<token>/wort/<int:vid>/audio")
def wort_audio(token, vid):
    """Wunsch #81: liest das fremdsprachige Wort per KI-TTS vor, einmalig
    erzeugt und dauerhaft im Datenordner gecacht (siehe _audio_pfad)."""
    user = _user(token)
    db = get_db()
    # Wunsch #150: auch geteilte Vokabeln - "die Media-Dateien anhoeren"
    # steht ausdruecklich im Wunsch.
    row = db.execute(f"""
        SELECT v.fremd, v.sprache_id FROM vokabeln v
        WHERE  v.id = :vid AND {_VOKABEL_SICHTBAR}
    """, {"vid": vid, "uid": user["id"]}).fetchone()
    if not row:
        abort(404)

    pfad = _audio_pfad(row["sprache_id"], row["fremd"])
    if not os.path.exists(pfad):
        try:
            audio, _mime = ki_text_zu_sprache(user["id"], row["fremd"], row["sprache_id"])
        except KiLimitError:
            abort(429)
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


def _aussprache_per_ki(user_id, wort, sprache_name, wav_b64):
    """Wunsch #258: Bewertet eine Stimmaufnahme gegen das Zielwort ueber die
    KI-Schicht (Zweck "vokabeln_aussprache", Audio-Modell mit EU-Anbieter,
    siehe AUSSPRACHE_STANDARD_* in 00_kern.py). Liefert
    {"note": 1..5, "verstanden": str, "tipp": str}. Wirft KiLimitError/
    KiFehler/ValueError - der Aufrufer macht daraus eine freundliche
    Meldung. Die Aufnahme wird nirgends gespeichert; sie lebt nur in dieser
    Anfrage."""
    system = (
        "Du bist ein freundlicher, geduldiger Aussprache-Trainer für Kinder, "
        "die Vokabeln lernen. Du bekommst ein Zielwort und eine kurze "
        "Tonaufnahme, in der das Kind versucht, dieses Wort auszusprechen. "
        "Beurteile NUR die Aussprache des Zielworts. Antworte AUSSCHLIESSLICH "
        'mit einem JSON-Objekt der Form {"verstanden": "...", "note": 1, '
        '"tipp": "..."}. "verstanden" ist, was du in der Aufnahme gehört hast '
        "(kurz, in der Fremdsprache). \"note\" ist eine Zahl von 1 bis 5: "
        "5 = sehr gut verständlich und richtig betont, 4 = gut mit kleiner "
        "Abweichung, 3 = verständlich, aber deutlich anders, 2 = schwer "
        "verständlich, 1 = nicht erkennbar oder ein anderes Wort. \"tipp\" "
        "ist EIN kurzer, konkreter, ermutigender Hinweis auf Deutsch (höchstens "
        "zwei Sätze), z. B. welcher Laut anders klingen sollte. Bei Note 5 "
        "genügt ein Lob. Keine Erklärung außerhalb des JSON, kein Markdown, "
        "kein Codeblock."
    )
    prompt = (
        f"Zielwort: „{wort}“ (Sprache: {sprache_name}). "
        "Bewerte die Aussprache in der Aufnahme."
    )
    antwort = ki_anfrage(
        user_id, "vokabeln_aussprache", system, prompt,
        max_tokens=300, audio=("wav", wav_b64),
    )
    bereinigt = antwort.strip()
    if bereinigt.startswith("```"):
        bereinigt = bereinigt.strip("`")
        if bereinigt.lower().startswith("json"):
            bereinigt = bereinigt[4:]
    # Manche Modelle stellen trotz Anweisung einen Satz voran - das JSON
    # beginnt bei der ersten geschweiften Klammer.
    anfang = bereinigt.find("{")
    ende = bereinigt.rfind("}")
    if anfang < 0 or ende < anfang:
        raise ValueError("KI hat kein JSON-Objekt geliefert")
    daten = json.loads(bereinigt[anfang:ende + 1])
    if not isinstance(daten, dict):
        raise ValueError("KI hat kein Objekt geliefert")
    note = to_int(daten.get("note"))
    if note is None:
        raise ValueError("KI hat keine Note geliefert")
    note = max(1, min(5, note))
    verstanden = str(daten.get("verstanden") or "").strip()
    tipp = str(daten.get("tipp") or "").strip()
    return {
        "note": note,
        "verstanden": verstanden[:_AUSSPRACHE_MAX_ZEICHEN_VERSTANDEN],
        "tipp": tipp[:_AUSSPRACHE_MAX_ZEICHEN_TIPP],
    }


@bp.route("/a/vokabeln/wort/<int:vid>/aussprache", defaults={"token": None}, methods=["POST"])
@bp.route("/a/vokabeln/<token>/wort/<int:vid>/aussprache", methods=["POST"])
def wort_aussprache(token, vid):
    """Wunsch #258: Nimmt eine WAV-Aufnahme (Body, audio/wav) entgegen und
    liefert die Bewertung als JSON. Antworten sind immer JSON mit `ok` und
    im Fehlerfall `fehler` - der Trainer zeigt den Text direkt an, statt
    einen Statuscode zu raten."""
    user = _user(token)
    db = get_db()
    row = db.execute(f"""
        SELECT v.fremd, s.name AS sprache
        FROM   vokabeln v JOIN vokabel_sprachen s ON s.id = v.sprache_id
        WHERE  v.id = :vid AND {_VOKABEL_SICHTBAR}
    """, {"vid": vid, "uid": user["id"]}).fetchone()
    if not row:
        abort(404)
    if not aussprache_moeglich(row["sprache"]):
        return jsonify(ok=False, fehler="Für diese Sprache gibt es kein Aussprache-Training."), 400

    # Groesse VOR dem Einlesen pruefen (Content-Length), und danach noch
    # einmal am echten Inhalt - der Header ist eine Behauptung des Clients.
    if (request.content_length or 0) > _AUSSPRACHE_MAX_BYTES:
        return jsonify(ok=False, fehler="Die Aufnahme ist zu lang."), 413
    daten = request.get_data(cache=False)
    if len(daten) > _AUSSPRACHE_MAX_BYTES:
        return jsonify(ok=False, fehler="Die Aufnahme ist zu lang."), 413
    if len(daten) < _AUSSPRACHE_MIN_BYTES or not daten.startswith(b"RIFF"):
        return jsonify(ok=False, fehler="Keine brauchbare Aufnahme - bitte noch einmal sprechen."), 400

    try:
        ergebnis = _aussprache_per_ki(
            user["id"], row["fremd"], row["sprache"],
            base64.b64encode(daten).decode("ascii"))
    except KiLimitError:
        return jsonify(
            ok=False,
            fehler="Monatliches KI-Kontingent aufgebraucht - bitte später erneut versuchen.",
        ), 429
    except (KiFehler, ValueError):
        return jsonify(
            ok=False,
            fehler="Die Bewertung klappt gerade nicht - bitte später noch einmal.",
        ), 502
    return jsonify(ok=True, **ergebnis)


def init_app(app):
    app.register_blueprint(bp)
