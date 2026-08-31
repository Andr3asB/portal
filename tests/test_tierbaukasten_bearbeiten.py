"""Wunsch #201: gespeicherte Figuren im Tierbaukasten bearbeiten.

Vorher gab es nur Anlegen und Löschen. Wer die Farbe danebengegriffen hatte,
musste die Figur wegwerfen und von vorne bauen.

Drei Dinge, die beim Nachrüsten eines Bearbeiten-Weges typischerweise
kaputtgehen, und die hier festgenagelt sind:

* **Bearbeiten darf nicht heimlich anlegen.** Ein UPDATE, das versehentlich
  als INSERT endet, sieht in der Galerie fast richtig aus - es steht nur
  plötzlich alles doppelt da.
* **Anlegen und Bearbeiten müssen dieselbe Grenze ziehen.** Sonst liesse sich
  über den selteneren Weg einschleusen, was der häufigere ablehnt. Geprüft
  über das VERHALTEN, nicht darüber, ob es einen gemeinsamen Helfer gibt -
  ein `hasattr`-Test bliebe grün, während die zweite Kopie längst abweicht.
* **Der Kategoriewechsel muss die Spalten der alten Kategorie räumen.** Bleibt
  beim Wechsel Mensch -> Tier das alte `dicebear_optionen` stehen, zeichnet
  die Galerie weiter den Avatar, obwohl in der Datenbank ein Tier steht.
"""
import json

import pytest
from teile.kern import new_token, token_lookup

TIER = {"tier_typ": "katze", "koerper_farbe": "#112233", "muster": "punkte",
        "muster_farbe": "#ffeedd", "accessoire": "hut", "koerperbau": "70",
        "name": "Bommel"}
MENSCH = {"tier_typ": "mensch", "mensch_frisur": "bob", "mensch_augen": "happy",
          "name": "Lisa"}


