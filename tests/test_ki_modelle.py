"""Wunsch #259: Welche KI-Modelle wofuer genutzt werden - und wo sie rechnen.

Sichtbar in der Hilfe (Kapitel "KI-Modelle") und auf der KI-Verbrauchsseite
der Verwaltung, beide aus derselben Quelle: `ki_modell_uebersicht()` liest
ki_konfiguration/ki_stimmen LIVE. Eine abgetippte Liste in der Hilfe waere
beim ersten `manage.py ki_modell` veraltet gewesen.

**Der Waechter, auf den es ankommt:** jeder Zweck, den ki_anfrage() im
Quelltext benutzt, braucht eine Zeile in KI_ZWECKE (Name + Beschreibung) und
einen Seed in ki_konfiguration. Genau so ist einkauf_barcode (#143)
aufgefallen: nie geseedet, fiel stumm auf KI_MODELL zurueck, stand nirgends.
"""
import pathlib
import re

import pytest

TEILE = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile"


@pytest.fixture()
def kern():
    from teile import kern
    return kern


def _zwecke_im_code():
    """Alle feature-Strings aus ki_anfrage(<user>, "<feature>", ...)-Aufrufen."""
    muster = re.compile(r"ki_anfrage\(\s*[\w\[\]\"'.]+\s*,\s*\"([a-z_]+)\"", re.DOTALL)
    gefunden = set()
    for datei in TEILE.glob("[0-9][0-9]_*.py"):
        gefunden.update(muster.findall(datei.read_text(encoding="utf-8")))
    return gefunden


def test_der_waechter_findet_die_aufrufe():
    """Ein Waechter, der nichts findet, waechtert nichts."""
    zwecke = _zwecke_im_code()
    assert {"rezepte_import", "vokabeln_ocr", "vokabeln_aussprache",
            "wunsch_titel", "einkauf_barcode"} <= zwecke, zwecke


def test_jeder_zweck_im_code_hat_namen_und_seed(kern, db):
    benannt = {z for z, _, _ in kern.KI_ZWECKE}
    geseedet = {r[0] for r in db["verbindung"].execute("SELECT zweck FROM ki_konfiguration")}
    fehlt_name = _zwecke_im_code() - benannt
    fehlt_seed = _zwecke_im_code() - geseedet
    assert not fehlt_name, f"ohne Namen in KI_ZWECKE: {sorted(fehlt_name)}"
    assert not fehlt_seed, f"ohne Seed in ki_konfiguration (_init_db): {sorted(fehlt_seed)}"


def test_jede_zeile_hat_beschreibung_und_label(kern):
    for zweck, label, beschreibung in kern.KI_ZWECKE:
        assert label and label != zweck, zweck
        assert len(beschreibung) > 20, zweck


# --- Beschreibung eines Modells ----------------------------------------------

def test_eu_anbieter_ist_festgelegt(kern):
    b = kern.ki_modell_beschreibung("mistralai/voxtral-small-24b-2507", "mistral/eu")
    assert b["entwickler"] == "Mistral AI"
    assert b["land"] == "Frankreich"
    assert b["festgelegt"] is True
    assert "EU" in b["hosting"]


def test_ohne_anbieter_wird_nichts_versprochen(kern):
    b = kern.ki_modell_beschreibung("anthropic/claude-haiku-4.5")
    assert (b["entwickler"], b["land"]) == ("Anthropic", "USA")
    assert b["festgelegt"] is False
    assert "nicht festgelegt" in b["hosting"]
    # Leerstring zaehlt wie None - so steht es nach manage.py ki_modell ... -
    assert kern.ki_modell_beschreibung("anthropic/x", "  ")["festgelegt"] is False


def test_unbekannter_hersteller_wird_nicht_geraten(kern):
    b = kern.ki_modell_beschreibung("irgendwer/modell", "irgendein-anbieter")
    assert b["entwickler"] == "irgendwer"
    assert b["land"] == "unbekannt"
    assert b["hosting"] == "irgendein-anbieter"
    assert kern.ki_modell_beschreibung("ohne-schraegstrich")["entwickler"] == "unbekannt"


# --- Die Uebersicht ----------------------------------------------------------

