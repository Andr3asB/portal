"""Wunsch #222: Ausfallprotokoll fürs Auto, für die Werkstatt.

Der Wunsch enthält einen Satz, der den ganzen Aufbau bestimmt:

> „Wichtig wäre das die GPS Position und die Uhrzeit vom ersten Knopfdruck
> gezogen wird und nicht erst mal speichern der Notiz."

Deshalb entsteht der Eintrag beim Knopfdruck – und **nur** der. Ort und Notiz
kommen danach dazu. Die beiden Tests, auf die es hier ankommt, sind
`test_ohne_ort_entsteht_der_eintrag_trotzdem` und
`test_gespeichert_wird_vor_der_ortung`: Ein Protokoll, das einen Ausfall
verschluckt, weil die Ortung zickt oder jemand im Auto abgelenkt wird, ist
für die Werkstatt wertlos – und der Fehler fiele erst auf, wenn man die
Zahlen braucht.

Der zweite Schwerpunkt ist, wer was darf. Alle mit der App sehen alles (der
Wunsch verlangt ausdrücklich „alle Einträge im log inklusive des Benutzers");
ändern darf nur, wer gemeldet hat – oder ein Admin.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
AUSFAELLE = TPL / "ausfaelle.html"


@pytest.fixture()
def app_tokens(app, db):
    """Alle drei aus der Testfamilie bekommen die App."""
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    tokens = {}
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='ausfaelle'").fetchone()["id"]
        for name, daten in db["familie"].items():
            klartext = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext
    v.commit()
    return tokens


def _melden(client, token):
    antwort = client.post(f"/a/ausfaelle/{token}/melden")
    assert antwort.status_code == 200, antwort.status_code
    return antwort.get_json()


# ── Der Knopfdruck ─────────────────────────────────────────────────────────

def test_die_app_ist_registriert(db):
    zeile = db["verbindung"].execute(
        "SELECT name, emoji FROM apps WHERE slug='ausfaelle'").fetchone()
    assert zeile, "App-Slug fehlt in _CORE_APPS"
    assert zeile["emoji"]


def test_ein_druck_legt_sofort_einen_eintrag_an(client, db, app_tokens):
    daten = _melden(client, app_tokens["TestAdmin"])
    assert daten["ok"] and daten["id"]

    zeile = db["verbindung"].execute(
        "SELECT * FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["user_id"] == db["familie"]["TestAdmin"]["id"]
    assert zeile["zeitpunkt"], "Kein Zeitpunkt gesetzt"


def test_ohne_ort_entsteht_der_eintrag_trotzdem(client, db, app_tokens):
    """Der wichtigste Test der Datei. Ortung kann abgelehnt werden, Sekunden
    dauern oder in der Tiefgarage gar nicht klappen - der Ausfall ist trotzdem
    passiert und muss im Protokoll stehen."""
    daten = _melden(client, app_tokens["TestAdmin"])
    zeile = db["verbindung"].execute(
        "SELECT lat, lon, notiz FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["lat"] is None and zeile["lon"] is None
    assert zeile["notiz"] is None

    seite = client.get(f"/a/ausfaelle/{app_tokens['TestAdmin']}/").get_data(as_text=True)
    assert f'id="eintrag-{daten["id"]}"' in seite
    assert "kein Ort erfasst" in seite


def test_die_zeit_kommt_vom_server_nicht_vom_browser(client, db, app_tokens):
    """Sonst könnte eine falsch gestellte Handy-Uhr ein Protokoll
    verfälschen, das später jemand in der Werkstatt vorlegt."""
    daten = client.post(f"/a/ausfaelle/{app_tokens['TestAdmin']}/melden",
                        json={"zeitpunkt": "1999-01-01 00:00:00"}).get_json()
    zeile = db["verbindung"].execute(
        "SELECT zeitpunkt FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert not zeile["zeitpunkt"].startswith("1999")


# ── Die Ortung danach ──────────────────────────────────────────────────────

def test_der_ort_laesst_sich_nachtragen(client, db, app_tokens):
    daten = _melden(client, app_tokens["TestAdmin"])
    antwort = client.post(f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/position",
                          json={"lat": 48.3705, "lon": 10.8978, "genauigkeit": 12.5})
    assert antwort.status_code == 200 and antwort.get_json()["ok"]

    zeile = db["verbindung"].execute(
        "SELECT lat, lon, genauigkeit FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert round(zeile["lat"], 4) == 48.3705
    assert round(zeile["lon"], 4) == 10.8978
    assert zeile["genauigkeit"] == 12.5


def test_ein_zweiter_ort_ueberschreibt_den_ersten_nicht(client, db, app_tokens):
    """Der erste Messwert gehört zum Knopfdruck. Ein späterer (zweiter Tab,
    ungenauere Nachmessung) darf ihn nicht verdrängen."""
    daten = _melden(client, app_tokens["TestAdmin"])
    pfad = f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/position"
    client.post(pfad, json={"lat": 48.3705, "lon": 10.8978})
    client.post(pfad, json={"lat": 0.0, "lon": 0.0})

    zeile = db["verbindung"].execute(
        "SELECT lat FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert round(zeile["lat"], 4) == 48.3705


@pytest.mark.parametrize("nutzlast", [
    {"lat": 91, "lon": 10},              # ausserhalb des Wertebereichs
    {"lat": 48, "lon": 181},
    {"lat": "hier", "lon": "dort"},      # gar keine Zahl
    {"lon": 10},                         # halbe Angabe
    {},
])
def test_unmoegliche_koordinaten_werden_abgelehnt(client, db, app_tokens, nutzlast):
    """Eine unmögliche Koordinate wäre schlimmer als gar keine - sie sieht
    aus wie eine Angabe."""
    daten = _melden(client, app_tokens["TestAdmin"])
    antwort = client.post(
        f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/position", json=nutzlast)
    assert antwort.status_code == 400

    zeile = db["verbindung"].execute(
        "SELECT lat, lon FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["lat"] is None and zeile["lon"] is None


# ── Die Notiz danach ───────────────────────────────────────────────────────

def test_die_notiz_kommt_hinterher(client, db, app_tokens):
    daten = _melden(client, app_tokens["TestAdmin"])
    client.post(f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/notiz",
                data={"notiz": "Radio aus, Rückfahrkamera schwarz"})
    zeile = db["verbindung"].execute(
        "SELECT notiz FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["notiz"] == "Radio aus, Rückfahrkamera schwarz"


def test_leere_notiz_wird_zu_nichts(client, db, app_tokens):
    """Sonst stünde eine leere Zeichenkette in der Datenbank und die Anzeige
    müsste beides unterscheiden."""
    daten = _melden(client, app_tokens["TestAdmin"])
    pfad = f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/notiz"
    client.post(pfad, data={"notiz": "erst was"})
    client.post(pfad, data={"notiz": "   "})
    zeile = db["verbindung"].execute(
        "SELECT notiz FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["notiz"] is None


# ── Wer darf was ───────────────────────────────────────────────────────────

def test_alle_sehen_alle_eintraege_mit_melder(client, db, app_tokens):
    """„In der App soll dann möglich sein, alle Einträge im log inklusive des
    Benutzers zu sehen" - wörtlich aus dem Wunsch."""
    _melden(client, app_tokens["TestAdmin"])
    seite = client.get(f"/a/ausfaelle/{app_tokens['TestEltern']}/").get_data(as_text=True)
    assert "TestAdmin" in seite


