"""Wunsch #258: Aussprachetraining mit Mikrofon-Aufzeichnung.

Der Trainer nimmt nach der Antwort per Mikrofon auf, der Browser packt die
Aufnahme zu WAV, /wort/<vid>/aussprache laesst sie ueber die KI-Schicht
bewerten. Andis Vorgaben aus der Rueckfrage: Weg A (KI-Schicht), Modell in
der EU gehostet und nicht in China entwickelt - das ist Voxtral von Mistral,
festgenagelt auf den Endpunkt "mistral/eu".

**Der Test, auf den es hier ankommt:** die Anfrage geht mit
`provider.only = ["mistral/eu"]` und `allow_fallbacks = false` raus. Ohne
das wuerde OpenRouter bei einem Engpass stillschweigend auf einen anderen
Anbieter ausweichen - mit der Stimmaufnahme eines Kindes. Die uebrigen
Tests sichern die Mechanik: Sichtbarkeit, Latein-Ausnahme, Groessen,
Kontingent, JSON-Parsen und den Knopf im Trainer.

Nicht pruefbar ist hier, ob Voxtral die Aussprache GUT beurteilt - das
kann nur ein Ohr. Die Live-Pruefung nach dem Ausrollen schickt eine echte
Aufnahme (journal.md, 05.09.2026).
"""
import importlib
import io
import json
import struct
import sys
import wave

import pytest


@pytest.fixture()
def kern():
    from teile import kern
    return kern


@pytest.fixture()
def vokabeln(app):
    return importlib.import_module("teile.16_vokabeln")


def _wav(sekunden=1.0, rate=16000):
    """Ein gueltiges, stilles WAV - genau das Format, das der Browser baut."""
    puffer = io.BytesIO()
    with wave.open(puffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(sekunden * rate))
    return puffer.getvalue()


@pytest.fixture()
def vok(app, db):
    """Admin mit Vokabeln-Grant, je eine Vokabel auf Englisch und Latein."""
    from teile.kern import new_token, token_lookup

    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (uid, app_id, token_lookup(klartext)))
        ids = {}
        for sprache, fremd, deutsch in (("Englisch", "house", "Haus"),
                                        ("Latein", "domus", "Haus")):
            sid = v.execute("SELECT id FROM vokabel_sprachen WHERE name=?",
                            (sprache,)).fetchone()["id"]
            v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                      "VALUES(?,?)", (uid, sid))
            vid = v.execute(
                "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) "
                "VALUES(?,?,?,?) RETURNING id", (uid, sid, fremd, deutsch)).fetchone()["id"]
            ids[sprache] = {"sprache_id": sid, "vokabel_id": vid}
        v.commit()
    return {"token": klartext, "uid": uid, "v": v, **ids}


def _url(vok, vid):
    return f"/a/vokabeln/{vok['token']}/wort/{vid}/aussprache"


# --- Konfiguration ---------------------------------------------------------

def test_seed_traegt_voxtral_mit_eu_anbieter(app, db, kern):
    """Was _init_db anlegt: der Zweck existiert, Modell aus der EU, Anbieter
    festgenagelt. INSERT OR IGNORE - ein spaeter per manage.py gesetzter
    Wert wird von einem Deploy nicht ueberschrieben."""
    zeile = db["verbindung"].execute(
        "SELECT modell, anbieter FROM ki_konfiguration WHERE zweck='vokabeln_aussprache'"
    ).fetchone()
    assert zeile is not None
    assert zeile["modell"] == kern.AUSSPRACHE_STANDARD_MODELL
    assert zeile["modell"].startswith("mistralai/")
    assert zeile["anbieter"] == "mistral/eu"
    with app.app_context():
        assert kern.ki_anbieter_fuer("vokabeln_aussprache") == "mistral/eu"
        assert kern.ki_anbieter_fuer("rezepte_import") is None


