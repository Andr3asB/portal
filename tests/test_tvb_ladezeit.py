"""Wunsch #270: Das erste Oeffnen der TVB-App nach laengerer Pause dauerte
rund acht Sekunden - der Seitenaufruf machte sieben Fremdaufrufe nacheinander
(Vereinsdaten 1,1 s, sechs Sportradar-Listen 5,5 s, zwei Tabellen 0,8 s;
gemessen 07.09.2026 im Container).

Drei Massnahmen, drei Wächter:
1. Die Sportradar-Listen laufen parallel (Reihenfolge beim Zusammenfuehren
   bleibt - test_tvb_nachladen prueft das Ergebnis).
2. Tabellen liegen in tvb_tabellen; die Seite liest sie, statt sie zu holen.
3. Ein Hintergrund-Thread frischt auf, bevor jemand die Seite oeffnet. Der
   Seitenaufruf holt nur noch selbst, wenn der Stand zu alt ist - stuendlich,
   waehrend eines Profispiels alle fuenf Minuten.

Der Thread selbst laeuft im Test NICHT (TVB_HINTERGRUND=0 in conftest); hier
wird sein Durchlauf als Funktion aufgerufen.
"""
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


@pytest.fixture()
def tvb(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='tvb'").fetchone()["id"]
        token = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (uid, app_id, token_lookup(token)))
        v.execute("""INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse, turnier_id, position, ist_profi, aktualisiert_am)
                     VALUES ('profis', 'TVB Stuttgart', 'Opel HBL', 'Profis', 'Herren', NULL, 0, 1, datetime('now'))""")
        v.execute("""INSERT INTO tvb_mannschaften(team_id, name, liga, kurz, altersklasse, turnier_id, position, ist_profi, aktualisiert_am)
                     VALUES ('87353', 'TV Bittenfeld II', '3. Liga Männer', 'Herren 3. Liga', 'Herren', '14056', 1, 0, datetime('now'))""")
        v.commit()
    return {"token": token, "v": v}


def _standings():
    return {"data": {"standings": []}}


def _zaehler(modul, monkeypatch):
    """Zaehlt Fremdaufrufe je Endpunkt; alle liefern leere, aber gueltige Antworten."""
    aufrufe = {"sr": [], "neu": [], "verein": 0}
    monkeypatch.setattr(modul, "_sr_get", lambda pfad, embed=248: aufrufe["sr"].append(pfad) or (
        _standings() if pfad.startswith("standings") else {"data": {"fixtures": []}}))
    monkeypatch.setattr(modul, "_neu_api_get", lambda pfad: aufrufe["neu"].append(pfad) or {"data": []})

    def verein():
        aufrufe["verein"] += 1
        return [], []
    monkeypatch.setattr(modul, "_mannschaften_von_api", verein)
    return aufrufe


