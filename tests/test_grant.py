"""Tests der Zugangsauflösung – der Kern, an dem der Umbau für Wunsch #140
ansetzt.

Diese Tests beschreiben den IST-Zustand vor dem Umbau. Sie müssen vor der
ersten Änderung grün sein und nach jeder Stufe wieder grün sein. Wenn eine
Stufe sie rot macht, ist entweder die Stufe falsch oder der Test muss bewusst
angepasst werden – beides soll auffallen.
"""
import pytest


# --- grant(): Token + App-Slug -> Nutzer ------------------------------------

def test_gueltiger_token_loest_auf(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert user is not None
    assert user["name"] == "TestAdmin"
    assert user["id"] == admin["id"]


def test_unbekannter_token_wird_abgelehnt(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        assert grant("gibtesnicht", "einkauf") is None


def test_leerer_token_wird_abgelehnt(app):
    from teile.kern import grant
    with app.test_request_context():
        assert grant("", "einkauf") is None


def test_token_gilt_nur_fuer_seine_app(app, admin):
    """Der Einkaufs-Token darf die Aufgaben-App nicht öffnen."""
    from teile.kern import grant
    with app.test_request_context():
        assert grant(admin["tokens"]["einkauf"], "todo") is None


def test_fremder_token_oeffnet_nicht_die_eigene_app(app, admin, kind):
    """Das Kind hat keinen Aufgaben-Zugang – sein Token darf ihn nicht öffnen."""
    from teile.kern import grant
    with app.test_request_context():
        assert grant(kind["tokens"]["einkauf"], "todo") is None


def test_app_ohne_grant_bleibt_zu(app, kind):
    from teile.kern import grant
    with app.test_request_context():
        assert grant(kind["tokens"]["einkauf"], "admin") is None


# --- Rollen und Rechte ------------------------------------------------------

def test_admin_flag_kommt_durch(app, admin):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert user["is_admin"] == 1


def test_kind_ist_kein_admin(app, kind):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(kind["tokens"]["einkauf"], "einkauf")
    assert user["is_admin"] == 0
    assert user["rolle"] == "kind"


def test_rolle_eltern_kommt_durch(app, eltern):
    from teile.kern import grant
    with app.test_request_context():
        user = grant(eltern["tokens"]["einkauf"], "einkauf")
    assert user["rolle"] == "eltern"
    assert user["is_admin"] == 0


# --- Navigations-Tokens (der Grund, warum #129 nicht hashen konnte) ---------

def test_keine_navigations_tokens_mehr(app, admin):
    """Wunsch #140, Stufe 6: Kehrtwende gegenüber Stufe 1–3.

    Bis Stufe 3 lieferte `grant()` bewusst `home_token` und `hilfe_token` mit -
    base.html baute daraus auf jeder Seite den ⌂-Knopf und den Hilfe-Link.
    Seit Stufe 4 sind alle Adressen token-frei, seit Stufe 6 gibt es den
    Klartext gar nicht mehr. Stünde hier wieder ein Token drin, wäre der ganze
    Umbau umsonst: Er landete über das Menü erneut in jeder Seite."""
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    assert "home_token" not in user
    assert "hilfe_token" not in user


def test_grant_liefert_keinen_einzigen_token_zurueck(app, admin):
    """Schärfer als der Test oben: KEIN Wert im Rückgabe-dict darf einem der
    Tokens dieses Nutzers entsprechen - egal unter welchem Namen."""
    from teile.kern import grant
    with app.test_request_context():
        user = grant(admin["tokens"]["einkauf"], "einkauf")
    werte = {str(v) for v in user.values()}
    for name, token in admin["tokens"].items():
        assert token not in werte, f"Token '{name}' steckt in der grant()-Antwort"


# --- Hashing (Wunsch #129, vollendet in #140 Stufe 6) -----------------------

def test_grants_tabelle_hat_keine_rueckholbare_spalte(app, db):
    """Der Kern von Stufe 6: `token_enc` ist weg.

    Solange die Spalte existierte, liess sich jeder Zugangslink mit dem
    TOKEN_KEY zurückrechnen - ein geleaktes Backup plus .env gab Vollzugriff.
    Jetzt steht nur noch der HMAC da, der sich nicht umkehren lässt."""
    spalten = [r[1] for r in db["verbindung"].execute("PRAGMA table_info(grants)")]
    assert "token_enc" not in spalten
    assert "token" not in spalten
    assert "token_lookup" in spalten


def test_klartext_token_steht_nicht_in_der_datenbank(app, db, admin):
    """Über ALLE Spalten der Grant-Zeile, nicht nur über zwei bekannte -
    sonst entginge dem Test eine künftig hinzugefügte Spalte."""
    klartext = admin["tokens"]["einkauf"]
    for zeile in db["verbindung"].execute("SELECT * FROM grants"):
        for wert in tuple(zeile):
            assert wert != klartext


def test_lookup_ist_deterministisch(app):
    """Suchen muss reproduzierbar sein - sonst fände `grant()` die Zeile nie."""
    from teile.kern import token_lookup
    with app.test_request_context():
        assert token_lookup("abc") == token_lookup("abc")
        assert token_lookup("abc") != token_lookup("abd")


def test_lookup_ist_nicht_umkehrbar(app):
    """Der HMAC darf den Token nicht enthalten - eine Prüfsumme, aus der man
    das Original herauslesen kann, ist keine."""
    from teile.kern import token_lookup
    with app.test_request_context():
        hash_wert = token_lookup("mein-geheimer-token")
    assert "mein-geheimer-token" not in hash_wert
    assert len(hash_wert) == 64          # SHA-256 als Hex


def test_verschluesselung_bleibt_fuer_die_alt_migration_nutzbar(app):
    """`token_verschluesseln`/`token_entschluesseln` werden im Betrieb nicht
    mehr aufgerufen, müssen aber funktionsfähig bleiben: Die #129-Migration
    liest damit eine Datenbank aus jener Zeit. Wer sie entfernt, macht ein
    altes Backup unlesbar."""
    from teile.kern import token_verschluesseln, token_entschluesseln
    with app.test_request_context():
        assert token_entschluesseln(token_verschluesseln("hallo-welt")) == "hallo-welt"
        assert token_entschluesseln("kein-gueltiger-geheimtext") == ""
        assert token_entschluesseln("") == ""


# --- Zugriff über HTTP ------------------------------------------------------

def test_startseite_mit_gueltigem_token(client, admin):
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert antwort.status_code == 200
    assert b"TestAdmin" in antwort.data


def test_startseite_mit_ungueltigem_token(client):
    antwort = client.get("/p/gibtesnicht")
    assert antwort.status_code == 403


def test_app_mit_fremdem_token_verweigert(client, kind):
    """Der Kind-Token darf die Verwaltung nicht öffnen."""
    antwort = client.get(f"/a/admin/{kind['tokens']['einkauf']}/")
    assert antwort.status_code == 403


def test_health_braucht_keinen_token(client):
    antwort = client.get("/health")
    assert antwort.status_code == 200
