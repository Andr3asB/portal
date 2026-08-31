"""Wunsch #153: „Wie Wirtschaftsprüfer brauchen die Eltern Zugriff auf das
Audit Log des Kassenbuchs."

Zwei Dinge muss diese Seite können, sonst ist sie Dekoration:

1. **Sie muss die andere Reihenfolge zeigen.** Das Kassenbuch sortiert nach dem
   Tag des Geldflusses, das Protokoll nach dem Zeitpunkt der Erfassung. Nur so
   fällt ein Nachtrag überhaupt auf – im Kontoauszug sieht er unauffällig aus.
2. **Sie darf nichts verschweigen.** Stornierte Einträge sind der interessante
   Teil; verschwänden sie hier wie im Saldo, wäre das Protokoll wertlos.

Dazu die Zugriffsgrenze in beide Richtungen und die Zeitzonenfalle: Die
Zeitstempel stehen als UTC in der Datenbank, der Container läuft auf UTC, die
Familie lebt in Europe/Berlin. Wer das nicht umrechnet, zeigt Uhrzeiten, die um
zwei Stunden danebenliegen – und markiert nachts jeden Eintrag fälschlich als
nachgetragen.
"""
import pytest


@pytest.fixture()
def buch(app, db):
    """Ein Kind mit vier Einträgen: Start, Einnahme, nachgetragene Ausgabe und
    eine stornierte Ausgabe."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    familie = db["familie"]
    kind    = familie["TestKind"]["id"]
    admin   = familie["TestAdmin"]["id"]
    eltern  = familie["TestEltern"]["id"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='kassenbuch'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    def rein(art, cent, person, zweck, datum, erstellt, von=None):
        return v.execute("""
            INSERT INTO kassenbuch_eintraege
                (user_id, art, betrag_cent, person, zweck, datum, erstellt_von, erstellt)
            VALUES (?,?,?,?,?,?,?,?) RETURNING id
        """, (kind, art, cent, person, zweck, datum, von or kind, erstellt)).fetchone()["id"]

    ids = {
        "start":   rein("start", 1500, None, "Startguthaben", "2026-08-01",
                        "2026-08-01 09:00:00"),
        "oma":     rein("einnahme", 500, "Oma", "Geburtstag", "2026-08-02",
                        "2026-08-02 10:00:00"),
        # Am 05.08. erfasst, gebucht auf den 02.08. -> nachgetragen
        "nachtrag": rein("ausgabe", 300, None, "Eis", "2026-08-02",
                         "2026-08-05 11:00:00"),
        "storno":  rein("ausgabe", 200, None, "Comic", "2026-08-06",
                        "2026-08-06 12:00:00"),
    }
    v.execute("""UPDATE kassenbuch_eintraege
                 SET storniert=1, storniert_von=?, storniert_am='2026-08-06 12:30:00'
                 WHERE id=?""", (kind, ids["storno"]))
    v.commit()
    return {"tokens": tokens, "ids": ids,
            "kind": kind, "admin": admin, "eltern": eltern}


def _seite(client, buch, wer="TestAdmin"):
    return client.get(
        f"/a/kassenbuch/{buch['tokens'][wer]}/kind/{buch['kind']}/pruefung"
    )


# --- Zugriff ---------------------------------------------------------------

def test_eltern_duerfen_das_protokoll_sehen(client, buch):
    assert _seite(client, buch, "TestEltern").status_code == 200


def test_admin_darf_das_protokoll_sehen(client, buch):
    assert _seite(client, buch, "TestAdmin").status_code == 200


def test_kind_darf_das_protokoll_nicht_sehen(client, buch):
    """Auch nicht das eigene. Die Prüfsicht ist die Perspektive der Aufsicht;
    das Kind sieht in seinem Kassenbuch ohnehin schon alle Einträge."""
    assert _seite(client, buch, "TestKind").status_code == 403


def test_ohne_gueltigen_zugang_kein_protokoll(client, buch):
    assert client.get(f"/a/kassenbuch/unsinn/kind/{buch['kind']}/pruefung"
                      ).status_code == 403


# --- Inhalt ----------------------------------------------------------------

def test_jede_handlung_steht_drin(client, buch):
    seite = _seite(client, buch).get_data(as_text=True)
    for text in ("Startbetrag", "Geburtstag", "Eis", "Comic"):
        assert text in seite, text


def test_storno_ist_ein_eigenes_ereignis(client, buch):
    """Vier Einträge, einer storniert -> fünf Ereignisse. Zählte das Storno
    nicht als eigene Handlung, verschwände der interessanteste Vorgang."""
    seite = _seite(client, buch).get_data(as_text=True)
    # Auf kbp-was zaehlen, nicht auf kbp-ereignis: letzteres traefe auch
    # kbp-ereignis-mitte und ergaebe stumm den doppelten Wert.
    assert seite.count('class="kbp-was"') == 5


def test_stornierter_eintrag_verschwindet_nicht(client, buch):
    seite = _seite(client, buch).get_data(as_text=True)
    assert "Comic" in seite
    assert "storniert" in seite


def test_urheber_wird_genannt(client, buch):
    """Die Spalten erstellt_von/storniert_von gibt es seit #144 – sichtbar
    waren sie bis #153 nirgends."""
    assert "TestKind" in _seite(client, buch).get_data(as_text=True)