def test_fremde_notiz_bleibt_unangetastet(client, db, app_tokens):
    daten = _melden(client, app_tokens["TestAdmin"])
    antwort = client.post(f"/a/ausfaelle/{app_tokens['TestEltern']}/{daten['id']}/notiz",
                          data={"notiz": "GEKAPERT"})
    assert antwort.status_code == 403
    zeile = db["verbindung"].execute(
        "SELECT notiz FROM ausfaelle WHERE id=?", (daten["id"],)).fetchone()
    assert zeile["notiz"] is None


def test_fremden_eintrag_kann_niemand_loeschen(client, db, app_tokens):
    daten = _melden(client, app_tokens["TestAdmin"])
    antwort = client.post(f"/a/ausfaelle/{app_tokens['TestEltern']}/{daten['id']}/loeschen")
    assert antwort.status_code == 403
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM ausfaelle").fetchone()["c"] == 1


def test_der_admin_darf_aufraeumen(client, db, app_tokens):
    """Ein Fehldruck von jemand anderem muss sich entfernen lassen - sonst
    steht ein Ausfall im Protokoll, den es nie gab."""
    daten = _melden(client, app_tokens["TestEltern"])
    client.post(f"/a/ausfaelle/{app_tokens['TestAdmin']}/{daten['id']}/loeschen")
    assert db["verbindung"].execute(
        "SELECT COUNT(*) c FROM ausfaelle").fetchone()["c"] == 0