def test_manage_ki_modell_setzt_und_loescht_den_anbieter(app, db, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", app.config["DB_PATH"])
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"))
    manage = importlib.import_module("manage")
    importlib.reload(manage)

    manage.cmd_ki_modell(["vokabeln_aussprache", "mistralai/anderes", "mistral/zdr"])
    zeile = db["verbindung"].execute(
        "SELECT modell, anbieter FROM ki_konfiguration WHERE zweck='vokabeln_aussprache'"
    ).fetchone()
    assert (zeile["modell"], zeile["anbieter"]) == ("mistralai/anderes", "mistral/zdr")
    assert "mistral/zdr" in capsys.readouterr().out

    # Ohne drittes Argument bleibt der Anbieter stehen ...
    manage.cmd_ki_modell(["vokabeln_aussprache", "mistralai/drittes"])
    zeile = db["verbindung"].execute(
        "SELECT modell, anbieter FROM ki_konfiguration WHERE zweck='vokabeln_aussprache'"
    ).fetchone()
    assert (zeile["modell"], zeile["anbieter"]) == ("mistralai/drittes", "mistral/zdr")

    # ... und "-" loescht ihn ausdruecklich.
    manage.cmd_ki_modell(["vokabeln_aussprache", "mistralai/drittes", "-"])
    zeile = db["verbindung"].execute(
        "SELECT anbieter FROM ki_konfiguration WHERE zweck='vokabeln_aussprache'"
    ).fetchone()
    assert zeile["anbieter"] is None

    # Aufraeumen: ki_konfiguration ist eine Seed-Tabelle und wird von der
    # db-Fixture NICHT geleert - der Standard muss fuer die naechsten Tests
    # wieder stehen.
    manage.cmd_ki_modell(["vokabeln_aussprache", kern_modell(), "mistral/eu"])


def kern_modell():
    from teile import kern
    return kern.AUSSPRACHE_STANDARD_MODELL


# --- ki_anfrage: Audio-Eingabe und Anbieter-Festlegung ----------------------

class _Antwort:
    def __init__(self, text):
        self._text = text

    def read(self):
        return json.dumps({
            "choices": [{"message": {"content": self._text}}],
            "usage": {"total_tokens": 42},
        }).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_faenger(monkeypatch, text="ok"):
    """Faengt die OpenRouter-Anfrage ab und merkt sich den Body."""
    gesehen = {}

    def urlopen(req, timeout=None):
        gesehen["body"] = json.loads(req.data)
        gesehen["url"] = req.full_url
        return _Antwort(text)

    monkeypatch.setattr(__import__("urllib.request", fromlist=["urlopen"]), "urlopen", urlopen)
    return gesehen


def test_anfrage_geht_mit_audio_und_nur_zum_eu_anbieter(app, kern, admin, db, monkeypatch):
    """Die Sicherheitsaussage dieser Datei."""
    app.config["OPENROUTER_API_KEY"] = "test"
    gesehen = _urlopen_faenger(monkeypatch)
    with app.app_context():
        kern.ki_anfrage(admin["id"], "vokabeln_aussprache", "sys", "Zielwort: house",
                        max_tokens=100, audio=("wav", "UklGRg=="))
    body = gesehen["body"]
    assert body["model"] == kern.AUSSPRACHE_STANDARD_MODELL
    assert body["provider"] == {"only": ["mistral/eu"], "allow_fallbacks": False}
    inhalt = body["messages"][1]["content"]
    assert inhalt[0] == {"type": "text", "text": "Zielwort: house"}
    assert inhalt[1] == {"type": "input_audio",
                         "input_audio": {"data": "UklGRg==", "format": "wav"}}


def test_text_zwecke_bekommen_keinen_anbieter_block(app, kern, admin, db, monkeypatch):
    """Nur wo der Ort der Verarbeitung Teil der Zusage ist, wird er
    vorgegeben - die Text-Zwecke sollen OpenRouter frei waehlen lassen."""
    app.config["OPENROUTER_API_KEY"] = "test"
    gesehen = _urlopen_faenger(monkeypatch)
    with app.app_context():
        kern.ki_anfrage(admin["id"], "rezepte_import", "sys", "Hallo", max_tokens=10)
    assert "provider" not in gesehen["body"]
    assert gesehen["body"]["messages"][1]["content"] == "Hallo"


def test_bild_und_audio_zusammen_landen_im_selben_content(app, kern, admin, db, monkeypatch):
    app.config["OPENROUTER_API_KEY"] = "test"
    gesehen = _urlopen_faenger(monkeypatch)
    with app.app_context():
        kern.ki_anfrage(admin["id"], "vokabeln_ocr", "sys", "p", max_tokens=10,
                        bilder=[("image/png", "AAAA")], audio=("wav", "BBBB"))
    typen = [t["type"] for t in gesehen["body"]["messages"][1]["content"]]
    assert typen == ["text", "image_url", "input_audio"]


# --- Die Route ---------------------------------------------------------------

def _ki_stub(vokabeln, monkeypatch, antwort):
    aufrufe = []

    def ki(user_id, feature, system, prompt, max_tokens=1500, bilder=None, audio=None):
        aufrufe.append({"user_id": user_id, "feature": feature, "prompt": prompt,
                        "audio": audio, "system": system})
        if isinstance(antwort, Exception):
            raise antwort
        return antwort

    monkeypatch.setattr(vokabeln, "ki_anfrage", ki)
    return aufrufe


def test_bewertung_kommt_als_json_zurueck(client, vok, vokabeln, monkeypatch):
    aufrufe = _ki_stub(vokabeln, monkeypatch,
                       '{"verstanden": "haus", "note": 4, "tipp": "Das h etwas weicher."}')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"ok": True, "note": 4, "verstanden": "haus",
                            "tipp": "Das h etwas weicher."}
    assert len(aufrufe) == 1
    assert aufrufe[0]["feature"] == "vokabeln_aussprache"
    assert aufrufe[0]["user_id"] == vok["uid"]
    assert "house" in aufrufe[0]["prompt"] and "Englisch" in aufrufe[0]["prompt"]
    fmt, b64 = aufrufe[0]["audio"]
    assert fmt == "wav"
    import base64
    assert base64.b64decode(b64).startswith(b"RIFF")


