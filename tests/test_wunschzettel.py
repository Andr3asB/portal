"""Wunsch #251: Gemeinsamer Wunschzettel für die Familie.

Die App selbst ist klein (erfassen, sehen, löschen, reservieren) - die
wichtigste Zusage ist die Überraschungs-Regel: **Der Wünschende erfährt
nicht, ob und von wem ein Wunsch reserviert ist.** Durchgesetzt in der
Route (die Felder verlassen den Server für ihn gar nicht), deshalb wird
hier das gerenderte HTML des Wünschenden auf ABWESENHEIT geprüft.
"""
import pytest


@pytest.fixture()
def wz(app, db):
    """Alle drei Familienmitglieder bekommen den Wunschzettel."""
    from teile.kern import new_token, token_lookup

    v = db["verbindung"]
    with app.app_context():
        app_row = v.execute("SELECT id FROM apps WHERE slug='wunschzettel'").fetchone()
        assert app_row is not None, "App-Slug 'wunschzettel' fehlt im Seed"
        zugang = {}
        for name in ("TestAdmin", "TestKind", "TestEltern"):
            klartext = new_token()
            v.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                (db["familie"][name]["id"], app_row["id"], token_lookup(klartext)),
            )
            zugang[name] = klartext
        v.commit()
    return {"v": v, "tokens": zugang, "familie": db["familie"]}


def _neu(client, wz, wer, text, link=None):
    daten = {"text": text}
    if link is not None:
        daten["link"] = link
    client.post(f"/a/wunschzettel/{wz['tokens'][wer]}/neu", data=daten)
    return wz["v"].execute(
        "SELECT id FROM wunschzettel ORDER BY id DESC LIMIT 1").fetchone()["id"]


def _seite(client, wz, wer):
    return client.get(f"/a/wunschzettel/{wz['tokens'][wer]}/").get_data(as_text=True)


def test_braucht_grant(client):
    assert client.get("/a/wunschzettel/kein-echter-token/").status_code == 403


def test_wunsch_erscheint_bei_allen(client, wz):
    _neu(client, wz, "TestKind", "Lego Raumstation")
    assert "Lego Raumstation" in _seite(client, wz, "TestKind")
    assert "Lego Raumstation" in _seite(client, wz, "TestEltern")


def test_wuenschender_sieht_die_reservierung_nicht(client, wz):
    """Die Überraschungs-Regel. `resv-` kommt nur an fremden Wünschen vor -
    auf der Seite des Wünschenden (der sonst nichts hat) darf es nach der
    Reservierung durch ein anderes Mitglied nirgends auftauchen."""
    wid = _neu(client, wz, "TestKind", "Kopfhörer")
    client.post(f"/a/wunschzettel/{wz['tokens']['TestEltern']}/{wid}/reservieren")
    assert wz["v"].execute(
        "SELECT reserviert_von FROM wunschzettel WHERE id=?", (wid,)
    ).fetchone()[0] == wz["familie"]["TestEltern"]["id"]

    seite = _seite(client, wz, "TestKind")
    # 'id="resv-' statt 'resv-': CSS-Klassen und die JS-Festtexte stehen
    # immer in der Seite - GERENDERT werden Reservierungs-Elemente nur an
    # fremden Wünschen. Entscheidend ist, dass weder ein Element noch der
    # Name des Reservierers auftaucht.
    assert 'id="resv-' not in seite
    assert "Wird schon besorgt" not in seite
    assert "TestEltern" not in seite


def test_die_anderen_sehen_die_reservierung(client, wz):
    wid = _neu(client, wz, "TestKind", "Kopfhörer")
    client.post(f"/a/wunschzettel/{wz['tokens']['TestEltern']}/{wid}/reservieren")
    assert "Von dir reserviert" in _seite(client, wz, "TestEltern")
    dritte = _seite(client, wz, "TestAdmin")
    assert "Wird schon besorgt" not in dritte      # Admin sieht den Freigabe-Knopf
    assert "Reserviert: TestEltern" in dritte


