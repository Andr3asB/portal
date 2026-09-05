"""Wunsch #234: Laenger als 7 Tage Gepacktes verschwindet aus der Ansicht.

Waehrend der Reise ist der Gepackt-Abschnitt nuetzlich, Wochen danach nur
noch Ballast. Ausgeblendet heisst: nicht gerendert - geloescht wird nichts,
`?gepackt=alle` und der Zaehl-Link holen alles zurueck.
"""
import pytest
from teile.kern import new_token, token_lookup


@pytest.fixture()
def liste(app, db):
    v = db["verbindung"]
    familie = db["familie"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='packliste'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (familie["TestAdmin"]["id"], app_id, token_lookup(klartext)))
    zid = v.execute(
        "INSERT INTO packlisten_ziele(name) VALUES('Sommerurlaub') RETURNING id"
    ).fetchone()["id"]
    kid = v.execute("SELECT id FROM packlisten_kategorien LIMIT 1").fetchone()["id"]
    v.commit()
    return {"token": klartext, "ziel": zid, "kategorie": kid}


def _eintrag(v, liste, name, gepackt_vor_tagen=None):
    gepackt_am = (None if gepackt_vor_tagen is None
                  else f"datetime('now', '-{gepackt_vor_tagen} days')")
    v.execute(
        "INSERT INTO packlisten_eintraege(name, ziel_id, kategorie_id, gepackt, gepackt_am) "
        f"VALUES(?,?,?,?, {gepackt_am or 'NULL'})",
        (name, liste["ziel"], liste["kategorie"], 0 if gepackt_vor_tagen is None else 1))
    v.commit()


def _seite(client, liste, extra=""):
    return client.get(
        f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}{extra}"
    ).get_data(as_text=True)


def test_frisch_gepacktes_bleibt_sichtbar(client, db, liste):
    _eintrag(db["verbindung"], liste, "Zahnbuerste", gepackt_vor_tagen=2)
    assert "Zahnbuerste" in _seite(client, liste)


def test_alt_gepacktes_ist_ausgeblendet_mit_hinweis(client, db, liste):
    _eintrag(db["verbindung"], liste, "Wintermuetze", gepackt_vor_tagen=10)
    seite = _seite(client, liste)
    assert "Wintermuetze" not in seite
    assert "1 vor mehr als 7 Tagen gepackte" in seite, (
        "Ohne Hinweis sieht die ausgeblendete Ware aus wie verloren."
    )


def test_gepackt_alle_holt_alles_zurueck(client, db, liste):
    _eintrag(db["verbindung"], liste, "Wintermuetze", gepackt_vor_tagen=10)
    seite = _seite(client, liste, "&gepackt=alle")
    assert "Wintermuetze" in seite
    assert "vor mehr als 7 Tagen gepackte" not in seite


def test_offene_eintraege_kennen_keine_frist(client, db, liste):
    """Nur GEPACKTES verschwindet - ein seit Wochen offener Eintrag ist eine
    Erinnerung, kein Ballast."""
    _eintrag(db["verbindung"], liste, "Reisepass")
    assert "Reisepass" in _seite(client, liste)
