"""Wunsch #250: Ausfallprotokoll als Ausdruck für die Werkstatt.

Der Kern des Wunsches ist die Kürzung der GPS-Koordinaten: Der Ausdruck soll
belegen, dass die Ausfälle wirklich unterwegs passiert sind, ohne dass sich
daraus eine Route oder Adresse ablesen lässt. Gewählt: zwei Nachkommastellen
(Raster ≈ 1,1 × 0,75 km).

Die wichtigste Prüfung hier ist deshalb eine ABWESENHEIT: Die vollen
Koordinaten dürfen im Druck-HTML nirgends auftauchen – auch nicht in einem
Attribut oder Kommentar. Gerundet wird serverseitig in der Route, die Vorlage
bekommt die vollen Werte gar nicht erst (25_ausfall.py, druck()).
"""
import pytest


@pytest.fixture()
def ausfall(app, db):
    """TestAdmin bekommt die Ausfälle-App freigeschaltet."""
    from teile.kern import new_token, token_lookup

    v = db["verbindung"]
    uid = db["familie"]["TestAdmin"]["id"]
    with app.app_context():
        app_row = v.execute("SELECT id FROM apps WHERE slug='ausfaelle'").fetchone()
        assert app_row is not None, "App-Slug 'ausfaelle' fehlt im Seed"
        klartext = new_token()
        v.execute(
            "INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
            (uid, app_row["id"], token_lookup(klartext)),
        )
        v.commit()
    return {"v": v, "token": klartext, "uid": uid}


def _eintrag(ausfall, lat=None, lon=None, notiz=None):
    ausfall["v"].execute(
        "INSERT INTO ausfaelle(user_id, lat, lon, genauigkeit, notiz) VALUES(?,?,?,?,?)",
        (ausfall["uid"], lat, lon, 12.0, notiz),
    )
    ausfall["v"].commit()


def test_druck_braucht_grant(client):
    assert client.get("/a/ausfaelle/kein-echter-token/druck").status_code == 403


def test_druck_rundet_auf_zwei_nachkommastellen(client, ausfall):
    _eintrag(ausfall, lat=48.123456, lon=10.987654, notiz="Radio schwarz")
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/druck").get_data(as_text=True)
    assert "48.12" in text and "10.99" in text


def test_volle_koordinaten_stehen_nirgends_im_druck(client, ausfall):
    """Die eigentliche Zusage des Wunsches: keine Route rekonstruierbar.
    Drei Nachkommastellen wären schon wieder ~110 m."""
    _eintrag(ausfall, lat=48.123456, lon=10.987654)
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/druck").get_data(as_text=True)
    assert "48.123" not in text
    assert "10.987" not in text
    # Auch die Genauigkeit (±12 m) gehört nicht auf den Ausdruck - neben
    # einem 1-km-Raster wäre sie nur Pseudo-Präzision.
    assert "12 m" not in text and "±" not in text


def test_eintrag_ohne_ort_bekommt_einen_strich(client, ausfall):
    _eintrag(ausfall, notiz="in der Tiefgarage")
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/druck").get_data(as_text=True)
    assert "–" in text
    assert "in der Tiefgarage" in text


def test_keine_namen_auf_dem_ausdruck(client, ausfall):
    """Die Werkstatt braucht Zeitpunkte und Häufigkeit, nicht die
    Familienmitglieder dahinter."""
    _eintrag(ausfall, lat=48.1, lon=10.9)
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/druck").get_data(as_text=True)
    assert "TestAdmin" not in text


def test_die_app_selbst_zeigt_weiter_den_vollen_ort(client, ausfall):
    """Gekürzt wird nur der Ausdruck. Die Familie sieht in der App weiterhin
    die genaue Position samt Kartensprung - dafür ist sie da."""
    _eintrag(ausfall, lat=48.123456, lon=10.987654)
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/").get_data(as_text=True)
    assert "48.12346" in text        # '%.5f'-Format der Listenansicht


def test_zahlen_stehen_auf_dem_blatt(client, ausfall):
    _eintrag(ausfall, lat=48.1, lon=10.9)
    _eintrag(ausfall)
    text = client.get(f"/a/ausfaelle/{ausfall['token']}/druck").get_data(as_text=True)
    assert "2</strong> Ausfälle insgesamt" in text
