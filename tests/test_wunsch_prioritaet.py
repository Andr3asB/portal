"""Wunsch #152: Admins priorisieren einen Wunsch schon bei der Eingabe.

Der Schwerpunkt liegt auf der Abgrenzung, nicht auf der Bequemlichkeit. Die
Priorität steuert, was ein Sammelauftrag („implementiere alle Wünsche")
anfasst und was nicht – `zurueckgestellt` ist die einzige, die nie
automatisch umgesetzt wird. Wer sie setzen darf, ist damit eine
Berechtigungsfrage: Könnte jeder beim Einreichen eine Priorität mitschicken,
liesse sich ein beliebiger Wunsch an die Spitze schieben oder – umgekehrt –
ein fremder Wunsch stillgelegt werden.

Die Auswahl steht im Template hinter `user.is_admin`. Genau darauf darf man
sich nicht verlassen: `/wunsch` nimmt JSON entgegen, ein selbstgebauter POST
umgeht jedes Template. Deshalb prüfen die Tests den Endpunkt, nicht die Seite.
"""
import pytest


@pytest.fixture()
def zugaenge(db):
    """Die Tokens, die conftest ohnehin anlegt.

    Erster Versuch war ein eigenes `INSERT OR IGNORE INTO grants` – das lief
    wegen `UNIQUE(user_id, app_id)` wortlos ins Leere, die Tokens waren
    ungültig, und fünf der Tests bestanden aus dem falschen Grund (kein
    Nutzer -> keine Priorität -> Erwartung erfüllt). Deshalb hier die
    vorhandenen: `hilfe` hat jedes Familienmitglied.
    """
    return {name: daten["tokens"]["hilfe"] for name, daten in db["familie"].items()}


def _einreichen(client, text, token=None, prioritaet=None):
    nutzlast = {"text": text, "app": "hilfe", "pfad": "/a/hilfe/"}
    if token is not None:
        nutzlast["token"] = token
    if prioritaet is not None:
        nutzlast["prioritaet"] = prioritaet
    return client.post("/wunsch", json=nutzlast)


def _prio_von(db, text):
    return db["verbindung"].execute(
        "SELECT prioritaet FROM wuensche WHERE text=?", (text,)).fetchone()["prioritaet"]


# --- Der Admin darf ---------------------------------------------------------

def test_admin_setzt_prioritaet_beim_anlegen(client, db, zugaenge):
    assert _einreichen(client, "A1", zugaenge["TestAdmin"], "hoch").status_code == 200
    assert _prio_von(db, "A1") == "hoch"


def test_admin_kann_zurueckgestellt_waehlen(client, db, zugaenge):
    """Die Voreinstellung der Oberfläche – sie muss auch ankommen."""
    _einreichen(client, "A2", zugaenge["TestAdmin"], "zurueckgestellt")
    assert _prio_von(db, "A2") == "zurueckgestellt"


# --- Alle anderen nicht -----------------------------------------------------

def test_kind_kann_keine_prioritaet_setzen(client, db, zugaenge):
    _einreichen(client, "K1", zugaenge["TestKind"], "sehr_hoch")
    assert _prio_von(db, "K1") is None


def test_eltern_ohne_adminrecht_koennen_keine_prioritaet_setzen(client, db, zugaenge):
    _einreichen(client, "E1", zugaenge["TestEltern"], "sehr_hoch")
    assert _prio_von(db, "E1") is None


def test_anonymer_wunsch_bekommt_keine_prioritaet(client, db):
    """Ohne Token gibt es keinen Nutzer und damit auch kein Adminrecht."""
    _einreichen(client, "X1", None, "sehr_hoch")
    assert _prio_von(db, "X1") is None


# --- Der Wunsch geht trotzdem nie verloren ---------------------------------

def test_wunsch_ohne_erlaubnis_wird_trotzdem_gespeichert(client, db, zugaenge):
    """Der unerlaubte Wert wird verworfen, NICHT der Vorschlag. Ein still
    weggeworfener Wunsch wäre der schlechtere Ausgang."""
    _einreichen(client, "K2", zugaenge["TestKind"], "hoch")
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM wuensche WHERE text='K2'").fetchone()["c"] == 1


def test_unbekannte_prioritaet_wird_verworfen(client, db, zugaenge):
    """Auch beim Admin: was nicht in der Liste steht, wird zu NULL statt
    ungeprüft in die Datenbank zu wandern."""
    _einreichen(client, "A3", zugaenge["TestAdmin"], "sofort!!")
    assert _prio_von(db, "A3") is None
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM wuensche WHERE text='A3'").fetchone()["c"] == 1


def test_ohne_angabe_bleibt_es_wie_bisher(client, db, zugaenge):
    """Bestandsverhalten: wer nichts mitschickt, bekommt NULL – auch als
    Admin. Sonst würde jeder Wunsch aus einer älteren PWA-Version plötzlich
    eine Priorität erben."""
    _einreichen(client, "A4", zugaenge["TestAdmin"])
    assert _prio_von(db, "A4") is None


# --- Die Liste steht an einer Stelle ---------------------------------------

def test_beide_module_nutzen_dieselbe_liste(app):
    """Zwei getrennte Listen würden auseinanderlaufen, und die Folge wäre
    still: ein Wert, den nur eine Seite kennt, wird von der anderen
    wortlos verworfen."""
    import importlib
    from teile.kern import WUNSCH_PRIORITAETEN
    werkstatt = importlib.import_module("teile.05_werkstatt_app")
    assert werkstatt._PRIORITAETEN is WUNSCH_PRIORITAETEN


def test_zurueckgestellt_ist_die_voreinstellung(app):
    from teile.kern import WUNSCH_PRIO_VOREINSTELLUNG, WUNSCH_PRIORITAETEN
    assert WUNSCH_PRIO_VOREINSTELLUNG == "zurueckgestellt"
    assert WUNSCH_PRIO_VOREINSTELLUNG in WUNSCH_PRIORITAETEN
