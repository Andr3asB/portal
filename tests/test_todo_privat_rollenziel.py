"""Wunsch #214 (Sicherheitsaudit, Befund F-06): Sehen und Ändern müssen
dieselbe Grenze ziehen.

`_visible_todos` fragt nach `privat`, `_darf_erledigen` tat es nicht. Bei genau
einer Kombination liefen die beiden auseinander:

    privat=1, zugewiesen_an IS NULL, zugewiesen_rollen='kind'

Für ein Kind war dieses Todo unsichtbar - und trotzdem änderbar. Über
`POST /a/todo/status/<id>` oder `/bearbeiten/<id>` mit geratener ID liess sich
der Status setzen oder Inhalt, Ziel und das Privat-Flag überschreiben, ohne den
Inhalt je zu sehen. Kein Informationsabfluss (beide Routen enden im Redirect),
aber Manipulation an etwas, das einen nichts angeht.

Der Test prüft deshalb **beide Seiten am selben Datensatz**: unsichtbar UND
unveränderbar. Getrennt geprüft wäre der Befund wieder möglich, sobald jemand
nur eine der beiden Funktionen anfasst.
"""
import pytest

from teile.kern import token_lookup, new_token


@pytest.fixture()
def todos(app, db):
    v = db["verbindung"]
    familie = db["familie"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        tokens = {}
        for name, daten in familie.items():
            klartext = new_token()
            v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                      "VALUES(?,?,?)", (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    def anlegen(inhalt, privat, rollen, von="TestEltern", an=None):
        return v.execute("""
            INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an,
                              zugewiesen_rollen, privat, status)
            VALUES(?,?,?,?,?, 'offen') RETURNING id
        """, (inhalt, familie[von]["id"], an, rollen, privat)).fetchone()["id"]

    ids = {
        # Der Befund: privat, kein konkreter Empfaenger, Rollenziel 'kind'
        "privat_rollenziel": anlegen("Geschenk fuer das Kind besorgen", 1, "kind"),
        # Gegenprobe: dasselbe, nur nicht privat - muss weiterhin gehen
        "offen_rollenziel":  anlegen("Zimmer aufraeumen", 0, "kind"),
    }
    v.commit()
    return {"tokens": tokens, "ids": ids, "familie": familie, "v": v}


def _zeile(todos, tid):
    return todos["v"].execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()


def _status_setzen(client, token, tid, status="erledigt"):
    return client.post(f"/a/todo/{token}/status/{tid}", data={"status": status})


def _bearbeiten(client, token, tid, **felder):
    daten = {"inhalt": "GEKAPERT"}
    daten.update(felder)
    return client.post(f"/a/todo/{token}/bearbeiten/{tid}", data=daten)


# --- Der Befund -------------------------------------------------------------

def test_kind_sieht_das_private_todo_nicht(client, todos):
    """Voraussetzung des Befunds - stimmt die nicht mehr, prüft der Rest
    unten etwas anderes als gedacht."""
    seite = client.get(f"/a/todo/{todos['tokens']['TestKind']}/").get_data(as_text=True)
    assert "Geschenk fuer das Kind besorgen" not in seite


def test_kind_kann_den_status_nicht_setzen(client, todos):
    tid = todos["ids"]["privat_rollenziel"]
    antwort = _status_setzen(client, todos["tokens"]["TestKind"], tid)
    assert antwort.status_code == 403
    assert _zeile(todos, tid)["status"] == "offen"


def test_kind_kann_den_inhalt_nicht_ueberschreiben(client, todos):
    tid = todos["ids"]["privat_rollenziel"]
    _bearbeiten(client, todos["tokens"]["TestKind"], tid)
    assert _zeile(todos, tid)["inhalt"] == "Geschenk fuer das Kind besorgen"


def test_kind_kann_das_privat_flag_nicht_abraeumen(client, todos):
    """Der unangenehmste Weg: erst das Flag entfernen, dann steht es offen da."""
    tid = todos["ids"]["privat_rollenziel"]
    _bearbeiten(client, todos["tokens"]["TestKind"], tid,
                inhalt="Geschenk fuer das Kind besorgen", privat="0")
    assert _zeile(todos, tid)["privat"] == 1


# --- Die Gegenrichtung ------------------------------------------------------

def test_nicht_privates_rollenziel_geht_weiterhin(client, todos):
    """Ohne diese Prüfung wäre der sicherste Fix, die Rollenzuweisung ganz zu
    sperren - und Wunsch #39 (Todo an eine Rolle statt an eine Person) wäre
    kaputt, ohne dass es auffiele."""
    tid = todos["ids"]["offen_rollenziel"]
    antwort = _status_setzen(client, todos["tokens"]["TestKind"], tid)
    assert antwort.status_code in (302, 303)
    assert _zeile(todos, tid)["status"] == "erledigt"


def test_wer_es_sieht_darf_es_auch_aendern(client, todos):
    """Ein privates Todo, das dem Kind direkt zugewiesen ist, sieht es - und
    darf es folglich auch abhaken. Sonst hätte der Fix zu viel gesperrt."""
    v = todos["v"]
    tid = v.execute("""
        INSERT INTO todos(inhalt, erstellt_von, zugewiesen_an, privat, status)
        VALUES('Zahnarzt', ?, ?, 1, 'offen') RETURNING id
    """, (todos["familie"]["TestEltern"]["id"],
          todos["familie"]["TestKind"]["id"])).fetchone()["id"]
    v.commit()

    _status_setzen(client, todos["tokens"]["TestKind"], tid)
    assert _zeile(todos, tid)["status"] == "erledigt"


def test_eltern_kommen_weiterhin_an_alles(client, todos):
    tid = todos["ids"]["privat_rollenziel"]
    _status_setzen(client, todos["tokens"]["TestEltern"], tid)
    assert _zeile(todos, tid)["status"] == "erledigt"


# --- Gegenprobe: hängt es wirklich an dieser einen Bedingung? ---------------

def test_ohne_die_privat_bedingung_stuende_es_offen(client, todos, monkeypatch):
    """Beweist, dass die 403 oben an `_darf_erledigen` hängen und nicht an
    etwas anderem. Die alte Fassung wird für einen Test wiederhergestellt -
    per monkeypatch, damit eine abgeschwächte Prüfung nicht einmal kurz in
    einer Datei steht, in der sie jemand committen könnte."""
    import importlib
    modul = importlib.import_module("teile.04_todo")
    alt = lambda user, row: (                                    # noqa: E731
        user["is_admin"] or user["rolle"] == "eltern"
        or row["erstellt_von"] == user["id"] or row["zugewiesen_an"] == user["id"]
        or (row["zugewiesen_an"] is None and modul._rolle_passt(row, user))
    )
    monkeypatch.setattr(modul, "_darf_erledigen", alt)

    tid = todos["ids"]["privat_rollenziel"]
    _status_setzen(client, todos["tokens"]["TestKind"], tid)
    assert _zeile(todos, tid)["status"] == "erledigt", (
        "Auch mit der alten Fassung kommt das Kind nicht durch - der Test "
        "oben beweist dann nichts über _darf_erledigen."
    )
