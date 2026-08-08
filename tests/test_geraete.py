"""Wunsch #154: Geräteübersicht in der Verwaltung.

Anlass war ein Fund: 817 Sitzungen für vier Menschen, davon 808 aus
Prüfabläufen – unbemerkt, weil die Tabelle für niemanden einsehbar war. Jede
Zeile ist ein gültiger, nie ablaufender Zugang.

Zwei Dinge muss die Seite können:

1. **Ein einzelnes Gerät abmelden, ohne die anderen auszusperren.** Bis dahin
   ging nur „Neuer Zugang + QR": alle Token neu, alle Geräte draussen. Wer
   sein Handy verlor, verlor damit auch Tablet und Kiosk.
2. **„zuletzt benutzt" muss stimmen.** `gesehen` wurde bisher nur beim Anlegen
   gesetzt und nie fortgeschrieben – eine Spalte mit dem Erstellzeitpunkt
   sähe richtig aus und wäre falsch. Das ist der unangenehmere der beiden
   Fehler, weil er nicht auffällt.
"""
import pytest


@pytest.fixture()
def sitzungen(app, db):
    """Zwei Geräte für den Admin, eines fürs Kind."""
    from teile.kern import token_lookup
    v = db["verbindung"]
    familie = db["familie"]

    def anlegen(user_id, kennwert, geraet, erstellt, gesehen=None):
        # token_lookup() braucht den App-Kontext (der Schlüssel steht in der
        # Config) - ohne den bricht schon die Fixture ab.
        with app.app_context():
            kennung = token_lookup(kennwert)
        return v.execute("""
            INSERT INTO sitzungen(user_id, kennung_lookup, quelle, geraet,
                                  erstellt, gesehen)
            VALUES(?,?,?,?,?,?) RETURNING id
        """, (user_id, kennung, "token", geraet,
              erstellt, gesehen)).fetchone()["id"]

    ids = {
        "admin_handy": anlegen(familie["TestAdmin"]["id"], "kw-handy",
                               "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7) Safari/604.1",
                               "2026-08-01 09:00:00", "2026-08-01 09:00:00"),
        "admin_pc":    anlegen(familie["TestAdmin"]["id"], "kw-pc",
                               "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/141.0",
                               "2026-08-02 09:00:00", "2026-08-06 20:00:00"),
        "kind":        anlegen(familie["TestKind"]["id"], "kw-kind",
                               "Mozilla/5.0 (Android 15) Chrome/141.0",
                               "2026-08-03 09:00:00", None),
    }
    v.commit()
    return ids


@pytest.fixture()
def cookie_gilt(app):
    """Sitzungs-Cookies autorisieren zu lassen ist ein Schalter (Wunsch #140,
    Stufe 3). In den Tests steht er nicht automatisch an - ohne ihn pruefen die
    Cookie-Tests unten stillschweigend gar nichts."""
    vorher = app.config.get("SITZUNG_KONSUMIEREN")
    app.config["SITZUNG_KONSUMIEREN"] = "1"
    yield
    app.config["SITZUNG_KONSUMIEREN"] = vorher


@pytest.fixture()
def admin_token(db):
    return db["familie"]["TestAdmin"]["tokens"]["admin"]


def _seite(client, admin_token):
    return client.get(f"/a/admin/{admin_token}/geraete")


# --- Zugriff ---------------------------------------------------------------

def test_admin_sieht_die_liste(client, admin_token, sitzungen):
    assert _seite(client, admin_token).status_code == 200


def test_kind_kommt_nicht_an_die_geraeteliste(client, db, sitzungen):
    """Die Liste nennt jedes angemeldete Gerät der ganzen Familie."""
    assert client.get(
        f"/a/admin/{db['familie']['TestKind']['tokens']['hilfe']}/geraete"
    ).status_code == 403


