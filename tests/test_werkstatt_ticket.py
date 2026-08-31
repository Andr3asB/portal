"""Wunsch #161: Die Werkstatt als Ticketsystem.

Drei Teile, und der interessante ist der erste:

1. **KI-Titel für titellose Wünsche.** Die Anfrage läuft im Hintergrund,
   *nachdem* der Wunsch gespeichert ist. Das ist der ganze Trick: Fällt
   OpenRouter aus, ist das Kontingent leer oder antwortet das Modell Unsinn,
   bleibt der Wunsch einfach ohne Titel – so wie vorher. Ein KI-Ausfall darf
   das Eintragen nie mitreissen; der Wunsch ist das Wertvolle, der Titel ist
   Beiwerk.
2. **Aktionen am Wunsch** – Plan, Rückfrage, Antwort, Umsetzung, jede mit
   Zeitpunkt und Urheber.
3. **Antworten dürfen auch Nicht-Admins**, sofern der Wunsch von ihnen
   stammt. Genau darum geht es: Wer etwas eingetragen hat, soll auf eine
   Rückfrage antworten können, ohne Admin zu sein.
"""
import importlib

import pytest


class SofortThread:
    """Ersatz fuer threading.Thread, der beim `start()` sofort ausfuehrt.

    Erster Versuch war `type("S", (), {"start": target})()` - dabei wird die
    Funktion zum Klassenattribut und damit zur METHODE, bekommt also `self`
    als erstes Argument und wirft TypeError. Der Test war dann rot, ohne dass
    am Code etwas falsch gewesen waere.
    """

    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture()
def zugaenge(db):
    return {name: daten["tokens"]["hilfe"] for name, daten in db["familie"].items()}


@pytest.fixture()
def werkstatt_token(app, db):
    """Die Werkstatt-App ist nicht Teil der Standard-Testfamilie."""
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


@pytest.fixture()
def wunsch(db):
    """Ein Wunsch vom Kind – damit sich Urheber und Admin unterscheiden."""
    v = db["verbindung"]
    wid = v.execute(
        "INSERT INTO wuensche(text, user_id, app_slug) VALUES(?,?,?) RETURNING id",
        ("Die Liste soll sich merken, wo ich war", db["familie"]["TestKind"]["id"],
         "einkauf")).fetchone()["id"]
    v.commit()
    return wid


# --- KI-Titel: der Wunsch überlebt jeden Ausfall ---------------------------

def test_ohne_api_schluessel_wird_gar_nicht_gefragt(client, db, zugaenge, monkeypatch):
    """Kein Schlüssel, keine KI-Anfrage – und der Wunsch trotzdem gespeichert."""
    modul = importlib.import_module("teile.02_werkstatt")
    gerufen = []
    monkeypatch.setattr(modul, "_titel_nachtragen",
                        lambda *a, **kw: gerufen.append(a))
    client.application.config["OPENROUTER_API_KEY"] = ""
    client.post("/wunsch", json={"text": "Ohne Schluessel", "app": "hilfe",
                                 "token": zugaenge["TestAdmin"]})
    assert gerufen == []
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM wuensche WHERE text='Ohne Schluessel'"
    ).fetchone()["c"] == 1


def test_ki_ausfall_kostet_nur_den_titel(client, db, zugaenge, monkeypatch):
    """Der wichtigste Test der Sache: Die KI wirft, der Wunsch bleibt."""
    modul = importlib.import_module("teile.02_werkstatt")

    def kaputt(*a, **kw):
        raise RuntimeError("OpenRouter nicht erreichbar")
    monkeypatch.setattr(modul, "ki_anfrage", kaputt)
    # Thread synchron ausführen, damit der Test nicht auf Zufall wartet
    monkeypatch.setattr(modul.threading, "Thread", SofortThread)

    client.application.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        antwort = client.post("/wunsch", json={
            "text": "KI faellt aus", "app": "hilfe", "token": zugaenge["TestAdmin"]})
    finally:
        client.application.config["OPENROUTER_API_KEY"] = ""

    assert antwort.status_code == 200
    zeile = db["verbindung"].execute(
        "SELECT titel FROM wuensche WHERE text='KI faellt aus'").fetchone()
    assert zeile is not None, "Der Wunsch muss gespeichert sein"
    assert not zeile["titel"]


