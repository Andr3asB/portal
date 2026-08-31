"""Wunsch #183: KI-Verbrauch je Nutzer, OpenRouter-Guthaben, Warnung bei Ebbe.

Drei Dinge, die getrennt schiefgehen können und deshalb getrennt geprüft werden:

1. **Die Übersicht** – nur für Admins, und sie muss auch dann tragen, wenn
   OpenRouter nicht antwortet (dann steht wenigstens der lokale Verbrauch da).
2. **Die Guthaben-Auswertung** – der kleinere aus Konto-Guthaben und
   Schlüssel-Limit entscheidet. Wer nur aufs Konto schaut, übersieht ein
   aufgebrauchtes Monatslimit und wundert sich über 402er.
3. **Der Wächter** – legt bei ≤ 1,00 USD genau EINE Aufgabe an, nicht eine je
   Durchlauf, und schickt eine Push-Nachricht dazu.

OpenRouter wird durchgehend über `_openrouter` ersetzt statt über
`urllib.request` – der Test soll die Auswertung prüfen, nicht das HTTP.
"""
import importlib

import pytest

budget = importlib.import_module("teile.24_ki_budget")


# --- Guthaben auswerten ----------------------------------------------------

def _antworten(monkeypatch, credits=None, key=None):
    def falsch(pfad, api_key):
        return {"/api/v1/credits": credits, "/api/v1/key": key}[pfad]
    monkeypatch.setattr(budget, "_openrouter", falsch)


def test_ohne_schluessel_kein_guthaben():
    assert budget.guthaben_lesen("") is None


def test_konto_guthaben_ist_gekauft_minus_verbraucht(monkeypatch):
    _antworten(monkeypatch, credits={"total_credits": 10, "total_usage": 0.5})
    assert budget.guthaben_lesen("k")["rest"] == 9.5


def test_das_kleinere_von_beiden_zaehlt(monkeypatch):
    """Konto voll, Monatslimit fast leer: es geht trotzdem nichts mehr durch."""
    _antworten(monkeypatch,
               credits={"total_credits": 50, "total_usage": 0},
               key={"limit": 10, "limit_remaining": 0.4})
    stand = budget.guthaben_lesen("k")
    assert stand["rest"] == 0.4
    assert stand["quelle"] == "limit"


def test_umgekehrt_genauso(monkeypatch):
    _antworten(monkeypatch,
               credits={"total_credits": 10, "total_usage": 9.8},
               key={"limit": 100, "limit_remaining": 90})
    stand = budget.guthaben_lesen("k")
    assert round(stand["rest"], 2) == 0.2
    assert stand["quelle"] == "konto"


def test_schluessel_ohne_limit_faellt_nicht_auf_null(monkeypatch):
    """`limit: null` heisst *kein* Limit - nicht 'null Dollar übrig'."""
    _antworten(monkeypatch,
               credits={"total_credits": 10, "total_usage": 1},
               key={"limit": None, "limit_remaining": None, "usage_daily": 0.1})
    stand = budget.guthaben_lesen("k")
    assert stand["rest"] == 9
    assert "limit_rest" not in stand


def test_openrouter_stumm_gibt_none(monkeypatch):
    _antworten(monkeypatch, credits=None, key=None)
    assert budget.guthaben_lesen("k") is None


# --- Der Wächter -----------------------------------------------------------

@pytest.fixture()
def kein_push(monkeypatch):
    """Sammelt die Push-Aufrufe, statt sie zu verschicken."""
    gesendet = []
    monkeypatch.setattr(budget, "push_send",
                        lambda *a, **k: gesendet.append(a))
    return gesendet


def _guthaben(monkeypatch, rest):
    monkeypatch.setattr(budget, "guthaben_lesen",
                        lambda key: {"rest": rest, "quelle": "konto"})


def test_ueber_der_schwelle_passiert_nichts(app, db, monkeypatch, kein_push):
    _guthaben(monkeypatch, 5.0)
    assert budget.guthaben_pruefen(app) is False
    assert not kein_push
    assert db["verbindung"].execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0