@pytest.fixture()
def figuren(app, db):
    """Je eine gespeicherte Figur von Kind und Elternteil."""
    v = db["verbindung"]
    familie = db["familie"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='tierbaukasten'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
        v.commit()

    def anlegen(wer, **felder):
        werte = dict(TIER)
        werte.update(felder)
        return v.execute("""
            INSERT INTO tierbaukasten_kreationen
                (user_id, tier_typ, koerper_farbe, muster, muster_farbe,
                 accessoire, koerperbau, name)
            VALUES(?,?,?,?,?,?,?,?) RETURNING id
        """, (familie[wer]["id"], werte["tier_typ"], werte["koerper_farbe"],
              werte["muster"], werte["muster_farbe"], werte["accessoire"],
              int(werte["koerperbau"]), werte["name"])).fetchone()["id"]

    ids = {"vom_kind": anlegen("TestKind"),
           "vom_elternteil": anlegen("TestEltern", name="Fremd")}
    v.commit()
    return {"tokens": tokens, "ids": ids, "familie": familie, "anlegen": anlegen}


def _bearbeiten(client, token, kid, **felder):
    daten = dict(TIER)
    daten.update({k: str(w) for k, w in felder.items()})
    return client.post(f"/a/tierbaukasten/{token}/bearbeiten/{kid}", data=daten)


def _zeile(db, kid):
    return db["verbindung"].execute(
        "SELECT * FROM tierbaukasten_kreationen WHERE id=?", (kid,)).fetchone()


def _anzahl(db):
    return db["verbindung"].execute(
        "SELECT COUNT(*) c FROM tierbaukasten_kreationen").fetchone()["c"]


# --- Der eigentliche Zweck --------------------------------------------------

def test_eigene_figur_laesst_sich_aendern(client, db, figuren):
    _bearbeiten(client, figuren["tokens"]["TestKind"], figuren["ids"]["vom_kind"],
                koerper_farbe="#aabbcc", name="Bommel II")
    zeile = _zeile(db, figuren["ids"]["vom_kind"])
    assert zeile["koerper_farbe"] == "#aabbcc"
    assert zeile["name"] == "Bommel II"


def test_bearbeiten_legt_nichts_neues_an(client, db, figuren):
    """Der Fehler, der in der Galerie am spätesten auffällt: alles doppelt."""
    vorher = _anzahl(db)
    _bearbeiten(client, figuren["tokens"]["TestKind"], figuren["ids"]["vom_kind"],
                koerper_farbe="#aabbcc")
    assert _anzahl(db) == vorher


def test_erstellt_bleibt_stehen(client, db, figuren):
    """Die Galerie sortiert nach `erstellt`. Würde das Bearbeiten es
    fortschreiben, spränge jede nachgebesserte Figur nach vorne."""
    kid = figuren["ids"]["vom_kind"]
    vorher = _zeile(db, kid)["erstellt"]
    _bearbeiten(client, figuren["tokens"]["TestKind"], kid, name="Neu")
    assert _zeile(db, kid)["erstellt"] == vorher


def test_alle_tierfelder_kommen_an(client, db, figuren):
    kid = figuren["ids"]["vom_kind"]
    _bearbeiten(client, figuren["tokens"]["TestKind"], kid,
                tier_typ="hund", muster="streifen", muster_farbe="#00ff00",
                accessoire="brille,schleife", koerperbau="20")
    zeile = _zeile(db, kid)
    assert zeile["tier_typ"] == "hund"
    assert zeile["muster"] == "streifen"
    assert zeile["muster_farbe"] == "#00ff00"
    assert set((zeile["accessoire"] or "").split(",")) == {"brille", "schleife"}
    assert zeile["koerperbau"] == 20


# --- Wer darf ---------------------------------------------------------------

def test_fremde_figur_bleibt_unberuehrt(client, db, figuren):
    """Jeder sieht nur seine eigene Galerie - eine fremde Figur zu ändern ist
    kein Versehen, das still ins Leere laufen darf."""
    fremd = figuren["ids"]["vom_elternteil"]
    antwort = _bearbeiten(client, figuren["tokens"]["TestKind"], fremd, name="GEKAPERT")
    assert antwort.status_code == 403
    assert _zeile(db, fremd)["name"] == "Fremd"


def test_ohne_zugang_keine_aenderung(client, db, figuren):
    kid = figuren["ids"]["vom_kind"]
    antwort = _bearbeiten(client, "unsinn", kid, name="GEKAPERT")
    assert antwort.status_code == 403
    assert _zeile(db, kid)["name"] == "Bommel"


def test_andere_figuren_bleiben_unberuehrt(client, db, figuren):
    _bearbeiten(client, figuren["tokens"]["TestKind"], figuren["ids"]["vom_kind"],
                name="Geändert")
    assert _zeile(db, figuren["ids"]["vom_elternteil"])["name"] == "Fremd"


# --- Kategoriewechsel räumt auf --------------------------------------------

def test_wechsel_zu_mensch_raeumt_die_tierspalten(client, db, figuren):
    kid = figuren["ids"]["vom_kind"]
    client.post(f"/a/tierbaukasten/{figuren['tokens']['TestKind']}/bearbeiten/{kid}",
                data=MENSCH)
    zeile = _zeile(db, kid)
    assert zeile["tier_typ"] == "mensch"
    assert zeile["dicebear_optionen"], "Die Avatar-Auswahl muss gespeichert sein"
    assert json.loads(zeile["dicebear_optionen"])["frisur"] == "bob"
    assert zeile["muster"] is None and zeile["accessoire"] is None


def test_wechsel_zu_tier_raeumt_die_avatardaten(client, db, figuren):
    """Andersherum der teurere Fehler: bliebe `dicebear_optionen` stehen,
    zeichnete die Galerie weiter den Avatar - die Zeile sagt Tier, das Bild
    zeigt einen Menschen."""
    kid = figuren["anlegen"]("TestKind", tier_typ="mensch")
    db["verbindung"].execute(
        "UPDATE tierbaukasten_kreationen SET dicebear_optionen=? WHERE id=?",
        (json.dumps({"frisur": "bob"}), kid))
    db["verbindung"].commit()

    _bearbeiten(client, figuren["tokens"]["TestKind"], kid, tier_typ="hase")
    zeile = _zeile(db, kid)
    assert zeile["tier_typ"] == "hase"
    assert zeile["dicebear_optionen"] is None


# --- Dieselbe Grenze wie beim Anlegen ---------------------------------------

@pytest.mark.parametrize("feld,wert,spalte,erwartet", [
    ("koerper_farbe", "rot; drop table", "koerper_farbe", "#e8b04b"),
    ("koerper_farbe", "#GGGGGG",         "koerper_farbe", "#e8b04b"),
    ("muster",        "karo",            "muster",        None),
    ("accessoire",    "raketenwerfer",   "accessoire",    None),
    ("koerperbau",    "9999",            "koerperbau",    100),
    ("koerperbau",    "-5",              "koerperbau",    0),
    ("koerperbau",    "keine zahl",      "koerperbau",    50),
])
def test_beide_wege_bereinigen_dasselbe(client, db, figuren, feld, wert, spalte, erwartet):
    """Anlegen und Bearbeiten teilen sich die Prüfung. Läuft eine Kopie
    auseinander, ist es die im selteneren Weg - also im Bearbeiten."""
    token = figuren["tokens"]["TestKind"]

    daten = dict(TIER)
    daten[feld] = wert
    client.post(f"/a/tierbaukasten/{token}/speichern", data=daten)
    neueste = db["verbindung"].execute(
        "SELECT * FROM tierbaukasten_kreationen ORDER BY id DESC LIMIT 1").fetchone()
    assert neueste[spalte] == erwartet, f"Anlegen liess {feld}={wert!r} durch"

    kid = figuren["ids"]["vom_kind"]
    _bearbeiten(client, token, kid, **{feld: wert})
    assert _zeile(db, kid)[spalte] == erwartet, f"Bearbeiten liess {feld}={wert!r} durch"


@pytest.mark.parametrize("typ", ["einhorn", "", "drache"])
def test_unbekannter_typ_aendert_nichts(client, db, figuren, typ):
    """Beim Anlegen fällt ein unbekannter Typ heraus; beim Bearbeiten darf er
    die vorhandene Figur nicht überschreiben."""
    token = figuren["tokens"]["TestKind"]
    vorher_anzahl = _anzahl(db)
    client.post(f"/a/tierbaukasten/{token}/speichern", data=dict(TIER, tier_typ=typ))
    assert _anzahl(db) == vorher_anzahl, "Anlegen hat einen unbekannten Typ gespeichert"

    kid = figuren["ids"]["vom_kind"]
    _bearbeiten(client, token, kid, tier_typ=typ, name="Kaputt")
    zeile = _zeile(db, kid)
    assert zeile["tier_typ"] == "katze" and zeile["name"] == "Bommel"


# --- Die Oberfläche ---------------------------------------------------------

def test_galerie_zeigt_je_figur_einen_bearbeiten_knopf(client, db, figuren):
    seite = client.get(f"/a/tierbaukasten/{figuren['tokens']['TestKind']}/") \
                  .get_data(as_text=True)
    kid = figuren["ids"]["vom_kind"]
    assert f'class="btn-bearbeiten-tier figur-bearbeiten" data-id="{kid}"' in seite
    assert f'/loeschen/{kid}' in seite, "Der Mülleimer bleibt daneben stehen"


def test_die_figurdaten_stehen_fuer_das_formular_bereit(client, db, figuren):
    """Ohne die Werte in der Seite könnte das ✏️ das Formular nicht füllen -
    der Knopf wäre da und täte nichts."""
    seite = client.get(f"/a/tierbaukasten/{figuren['tokens']['TestKind']}/") \
                  .get_data(as_text=True)
    assert "const FIGUREN = " in seite
    assert '"koerper_farbe": "#112233"' in seite.replace("&#34;", '"')


def test_fremde_figuren_stehen_nicht_in_der_seite(client, db, figuren):
    """Gegenprobe: Die Werte im JSON stammen aus derselben Abfrage wie die
    Galerie - fiele der user_id-Filter weg, stünde hier fremdes Material."""
    seite = client.get(f"/a/tierbaukasten/{figuren['tokens']['TestKind']}/") \
                  .get_data(as_text=True)
    assert "Fremd" not in seite
