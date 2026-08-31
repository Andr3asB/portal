"""Wunsch #164: Portionen anpassen.

Das Umrechnen selbst passiert im Browser (reine Anzeige, nichts wird
gespeichert) und ist dort live geprüft. Was hier getestet wird, ist die
Stelle, an der das Umrechnen den Server berührt – und das ist genau die
Stelle, an der es still falsch werden konnte:

**Der 🛒-Knopf.** Er setzt eine Zutat auf die Einkaufsliste. Bis #164 nahm der
Server dafür immer den GESPEICHERTEN Text. Hätte ich nur die Anzeige skaliert,
sähe man „750 g Mehl" und bekäme „500 g Mehl" auf die Liste – ohne jeden
Hinweis. Deshalb schickt das Frontend die angezeigte Zeile mit.

Abgegrenzt: Die strukturierte Zerlegung in Menge/Einheit/Name ist Wunsch #51
und bleibt zurückgestellt. Der mitgeschickte Text wird als Anzeigetext
übernommen, nicht ausgewertet.
"""
import pytest


@pytest.fixture()
def rezept(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='rezepte'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))

    rid = v.execute(
        "INSERT INTO rezepte(name, portionen) VALUES('Zwiebelkuchen','4') RETURNING id"
    ).fetchone()["id"]
    zid = v.execute(
        "INSERT INTO rezept_zutaten(rezept_id, name, position) "
        "VALUES(?, '500 g Mehl', 0) RETURNING id", (rid,)).fetchone()["id"]
    v.commit()
    return {"token": klartext, "rid": rid, "zid": zid}


def _einkaufen(client, rezept, text=None):
    nutzlast = {} if text is None else {"text": text}
    return client.post(f"/a/rezepte/{rezept['token']}/zutat/{rezept['zid']}/einkaufen",
                       json=nutzlast)


def _liste(db):
    return [r["name"] for r in db["verbindung"].execute(
        "SELECT name FROM einkauf_eintraege ORDER BY id")]


def test_umgerechnete_menge_landet_auf_der_liste(client, db, rezept):
    """Der Kern: Was auf dem Bildschirm steht, muss auf die Liste."""
    assert _einkaufen(client, rezept, "750 g Mehl").status_code == 200
    assert _liste(db) == ["750 g Mehl"]


def test_ohne_text_gilt_die_originalmenge(client, db, rezept):
    """Aeltere PWA im Cache schickt kein JSON mit - der Knopf muss trotzdem
    funktionieren, statt eine leere Zeile anzulegen."""
    _einkaufen(client, rezept)
    assert _liste(db) == ["500 g Mehl"]


def test_leerer_text_gilt_als_nicht_mitgeschickt(client, db, rezept):
    _einkaufen(client, rezept, "   ")
    assert _liste(db) == ["500 g Mehl"]


def test_unbekannte_zutat_bleibt_404(client, db, rezept):
    """Der Text darf nicht dazu fuehren, dass eine gar nicht existierende
    Zutat anlegbar wird - sonst waere der Endpunkt ein freies Eingabefeld
    fuer die Einkaufsliste."""
    antwort = client.post(
        f"/a/rezepte/{rezept['token']}/zutat/999999/einkaufen",
        json={"text": "1 kg Untergeschobenes"})
    assert antwort.status_code == 404
    assert _liste(db) == []


def test_text_wird_begrenzt(client, db, rezept):
    """200 Zeichen reichen fuer jede Zutatenzeile; ohne Grenze koennte ein
    beliebig langer Text in die Liste wandern."""
    _einkaufen(client, rezept, "9 " + "x" * 500)
    assert len(_liste(db)[0]) == 200


def test_ohne_zugang_kein_eintrag(client, db, rezept):
    antwort = client.post(f"/a/rezepte/unsinn/zutat/{rezept['zid']}/einkaufen",
                          json={"text": "750 g Mehl"})
    assert antwort.status_code == 403
    assert _liste(db) == []


# --- Die Oberfläche zeigt den Wähler nur, wenn er etwas tun kann -----------

def test_waehler_kennt_die_ausgangsportionen(client, db, rezept):
    seite = client.get(
        f"/a/rezepte/{rezept['token']}/{rezept['rid']}").get_data(as_text=True)
    assert 'id="portionen-wahl"' in seite
    assert 'data-basis="4"' in seite


def test_zutat_traegt_ihren_originaltext(client, db, rezept):
    """Das Umrechnen geht immer von der Ausgangsmenge aus – sonst summierten
    sich Rundungsfehler über mehrere Klicks auf."""
    seite = client.get(
        f"/a/rezepte/{rezept['token']}/{rezept['rid']}").get_data(as_text=True)
    assert 'data-original="500 g Mehl"' in seite


