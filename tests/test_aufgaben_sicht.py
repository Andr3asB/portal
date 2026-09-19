"""Aufgaben (neu), Schritt 1 - Sichtbarkeit (Spezifikation 3.1).

Eine Aufgabe ist sichtbar, wenn man sie angelegt hat, ein Termin einem
zugewiesen ist, `sicht='alle'`, `sicht='eltern'` mit Rolle eltern oder
`sicht='kinder'` mit Rolle kind. `sicht='ich'` oeffnet nichts darueber hinaus -
auch nicht fuer Eltern oder Admin (Entscheidung 7: privat heisst privat).
Gaeste sehen nur `alle`.

Es gibt genau EINE Sichtbarkeitsfunktion (`sichtbare_termine`); Zaehler und
Routen bauen darauf auf. Diese Tests pruefen sie je Rolle und Stufe.
"""
import pytest
from teile.aufgaben import (
    AufgabenFehler,
    aufgabe_neu,
    aufgabe_sichtbar,
    sichtbare_aufgaben,
    sichtbare_termine,
    termin_sichtbar,
)


@pytest.fixture()
def familie(app, db):
    """conftest: TestAdmin (eltern, is_admin), TestKind (kind), TestEltern
    (eltern). Dazu ein zweites Kind und ein Gast, damit jede Stufe ein
    Gegenueber hat."""
    v = db["verbindung"]
    f = {name: dict(daten) for name, daten in db["familie"].items()}
    for name, rolle in (("Kind2", "kind"), ("Gast", "gast")):
        uid = v.execute("INSERT INTO users(name, farbe, is_admin, rolle) VALUES(?,?,0,?) RETURNING id",
                        (name, "#444444", rolle)).fetchone()["id"]
        f[name] = {"id": uid, "rolle": rolle, "is_admin": 0}
    v.commit()
    nutzer = {}
    for name, daten in f.items():
        nutzer[name] = v.execute("SELECT * FROM users WHERE id=?", (daten["id"],)).fetchone()
    return {"v": v, "n": nutzer}


def _ids(zeilen):
    return {z["id"] for z in zeilen}


def test_jede_sichtstufe_je_rolle(app, familie):
    v, n = familie["v"], familie["n"]
    with app.app_context():
        alle    = aufgabe_neu(v, n["TestEltern"], "Alle sehen das", sicht="alle", push=False)
        eltern  = aufgabe_neu(v, n["TestEltern"], "Nur Eltern", sicht="eltern", push=False)
        kinder  = aufgabe_neu(v, n["TestKind"],   "Nur Kinder", sicht="kinder", push=False)
        ich_k   = aufgabe_neu(v, n["TestKind"],   "Nur ich (Kind)", sicht="ich", push=False)
        ich_e   = aufgabe_neu(v, n["TestEltern"], "Nur ich (Eltern)", sicht="ich", push=False)

    def sieht(name):
        return {z["aufgabe_id"] for z in sichtbare_termine(v, n[name])}

    a = {k: r["aufgabe_id"] for k, r in
         (("alle", alle), ("eltern", eltern), ("kinder", kinder), ("ich_k", ich_k), ("ich_e", ich_e))}

    assert sieht("TestEltern") == {a["alle"], a["eltern"], a["ich_e"]}
    assert sieht("TestKind")   == {a["alle"], a["kinder"], a["ich_k"]}
    assert sieht("Kind2")      == {a["alle"], a["kinder"]}
    assert sieht("Gast")       == {a["alle"]}
    # Admin ohne Sonderrecht: TestAdmin hat Rolle eltern UND is_admin=1 -
    # sieht genau das, was Eltern sehen, nicht die privaten Dinge der Kinder.
    assert sieht("TestAdmin")  == {a["alle"], a["eltern"]}


