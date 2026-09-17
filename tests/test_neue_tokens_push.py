"""Wunsch #283 (Sicherheitsaudit 16.09.2026, Befund N-04): „Zugänge neu
erzeugen" löschte Sitzungen, aber nicht die Push-Abos.

Der Notfallknopf für „Handy weg" erneuerte alle Tokens und warf alle
Sitzungen raus – das verlorene Gerät bekam trotzdem weiter jede
Benachrichtigung samt Inhalt: Aufgabentexte, Werkstatt-Rückfragen,
Geburtstage, Briefing. Sitzung und Push-Abo hängen nicht zusammen (der
Endpunkt gehört dem Browser), also können nur ALLE Abos des Nutzers weg;
die verbliebenen Geräte erlauben Push einmal neu, und der Hinweis auf der
Zugangsseite sagt das.
"""


def _abos(db, uid):
    return db["verbindung"].execute(
        "SELECT COUNT(*) FROM push_abos WHERE user_id=?", (uid,)).fetchone()[0]


def test_neue_tokens_raeumt_push_abos_des_nutzers_weg(client, db, admin, kind, eltern):
    v = db["verbindung"]
    for uid, nr in ((kind["id"], 1), (kind["id"], 2), (eltern["id"], 3)):
        v.execute("INSERT INTO push_abos(user_id, endpoint, p256dh, auth, geraet) "
                  "VALUES(?,?,?,?,?)", (uid, f"https://push.example/{nr}", "p", "a", "G"))
    v.commit()
    assert _abos(db, kind["id"]) == 2

    r = client.post(f"/a/admin/{admin['tokens']['admin']}/user/{kind['id']}/neue_tokens")
    assert r.status_code == 200
    assert _abos(db, kind["id"]) == 0, "verlorenes Gerät bekäme weiter Pushes"
    assert _abos(db, eltern["id"]) == 1, "andere Nutzer bleiben unberührt"
    assert "Push-Benachrichtigungen" in r.get_data(as_text=True)
