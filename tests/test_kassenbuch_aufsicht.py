"""Wunsch #212 (Sicherheitsaudit, Befund F-04): Aufsicht ist positiv definiert.

Vorher stand an drei Stellen sinngemäss „wer kein Kind ist, darf zusehen".
Das ist eine negative Liste, und die hatte ein Loch mit Ansage: `gast` ist der
Schema-Default und die Voreinstellung im Anlegeformular. Der nächste Nutzer,
der ohne ausdrückliche Rollenwahl entsteht - Besuch, Leihgerät -, hätte jedes
Kinder-Kassenbuch samt Kontostand, Beträgen, Zwecken und Gegenpersonen sehen
können, über die Prüfsicht zusätzlich Zeitstempel und Urheber.

Der Test hält deshalb DREI Einstiege gleichzeitig fest - Übersicht, fremdes
Buch, Prüfprotokoll. Die erste Fassung des Befunds nannte nur die letzten
beiden; die Übersicht (`/a/kassenbuch/<token>/`) listet aber ebenfalls jedes
Kind mit Kontostand und wäre offen geblieben.

Der Gast bekommt hier ausdrücklich einen Grant. Ohne ihn prüfte der Test nur,
dass ein fehlender Grant sperrt - und bliebe grün, während die Routen selbst
weiterhin jeden hereinliessen.
"""
import pytest

from teile.kern import token_lookup, new_token