def test_wuenschender_kann_nicht_reservieren(client, wz):
    wid = _neu(client, wz, "TestKind", "Buch")
    r = client.post(f"/a/wunschzettel/{wz['tokens']['TestKind']}/{wid}/reservieren")
    assert r.status_code == 403


def test_fremde_reservierung_ist_unantastbar(client, wz):
    """Wer fremde Reservierungen umwerfen könnte, machte die Absprache
    wertlos - nur der Reservierer selbst (oder Admin) gibt frei."""
    wid = _neu(client, wz, "TestAdmin", "Werkzeugkoffer")
    client.post(f"/a/wunschzettel/{wz['tokens']['TestEltern']}/{wid}/reservieren")
    r = client.post(f"/a/wunschzettel/{wz['tokens']['TestKind']}/{wid}/reservieren")
    assert r.status_code == 403
    # Der Reservierer selbst darf zurückziehen.
    client.post(f"/a/wunschzettel/{wz['tokens']['TestEltern']}/{wid}/reservieren")
    assert wz["v"].execute(
        "SELECT reserviert_von FROM wunschzettel WHERE id=?", (wid,)
    ).fetchone()[0] is None


def test_reservieren_antwortet_der_seite_mit_json(client, wz):
    """Wunsch #171-Muster: mit Accept-Kopf JSON für die Stelle, ohne ihn
    Weiterleitung."""
    wid = _neu(client, wz, "TestKind", "Puzzle")
    r = client.post(
        f"/a/wunschzettel/{wz['tokens']['TestEltern']}/{wid}/reservieren",
        headers={"Accept": "application/json"})
    d = r.get_json()
    assert d["ok"] and d["reserviert"] and d["id"] == wid


def test_loeschen_nur_selbst_oder_admin(client, wz):
    wid = _neu(client, wz, "TestEltern", "Gutschein")
    assert client.post(
        f"/a/wunschzettel/{wz['tokens']['TestKind']}/{wid}/loeschen"
    ).status_code == 403
    client.post(f"/a/wunschzettel/{wz['tokens']['TestAdmin']}/{wid}/loeschen")
    assert wz["v"].execute(
        "SELECT COUNT(*) FROM wunschzettel WHERE id=?", (wid,)).fetchone()[0] == 0


def test_bearbeiten_darf_nur_der_wuenschende(client, wz):
    """Auch kein Admin: Auf einem fremden Zettel formuliert niemand Wünsche
    um."""
    wid = _neu(client, wz, "TestKind", "Roller")
    r = client.post(
        f"/a/wunschzettel/{wz['tokens']['TestAdmin']}/{wid}/bearbeiten",
        data={"text": "Anderer Text"})
    assert r.status_code == 403
    client.post(
        f"/a/wunschzettel/{wz['tokens']['TestKind']}/{wid}/bearbeiten",
        data={"text": "Roller, blau", "link": "https://example.org/roller"})
    zeile = wz["v"].execute(
        "SELECT text, link FROM wunschzettel WHERE id=?", (wid,)).fetchone()
    assert zeile["text"] == "Roller, blau"
    assert zeile["link"] == "https://example.org/roller"


def test_nur_echte_web_links_werden_gespeichert(client, wz):
    """`javascript:` im href wäre trotz CSP ein vermeidbares Loch - alles
    außer http(s) wird verworfen, nicht repariert."""
    _neu(client, wz, "TestKind", "Spiel", link="javascript:alert(1)")
    assert wz["v"].execute(
        "SELECT link FROM wunschzettel ORDER BY id DESC LIMIT 1"
    ).fetchone()[0] is None
    _neu(client, wz, "TestKind", "Spiel 2", link="https://example.org/spiel")
    assert wz["v"].execute(
        "SELECT link FROM wunschzettel ORDER BY id DESC LIMIT 1"
    ).fetchone()[0] == "https://example.org/spiel"


def test_leerer_text_legt_nichts_an(client, wz):
    client.post(f"/a/wunschzettel/{wz['tokens']['TestKind']}/neu",
                data={"text": "   "})
    assert wz["v"].execute("SELECT COUNT(*) FROM wunschzettel").fetchone()[0] == 0