def test_nachtrag_wird_markiert(client, buch):
    """Der eigentliche Zweck der Seite: ein Eintrag, der Tage nach dem
    Geldfluss erfasst wurde, muss auffallen."""
    assert "nachgetragen" in _seite(client, buch).get_data(as_text=True)


def test_zeitnaher_eintrag_wird_nicht_markiert(client, buch, db):
    """Gegenprobe – sonst stünde die Markierung an jeder Zeile und sagte
    nichts mehr aus."""
    v = db["verbindung"]
    v.execute("DELETE FROM kassenbuch_eintraege WHERE id=?", (buch["ids"]["nachtrag"],))
    v.commit()
    assert "nachgetragen" not in _seite(client, buch).get_data(as_text=True)


# --- Reihenfolge -----------------------------------------------------------

def test_neueste_handlung_zuerst(client, buch):
    """Nach ERFASSUNGSzeit, nicht nach Buchungsdatum. Der Nachtrag vom 05.08.
    (gebucht auf den 02.08.) muss deshalb VOR der Einnahme vom 02.08. stehen."""
    seite = _seite(client, buch).get_data(as_text=True)
    assert seite.index("Eis") < seite.index("Geburtstag")


# --- Rechenprobe -----------------------------------------------------------

def test_rechenprobe_zeigt_die_summanden(client, buch):
    """15,00 + 5,00 − 3,00 = 17,00; die stornierten 2,00 zählen nicht mit."""
    seite = _seite(client, buch).get_data(as_text=True)
    for betrag in ("15,00 €", "5,00 €", "3,00 €", "17,00 €"):
        assert betrag in seite, betrag


def test_rechenprobe_meldet_keine_abweichung(client, buch):
    assert "Summe stimmt nicht" not in _seite(client, buch).get_data(as_text=True)


# --- Zeitzone --------------------------------------------------------------

def test_uhrzeit_wird_in_ortszeit_gezeigt(client, buch):
    """09:00 UTC ist 11:00 in Berlin (Sommerzeit). Stünde hier 09:00, wäre
    jede Zeitangabe der Seite um zwei Stunden falsch."""
    seite = _seite(client, buch).get_data(as_text=True)
    assert "11:00" in seite
    assert "01.08.2026, 09:00" not in seite


def test_heute_lokal_kennt_die_zeitzone(app):
    """`date.today()` liefert im UTC-Container zwischen Mitternacht und 2 Uhr
    den Vortag - für ein Kassenbuch heißt das: Eintrag auf den falschen Tag,
    und die "kein Nachtragen in die Zukunft"-Regel schiebt ihn stumm zurück."""
    from datetime import datetime

    from teile.kern import LOKAL_TZ, heute_lokal
    assert heute_lokal() == datetime.now(LOKAL_TZ).date().isoformat()


def test_utc_zu_lokal_rechnet_um(app):
    from teile.kern import utc_zu_lokal
    assert utc_zu_lokal("2026-08-01 09:00:00") == "01.08.2026, 11:00"
    # Winterzeit: nur eine Stunde Versatz - ein fester Offset wäre falsch.
    assert utc_zu_lokal("2026-01-15 09:00:00") == "15.01.2026, 10:00"


def test_utc_zu_lokal_vertraegt_leere_werte(app):
    """storniert_am ist NULL, solange nichts storniert wurde."""
    from teile.kern import utc_zu_lokal
    assert utc_zu_lokal(None) is None
    assert utc_zu_lokal("") is None