def test_ohne_grant_kein_zugriff(client, db, app_tokens):
    """Gegenprobe zur Freigabe: Der Token einer anderen App zieht hier nicht."""
    fremd = db["familie"]["TestKind"]["tokens"]["einkauf"]
    assert client.get(f"/a/ausfaelle/{fremd}/").status_code == 403
    assert client.post(f"/a/ausfaelle/{fremd}/melden").status_code == 403


def test_die_app_geht_an_eltern_nicht_an_kinder(app, db):
    """Ein Kind, das den grossen roten Knopf findet, trägt Ausfälle ein, die
    es nicht gab - und der Ausdruck für die Werkstatt ist genau dann wertlos,
    wenn er angezweifelt werden kann."""
    from teile.kern import _auto_grant_all
    v = db["verbindung"]
    v.execute("DELETE FROM grants WHERE app_id=(SELECT id FROM apps WHERE slug='ausfaelle')")
    v.commit()

    with app.app_context():
        from teile.kern import get_db
        _auto_grant_all(get_db(), "ausfaelle", rollen=("eltern",))
        get_db().commit()

    hat = {r["rolle"] for r in v.execute("""
        SELECT u.rolle FROM grants g
        JOIN users u ON u.id = g.user_id
        WHERE g.app_id = (SELECT id FROM apps WHERE slug='ausfaelle')""")}
    assert "eltern" in hat
    assert "kind" not in hat


# ── Der Ablauf im Browser ──────────────────────────────────────────────────

def test_gespeichert_wird_vor_der_ortung():
    """Der Kern des Wunsches, und nur hier prüfbar: Der Aufruf von `/melden`
    darf NICHT in der Geolocation-Rückmeldung stehen. Stünde er dort, ginge
    jeder Ausfall verloren, bei dem die Ortung scheitert oder zu lange
    braucht – und genau das ist im Auto der Normalfall, nicht die Ausnahme.

    Gegenprobe beim Schreiben gemacht: verschiebt man den fetch in den
    getCurrentPosition-Rückruf, schlägt der Test an."""
    quelle = AUSFAELLE.read_text(encoding="utf-8")
    melden_pos = quelle.index("melden`")
    ortung_pos = quelle.index("getCurrentPosition")
    assert melden_pos < ortung_pos, (
        "Der Eintrag wird erst nach der Ortung angelegt - dann geht er "
        "verloren, sobald die Ortung scheitert.")


def test_die_ortung_hat_eine_zeitgrenze():
    """Ohne `timeout` wartet getCurrentPosition unter Umständen endlos, und
    die Seite lädt nie neu - der Eintrag sähe für den Nutzer aus wie nicht
    gespeichert."""
    quelle = AUSFAELLE.read_text(encoding="utf-8")
    assert re.search(r"timeout:\s*\d+", quelle)


def test_das_loeschen_fragt_nach():
    """Projektkonvention: jedes echte Löschen fragt vorher (Wunsch #142)."""
    quelle = AUSFAELLE.read_text(encoding="utf-8")
    block = re.search(r'action="[^"]*loeschen"[^>]*', quelle).group(0)
    assert "data-bestaetigen=" in block


def test_jede_verdrahtete_aktion_existiert_auch():
    """Ein Tippfehler im data-klick ergibt einen Knopf, der still nichts tut."""
    quelle = AUSFAELLE.read_text(encoding="utf-8")
    for name in set(re.findall(r'data-(?:klick|aendern|eingabe)="(\w+)"', quelle)):
        assert re.search(r"function\s+%s\s*\(" % re.escape(name), quelle), name