def test_zuweisung_oeffnet_den_einen_termin(app, familie):
    """'Nur ich' des Elternteils mit Ziel Kind wird vom Server abgelehnt (Ziel
    muss sehen duerfen); 'Nur Eltern' fuer ein Kind ebenso. Zulaessig ist die
    Zuweisung innerhalb der Sicht - dann sieht das Kind genau diesen Termin."""
    v, n = familie["v"], familie["n"]
    with app.app_context():
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, n["TestEltern"], "Geheim", sicht="ich",
                        ziel_user=n["TestKind"]["id"], push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, n["TestEltern"], "Elternding", sicht="eltern",
                        ziel_user=n["TestKind"]["id"], push=False)
        with pytest.raises(AufgabenFehler):
            aufgabe_neu(v, n["TestEltern"], "Kinderding an Gruppe alle", sicht="kinder",
                        ziel_gruppe="alle", push=False)
        ok = aufgabe_neu(v, n["TestEltern"], "Zimmer", sicht="kinder",
                         ziel_user=n["TestKind"]["id"], push=False)
    assert termin_sichtbar(v, n["TestKind"], ok["termin_id"]) is not None
    assert termin_sichtbar(v, n["Kind2"], ok["termin_id"]) is not None   # sicht kinder
    assert termin_sichtbar(v, n["Gast"], ok["termin_id"]) is None


def test_unsichtbar_und_nicht_vorhanden_sind_gleich(app, familie):
    """Grundlage der 404-vor-403-Regel: fuer die Route ist beides None."""
    v, n = familie["v"], familie["n"]
    with app.app_context():
        privat = aufgabe_neu(v, n["TestKind"], "Tagebuch", sicht="ich", push=False)
    assert termin_sichtbar(v, n["TestEltern"], privat["termin_id"]) is None
    assert termin_sichtbar(v, n["TestEltern"], 999999) is None
    assert aufgabe_sichtbar(v, n["TestAdmin"], privat["aufgabe_id"]) is None
    assert aufgabe_sichtbar(v, n["TestKind"], privat["aufgabe_id"]) is not None


def test_private_termine_fehlen_in_fremden_zaehlern(app, familie):
    """Wer zaehlt, zaehlt ueber sichtbare_termine - private Aufgaben anderer
    tauchen in keiner Summe des Betrachters auf."""
    v, n = familie["v"], familie["n"]
    with app.app_context():
        aufgabe_neu(v, n["TestKind"], "Privat 1", sicht="ich", push=False)
        aufgabe_neu(v, n["TestKind"], "Privat 2", sicht="ich", push=False)
        aufgabe_neu(v, n["TestKind"], "Oeffentlich", sicht="alle", push=False)
    kind_id = n["TestKind"]["id"]
    assert len(sichtbare_termine(v, n["TestEltern"], user_id=kind_id)) == 1
    assert len(sichtbare_termine(v, n["TestKind"], user_id=kind_id)) == 3


def test_filter_status_tag_und_frei(app, familie):
    v, n = familie["v"], familie["n"]
    with app.app_context():
        heute = aufgabe_neu(v, n["TestEltern"], "Heute", wann="heute", push=False)
        geparkt = aufgabe_neu(v, n["TestEltern"], "Irgendwann", wann="geparkt", push=False)
        gruppe = aufgabe_neu(v, n["TestEltern"], "Altglas", ziel_gruppe="alle", push=False)
    e = n["TestEltern"]
    assert _ids(sichtbare_termine(v, e, status="geparkt")) == {geparkt["termin_id"]}
    assert _ids(sichtbare_termine(v, e, frei=True)) == {gruppe["termin_id"]}
    assert heute["termin_id"] in _ids(sichtbare_termine(v, e, status=("offen", "erledigt")))
    assert geparkt["termin_id"] not in _ids(sichtbare_termine(v, e, status="offen"))
    assert len(sichtbare_aufgaben(v, e)) == 3


def test_gast_kann_nichts_anlegen(app, familie):
    from teile.aufgaben import Verboten
    with app.app_context(), pytest.raises(Verboten):
        aufgabe_neu(familie["v"], familie["n"]["Gast"], "Versuch", push=False)