def test_uebersicht_zeigt_jeden_zweck_mit_seinem_modell(app, kern, db):
    with app.app_context():
        u = kern.ki_modell_uebersicht()
    je_zweck = {z["zweck"]: z for z in u["zwecke"]}
    assert set(je_zweck) >= {z for z, _, _ in kern.KI_ZWECKE}
    a = je_zweck["vokabeln_aussprache"]
    assert a["modell"] == kern.AUSSPRACHE_STANDARD_MODELL
    assert a["festgelegt"] and a["anbieter"] == "mistral/eu"
    assert a["label"] == "Aussprache bewerten"
    assert not je_zweck["rezepte_import"]["festgelegt"]
    assert not any(z["standard"] for z in u["zwecke"]), (
        "jeder benannte Zweck ist geseedet - 'Standard' duerfte nicht vorkommen")


def test_uebersicht_zeigt_vorlesen_je_aktiver_sprache(app, kern, db):
    v = db["verbindung"]
    aktive = {r[0] for r in v.execute("SELECT name FROM vokabel_sprachen WHERE aktiv=1")}
    with app.app_context():
        u = kern.ki_modell_uebersicht()
    sprachen = {s["sprache"] for s in u["stimmen"]}
    assert sprachen == aktive
    assert all(s["stimme"] and s["modell"] for s in u["stimmen"])


def test_unbenannter_zweck_aus_der_db_erscheint_trotzdem(app, kern, db):
    """Was in der DB steht, wird gezeigt - notfalls unter seinem Schluessel.
    ki_konfiguration ist eine Seed-Tabelle, deshalb hinterher aufraeumen."""
    v = db["verbindung"]
    v.execute("INSERT INTO ki_konfiguration(zweck, modell) VALUES('test_fremd', 'openai/x')")
    v.commit()
    try:
        with app.app_context():
            u = kern.ki_modell_uebersicht()
        fremd = [z for z in u["zwecke"] if z["zweck"] == "test_fremd"]
        assert fremd and fremd[0]["label"] == "test_fremd"
        assert fremd[0]["entwickler"] == "OpenAI"
    finally:
        v.execute("DELETE FROM ki_konfiguration WHERE zweck='test_fremd'")
        v.commit()


# --- Sichtbar in Hilfe und Verwaltung ----------------------------------------

def test_hilfe_hat_das_kapitel_mit_livestand(client, admin, kern):
    seite = client.get(f"/a/hilfe/{admin['tokens']['hilfe']}/").get_data(as_text=True)
    assert 'id="kapitel-26"' in seite
    assert "KI-Modelle" in seite
    assert kern.AUSSPRACHE_STANDARD_MODELL in seite
    assert "Rechenzentrum in der EU" in seite
    assert "Aussprache bewerten" in seite
    assert "Vorlesen – Englisch" in seite
    assert "nicht festgelegt" in seite


def test_verwaltung_zeigt_dieselbe_liste(client, admin, kern):
    seite = client.get(f"/a/admin/{admin['tokens']['admin']}/ki").get_data(as_text=True)
    assert "Welche Modelle, und wo sie rechnen" in seite
    assert kern.AUSSPRACHE_STANDARD_MODELL in seite
    assert "Rechenzentrum in der EU" in seite
    assert "Kategorie nach Barcode" in seite


def test_aenderung_per_manage_steht_sofort_in_der_hilfe(app, client, admin, db, monkeypatch):
    """Der Grund fuer 'live statt abgetippt'."""
    import importlib
    import sys
    monkeypatch.setenv("DB_PATH", app.config["DB_PATH"])
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
    manage = importlib.import_module("manage")
    importlib.reload(manage)
    from teile import kern

    manage.cmd_ki_modell(["wunsch_titel", "mistralai/mistral-small-test", "mistral/eu"])
    try:
        seite = client.get(f"/a/hilfe/{admin['tokens']['hilfe']}/").get_data(as_text=True)
        assert "mistralai/mistral-small-test" in seite
    finally:
        manage.cmd_ki_modell(["wunsch_titel", kern.KI_MODELL, "-"])
    seite = client.get(f"/a/hilfe/{admin['tokens']['hilfe']}/").get_data(as_text=True)
    assert "mistralai/mistral-small-test" not in seite
