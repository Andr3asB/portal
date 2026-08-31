"""Wunsch #150: Vokabel-Kapitel mit anderen teilen.

Der Wunsch verlangt: geteilt wird ein Kapitel, der Empfänger kann damit üben
und die Aussprache anhören, alle Trainings werden wie gehabt dokumentiert –
und zwar so lange, bis das Teilen aufgehoben wird.

Die Tests decken beide Richtungen ab: dass der Empfänger genug darf (sonst
ist das Teilen wertlos) und dass er nicht zu viel darf (fremde Vokabeln sind
zum Üben da, nicht zum Ändern). Der zweite Teil ist der wichtigere – eine zu
weite Freigabe fällt im Alltag nicht auf.
"""
import pytest


@pytest.fixture()
def vok(app, db):
    """Andi (Admin) hat ein Kapitel mit zwei Vokabeln; das Kind hat nichts."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    familie = db["familie"]
    besitzer = familie["TestAdmin"]["id"]
    empfaenger = familie["TestKind"]["id"]
    dritter = familie["TestEltern"]["id"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='vokabeln'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    zeile = v.execute("SELECT id FROM vokabel_sprachen WHERE name='Englisch'").fetchone()
    sid = zeile["id"] if zeile else v.execute(
        "INSERT INTO vokabel_sprachen(name) VALUES('Englisch') RETURNING id").fetchone()["id"]
    for uid in (besitzer, empfaenger, dritter):
        v.execute("INSERT OR IGNORE INTO vokabel_sprachen_nutzer(user_id, sprache_id) "
                  "VALUES(?,?)", (uid, sid))

    kid = v.execute(
        "INSERT INTO vokabel_kapitel(user_id, name) VALUES(?, 'Unit 5') RETURNING id",
        (besitzer,)).fetchone()["id"]
    vids = []
    for fremd, deutsch in (("house", "Haus"), ("tree", "Baum")):
        vid = v.execute(
            "INSERT INTO vokabeln(user_id, sprache_id, fremd, deutsch) VALUES(?,?,?,?) "
            "RETURNING id", (besitzer, sid, fremd, deutsch)).fetchone()["id"]
        v.execute("INSERT INTO vokabel_kapitel_zuordnung(vokabel_id, kapitel_id) VALUES(?,?)",
                  (vid, kid))
        vids.append(vid)
    v.commit()
    return {"tokens": tokens, "sid": sid, "kid": kid, "vids": vids,
            "besitzer": besitzer, "empfaenger": empfaenger, "dritter": dritter}


def _teilen(db, kid, user_id):
    db["verbindung"].execute(
        "INSERT OR IGNORE INTO vokabel_kapitel_freigabe(kapitel_id, user_id) VALUES(?,?)",
        (kid, user_id))
    db["verbindung"].commit()


# --- Ohne Freigabe sieht niemand etwas ------------------------------------

def test_ohne_freigabe_keine_fremden_vokabeln(client, vok):
    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestKind']}/").get_data(as_text=True)
    assert "house" not in seite


def test_ohne_freigabe_kein_audio(client, vok):
    antwort = client.get(f"/a/vokabeln/{vok['tokens']['TestKind']}/wort/{vok['vids'][0]}/audio")
    assert antwort.status_code == 404


# --- Mit Freigabe: der Empfänger darf üben --------------------------------

def test_geteilte_vokabeln_erscheinen_in_der_liste(client, vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestKind']}/").get_data(as_text=True)
    assert "house" in seite and "tree" in seite


def test_geteiltes_kapitel_steht_im_trainer(client, vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestKind']}/lernen").get_data(as_text=True)
    assert "Unit 5" in seite
    assert "TestAdmin" in seite, "Herkunft muss erkennbar sein"


def test_training_mit_geteiltem_kapitel_liefert_vokabeln(client, vok, db):
    """Ohne das wäre das Kapitel zwar auswählbar, das Training aber leer –
    der unangenehmste Fehler, weil er wie ein leeres Kapitel aussieht."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    antwort = client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/lernen/start", data={
        "sprache_id": vok["sid"], "kapitel_ids": [str(vok["kid"])]})
    assert antwort.status_code == 200
    assert b"house" in antwort.data


def test_versuch_mit_geteilter_vokabel_wird_gezaehlt(client, vok, db):
    """„Alle Trainings sollen wie gehabt dokumentiert werden."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/lernen/start", data={
        "sprache_id": vok["sid"], "kapitel_ids": [str(vok["kid"])]})
    sid_session = db["verbindung"].execute(
        "SELECT id FROM vokabel_sessions WHERE user_id=? ORDER BY id DESC",
        (vok["empfaenger"],)).fetchone()["id"]
    antwort = client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/versuch", json={
        "session_id": sid_session, "vokabel_id": vok["vids"][0], "richtig": True})
    assert antwort.status_code == 200
    anzahl = db["verbindung"].execute(
        "SELECT COUNT(*) c FROM vokabel_versuche WHERE vokabel_id=?",
        (vok["vids"][0],)).fetchone()["c"]
    assert anzahl == 1


def test_audio_mit_freigabe_erlaubt(client, vok, db, monkeypatch):
    """„die Media-Dateien anhören" steht ausdrücklich im Wunsch."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    from teile import kern
    monkeypatch.setattr(kern, "_tts_anfrage", lambda *a, **kw: b"RIFF----WAVEfake")
    client.application.config["OPENROUTER_API_KEY"] = "test-key"
    try:
        antwort = client.get(
            f"/a/vokabeln/{vok['tokens']['TestKind']}/wort/{vok['vids'][0]}/audio")
    finally:
        client.application.config["OPENROUTER_API_KEY"] = ""
    assert antwort.status_code == 200