def test_ohne_portionsangabe_kein_waehler(client, db, rezept):
    """Ein Regler ohne Ausgangswert könnte nichts umrechnen. Er wird deshalb
    erst im Browser eingeblendet, wenn die Angabe eine Zahl enthält – das
    `data-basis` bleibt hier leer."""
    v = db["verbindung"]
    rid = v.execute(
        "INSERT INTO rezepte(name, portionen) VALUES('Ohne Angabe', NULL) RETURNING id"
    ).fetchone()["id"]
    # Mit Zutat, sonst rendert der ganze Zutaten-Abschnitt nicht und der Test
    # bestuende aus dem falschen Grund.
    v.execute("INSERT INTO rezept_zutaten(rezept_id, name, position) "
              "VALUES(?, '2 Eier', 0)", (rid,))
    v.commit()
    seite = client.get(
        f"/a/rezepte/{rezept['token']}/{rid}").get_data(as_text=True)
    assert 'data-basis=""' in seite


# --- Wunsch #165: Verlauf „gekocht" im Rezept ------------------------------

@pytest.fixture()
def gekocht_verlauf(db, rezept):
    """Drei Einträge – bewusst mit einem NACHGETRAGENEN dabei: am 20.7.
    gegessen, aber erst am 8.8. abgehakt."""
    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    for tag, mahlzeit, markiert in [
            ("2026-07-20", "abend",  "2026-08-08 19:00:00"),   # nachgetragen
            ("2026-08-01", "mittag", "2026-08-01 13:00:00"),
            ("2026-08-05", "abend",  "2026-08-05 19:30:00")]:
        v.execute("INSERT INTO rezept_gekocht(rezept_id, tag, mahlzeit, "
                  "markiert_von, markiert_am) VALUES(?,?,?,?,?)",
                  (rezept["rid"], tag, mahlzeit, uid, markiert))
    v.commit()
    return rezept


def _seite(client, rezept):
    return client.get(
        f"/a/rezepte/{rezept['token']}/{rezept['rid']}").get_data(as_text=True)


def test_verlauf_listet_alle_termine(client, db, gekocht_verlauf):
    seite = _seite(client, gekocht_verlauf)
    for datum in ("20.07.2026", "01.08.2026", "05.08.2026"):
        assert datum in seite, datum


def test_neuester_termin_zuerst(client, db, gekocht_verlauf):
    """Sortiert nach dem TAG des Essensplans, nicht nach dem Zeitpunkt des
    Anhakens. Der Eintrag vom 20.07. wurde zuletzt vermerkt (08.08.) – nach
    Vermerkzeit stünde er faelschlich ganz oben, obwohl es ihn zuerst gab."""
    seite = _seite(client, gekocht_verlauf)
    assert seite.index("05.08.2026") < seite.index("01.08.2026") < seite.index("20.07.2026")


def test_zusammenfassung_steht_schon_zugeklappt_da(client, db, gekocht_verlauf):
    """Die haeufigste Frage ist „wann zuletzt?" – dafuer soll man nicht
    erst aufklappen muessen."""
    seite = _seite(client, gekocht_verlauf)
    assert "3×, zuletzt am 05.08.2026" in seite


def test_liste_ist_zugeklappt(client, db, gekocht_verlauf):
    """`.gekocht-liste` ist display:none, `offen` kommt erst per Klick dazu."""
    seite = _seite(client, gekocht_verlauf)
    assert 'id="gekocht-liste"' in seite
    assert 'class="gekocht-liste offen"' not in seite


def test_ohne_verlauf_steht_eine_erklaerung_da(client, db, rezept):
    """Eine leere Liste ohne Erklaerung liesse offen, ob es kaputt ist."""
    seite = _seite(client, rezept)
    assert "noch nie vermerkt" in seite
    assert "als \u201egekocht\u201c abgehakt" in seite


def test_verlauf_eines_anderen_rezepts_taucht_nicht_auf(client, db, gekocht_verlauf):
    """Ohne die WHERE-Klausel saehe jedes Rezept die Termine aller anderen."""
    v = db["verbindung"]
    rid2 = v.execute(
        "INSERT INTO rezepte(name, portionen) VALUES('Anderes','2') RETURNING id"
    ).fetchone()["id"]
    v.execute("INSERT INTO rezept_zutaten(rezept_id, name, position) "
              "VALUES(?, '1 Ei', 0)", (rid2,))
    v.commit()
    seite = client.get(
        f"/a/rezepte/{gekocht_verlauf['token']}/{rid2}").get_data(as_text=True)
    assert "20.07.2026" not in seite
    assert "noch nie vermerkt" in seite