def test_kind_kann_kein_geraet_abmelden(client, db, sitzungen):
    kind = db["familie"]["TestKind"]["tokens"]["hilfe"]
    client.post(f"/a/admin/{kind}/geraete/{sitzungen['admin_handy']}/abmelden")
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM sitzungen WHERE id=?",
        (sitzungen["admin_handy"],)).fetchone()["c"] == 1


# --- Inhalt ----------------------------------------------------------------

def test_alle_geraete_stehen_drin(client, admin_token, sitzungen):
    seite = _seite(client, admin_token).get_data(as_text=True)
    assert "iPhone" in seite and "Windows" in seite and "Android" in seite


def test_zu_jedem_geraet_steht_die_person(client, admin_token, sitzungen):
    seite = _seite(client, admin_token).get_data(as_text=True)
    assert "TestAdmin" in seite and "TestKind" in seite


def test_nie_benutzte_sitzung_wird_als_solche_gezeigt(client, admin_token, sitzungen):
    """`gesehen` ist NULL – dann darf dort nicht das Erstelldatum stehen."""
    assert "noch nie" in _seite(client, admin_token).get_data(as_text=True)


# --- Abmelden --------------------------------------------------------------

def test_abmelden_entfernt_genau_ein_geraet(client, db, admin_token, sitzungen):
    client.post(f"/a/admin/{admin_token}/geraete/{sitzungen['admin_handy']}/abmelden")
    uebrig = {r["id"] for r in db["verbindung"].execute("SELECT id FROM sitzungen")}
    assert sitzungen["admin_handy"] not in uebrig
    assert sitzungen["admin_pc"] in uebrig
    assert sitzungen["kind"] in uebrig


def test_abmelden_laesst_die_zugaenge_unberuehrt(client, db, admin_token, sitzungen):
    """Der ganze Unterschied zu „Neuer Zugang + QR": der Link des Nutzers
    bleibt gültig, er kann sich damit wieder anmelden."""
    vorher = [r["token_lookup"] for r in db["verbindung"].execute(
        "SELECT token_lookup FROM grants ORDER BY id")]
    client.post(f"/a/admin/{admin_token}/geraete/{sitzungen['admin_handy']}/abmelden")
    nachher = [r["token_lookup"] for r in db["verbindung"].execute(
        "SELECT token_lookup FROM grants ORDER BY id")]
    assert vorher == nachher


def test_abgemeldetes_geraet_kommt_nicht_mehr_rein(client, db, admin_token, sitzungen, cookie_gilt):
    """Die Zusage muss auch wirken, nicht nur die Zeile verschwinden."""
    client.set_cookie("portal_sitzung", "kw-handy", domain="localhost")
    assert client.get("/a/admin/").status_code == 200

    client.post(f"/a/admin/{admin_token}/geraete/{sitzungen['admin_handy']}/abmelden")
    client.set_cookie("portal_sitzung", "kw-handy", domain="localhost")
    assert client.get("/a/admin/").status_code == 403


# --- "zuletzt benutzt" wird wirklich fortgeschrieben -----------------------

def test_benutzung_aktualisiert_gesehen(client, db, sitzungen, cookie_gilt):
    """Der Kern von #154. Ohne das zeigte die Spalte immer den
    Erstellzeitpunkt - sähe richtig aus, wäre falsch."""
    v = db["verbindung"]
    vorher = v.execute("SELECT gesehen FROM sitzungen WHERE id=?",
                       (sitzungen["admin_handy"],)).fetchone()["gesehen"]
    client.set_cookie("portal_sitzung", "kw-handy", domain="localhost")
    client.get("/a/admin/")
    nachher = v.execute("SELECT gesehen FROM sitzungen WHERE id=?",
                        (sitzungen["admin_handy"],)).fetchone()["gesehen"]
    assert nachher > vorher


def _gesehen_setzen(db, sid, versatz):
    db["verbindung"].execute(
        f"UPDATE sitzungen SET gesehen = datetime('now', '{versatz}') WHERE id=?", (sid,))
    db["verbindung"].commit()