def test_sprache_muss_nicht_selbst_aktiviert_sein(client, vok, db):
    """Sonst liefe das Teilen ins Leere, sobald der Empfänger die Sprache
    nicht selbst gewählt hat - ohne jeden Hinweis, woran es liegt."""
    db["verbindung"].execute(
        "DELETE FROM vokabel_sprachen_nutzer WHERE user_id=?", (vok["empfaenger"],))
    db["verbindung"].commit()
    _teilen(db, vok["kid"], vok["empfaenger"])
    antwort = client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/lernen/start", data={
        "sprache_id": vok["sid"], "kapitel_ids": [str(vok["kid"])]})
    assert antwort.status_code == 200
    assert b"house" in antwort.data


# --- Aber nicht mehr als das ----------------------------------------------

def test_empfaenger_kann_fremde_vokabel_nicht_aendern(client, vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/{vok['vids'][0]}/bearbeiten", data={
        "sprache_id": vok["sid"], "fremd": "GEKAPERT", "deutsch": "x"})
    zeile = db["verbindung"].execute(
        "SELECT fremd FROM vokabeln WHERE id=?", (vok["vids"][0],)).fetchone()
    assert zeile["fremd"] == "house"


def test_empfaenger_kann_fremde_vokabel_nicht_loeschen(client, vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/{vok['vids'][0]}/loeschen")
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM vokabeln WHERE id=?", (vok["vids"][0],)).fetchone()["c"] == 1


def test_empfaenger_kann_das_kapitel_nicht_umbenennen(client, vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/kapitel", data={
        "action": "umbenennen", "id": vok["kid"], "name": "GEKAPERT"})
    assert db["verbindung"].execute(
        "SELECT name FROM vokabel_kapitel WHERE id=?", (vok["kid"],)).fetchone()["name"] == "Unit 5"


def test_empfaenger_kann_nicht_weiterteilen(client, vok, db):
    """Sonst könnte eine Freigabe unbemerkt weiterwandern - der Eigentümer
    wüsste nicht mehr, wer sein Kapitel sieht."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    client.post(f"/a/vokabeln/{vok['tokens']['TestKind']}/kapitel", data={
        "action": "teilen", "id": vok["kid"], "mit_user_ids": [str(vok["dritter"])]})
    empfaenger_liste = [r["user_id"] for r in db["verbindung"].execute(
        "SELECT user_id FROM vokabel_kapitel_freigabe WHERE kapitel_id=?", (vok["kid"],))]
    assert vok["dritter"] not in empfaenger_liste


def test_dritter_sieht_nichts(client, vok, db):
    """Freigabe gilt genau für die gewählte Person, nicht für alle."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestEltern']}/").get_data(as_text=True)
    assert "house" not in seite


# --- Aufheben --------------------------------------------------------------

def test_freigabe_aufheben_entzieht_den_zugriff(client, vok, db):
    """„bis das Teilen aufgehoben wird" - der Kern der Zusage."""
    _teilen(db, vok["kid"], vok["empfaenger"])
    assert "house" in client.get(
        f"/a/vokabeln/{vok['tokens']['TestKind']}/").get_data(as_text=True)

    # Der Eigentümer nimmt alle Haken heraus
    client.post(f"/a/vokabeln/{vok['tokens']['TestAdmin']}/kapitel", data={
        "action": "teilen", "id": vok["kid"]})

    seite = client.get(f"/a/vokabeln/{vok['tokens']['TestKind']}/").get_data(as_text=True)
    assert "house" not in seite
    assert client.get(
        f"/a/vokabeln/{vok['tokens']['TestKind']}/wort/{vok['vids'][0]}/audio"
    ).status_code == 404


def test_besitzer_kann_ueber_die_oberflaeche_teilen(client, vok, db):
    client.post(f"/a/vokabeln/{vok['tokens']['TestAdmin']}/kapitel", data={
        "action": "teilen", "id": vok["kid"], "mit_user_ids": [str(vok["empfaenger"])]})
    empfaenger_liste = [r["user_id"] for r in db["verbindung"].execute(
        "SELECT user_id FROM vokabel_kapitel_freigabe WHERE kapitel_id=?", (vok["kid"],))]
    assert empfaenger_liste == [vok["empfaenger"]]


def test_geloeschtes_kapitel_raeumt_die_freigabe_mit_ab(vok, db):
    _teilen(db, vok["kid"], vok["empfaenger"])
    v = db["verbindung"]
    v.execute("PRAGMA foreign_keys=ON")
    v.execute("DELETE FROM vokabel_kapitel WHERE id=?", (vok["kid"],))
    v.commit()
    assert v.execute("SELECT COUNT(*) c FROM vokabel_kapitel_freigabe").fetchone()["c"] == 0