def test_bei_ebbe_entsteht_eine_aufgabe_mit_push(app, db, monkeypatch, kein_push):
    _guthaben(monkeypatch, 0.42)
    assert budget.guthaben_pruefen(app) is True

    zeile = db["verbindung"].execute(
        "SELECT inhalt, zugewiesen_an, status FROM todos").fetchone()
    assert budget.AUFGABEN_MARKE in zeile["inhalt"]
    assert "0,42" in zeile["inhalt"], "Betrag mit deutschem Komma"
    assert zeile["status"] == "offen"
    assert zeile["zugewiesen_an"] == db["familie"]["TestAdmin"]["id"]
    assert len(kein_push) == 1
    assert kein_push[0][3] == "todo"


def test_genau_auf_der_schwelle_zaehlt_noch(app, db, monkeypatch, kein_push):
    """Der Wunsch sagt 'auf ein Euro ODER NIEDRIGER' - 1,00 loest also aus."""
    _guthaben(monkeypatch, budget.SCHWELLE_USD)
    assert budget.guthaben_pruefen(app) is True


def test_zweiter_durchlauf_legt_keine_zweite_aufgabe_an(app, db, monkeypatch, kein_push):
    _guthaben(monkeypatch, 0.2)
    assert budget.guthaben_pruefen(app) is True
    assert budget.guthaben_pruefen(app) is False
    assert budget.guthaben_pruefen(app) is False
    assert db["verbindung"].execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 1
    assert len(kein_push) == 1


def test_nach_dem_abhaken_darf_wieder_gewarnt_werden(app, db, monkeypatch, kein_push):
    """Sonst wäre die erste Aufladung die letzte Warnung für immer."""
    _guthaben(monkeypatch, 0.2)
    assert budget.guthaben_pruefen(app) is True
    v = db["verbindung"]
    v.execute("UPDATE todos SET status='erledigt', erledigt=1")
    v.commit()
    assert budget.guthaben_pruefen(app) is True
    assert v.execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 2


def test_ohne_antwort_von_openrouter_kein_alarm(app, db, monkeypatch, kein_push):
    """Ein Netzwerkfehler ist kein leeres Konto - sonst stünde nach dem ersten
    Aussetzer eine Aufgabe da, die nichts bedeutet."""
    monkeypatch.setattr(budget, "guthaben_lesen", lambda key: None)
    assert budget.guthaben_pruefen(app) is False
    assert db["verbindung"].execute("SELECT COUNT(*) FROM todos").fetchone()[0] == 0


# --- Die Seite -------------------------------------------------------------

def test_seite_zeigt_verbrauch_je_nutzer(client, db, monkeypatch):
    monkeypatch.setattr(budget, "guthaben_lesen", lambda key: None)
    v = db["verbindung"]
    andi = db["familie"]["TestAdmin"]["id"]
    kind = db["familie"]["TestKind"]["id"]
    v.execute("INSERT INTO ki_nutzung(user_id, feature, tokens) VALUES(?,?,?)",
              (andi, "rezept_import", 1234))
    v.execute("INSERT INTO ki_nutzung(user_id, feature, tokens) VALUES(?,?,?)",
              (kind, "vokabeln", 500))
    v.execute("INSERT INTO ki_tts_nutzung(user_id, feature, zeichen) VALUES(?,?,?)",
              (kind, "vorlesen", 900))
    v.commit()

    seite = client.get(f"/a/admin/{db['familie']['TestAdmin']['tokens']['admin']}/ki")
    assert seite.status_code == 200
    text = seite.get_data(as_text=True)
    # "1.234 von 100.000", nicht nur "1.234": die Zahl allein steht auch in der
    # Aufstellung je Funktion weiter unten. Ohne das " von" blieb der Test
    # gruen, als die Nutzerzeile ihre Zahl gar nicht mehr ausgab.
    assert "1.234 von" in text and "100.000 Tokens" in text
    assert "TestAdmin" in text
    assert "900 Zeichen vorgelesen" in text
    assert "rezept_import" in text