def test_titel_wird_gesetzt_und_aufgeraeumt(client, db, zugaenge, monkeypatch):
    """Modelle liefern die Überschrift gern in Anführungszeichen."""
    modul = importlib.import_module("teile.02_werkstatt")
    monkeypatch.setattr(modul, "ki_anfrage",
                        lambda *a, **kw: '  "Einkaufsliste merkt sich die Position"\n')
    monkeypatch.setattr(modul.threading, "Thread", SofortThread)
    client.application.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        client.post("/wunsch", json={"text": "Position merken", "app": "einkauf",
                                     "token": zugaenge["TestAdmin"]})
    finally:
        client.application.config["OPENROUTER_API_KEY"] = ""
    titel = db["verbindung"].execute(
        "SELECT titel FROM wuensche WHERE text='Position merken'").fetchone()["titel"]
    assert titel == "Einkaufsliste merkt sich die Position"


def test_vorhandener_titel_wird_nicht_ueberschrieben(client, db, zugaenge, monkeypatch):
    """Zwischen Absenden und Antwort der KI kann ein Admin von Hand einen
    Titel vergeben haben – der Mensch hat Vorrang vor der Maschine."""
    modul = importlib.import_module("teile.02_werkstatt")
    v = db["verbindung"]

    def langsam(*a, **kw):
        # tut so, als sei in der Zwischenzeit ein Titel gesetzt worden
        v.execute("UPDATE wuensche SET titel='Von Hand' WHERE text='Wettlauf'")
        v.commit()
        return "Von der KI"
    monkeypatch.setattr(modul, "ki_anfrage", langsam)
    monkeypatch.setattr(modul.threading, "Thread", SofortThread)
    client.application.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        client.post("/wunsch", json={"text": "Wettlauf", "app": "hilfe",
                                     "token": zugaenge["TestAdmin"]})
    finally:
        client.application.config["OPENROUTER_API_KEY"] = ""
    assert v.execute(
        "SELECT titel FROM wuensche WHERE text='Wettlauf'").fetchone()["titel"] == "Von Hand"


# --- Aktionen ---------------------------------------------------------------

def _aktion(client, token, wid, art="antwort", text="Ja, genau so."):
    return client.post(f"/a/werkstatt/{token}/aktion/{wid}",
                       data={"art": art, "text": text})


def _aktionen(db, wid):
    return db["verbindung"].execute(
        "SELECT art, text, user_id FROM wunsch_aktionen WHERE wunsch_id=? "
        "ORDER BY id", (wid,)).fetchall()


def test_admin_darf_eine_aktion_anlegen(client, db, werkstatt_token, wunsch):
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, "plan", "Erst messen.")
    zeilen = _aktionen(db, wunsch)
    assert len(zeilen) == 1
    assert zeilen[0]["art"] == "plan" and zeilen[0]["text"] == "Erst messen."


def test_urheber_darf_antworten_ohne_admin_zu_sein(client, db, werkstatt_token, wunsch):
    """Der Kern des Wunsches: auf Rückfragen antworten können."""
    _aktion(client, werkstatt_token["TestKind"], wunsch)
    assert len(_aktionen(db, wunsch)) == 1


def test_fremde_duerfen_nicht_hineinschreiben(client, db, werkstatt_token, wunsch):
    """TestEltern ist weder Admin noch Urheber – lesen ja, schreiben nein."""
    antwort = _aktion(client, werkstatt_token["TestEltern"], wunsch)
    assert antwort.status_code == 403
    assert _aktionen(db, wunsch) == []


def test_ohne_zugang_keine_aktion(client, db, wunsch):
    assert _aktion(client, "unsinn", wunsch).status_code == 403
    assert _aktionen(db, wunsch) == []


def test_leere_aktion_wird_verworfen(client, db, werkstatt_token, wunsch):
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, text="   ")
    assert _aktionen(db, wunsch) == []


