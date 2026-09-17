"""Wunsch #284 (Sicherheitsaudit 16.09.2026, Befund N-05): Ein Nicht-Admin
konnte dem Stundenlauf „Antworten von Andi" unterschieben.

Zwei Löcher, eines im Server, eines im Prüfskript:

1. `aktion_neu` liess dem Urheber eines Wunsches JEDE Aktionsart durch –
   die Vorlage blendete `plan`/`umsetzung`/`notiz` nur im UI aus. Per
   handgebautem POST konnte ein Kind die „letzte Arbeit" fälschen.
2. `scripts/wunsch_lauf_check.py` zählte jede `antwort` als „Andi hat
   geantwortet – hat Vorrang". Der autonome Lauf (Code-Änderung + Deploy)
   hätte eine Kinder-Antwort als Anweisung des Admins gelesen.

Der Server erlaubt Nicht-Admins jetzt nur `frage` und `antwort`; das Skript
zählt nur Admin-Antworten und listet Urheber-Antworten als KONTEXT.
"""
import pathlib
import runpy

import pytest

SKRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "wunsch_lauf_check.py"


@pytest.fixture()
def werkstatt_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    tokens = {}
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        for name, daten in db["familie"].items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
    v.commit()
    return tokens


def _wunsch(db, user_id, prioritaet=None):
    v = db["verbindung"]
    wid = v.execute(
        "INSERT INTO wuensche(text, titel, app_slug, prioritaet, user_id) "
        "VALUES(?,?,?,?,?) RETURNING id",
        ("Bitte etwas bauen", "Etwas", "werkstatt", prioritaet, user_id)).fetchone()["id"]
    v.commit()
    return wid


def _aktionen(db, wid):
    return [dict(r) for r in db["verbindung"].execute(
        "SELECT art, user_id FROM wunsch_aktionen WHERE wunsch_id=? ORDER BY id", (wid,))]


def test_urheber_darf_nur_fragen_und_antworten(client, db, kind, werkstatt_token):
    wid = _wunsch(db, kind["id"])
    tok = werkstatt_token["TestKind"]
    for art in ("umsetzung", "plan", "notiz"):
        r = client.post(f"/a/werkstatt/{tok}/aktion/{wid}", data={"art": art, "text": "x"})
        assert r.status_code == 403, art
    assert _aktionen(db, wid) == []

    r = client.post(f"/a/werkstatt/{tok}/aktion/{wid}", data={"art": "antwort", "text": "ok"})
    assert r.status_code == 302
    r = client.post(f"/a/werkstatt/{tok}/aktion/{wid}", data={"art": "frage", "text": "?"})
    assert r.status_code == 302
    assert [a["art"] for a in _aktionen(db, wid)] == ["antwort", "frage"]


def test_admin_darf_weiterhin_alles(client, db, admin, kind, werkstatt_token):
    wid = _wunsch(db, kind["id"])
    tok = werkstatt_token["TestAdmin"]
    for art in ("plan", "umsetzung", "notiz", "antwort", "frage"):
        r = client.post(f"/a/werkstatt/{tok}/aktion/{wid}", data={"art": art, "text": "x"})
        assert r.status_code == 302, art
    assert len(_aktionen(db, wid)) == 5


def _aktion(db, wid, art, user_id, erstellt):
    db["verbindung"].execute(
        "INSERT INTO wunsch_aktionen(wunsch_id, art, text, user_id, erstellt) "
        "VALUES(?,?,?,?,?)", (wid, art, "text", user_id, erstellt))
    db["verbindung"].commit()


def _lauf_check(capsys):
    """Das Prüfskript so ausführen, wie es im Container läuft - gegen die
    Datenbank aus DB_PATH (conftest zeigt auf die Wegwerf-DB)."""
    runpy.run_path(str(SKRIPT), run_name="__main__")
    return capsys.readouterr().out


def test_kinder_antwort_ist_kontext_keine_anweisung(db, admin, kind, capsys):
    wid = _wunsch(db, kind["id"], prioritaet="hoch")
    _aktion(db, wid, "frage", None, "2026-09-17 08:00:00")            # der Lauf fragt
    _aktion(db, wid, "antwort", kind["id"], "2026-09-17 09:00:00")     # das Kind antwortet

    out = _lauf_check(capsys)
    assert out.splitlines()[0] == "ARBEIT: 0  (antworten=0 freigegeben=0 wartet_auf_andi=1)"
    kontext = out.split("=== KONTEXT VOM URHEBER")[1]
    assert f"#{wid}" in kontext
    antworten = out.split("=== NEUE ANTWORTEN")[1].split("===")[0]
    assert f"#{wid}" not in antworten


def test_admin_antwort_zaehlt_als_arbeit(db, admin, kind, capsys):
    wid = _wunsch(db, kind["id"], prioritaet="hoch")
    _aktion(db, wid, "frage", None, "2026-09-17 08:00:00")
    _aktion(db, wid, "antwort", kind["id"], "2026-09-17 09:00:00")
    _aktion(db, wid, "antwort", admin["id"], "2026-09-17 10:00:00")

    out = _lauf_check(capsys)
    assert out.splitlines()[0] == "ARBEIT: 1  (antworten=1 freigegeben=0 wartet_auf_andi=0)"
    antworten = out.split("=== NEUE ANTWORTEN")[1].split("=== FREIGEGEBEN")[0]
    assert f"#{wid}" in antworten
    assert "NICHT-ADMIN, nur Kontext" in antworten   # die Kinder-Antwort ist markiert


def test_ohne_prioritaet_bleibt_auch_mit_admin_antwort_keine_arbeit(db, admin, kind, capsys):
    """Die Priorität ist das Tor - eine Antwort öffnet es nicht (Wunsch #152)."""
    wid = _wunsch(db, kind["id"], prioritaet=None)
    _aktion(db, wid, "frage", None, "2026-09-17 08:00:00")
    _aktion(db, wid, "antwort", admin["id"], "2026-09-17 10:00:00")
    out = _lauf_check(capsys)
    # Beantwortet zählt unabhängig von der Priorität - so war es schon vorher:
    # eine Antwort von Andi ist eine Antwort von Andi. Was hier gesichert wird:
    # der Wunsch landet NICHT unter FREIGEGEBEN.
    freigegeben = out.split("=== FREIGEGEBEN")[1].split("=== WARTET")[0]
    assert f"#{wid}" not in freigegeben