def test_seite_traegt_auch_ohne_openrouter(client, db, monkeypatch):
    """Der lokale Verbrauch ist unabhängig davon, ob OpenRouter antwortet."""
    monkeypatch.setattr(budget, "guthaben_lesen", lambda key: None)
    seite = client.get(f"/a/admin/{db['familie']['TestAdmin']['tokens']['admin']}/ki")
    assert seite.status_code == 200
    assert "nicht erreichbar" in seite.get_data(as_text=True)


def test_guthaben_wird_angezeigt(client, db, monkeypatch):
    monkeypatch.setattr(budget, "guthaben_lesen", lambda key: {
        "rest": 9.87, "quelle": "konto", "konto_rest": 9.87,
        "konto_gekauft": 10, "konto_verbraucht": 0.13,
        "limit_rest": 9.87, "limit": 10, "limit_reset": "jeden Monat",
        "usage_taeglich": 0.01, "usage_monatlich": 0.13,
    })
    text = client.get(
        f"/a/admin/{db['familie']['TestAdmin']['tokens']['admin']}/ki"
    ).get_data(as_text=True)
    assert "9,87" in text
    assert "setzt sich jeden Monat zurück" in text


def test_knapper_stand_wird_hervorgehoben(client, db, monkeypatch):
    monkeypatch.setattr(budget, "guthaben_lesen",
                        lambda key: {"rest": 0.5, "quelle": "konto", "konto_rest": 0.5})
    text = client.get(
        f"/a/admin/{db['familie']['TestAdmin']['tokens']['admin']}/ki"
    ).get_data(as_text=True)
    assert "kib-zahl knapp" in text
    assert "Aufgabe zum Aufladen" in text


def test_nur_admins(client, db, monkeypatch):
    """Zwei verschiedene Verweigerungsgründe, beide gemeint:

    Der fremde Token scheitert schon am fehlenden Grant. Der zweite Fall ist
    der eigentliche - ein Nutzer MIT Zugang zur Verwaltung, aber ohne
    `is_admin`. Ohne ihn blieb der Test grün, als der is_admin-Check entfernt
    war: der Grant fehlte ja ohnehin.
    """
    from teile.kern import new_token, token_lookup
    monkeypatch.setattr(budget, "guthaben_lesen", lambda key: None)
    kind = db["familie"]["TestKind"]
    v = db["verbindung"]

    assert client.get("/a/admin/ki").status_code == 403
    assert client.get(f"/a/admin/{kind['tokens']['home']}/ki").status_code == 403

    with client.application.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='admin'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (kind["id"], app_id, token_lookup(klartext)))
        v.commit()
    assert client.get(f"/a/admin/{klartext}/ki").status_code == 403


def test_die_verwaltung_verlinkt_die_seite(client, db):
    """Eine Seite, die niemand erreicht, ist keine Übersicht."""
    text = client.get(
        f"/a/admin/{db['familie']['TestAdmin']['tokens']['admin']}/"
    ).get_data(as_text=True)
    assert 'href="/a/admin/' in text and "ki\">🤖 KI-Verbrauch" in text


def test_rhythmus_wird_uebersetzt(monkeypatch):
    """OpenRouter sagt "monthly" - auf einer deutschen Seite steht das nicht."""
    _antworten(monkeypatch,
               credits={"total_credits": 10, "total_usage": 0},
               key={"limit": 10, "limit_remaining": 9, "limit_reset": "monthly"})
    assert budget.guthaben_lesen("k")["limit_reset"] == "jeden Monat"


def test_unbekannter_rhythmus_geht_unveraendert_durch(monkeypatch):
    """Lieber ein englisches Wort als eine leere Klammer."""
    _antworten(monkeypatch,
               credits={"total_credits": 10, "total_usage": 0},
               key={"limit": 10, "limit_remaining": 9, "limit_reset": "hourly"})
    assert budget.guthaben_lesen("k")["limit_reset"] == "hourly"