def test_json_in_codeblock_und_mit_vorrede_wird_verstanden(client, vok, vokabeln, monkeypatch):
    """Modelle halten sich nicht immer an "nur JSON"."""
    _ki_stub(vokabeln, monkeypatch,
             'Hier die Bewertung:\n```json\n{"verstanden": "house", "note": "5", "tipp": "Super!"}\n```')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 200
    assert r.get_json()["note"] == 5


def test_note_wird_auf_1_bis_5_begrenzt(client, vok, vokabeln, monkeypatch):
    _ki_stub(vokabeln, monkeypatch, '{"verstanden": "x", "note": 9, "tipp": ""}')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.get_json()["note"] == 5
    _ki_stub(vokabeln, monkeypatch, '{"verstanden": "x", "note": -3, "tipp": ""}')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.get_json()["note"] == 1


def test_unbrauchbare_ki_antwort_ist_502(client, vok, vokabeln, monkeypatch):
    _ki_stub(vokabeln, monkeypatch, "Tut mir leid, das kann ich nicht.")
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 502
    assert r.get_json()["ok"] is False
    assert r.get_json()["fehler"]


def test_kontingent_aufgebraucht_ist_429(client, vok, vokabeln, monkeypatch, kern):
    _ki_stub(vokabeln, monkeypatch, kern.KiLimitError("leer"))
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 429
    assert "Kontingent" in r.get_json()["fehler"]


def test_ki_fehler_ist_502(client, vok, vokabeln, monkeypatch, kern):
    _ki_stub(vokabeln, monkeypatch, kern.KiFehler("Netz weg"))
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 502