def _profis_ok(db, vor_minuten):
    wann = (datetime.now(UTC) - timedelta(minutes=vor_minuten)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("INSERT INTO tvb_quellen(quelle, zuletzt_ok, zuletzt_versuch, letzter_fehler) VALUES ('profis', ?, ?, NULL) "
               "ON CONFLICT(quelle) DO UPDATE SET zuletzt_ok=excluded.zuletzt_ok, zuletzt_versuch=excluded.zuletzt_versuch, letzter_fehler=NULL",
               (wann, wann))
    db.commit()


# --- Frische ----------------------------------------------------------------------

def test_frischer_stand_kostet_keinen_fremdaufruf(client, tvb, modul, monkeypatch):
    """Die Kernaussage: Hintergrund hat vor 10 Minuten geliefert, die Seite
    liest nur noch - kein einziger Aufruf nach draussen."""
    aufrufe = _zaehler(modul, monkeypatch)
    _profis_ok(tvb["v"], 10)
    tvb["v"].execute("INSERT INTO tvb_tabellen(team_id, daten) VALUES ('profis', ?)", (json.dumps(_standings()),))
    tvb["v"].commit()
    r = client.get(f"/a/tvb/{tvb['token']}/")
    assert r.status_code == 200
    assert aufrufe["sr"] == [] and aufrufe["neu"] == [] and aufrufe["verein"] == 0
    assert "nicht abrufbar" not in r.get_data(as_text=True)


def test_alter_stand_wird_beim_aufruf_nachgeholt(client, tvb, modul, monkeypatch):
    """Rueckfall wie vor #270: ist der Stand zu alt (Thread tot, Neustart),
    holt der Seitenaufruf selbst - und speichert die Tabelle."""
    aufrufe = _zaehler(modul, monkeypatch)
    _profis_ok(tvb["v"], 90)
    client.get(f"/a/tvb/{tvb['token']}/")
    assert any(p.startswith("standings") for p in aufrufe["sr"])
    assert any(p.startswith("fixtures") for p in aufrufe["sr"])
    assert tvb["v"].execute("SELECT 1 FROM tvb_tabellen WHERE team_id='profis'").fetchone()


def test_waehrend_eines_spiels_gilt_der_stand_nur_fuenf_minuten(app, tvb, modul):
    v = tvb["v"]
    with app.app_context():
        from teile.kern import get_db
        db = get_db()
        _profis_ok(v, 10)
        assert modul._profis_frisch(db) is True, "ohne Spiel reicht eine Stunde"
        anstoss = (datetime.now(modul._TZ) - timedelta(minutes=30)).isoformat()
        v.execute("INSERT INTO tvb_spiele(id, team_id, heim, gast, anstoss, status, bestaetigt) "
                  "VALUES ('srlive', 'profis', 'TVB Stuttgart', 'X', ?, 'Live', 0)", (anstoss,))
        v.commit()
        assert modul._spiel_im_fenster(db) is True
        assert modul._profis_frisch(db) is False, "im Spielfenster sind zehn Minuten zu alt"
        _profis_ok(v, 2)
        assert modul._profis_frisch(db) is True


def test_spielfenster_reicht_zwei_stunden_vor_und_drei_danach(app, tvb, modul):
    v = tvb["v"]
    with app.app_context():
        from teile.kern import get_db
        db = get_db()
        for versatz, erwartet in ((-4 * 60, False), (-150, True), (90, True), (150, False)):
            v.execute("DELETE FROM tvb_spiele")
            anstoss = (datetime.now(modul._TZ) + timedelta(minutes=versatz)).isoformat()
            v.execute("INSERT INTO tvb_spiele(id, team_id, heim, gast, anstoss, status, bestaetigt) "
                      "VALUES ('srx', 'profis', 'A', 'B', ?, 'Pre', 0)", (anstoss,))
            v.commit()
            assert modul._spiel_im_fenster(db) is erwartet, versatz


# --- Tabellen-Zwischenspeicher ------------------------------------------------------

def test_amateur_tabelle_wird_gespeichert_und_wiederverwendet(client, tvb, modul, monkeypatch):
    aufrufe = _zaehler(modul, monkeypatch)
    _profis_ok(tvb["v"], 10)
    client.get(f"/a/tvb/{tvb['token']}/?team=87353")
    client.get(f"/a/tvb/{tvb['token']}/?team=87353")
    assert aufrufe["neu"].count("standings?phase_id=14056") == 1, "beim zweiten Aufruf aus tvb_tabellen"


def test_alte_tabelle_zaehlt_nicht(app, tvb, modul):
    v = tvb["v"]
    v.execute("INSERT INTO tvb_tabellen(team_id, daten, aktualisiert_am) VALUES ('87353', '{}', datetime('now', '-2 hours'))")
    v.commit()
    with app.app_context():
        from teile.kern import get_db
        assert modul._tabelle_laden(get_db(), "87353") is None
        assert modul._tabelle_laden(get_db(), "87353", max_minuten=24 * 60) == {}


# --- Der Hintergrund-Durchlauf --------------------------------------------------------

def test_hintergrund_frischt_nur_auf_was_zu_alt_ist(app, tvb, modul, monkeypatch):
    aufrufe = _zaehler(modul, monkeypatch)
    v = tvb["v"]
    # Mannschaften frisch (Fixture), Profis alt, Amateur-Tabelle fehlt.
    _profis_ok(v, 90)
    modul._hintergrund_auffrischen(app)
    assert aufrufe["verein"] == 0, "Mannschaften waren frisch"
    assert any(p.startswith("standings") for p in aufrufe["sr"]), "Profis waren alt"
    assert "standings?phase_id=14056" in aufrufe["neu"], "fehlende Amateur-Tabelle geholt"
    # Zweiter Durchlauf direkt danach: nichts mehr zu tun.
    vorher = (len(aufrufe["sr"]), len(aufrufe["neu"]), aufrufe["verein"])
    modul._hintergrund_auffrischen(app)
    assert (len(aufrufe["sr"]), len(aufrufe["neu"]), aufrufe["verein"]) == vorher


def test_hintergrund_frischt_alte_mannschaften_auf(app, tvb, modul, monkeypatch):
    aufrufe = _zaehler(modul, monkeypatch)
    v = tvb["v"]
    v.execute("UPDATE tvb_mannschaften SET aktualisiert_am = datetime('now', '-3 hours')")
    v.commit()
    _profis_ok(v, 10)
    modul._hintergrund_auffrischen(app)
    assert aufrufe["verein"] == 1


def test_hintergrund_respektiert_die_pause_nach_fehlschlag(app, tvb, modul, monkeypatch):
    aufrufe = _zaehler(modul, monkeypatch)
    v = tvb["v"]
    v.execute("INSERT INTO tvb_quellen(quelle, zuletzt_ok, zuletzt_versuch, letzter_fehler) "
              "VALUES ('profis', NULL, datetime('now', '-5 minutes'), 'Sportradar nicht abrufbar')")
    v.commit()
    modul._hintergrund_auffrischen(app)
    assert not any(p.startswith("fixtures") for p in aufrufe["sr"]), "30 Minuten Pause nach einem Fehlschlag"


def test_schalter_steht_in_app_und_conftest():
    import pathlib
    wurzel = pathlib.Path(__file__).resolve().parents[1]
    assert 'app.config["TVB_HINTERGRUND"]' in (wurzel / "src" / "app.py").read_text(encoding="utf-8")
    assert 'os.environ["TVB_HINTERGRUND"] = "0"' in (wurzel / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "TVB_HINTERGRUND=1" in (wurzel / ".env.example").read_text(encoding="utf-8")


def test_der_thread_laeuft_im_test_nicht(app):
    assert str(app.config.get("TVB_HINTERGRUND")) == "0"
