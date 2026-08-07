"""Wunsch #149 (Sprachangabe beim Vorlesen) und #148 (Audio-Kennzeichnung).

Zu #149: Gemeldet war „Dänisch funktioniert nicht". Die Prüfung ergab, dass
technisch alles funktionierte – die Dateien lagen im Cache, waren gültiges
WAV mit denselben Parametern wie bei Englisch. Falsch war die *Aussprache*:
Ans Modell ging nur der nackte Text, ohne jeden Hinweis auf die Sprache. Bei
einem kurzen Wort wie „Hej" oder „God morgen" muss es dann raten und rät bei
einer kleinen Sprache naheliegenderweise auf Englisch.

Diese Tests sichern die Mechanik ab – nicht den Klang, den kann nur ein Ohr
beurteilen.
"""
import importlib

import pytest


@pytest.fixture()
def kern():
    import teile.kern as kern
    return kern


@pytest.fixture()
def vokabeln(app):
    return importlib.import_module("teile.16_vokabeln")


def _sprache(db, name):
    """Holt die Sprache oder legt sie an.

    `vokabel_sprachen` gehoert zu den Seed-Daten und wird von der db-Fixture
    bewusst nicht geleert - ein blankes INSERT liefe deshalb beim zweiten Lauf
    in die UNIQUE-Bedingung."""
    v = db["verbindung"]
    zeile = v.execute("SELECT id FROM vokabel_sprachen WHERE name=?", (name,)).fetchone()
    if zeile:
        return zeile["id"]
    sid = v.execute(
        "INSERT INTO vokabel_sprachen(name) VALUES(?) RETURNING id", (name,)
    ).fetchone()["id"]
    v.commit()
    return sid


# --- Wunsch #149: Sprachangabe ---------------------------------------------

def test_sprachangabe_wird_vorangestellt(kern):
    assert kern.tts_eingabe("God morgen", "Dänisch") == "Sprich auf Dänisch: God morgen"


def test_ohne_sprachnamen_bleibt_der_text_unveraendert(kern):
    """Lieber ohne Angabe vorlesen als mit einer kaputten - eine Anweisung
    wie 'Sprich auf : hus' könnte das Modell mitsprechen."""
    assert kern.tts_eingabe("hus", "") == "hus"
    assert kern.tts_eingabe("hus", None) == "hus"
    assert kern.tts_eingabe("hus", "   ") == "hus"


def test_sprachname_kommt_aus_der_datenbank(app, kern, db):
    """Bewusst keine Zuordnungstabelle im Code: So funktioniert es auch für
    Sprachen, die später jemand selbst anlegt."""
    sid = _sprache(db, "Suaheli")
    with app.app_context():
        assert kern.ki_sprachname(sid) == "Suaheli"
        assert kern.tts_eingabe("jambo", kern.ki_sprachname(sid)) == "Sprich auf Suaheli: jambo"


def test_unbekannte_sprache_liefert_leeren_namen(app, kern):
    with app.app_context():
        assert kern.ki_sprachname(999999) == ""


def test_tts_schickt_die_sprachangabe_ans_modell(app, kern, db, admin, monkeypatch):
    """Der eigentliche Punkt: Die Angabe muss auch wirklich rausgehen."""
    gesendet = {}

    def falscher_aufruf(text, modell, stimme, key, response_format):
        gesendet["text"] = text
        return b"fake-mp3"

    monkeypatch.setattr(kern, "_tts_anfrage", falscher_aufruf)
    sid = _sprache(db, "Dänisch")

    app.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        with app.app_context():
            kern.ki_text_zu_sprache(admin["id"], "God morgen", sid)
    finally:
        app.config["OPENROUTER_API_KEY"] = ""
    assert gesendet["text"] == "Sprich auf Dänisch: God morgen"


def test_kontingent_zaehlt_nur_das_wort_nicht_die_anweisung(app, kern, db, admin, monkeypatch):
    """Sonst würde jede Vokabel plötzlich das Dreifache kosten, nur weil wir
    dem Modell etwas dazusagen."""
    monkeypatch.setattr(kern, "_tts_anfrage", lambda *a, **kw: b"fake")
    sid = _sprache(db, "Dänisch")

    app.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        with app.app_context():
            vorher = kern.ki_tts_zeichen_uebrig(admin["id"])
            kern.ki_text_zu_sprache(admin["id"], "God morgen", sid)
            nachher = kern.ki_tts_zeichen_uebrig(admin["id"])
    finally:
        app.config["OPENROUTER_API_KEY"] = ""
    assert vorher - nachher == len("God morgen")


# --- Cache-Entwertung ------------------------------------------------------

def test_cache_schluessel_ist_versioniert(app, vokabeln):
    """Ohne Versionswechsel würden die alten, falsch klingenden Dateien ewig
    weiterverwendet - der Fehler wäre behoben und trotzdem hörbar."""
    with app.app_context():
        pfad = vokabeln._audio_pfad(3, "God morgen")
    import hashlib
    alt = hashlib.sha256("3:god morgen".encode()).hexdigest()
    neu = hashlib.sha256("v2:3:god morgen".encode()).hexdigest()
    assert neu in pfad
    assert alt not in pfad


def test_gleiches_wort_gleiche_datei(app, vokabeln):
    """Der Cache teilt sich weiterhin über Vokabelzeilen hinweg - Gross- und
    Kleinschreibung und Leerraum dürfen keinen zweiten Aufruf auslösen."""
    with app.app_context():
        assert vokabeln._audio_pfad(3, "God morgen") == vokabeln._audio_pfad(3, "  god MORGEN ")


def test_verschiedene_sprachen_getrennte_dateien(app, vokabeln):
    """Dasselbe Wort klingt je Sprache anders - 'god' gibt es im Englischen
    wie im Dänischen."""
    with app.app_context():
        assert vokabeln._audio_pfad(1, "god") != vokabeln._audio_pfad(3, "god")


# --- Wunsch #148: Kennzeichnung --------------------------------------------

def test_liste_meldet_ob_audio_vorliegt(app, client, admin, db):
    """`audio_da` kommt aus dem Dateisystem, nicht aus einem Datenbank-Merker:
    Der Cache ist die Wahrheit - ein Merker könnte davon abweichen und dann
    das Falsche anzeigen."""
    import os
    v = db["verbindung"]
    sid = _sprache(db, "Dänisch")
    v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) VALUES(?,?)",
              (admin["id"], sid))
    v.execute("INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) "
              "VALUES(?,?,'Hej','Hallo')", (admin["id"], sid))
    v.commit()

    from teile.kern import token_lookup, new_token
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (admin["id"], app_id, token_lookup(klartext)))
        v.commit()

    # Ohne Datei: blasser Knopf
    seite = client.get(f"/a/vokabeln/{klartext}/").get_data(as_text=True)
    assert "vokabel-anhoeren-btn audio-da" not in seite

    # Mit Datei: hervorgehoben
    modul = importlib.import_module("teile.16_vokabeln")
    with app.app_context():
        pfad = modul._audio_pfad(sid, "Hej")
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "wb") as f:
        f.write(b"RIFF----WAVE")
    try:
        seite = client.get(f"/a/vokabeln/{klartext}/").get_data(as_text=True)
        assert "vokabel-anhoeren-btn audio-da" in seite
    finally:
        os.remove(pfad)
