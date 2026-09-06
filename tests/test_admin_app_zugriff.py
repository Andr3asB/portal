"""Wunsch #266: Mitgliederliste und App-Zugriff sind getrennte Seiten.

Die Verwaltung zeigte je Mitglied alle Apps als Chips - bei inzwischen 20
Apps war das keine Uebersicht mehr. Jetzt: die Liste zeigt nur die Zahl,
`/user/<id>/apps` die Apps eines Mitglieds in zwei Gruppen mit Beschreibung,
`/apps` alles auf einmal als Tabelle. Die grant/revoke-Routen sind
unveraendert und leiten dorthin zurueck, woher der Klick kam - aber nur auf
Admin-Pfade (das Feld kommt aus dem Formular, also vom Client).
"""


def _apps(db):
    return {r["slug"]: r["id"] for r in db["verbindung"].execute("SELECT slug, id FROM apps")}


def test_die_uebersicht_zeigt_nur_die_zahl(client, admin, kind):
    seite = client.get(f"/a/admin/{admin['tokens']['admin']}/").get_data(as_text=True)
    assert "grant-chip" not in seite, "die Chips sind von der Uebersicht verschwunden"
    assert "von" in seite and "Apps</div>" in seite
    assert f"/user/{kind['id']}/apps\"" in seite, "je Mitglied ein Apps-Knopf"
    assert "/apps\">🧩 App-Zugriff" in seite, "die Tabelle oben im Kopf"
    # home zaehlt nicht mit: das Kind hat home, hilfe, einkauf -> 2 Apps
    assert "2 von" in seite


def test_seite_eines_mitglieds_in_zwei_gruppen(client, admin, kind):
    seite = client.get(f"/a/admin/{admin['tokens']['admin']}/user/{kind['id']}/apps").get_data(as_text=True)
    assert "TestKind" in seite
    frei = seite[seite.index("Freigeschaltet</h2>"):seite.index("Nicht freigeschaltet</h2>")]
    gesperrt = seite[seite.index("Nicht freigeschaltet</h2>"):]
    assert "/revoke/einkauf" in frei and "/revoke/hilfe" in frei
    assert "/grant/todo" in gesperrt and "/grant/admin" in gesperrt
    assert "/grant/home" not in seite and "/revoke/home" not in seite
    assert 'name="zurueck"' in seite and f"/user/{kind['id']}/apps\"" in seite


def test_unbekanntes_mitglied_404(client, admin):
    assert client.get(f"/a/admin/{admin['tokens']['admin']}/user/99999/apps").status_code == 404


def test_schalten_fuehrt_auf_die_seite_zurueck(client, admin, kind, db):
    token = admin["tokens"]["admin"]
    apps = _apps(db)
    r = client.post(f"/a/admin/{token}/user/{kind['id']}/grant/todo",
                    data={"zurueck": f"/a/admin/{token}/user/{kind['id']}/apps"})
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/user/{kind['id']}/apps")
    assert db["verbindung"].execute("SELECT 1 FROM grants WHERE user_id=? AND app_id=?",
                                    (kind["id"], apps["todo"])).fetchone()
    r = client.post(f"/a/admin/{token}/user/{kind['id']}/revoke/todo",
                    data={"zurueck": f"/a/admin/{token}/apps"})
    assert r.headers["Location"].endswith("/apps")
    assert not db["verbindung"].execute("SELECT 1 FROM grants WHERE user_id=? AND app_id=?",
                                        (kind["id"], apps["todo"])).fetchone()


def test_ohne_oder_mit_fremdem_ziel_geht_es_zur_uebersicht(client, admin, kind):
    token = admin["tokens"]["admin"]
    r = client.post(f"/a/admin/{token}/user/{kind['id']}/grant/todo")
    assert r.headers["Location"].rstrip("/").endswith(f"/a/admin/{token}")
    for boese in ("https://boese.example/", "//boese.example/a/admin/", "/p/x", "/a/admin/\\boese"):
        r = client.post(f"/a/admin/{token}/user/{kind['id']}/revoke/todo", data={"zurueck": boese})
        assert r.headers["Location"].rstrip("/").endswith(f"/a/admin/{token}"), boese


def test_tabelle_zeigt_alle_apps_und_mitglieder(client, admin, kind, eltern, db):
    token = admin["tokens"]["admin"]
    seite = client.get(f"/a/admin/{token}/apps").get_data(as_text=True)
    for name in ("TestAdmin", "TestKind", "TestEltern"):
        assert name in seite
    slugs = [r["slug"] for r in db["verbindung"].execute("SELECT slug FROM apps WHERE slug != 'home'")]
    for slug in slugs:
        assert f"/grant/{slug}" in seite or f"/revoke/{slug}" in seite, slug
    assert "/grant/home" not in seite
    # Das Kind hat einkauf: ein Abschalt-Knopf mit Namen
    assert f"/user/{kind['id']}/revoke/einkauf" in seite
    assert 'aria-label="Einkauf' in seite or "für TestKind abschalten" in seite
    # Der eigene Verwaltungszugang ist gesperrt, nicht schaltbar
    assert f"/user/{admin['id']}/revoke/admin" not in seite
    assert "nicht abschaltbar" in seite


def test_eigener_verwaltungszugang_bleibt_auch_per_post(client, admin, db):
    token = admin["tokens"]["admin"]
    apps = _apps(db)
    client.post(f"/a/admin/{token}/user/{admin['id']}/revoke/admin", data={"zurueck": f"/a/admin/{token}/apps"})
    assert db["verbindung"].execute("SELECT 1 FROM grants WHERE user_id=? AND app_id=?",
                                    (admin["id"], apps["admin"])).fetchone()


def test_nur_admins(client, kind):
    for pfad in ("/apps", f"/user/{kind['id']}/apps"):
        r = client.get(f"/a/admin/{kind['tokens']['hilfe']}{pfad}")
        assert r.status_code == 403, pfad
