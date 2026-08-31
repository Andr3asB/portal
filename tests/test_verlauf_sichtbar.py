"""Der Verlauf eines Wunsches muss von aussen erkennbar sein.

Wunsch #161 hat die Werkstatt zum Ticketsystem gemacht: Rückfragen, Antworten
und Pläne stehen als Aktionen am Wunsch. Sichtbar waren sie aber ausschliess-
lich in der **aufgeklappten** Detailansicht. Bei knapp 190 Karten heisst das:
Eine Rückfrage, die auf eine Antwort wartet, findet nur, wer jede Karte
einzeln antippt – also niemand.

Der Fall, der das aufgedeckt hat: Eine Rückfrage zu #188 stand nur im
Chatverlauf und nirgends am Wunsch. Deshalb hier zwei Dinge zusammen:

* `verlauf_stand()` sagt, was auf die eingeklappte Karte gehört.
* `manage.py wunsch_aktion` trägt eine Aktion von der Kommandozeile ein –
  ohne diesen Weg landet jede beim Arbeiten entstehende Rückfrage wieder
  ausserhalb des Systems.

**Die Kernregel:** „offen" ist eine Rückfrage, auf die **keine Antwort mehr
folgt**. Es zählt die Reihenfolge, nicht die blosse Anwesenheit einer Antwort
irgendwo im Verlauf.
"""
import re

import pytest
from teile.werkstatt_app import verlauf_stand


def _aktionen(*arten):
    """Verlauf in der Reihenfolge, in der er entstanden ist."""
    return [{"art": a, "text": "x"} for a in arten]


# --- Die Regel selbst -------------------------------------------------------

def test_leerer_verlauf():
    assert verlauf_stand([]) == {"anzahl": 0, "offene_frage": False}
    assert verlauf_stand(None) == {"anzahl": 0, "offene_frage": False}


def test_frage_ohne_antwort_ist_offen():
    assert verlauf_stand(_aktionen("frage"))["offene_frage"] is True


def test_frage_mit_antwort_ist_erledigt():
    assert verlauf_stand(_aktionen("frage", "antwort"))["offene_frage"] is False


def test_neue_frage_nach_alter_antwort_ist_wieder_offen():
    """Der Grund, warum die Reihenfolge zählt und nicht das blosse Vorkommen:
    Wer auf eine alte Frage geantwortet hat und danach eine neue stellt, hat
    wieder eine offene."""
    assert verlauf_stand(_aktionen("frage", "antwort", "frage"))["offene_frage"] is True


def test_notizen_dazwischen_aendern_nichts():
    """Ein Plan oder eine Notiz ist keine Antwort - sonst gälte eine Frage als
    beantwortet, sobald irgendjemand irgendetwas dazuschreibt."""
    assert verlauf_stand(
        _aktionen("frage", "notiz", "plan", "umsetzung"))["offene_frage"] is True


def test_ohne_frage_nie_offen():
    assert verlauf_stand(_aktionen("notiz", "plan"))["offene_frage"] is False


def test_die_anzahl_zaehlt_alles():
    assert verlauf_stand(_aktionen("frage", "antwort", "notiz"))["anzahl"] == 3


# --- Auf der Karte ----------------------------------------------------------

@pytest.fixture()
def werkstatt_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _wunsch_mit_verlauf(v, text, arten, erledigt=0):
    wid = v.execute("INSERT INTO wuensche(text, erledigt) VALUES(?,?) RETURNING id",
                    (text, erledigt)).fetchone()["id"]
    for i, art in enumerate(arten):
        v.execute("INSERT INTO wunsch_aktionen(wunsch_id, art, text, erstellt) "
                  "VALUES(?,?,?,?)",
                  (wid, art, f"Text {i}", f"2026-08-10 10:0{i}:00"))
    v.commit()
    return wid


def _karte(text, wid):
    """Nur die eine Karte, nicht die ganze Seite."""
    anfang = text.index(f'id="wunsch-{wid}"')
    return text[anfang:anfang + 1500]


def test_offene_rueckfrage_steht_auf_der_karte(client, db, werkstatt_token):
    wid = _wunsch_mit_verlauf(db["verbindung"], "Mit offener Frage", ["frage"])
    seite = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "Rückfrage offen" in _karte(seite, wid)


def test_beantwortete_frage_zeigt_nur_die_anzahl(client, db, werkstatt_token):
    wid = _wunsch_mit_verlauf(db["verbindung"], "Beantwortet", ["frage", "antwort"])
    karte = _karte(client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True), wid)
    assert "Rückfrage offen" not in karte
    assert 'class="verlauf-badge">💬 2<' in karte


def test_wunsch_ohne_verlauf_bekommt_kein_abzeichen(client, db, werkstatt_token):
    """Ein Abzeichen an jeder Karte wäre so nutzlos wie gar keins."""
    wid = _wunsch_mit_verlauf(db["verbindung"], "Ohne alles", [])
    assert "verlauf-badge" not in _karte(
        client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True), wid)


def test_auch_erledigte_wuensche_zeigen_ihren_verlauf(client, db, werkstatt_token):
    """Die zweite Kartenart wird leicht vergessen - sie hat einen eigenen
    Block in der Vorlage."""
    wid = _wunsch_mit_verlauf(db["verbindung"], "Fertig, mit Verlauf",
                              ["plan", "umsetzung"], erledigt=1)
    assert 'class="verlauf-badge">💬 2<' in _karte(
        client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True), wid)


def test_die_wartende_frage_ist_farbig_hervorgehoben(client, db, werkstatt_token):
    """Eine Aufforderung, die aussieht wie ein Zählwert, wird überlesen."""
    import pathlib
    tpl = (pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" /
           "templates" / "werkstatt_app.html").read_text(encoding="utf-8")
    grau   = re.search(r"\.verlauf-badge\s*\{([^}]*)\}", tpl).group(1)
    wartet = re.search(r"\.verlauf-badge\.wartet\s*\{([^}]*)\}", tpl).group(1)
    assert "var(--surface-2)" in grau
    assert "background:#" in wartet.replace(" ", ""), "keine eigene Farbe"


def test_das_abzeichen_haengt_am_richtigen_wunsch(client, db, werkstatt_token):
    """Der Fehler, der sonst unbemerkt bliebe: ein Verlauf, der auf allen
    Karten auftaucht, weil das Dict nicht je Wunsch abgefragt wird."""
    v = db["verbindung"]
    mit  = _wunsch_mit_verlauf(v, "Hat eine Frage", ["frage"])
    ohne = _wunsch_mit_verlauf(v, "Hat nichts", [])
    seite = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert "Rückfrage offen" in _karte(seite, mit)
    assert "verlauf-badge" not in _karte(seite, ohne)
    assert seite.count("Rückfrage offen") == 1