def _gesehen(db, sid):
    return db["verbindung"].execute(
        "SELECT gesehen FROM sitzungen WHERE id=?", (sid,)).fetchone()["gesehen"]


def test_gesehen_wird_innerhalb_des_takts_nicht_neu_geschrieben(
        client, db, sitzungen, cookie_gilt):
    """Gedrosselt auf einmal je Stunde – sonst ein Schreibvorgang pro
    Seitenaufruf auf einer SQLite-Datei mit einem einzigen Worker.

    Der Versatz ist der Kern des Tests. Eine erste Fassung rief einfach
    zweimal auf und verglich – die beiden Aufrufe fielen aber in dieselbe
    Sekunde, `datetime('now')` lieferte zweimal denselben Wert, und der Test
    bestand auch nach ENTFERNTER Drosselung. Er prüfte also nichts.
    """
    _gesehen_setzen(db, sitzungen["admin_handy"], "-5 minutes")
    vorher = _gesehen(db, sitzungen["admin_handy"])
    client.set_cookie("portal_sitzung", "kw-handy", domain="localhost")
    client.get("/a/admin/")
    assert _gesehen(db, sitzungen["admin_handy"]) == vorher


def test_gesehen_wird_nach_dem_takt_fortgeschrieben(
        client, db, sitzungen, cookie_gilt):
    """Gegenstück: liegt der letzte Besuch länger zurück, muss geschrieben
    werden – sonst stünde in der Liste dauerhaft ein alter Wert."""
    _gesehen_setzen(db, sitzungen["admin_handy"], "-2 hours")
    vorher = _gesehen(db, sitzungen["admin_handy"])
    client.set_cookie("portal_sitzung", "kw-handy", domain="localhost")
    client.get("/a/admin/")
    assert _gesehen(db, sitzungen["admin_handy"]) > vorher


# --- Gerätenamen -----------------------------------------------------------

def test_geraetename_erkennt_das_system(app):
    from importlib import import_module
    lesbar = import_module("teile.03_admin")._geraet_lesbar
    assert lesbar("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7) Safari/604.1") == "iPhone · Safari"
    assert lesbar("Mozilla/5.0 (Android 15) Chrome/141.0") == "Android · Chrome"


def test_geraetename_faellt_nicht_auf_safari_herein(app):
    """Jeder Chrome nennt sich zusätzlich "Safari", Edge nennt sich
    zusätzlich "Chrome". Wer der Reihe nach von hinten prüft, hält am Ende
    jedes Gerät für ein Safari."""
    from importlib import import_module
    lesbar = import_module("teile.03_admin")._geraet_lesbar
    assert lesbar("Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/141 Safari/537") \
        == "Windows · Chrome"
    assert lesbar("Mozilla/5.0 (Windows NT 10.0) Chrome/141 Safari/537 Edg/141") \
        == "Windows · Edge"


def test_geraetename_ueberlebt_die_kuerzung(app):
    """Die entscheidende Probe: Der User-Agent wird beim Anlegen auf
    `_GERAET_MAX` Zeichen gekürzt. Bei 80 – dem urspünglichen Wert – endete
    JEDER echte Browser vor seinem Namen, und die Liste zeigte nur noch das
    Betriebssystem. Die anderen Tests hier merkten davon nichts, weil sie mit
    künstlich kurzen Kennungen arbeiten.
    """
    from importlib import import_module
    lesbar  = import_module("teile.03_admin")._geraet_lesbar
    sitzung = import_module("teile.19_sitzung")
    echt = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    assert lesbar(echt[:sitzung._GERAET_MAX]) == "Windows · Chrome"

    iphone = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.7 "
              "Mobile/15E148 Safari/604.1")
    assert lesbar(iphone[:sitzung._GERAET_MAX]) == "iPhone · Safari"


def test_geraetename_ohne_kennung(app):
    from importlib import import_module
    lesbar = import_module("teile.03_admin")._geraet_lesbar
    assert lesbar("") == "unbekannt"
    assert lesbar(None) == "unbekannt"