@pytest.fixture()
def buecher(app, db):
    """Kassenbuch-Grant für alle, dazu ein Gast und ein befülltes Kinderbuch."""
    v = db["verbindung"]
    familie = dict(db["familie"])

    with app.app_context():
        gast_id = v.execute(
            "INSERT INTO users(name, farbe, is_admin, rolle) "
            "VALUES('TestGast', '#444444', 0, 'gast') RETURNING id").fetchone()["id"]
        familie["TestGast"] = {"id": gast_id, "rolle": "gast", "is_admin": 0}

        app_id = v.execute("SELECT id FROM apps WHERE slug='kassenbuch'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

        kind_id = familie["TestKind"]["id"]
        v.execute("""INSERT INTO kassenbuch_eintraege
                     (user_id, art, betrag_cent, zweck, datum, erstellt_von)
                     VALUES(?, 'start', 1234, 'Startguthaben', '2026-08-01', ?)""",
                  (kind_id, kind_id))
        v.execute("""INSERT INTO kassenbuch_eintraege
                     (user_id, art, betrag_cent, person, zweck, datum, erstellt_von)
                     VALUES(?, 'ausgabe', 300, 'Kiosk', 'Geheimes Eis', '2026-08-02', ?)""",
                  (kind_id, kind_id))
        v.commit()
    return {"tokens": tokens, "familie": familie, "kind_id": kind_id}


def _wege(buecher, wer):
    """Die drei Einstiege, über die fremde Kassenbuchdaten sichtbar werden."""
    t = buecher["tokens"][wer]
    kid = buecher["kind_id"]
    return {
        "Übersicht":      f"/a/kassenbuch/{t}/",
        "fremdes Buch":   f"/a/kassenbuch/{t}/kind/{kid}",
        "Prüfprotokoll":  f"/a/kassenbuch/{t}/kind/{kid}/pruefung",
    }


# --- Der Befund -------------------------------------------------------------

@pytest.mark.parametrize("weg", ["Übersicht", "fremdes Buch", "Prüfprotokoll"])
def test_gast_kommt_nirgends_hinein(client, db, buecher, weg):
    antwort = client.get(_wege(buecher, "TestGast")[weg])
    assert antwort.status_code == 403, f"{weg} steht einem Gast offen"


@pytest.mark.parametrize("weg", ["Übersicht", "fremdes Buch", "Prüfprotokoll"])
def test_kein_zeichen_der_daten_im_koerper(client, db, buecher, weg):
    """Gegenprobe zum Statuscode: Läge der Inhalt trotz 403 in der Antwort,
    wäre die Sperre nur Fassade."""
    antwort = client.get(_wege(buecher, "TestGast")[weg])
    for verraeterisch in (b"Geheimes Eis", b"Kiosk", b"12,34", b"9,34"):
        assert verraeterisch not in antwort.data, f"{weg} verrät {verraeterisch!r}"


# --- Die Gegenrichtung: wer darf, darf weiterhin ----------------------------

@pytest.mark.parametrize("wer", ["TestAdmin", "TestEltern"])
@pytest.mark.parametrize("weg", ["Übersicht", "fremdes Buch", "Prüfprotokoll"])
def test_aufsicht_bleibt_moeglich(client, db, buecher, wer, weg):
    """Ohne diese Richtung wäre der sicherste Fix, alles zu sperren - und die
    vom Wunsch #144 ausdrücklich verlangte Auditierung wäre kaputt."""
    antwort = client.get(_wege(buecher, wer)[weg])
    assert antwort.status_code == 200, f"{wer} kommt nicht mehr an {weg}"


def test_eltern_sehen_die_eintraege_wirklich(client, db, buecher):
    antwort = client.get(_wege(buecher, "TestEltern")["fremdes Buch"])
    assert "Geheimes Eis".encode() in antwort.data


def test_kind_sieht_sein_eigenes_buch(client, db, buecher):
    antwort = client.get(f"/a/kassenbuch/{buecher['tokens']['TestKind']}/")
    assert antwort.status_code == 200


def test_kind_kommt_nicht_ins_pruefprotokoll(client, db, buecher):
    """Unverändert seit #153 - die Prüfsicht ist die Perspektive der Aufsicht,
    auch beim eigenen Buch."""
    t = buecher["tokens"]["TestKind"]
    antwort = client.get(f"/a/kassenbuch/{t}/kind/{buecher['kind_id']}/pruefung")
    assert antwort.status_code == 403


# --- Gegenprobe: schlägt der Wächter überhaupt an? --------------------------

@pytest.mark.parametrize("weg", ["Übersicht", "fremdes Buch", "Prüfprotokoll"])
def test_mit_der_alten_regel_stuende_alles_offen(client, db, buecher, monkeypatch, weg):
    """Der Nachweis, dass die Tests oben nicht aus einem anderen Grund grün sind.

    Hier wird `_darf_aufsicht` für die Dauer eines Tests durch die ALTE,
    negative Regel ersetzt (`wer kein Kind ist, darf`). Kommt der Gast dann
    überall hinein, hängen die 403 oben tatsächlich an dieser einen Funktion -
    und nicht daran, dass ihm ohnehin etwas anderes im Weg steht.

    Bewusst per monkeypatch und nicht durch kurzzeitiges Aufweichen des
    Quelltextes: eine abgeschwächte Berechtigungsprüfung soll nicht einmal für
    Minuten in einer Datei stehen, in der sie jemand committen könnte.
    """
    import importlib
    modul = importlib.import_module("teile.22_kassenbuch")
    monkeypatch.setattr(modul, "_darf_aufsicht", lambda user: user["rolle"] != "kind")

    antwort = client.get(_wege(buecher, "TestGast")[weg])
    assert antwort.status_code == 200, (
        f"{weg} sperrt den Gast auch mit der alten Regel - der Test oben "
        f"beweist dann nichts über _darf_aufsicht."
    )


# --- Die Voreinstellung, die den Befund erst gefährlich macht ---------------

def test_gast_ist_weiterhin_die_voreinstellung(db):
    """Nicht geändert, nur festgehalten: Solange `gast` der Default ist, muss
    die Berechtigung positiv formuliert bleiben. Kippt jemand diesen Default,
    soll er hier vorbeikommen und den Kommentar lesen."""
    v = db["verbindung"]
    uid = v.execute("INSERT INTO users(name, farbe) VALUES('Ohne Rolle','#555555') "
                    "RETURNING id").fetchone()["id"]
    v.commit()
    assert v.execute("SELECT rolle FROM users WHERE id=?", (uid,)).fetchone()["rolle"] == "gast"


def test_auto_grant_uebergeht_gaeste(app, db):
    """Ein Gast soll die Kachel gar nicht erst bekommen - eine Kachel, hinter
    der nur ein 403 steht, ist eine Einladung, die Sperre wieder aufzuweichen."""
    import importlib
    kern = importlib.import_module("teile.kern")
    v = db["verbindung"]
    gast = v.execute("INSERT INTO users(name, farbe, rolle) "
                     "VALUES('NurGast','#666666','gast') RETURNING id").fetchone()["id"]
    kind = v.execute("INSERT INTO users(name, farbe, rolle) "
                     "VALUES('NochEinKind','#777777','kind') RETURNING id").fetchone()["id"]
    v.commit()

    with app.app_context():          # token_lookup() braucht den TOKEN_KEY
        kern._auto_grant_all(v, "kassenbuch", rollen=("eltern", "kind"))
    v.commit()

    def hat_grant(uid):
        return v.execute("""SELECT 1 FROM grants g JOIN apps a ON a.id=g.app_id
                            WHERE g.user_id=? AND a.slug='kassenbuch'""",
                         (uid,)).fetchone() is not None

    assert not hat_grant(gast), "Der Gast hat das Kassenbuch automatisch bekommen"
    assert hat_grant(kind), "Das Kind hat es NICHT bekommen - Filter zu scharf"
