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
    from teile.kern import token_lookup, new_token
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