def test_unbekannte_art_wird_verworfen(client, db, werkstatt_token, wunsch):
    """Sonst stünde in der Liste eine Art, für die es kein Symbol gibt – und
    das Template bräche mit einem KeyError."""
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, art="quatsch")
    assert _aktionen(db, wunsch) == []


def test_aktion_zu_unbekanntem_wunsch(client, db, werkstatt_token):
    assert _aktion(client, werkstatt_token["TestAdmin"], 99999).status_code == 404


def test_aktionen_erscheinen_in_der_liste(client, db, werkstatt_token, wunsch):
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, "frage", "Welche Liste genau?")
    _aktion(client, werkstatt_token["TestKind"], wunsch, "antwort", "Die Einkaufsliste.")
    seite = client.get(f"/a/werkstatt/{werkstatt_token['TestAdmin']}/").get_data(as_text=True)
    assert "Welche Liste genau?" in seite
    assert "Die Einkaufsliste." in seite


def test_geloeschter_wunsch_raeumt_die_aktionen_mit_ab(db, werkstatt_token, wunsch, client):
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, "notiz", "bleibt nicht")
    v = db["verbindung"]
    v.execute("PRAGMA foreign_keys=ON")
    v.execute("DELETE FROM wuensche WHERE id=?", (wunsch,))
    v.commit()
    assert v.execute("SELECT COUNT(*) c FROM wunsch_aktionen").fetchone()["c"] == 0


# --- Wunsch #166: Rückfragen melden sich ------------------------------------

@pytest.fixture()
def push_protokoll(monkeypatch):
    """Fängt push_send ab – die Tests prüfen, WER benachrichtigt wird."""
    modul = importlib.import_module("teile.05_werkstatt_app")
    gesendet = []
    monkeypatch.setattr(modul, "push_send",
                        lambda uid, titel, text, app="", url="", **kw:
                            gesendet.append({"uid": uid, "titel": titel,
                                             "text": text, "url": url}))
    return gesendet


def test_rueckfrage_meldet_sich_beim_admin(client, db, werkstatt_token, wunsch,
                                           push_protokoll):
    """Der Kern von #166 – eine Rückfrage soll nicht unbemerkt liegen bleiben."""
    _aktion(client, werkstatt_token["TestKind"], wunsch, "frage", "Welche Liste?")
    assert [p["uid"] for p in push_protokoll] == [db["familie"]["TestAdmin"]["id"]]


def test_antwort_meldet_sich_nicht(client, db, werkstatt_token, wunsch, push_protokoll):
    """Nur Rückfragen. Würde jede Notiz melden, wäre die Meldung wertlos –
    und dann schaut irgendwann niemand mehr hin."""
    _aktion(client, werkstatt_token["TestKind"], wunsch, "antwort", "Die Einkaufsliste.")
    _aktion(client, werkstatt_token["TestKind"], wunsch, "notiz", "Nur so.")
    assert push_protokoll == []


def test_eigene_rueckfrage_kommt_nicht_zurueck(client, db, werkstatt_token, wunsch,
                                               push_protokoll):
    """Sonst meldet sich Andis Handy bei jeder Rückfrage, die er selbst stellt."""
    _aktion(client, werkstatt_token["TestAdmin"], wunsch, "frage", "Wie meinst du das?")
    assert push_protokoll == []


def test_meldung_verlinkt_auf_den_wunsch(client, db, werkstatt_token, wunsch,
                                         push_protokoll):
    """Ohne Sprungziel müsste man die Rückfrage in 160 Wünschen suchen."""
    _aktion(client, werkstatt_token["TestKind"], wunsch, "frage", "Welche Liste?")
    assert push_protokoll[0]["url"].endswith(f"#wunsch-{wunsch}")
    assert f"#{wunsch}" in push_protokoll[0]["titel"]


def test_verworfene_aktion_meldet_sich_nicht(client, db, werkstatt_token, wunsch,
                                             push_protokoll):
    """Ein leerer Text legt keine Aktion an – dann darf es auch keine
    Benachrichtigung geben."""
    _aktion(client, werkstatt_token["TestKind"], wunsch, "frage", "   ")
    assert _aktionen(db, wunsch) == []
    assert push_protokoll == []