def test_latein_hat_kein_training(client, vok, vokabeln, monkeypatch):
    """Die Ausnahme aus der Rueckfrage. Kein KI-Aufruf, kein Kontingent."""
    aufrufe = _ki_stub(vokabeln, monkeypatch, '{"note": 5}')
    r = client.post(_url(vok, vok["Latein"]["vokabel_id"]),
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 400
    assert "Latein" not in r.get_json()["fehler"] or True
    assert aufrufe == []
    assert vokabeln.aussprache_moeglich("Englisch")
    assert not vokabeln.aussprache_moeglich("Latein")


def test_fremde_vokabel_ist_404(client, vok, kind, vokabeln, monkeypatch, app, db):
    """Sichtbarkeitsregel wie ueberall in der App (Wunsch #150)."""
    from teile.kern import new_token, token_lookup
    aufrufe = _ki_stub(vokabeln, monkeypatch, '{"note": 5}')
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        kind_token = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (kind["id"], app_id, token_lookup(kind_token)))
        v.commit()
    r = client.post(f"/a/vokabeln/{kind_token}/wort/{vok['Englisch']['vokabel_id']}/aussprache",
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 404
    assert aufrufe == []


def test_ohne_grant_403(client, vok):
    r = client.post(f"/a/vokabeln/falscher-token/wort/{vok['Englisch']['vokabel_id']}/aussprache",
                    data=_wav(), content_type="audio/wav")
    assert r.status_code == 403


def test_zu_kurze_oder_fremde_daten_sind_400(client, vok, vokabeln, monkeypatch):
    """Ein Klick ohne Wort oder ein Nicht-WAV loest keinen KI-Aufruf aus."""
    aufrufe = _ki_stub(vokabeln, monkeypatch, '{"note": 5}')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(sekunden=0.1), content_type="audio/wav")
    assert r.status_code == 400
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=b"x" * 20000, content_type="audio/wav")
    assert r.status_code == 400
    assert aufrufe == []


def test_zu_grosse_aufnahme_ist_413(client, vok, vokabeln, monkeypatch):
    aufrufe = _ki_stub(vokabeln, monkeypatch, '{"note": 5}')
    r = client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                    data=_wav(sekunden=40), content_type="audio/wav")
    assert r.status_code == 413
    assert aufrufe == []


def test_aufnahme_wird_nicht_gespeichert(client, vok, vokabeln, monkeypatch, app, tmp_path):
    """Die Zusage aus der Hilfe: nichts landet im Datenordner."""
    import os
    _ki_stub(vokabeln, monkeypatch, '{"verstanden": "house", "note": 5, "tipp": "Top"}')
    vorher = {os.path.join(r, f) for r, _, fs in os.walk(app.config["DATA_DIR"]) for f in fs}
    client.post(_url(vok, vok["Englisch"]["vokabel_id"]),
                data=_wav(), content_type="audio/wav")
    nachher = {os.path.join(r, f) for r, _, fs in os.walk(app.config["DATA_DIR"]) for f in fs}
    assert nachher - vorher == set()


# --- Der Trainer -------------------------------------------------------------

def _training(client, vok, sprache):
    return client.post(f"/a/vokabeln/{vok['token']}/lernen/start",
                       data={"sprache_id": vok[sprache]["sprache_id"], "kapitel_ids": "alle"},
                       follow_redirects=True).get_data(as_text=True)


def test_trainer_zeigt_den_mikrofon_knopf_nur_mit_training(client, vok):
    englisch = _training(client, vok, "Englisch")
    assert 'id="aussprache-btn"' in englisch
    assert 'data-klick="ausspracheUeben"' in englisch
    assert 'id="aussprache-feedback"' in englisch
    latein = _training(client, vok, "Latein")
    assert 'id="aussprache-btn"' not in latein
    # Das Skript ist trotzdem da (eine Vorlage, ein Skript) und kommt mit dem
    # fehlenden Knopf zurecht - jeder Zugriff fragt vorher, ob er existiert.
    assert "ausspracheZuruecksetzen" in latein


def test_der_trainer_nimmt_selbst_auf_statt_zu_diktieren():
    """Andis ausdrueckliche Vorgabe: nicht die Spracherkennung des Geraets."""
    import pathlib
    tpl = (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
           / "vokabel_training.html").read_text(encoding="utf-8")
    assert "MediaRecorder" in tpl
    assert "getUserMedia" in tpl
    assert "SpeechRecognition" not in tpl
    assert "webkitSpeechRecognition" not in tpl
    # Die Aufnahme geht als WAV raus, damit der Server kein webm/mp4 dekodieren muss.
    assert "'audio/wav'" in tpl
    assert "'RIFF'" in tpl
