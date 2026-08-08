"""Wunsch #158: Geburtstagseinträge sollen editierbar sein.

Ein Eintrag gilt für die ganze Familie – das macht Bearbeiten zu einer
Berechtigungsfrage, nicht bloss zu einem Formular. Die Regel ist deshalb
dieselbe wie beim Löschen: Urheber, Eltern oder Admin. Wer einen fremden
Eintrag nur für sich loswerden will, blendet ihn aus.

Zwei Dinge, die beim Bearbeiten leicht kaputtgehen und hier festgenagelt sind:

* **`erstellt_von` darf sich nicht ändern.** Wanderte die Urheberschaft mit
  jeder Korrektur mit, könnte der ursprüngliche Eintragende seinen eigenen
  Eintrag plötzlich nicht mehr anfassen, nachdem ein Elternteil einen
  Tippfehler behoben hat.
* **Die Erinnerungssperre darf nicht kippen.** `geburtstag_gesendet`
  schlüsselt auf den VERSANDTAG, nicht auf das Geburtsdatum – eine Korrektur
  darf also keine künftige Erinnerung unterdrücken.
"""
import pytest


@pytest.fixture()
def eintraege(app, db):
    """Zwei Einträge: einer vom Kind, einer vom Admin."""
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    familie = db["familie"]

    with app.app_context():
        app_id = v.execute(
            "SELECT id FROM apps WHERE slug='geburtstage'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    def anlegen(wer, name, tag, monat, jahr=None, notiz=None):
        return v.execute("""
            INSERT INTO geburtstage(name, tag, monat, jahr, notiz, erstellt_von)
            VALUES(?,?,?,?,?,?) RETURNING id
        """, (name, tag, monat, jahr, notiz, familie[wer]["id"])).fetchone()["id"]

    ids = {
        "vom_kind":  anlegen("TestKind", "Oma Erika", 24, 3, 1948, "mag Rosen"),
        "vom_admin": anlegen("TestAdmin", "Onkel Karl", 5, 11),
    }
    v.commit()
    return {"tokens": tokens, "ids": ids, "familie": familie}


def _bearbeiten(client, token, gid, **felder):
    daten = {"name": "Oma Erika", "tag": "24", "monat": "3",
             "jahr": "1948", "notiz": "mag Rosen"}
    daten.update({k: str(v) for k, v in felder.items()})
    return client.post(f"/a/geburtstage/{token}/{gid}/bearbeiten", data=daten)


def _zeile(db, gid):
    return db["verbindung"].execute(
        "SELECT * FROM geburtstage WHERE id=?", (gid,)).fetchone()


# --- Wer darf ---------------------------------------------------------------

def test_urheber_darf_seinen_eintrag_aendern(client, db, eintraege):
    _bearbeiten(client, eintraege["tokens"]["TestKind"],
                eintraege["ids"]["vom_kind"], name="Oma Erika Schmidt")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["name"] == "Oma Erika Schmidt"


def test_eltern_duerfen_fremde_eintraege_korrigieren(client, db, eintraege):
    """Der Sinn der Sache: einen Tippfehler beheben, ohne den Eintrag zu
    löschen und neu anzulegen."""
    _bearbeiten(client, eintraege["tokens"]["TestEltern"],
                eintraege["ids"]["vom_kind"], tag="25")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["tag"] == 25


def test_admin_darf_fremde_eintraege_korrigieren(client, db, eintraege):
    _bearbeiten(client, eintraege["tokens"]["TestAdmin"],
                eintraege["ids"]["vom_kind"], notiz="mag Tulpen")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["notiz"] == "mag Tulpen"


def test_kind_darf_fremden_eintrag_nicht_aendern(client, db, eintraege):
    """Gleiche Grenze wie beim Löschen – ein Eintrag gilt für alle."""
    antwort = _bearbeiten(client, eintraege["tokens"]["TestKind"],
                          eintraege["ids"]["vom_admin"], name="GEKAPERT")
    assert antwort.status_code == 403
    assert _zeile(db, eintraege["ids"]["vom_admin"])["name"] == "Onkel Karl"


def test_ohne_zugang_keine_aenderung(client, db, eintraege):
    client.post(f"/a/geburtstage/unsinn/{eintraege['ids']['vom_kind']}/bearbeiten",
                data={"name": "GEKAPERT", "tag": "1", "monat": "1"})
    assert _zeile(db, eintraege["ids"]["vom_kind"])["name"] == "Oma Erika"


# --- Was sich nicht ändern darf --------------------------------------------

def test_urheberschaft_bleibt_beim_eintragenden(client, db, eintraege):
    """Sonst könnte das Kind seinen eigenen Eintrag nicht mehr anfassen,
    nachdem ein Elternteil einen Tippfehler behoben hat."""
    vorher = _zeile(db, eintraege["ids"]["vom_kind"])["erstellt_von"]
    _bearbeiten(client, eintraege["tokens"]["TestAdmin"],
                eintraege["ids"]["vom_kind"], name="Oma Erika S.")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["erstellt_von"] == vorher


def test_andere_eintraege_bleiben_unberuehrt(client, db, eintraege):
    _bearbeiten(client, eintraege["tokens"]["TestAdmin"],
                eintraege["ids"]["vom_kind"], name="Geändert")
    assert _zeile(db, eintraege["ids"]["vom_admin"])["name"] == "Onkel Karl"


# --- Dieselbe Prüfung wie beim Anlegen -------------------------------------

def test_unsinniges_datum_wird_abgelehnt(client, db, eintraege):
    """Die Prüfung teilen sich Anlegen und Bearbeiten. Ginge sie hier durch,
    liesse sich per Bearbeiten eintragen, was beim Anlegen abgelehnt wird –
    und `_tage_bis()` bekäme einen Monat 13 zu sehen."""
    _bearbeiten(client, eintraege["tokens"]["TestKind"],
                eintraege["ids"]["vom_kind"], monat="13")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["monat"] == 3


def test_leerer_name_wird_abgelehnt(client, db, eintraege):
    _bearbeiten(client, eintraege["tokens"]["TestKind"],
                eintraege["ids"]["vom_kind"], name="   ")
    assert _zeile(db, eintraege["ids"]["vom_kind"])["name"] == "Oma Erika"


def test_unsinniges_jahr_wird_zu_null(client, db, eintraege):
    """Ein Jahr in der Zukunft ist ein Tippfehler – der Eintrag bleibt, das
    Jahr fällt weg (wie beim Anlegen)."""
    _bearbeiten(client, eintraege["tokens"]["TestKind"],
                eintraege["ids"]["vom_kind"], jahr="2099")
    zeile = _zeile(db, eintraege["ids"]["vom_kind"])
    assert zeile["jahr"] is None
    assert zeile["name"] == "Oma Erika"


@pytest.mark.parametrize("feld,wert", [
    ("monat", "13"), ("monat", "0"), ("tag", "32"), ("tag", "0"), ("name", "  "),
])
def test_beide_wege_lehnen_dasselbe_ab(client, db, eintraege, feld, wert):
    """Anlegen und Bearbeiten müssen dieselbe Grenze ziehen.

    Bewusst über das VERHALTEN geprüft und nicht darüber, ob es einen
    gemeinsamen Helfer gibt: Ein Test, der nur `hasattr(modul, "_eingaben_lesen")`
    abfragt, bliebe grün, während die zweite Kopie längst abweicht."""
    token = eintraege["tokens"]["TestKind"]
    vorher = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM geburtstage").fetchone()["c"]

    # Weg 1: anlegen
    daten = {"name": "Neu", "tag": "1", "monat": "1"}
    daten[feld] = wert
    client.post(f"/a/geburtstage/{token}/neu", data=daten)
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM geburtstage").fetchone()["c"] == vorher,         f"Anlegen hat {feld}={wert!r} durchgelassen"

    # Weg 2: bearbeiten
    _bearbeiten(client, token, eintraege["ids"]["vom_kind"], **{feld: wert})
    zeile = _zeile(db, eintraege["ids"]["vom_kind"])
    assert (zeile["name"], zeile["tag"], zeile["monat"]) == ("Oma Erika", 24, 3),         f"Bearbeiten hat {feld}={wert!r} durchgelassen"


# --- Erinnerungssperre ------------------------------------------------------

def test_korrektur_unterdrueckt_keine_erinnerung(client, db, eintraege, app):
    """`geburtstag_gesendet` schlüsselt auf den Versandtag, nicht auf das
    Geburtsdatum. Wird ein Datum korrigiert, muss die Erinnerung am neuen
    Termin trotzdem fällig werden."""
    import importlib
    from datetime import date
    modul = importlib.import_module("teile.23_geburtstage")
    v = db["verbindung"]
    gid  = eintraege["ids"]["vom_kind"]
    kind = eintraege["familie"]["TestKind"]["id"]

    v.execute("""INSERT INTO geburtstag_einstellungen
                     (user_id, geburtstag_id, erinnerung) VALUES(?,?,1)""",
              (kind, gid))
    # So tun, als sei fuer diesen Eintrag heute schon etwas rausgegangen
    v.execute("""INSERT INTO geburtstag_gesendet(user_id, geburtstag_id, art, datum)
                 VALUES(?,?,'vorlauf',?)""", (kind, gid, date.today().isoformat()))
    v.commit()

    # Datum auf HEUTE korrigieren
    heute = date.today()
    _bearbeiten(client, eintraege["tokens"]["TestKind"], gid,
                tag=heute.day, monat=heute.month)

    with app.app_context():
        faellig = modul.faellige_erinnerungen(v, heute)
    arten = {(f["geburtstag_id"], f["art"]) for f in faellig}
    assert (gid, "tag") in arten, (
        "Die Tages-Erinnerung muss trotz des heutigen 'vorlauf'-Vermerks fällig sein"
    )


# --- Wunsch #159: Löschen nur im Bearbeiten-Modus --------------------------

def _panel_inhalt(seite, panel_id):
    """Der Text ZWISCHEN dem öffnenden div des Panels und seinem passenden
    schliessenden div – per Tiefenzählung, nicht per "bis zum nächsten </div>".

    Die erste Fassung dieses Tests hat bis zur nächsten Karte gesucht. Das
    war wertlos: Schiebt man das Löschen-Formular aus dem Panel heraus,
    landet es unmittelbar dahinter – immer noch vor der nächsten Karte, und
    der Test blieb grün. Aufgefallen erst beim absichtlichen Kaputtmachen.
    """
    import re
    beginn = seite.index(f'id="{panel_id}"')
    # zurück zum '<div' dieses Tags
    auf = seite.rindex("<div", 0, beginn)
    tiefe = 0
    for m in re.finditer("</?div[ >]", seite[auf:]):
        tiefe += -1 if m.group(0).startswith("</") else 1
        if tiefe == 0:
            return seite[auf:auf + m.start()]
    raise AssertionError(f"Panel {panel_id} wird nie geschlossen")


def test_loeschen_steckt_im_bearbeiten_panel(client, db, eintraege):
    """Der Löschen-Knopf stand vorher dauerhaft unter jeder Karte – in einer
    Liste, in der man normalerweise nichts löschen will, war er damit der
    auffälligste Knopf der Seite."""
    gid = eintraege["ids"]["vom_kind"]
    antwort = client.get(f"/a/geburtstage/{eintraege['tokens']['TestAdmin']}/")
    seite = antwort.get_data(as_text=True)

    assert f"/{gid}/loeschen" in seite, "Voraussetzung: der Admin darf löschen"
    assert f"/{gid}/loeschen" in _panel_inhalt(seite, f"gb-edit-{gid}"), (
        "Das Löschen-Formular gehört IN das Bearbeiten-Panel, nicht daneben."
    )


def test_bearbeiten_panel_ist_zugeklappt(client, db, eintraege):
    """Das Panel trägt `gb-panel` ohne `open` – und `.gb-panel` ist
    `display:none`. Ohne das wäre das Verschieben wirkungslos: Der
    Löschen-Knopf stünde weiterhin sichtbar da, nur woanders."""
    gid = eintraege["ids"]["vom_kind"]
    seite = client.get(f"/a/geburtstage/{eintraege['tokens']['TestAdmin']}/") \
                  .get_data(as_text=True)
    beginn = seite.index(f'id="gb-edit-{gid}"')
    # Das class-Attribut steht unmittelbar vor der id
    davor = seite[max(0, beginn - 120):beginn]
    assert 'class="gb-panel"' in davor, davor
    assert "open" not in davor


def test_ohne_berechtigung_gibt_es_gar_kein_loeschen(client, db, eintraege):
    """Gegenprobe: Das Kind sieht beim fremden Eintrag weder Bearbeiten noch
    Löschen – sonst hätte das Verschieben den Knopf nur versteckt statt ihn
    an die Berechtigung zu binden."""
    gid = eintraege["ids"]["vom_admin"]
    seite = client.get(f"/a/geburtstage/{eintraege['tokens']['TestKind']}/") \
                  .get_data(as_text=True)
    assert f'/{gid}/loeschen' not in seite
    assert f'id="gb-edit-{gid}"' not in seite
