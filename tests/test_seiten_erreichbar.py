"""Rauchtest über alle Seiten – das Netz für Stufe 4 von Wunsch #140.

Stufe 4 fasst rund 290 Stellen an (91 Routen, 87 Template-Links, 113
JS-Pfade). Ohne einen Test, der jede Seite tatsächlich aufruft, würde eine
kaputte App erst auffallen, wenn sie jemand benutzt.

Geprüft werden nur Routen, deren einzige Variable `<token>` ist – also die
Hauptseite jeder App und ihre parameterlosen Unterseiten. Routen mit
zusätzlichen IDs (`<int:eid>`) bräuchten Testdaten je App und sind hier
bewusst außen vor; sie hängen an denselben Vorlagen.
"""
import pytest


def _seiten_routen(app):
    """Alle GET-Routen, deren einzige Variable <token> ist."""
    for regel in app.url_map.iter_rules():
        if "GET" not in regel.methods:
            continue
        if regel.endpoint == "static":
            continue
        if regel.arguments - {"token"}:
            continue                      # braucht weitere Parameter
        if "<token>" not in str(regel):
            continue
        yield regel


def test_es_gibt_genug_zu_pruefen(app):
    """Fängt ab, dass der Filter oben versehentlich alles wegwirft."""
    assert len(list(_seiten_routen(app))) >= 20


def test_alle_seiten_mit_token_erreichbar(app, client, admin, db):
    """Jede Seite, für die der Admin einen Grant hat, muss 200 liefern.

    Das ist die Messlatte für Stufe 4: Nach dem Umbau muss dasselbe gelten,
    zusätzlich für die token-freie Form."""
    # Admin bekommt alle Apps, damit wirklich jede Seite geprüft wird.
    #
    # Wunsch #140, Stufe 6: Die Klartext-Tokens lassen sich nicht mehr aus der
    # Datenbank zurückholen - dieser Test merkt sie sich deshalb beim Anlegen,
    # genau wie es der Produktivcode inzwischen tut (grant_anlegen()).
    verbindung = db["verbindung"]
    from teile.kern import token_lookup, new_token
    tokens = dict(admin["tokens"])
    with app.app_context():
        for app_id, slug in verbindung.execute(
            "SELECT id, slug FROM apps WHERE id NOT IN "
            "(SELECT app_id FROM grants WHERE user_id=?)", (admin["id"],)
        ).fetchall():
            klartext = new_token()
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) "
                "VALUES(?,?,?)", (admin["id"], app_id, token_lookup(klartext)))
            tokens[slug] = klartext
        verbindung.commit()

    fehler = []
    for regel in _seiten_routen(app):
        pfad = str(regel)
        # Slug aus dem Pfad ziehen: /a/<slug>/<token>/...  bzw. /p/<token>
        slug = pfad.split("/")[2] if pfad.startswith("/a/") else "home"
        token = tokens.get(slug)
        if not token:
            # Bewusst KEIN stilles Überspringen: genau das hat verdeckt, dass
            # fünf Apps gar keine Zeile in `apps` hatten und der Test in
            # Wahrheit weniger prüfte als er behauptete.
            fehler.append(f"{pfad} -> kein Grant, App '{slug}' fehlt in apps")
            continue
        antwort = client.get(pfad.replace("<token>", token))
        if antwort.status_code != 200:
            fehler.append(f"{pfad} -> {antwort.status_code}")

    assert not fehler, "Diese Seiten sind nicht erreichbar:\n  " + "\n  ".join(fehler)


@pytest.fixture()
def stufe4(app):
    """Alle drei Schalter an – der Zustand nach Stufe 4."""
    schluessel = ("SITZUNG_AUSSTELLEN", "SITZUNG_KONSUMIEREN", "TOKENFREIE_URLS")
    vorher = {k: app.config.get(k) for k in schluessel}
    for k in schluessel:
        app.config[k] = "1"
    yield
    app.config.update(vorher)


def test_alle_seiten_auch_ohne_token_erreichbar(app, client, admin, db, stufe4):
    """Dieselben Seiten, token-frei, allein über das Sitzungs-Cookie.

    Der eigentliche Beweis für Stufe 4: Eine vergessene Route fällt hier auf,
    weil die token-freie Form dann gar nicht existiert (404) oder niemanden
    autorisiert (403)."""
    verbindung = db["verbindung"]
    from teile.kern import token_lookup, new_token
    with app.app_context():
        for (app_id,) in verbindung.execute(
            "SELECT id FROM apps WHERE id NOT IN "
            "(SELECT app_id FROM grants WHERE user_id=?)", (admin["id"],)
        ).fetchall():
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) "
                "VALUES(?,?,?)", (admin["id"], app_id, token_lookup(new_token())))
        verbindung.commit()

    # Einmal mit Token rein – danach trägt das Cookie.
    client.get(f"/p/{admin['tokens']['home']}")

    fehler = []
    for regel in _seiten_routen(app):
        # Die token-freie Zwillingsregel desselben Endpunkts.
        tokenfrei = [str(r) for r in app.url_map.iter_rules(regel.endpoint)
                     if "<token>" not in str(r)]
        if not tokenfrei:
            fehler.append(f"{regel} -> keine token-freie Regel")
            continue
        antwort = client.get(tokenfrei[0])
        if antwort.status_code != 200:
            fehler.append(f"{tokenfrei[0]} -> {antwort.status_code}")

    assert not fehler, "Token-frei nicht erreichbar:\n  " + "\n  ".join(fehler)


def test_tokenfreie_seite_zeigt_keinen_token_in_links(app, client, admin, stufe4):
    """Der Sinn der ganzen Stufe: Auf einer token-freien Seite darf in keinem
    Link mehr ein Token stehen – sonst wandert er über das Menü (⌂, Hilfe,
    App-Kacheln) doch wieder in Verlauf, Lesezeichen und Screenshots.

    Geprüft wird über ALLE Seiten, für die der Testnutzer einen Grant hat, und
    gegen ALLE seine Tokens – nicht nur den der gerade offenen App. Genau die
    Verwechslung wäre der wahrscheinliche Fehler: `tp` stimmt, aber ein
    App-übergreifender Link baut den Token weiter ein.

    Die Verwaltungsseite ist ausgenommen: Sie ZEIGT die Links absichtlich her,
    damit man sie weitergeben kann. Dass sie das tut, ist ein eigener Befund
    aus der Sicherheitsanalyse und Gegenstand von Stufe 6 (echtes Hashing)."""
    client.get(f"/p/{admin['tokens']['home']}")

    seiten = ["/start"] + [
        f"/a/{slug}/" for slug in admin["tokens"] if slug not in ("home", "admin")
    ]
    fehler = []
    for pfad in seiten:
        antwort = client.get(pfad)
        assert antwort.status_code == 200, f"{pfad} -> {antwort.status_code}"
        text = antwort.get_data(as_text=True)
        for name, wert in admin["tokens"].items():
            if wert in text:
                fehler.append(f"{pfad}: Token '{name}' steht noch in der Seite")

    assert not fehler, "\n  ".join([""] + fehler)


def test_jede_aktion_zeigt_auf_eine_vorhandene_funktion(app, client, admin, db, stufe4):
    """Wunsch #142: Jedes `data-klick` muss eine Funktion treffen, die es gibt.

    Der Verteiler in `base.html` löst den Namen zur Laufzeit über `window[...]`
    auf. Ein Tippfehler ist deshalb kein Fehler beim Laden, sondern ein Knopf,
    der beim Drücken nichts tut – der unangenehmste Fehler überhaupt, weil ihn
    niemand meldet, sondern alle für „hängt halt manchmal" halten.

    Geprüft wird an der **ausgelieferten Seite**, nicht an der Vorlage: Die
    Funktion kann in der Vorlage selbst oder in `base.html` stehen, und erst im
    fertigen HTML ist beides beisammen."""
    verbindung = db["verbindung"]
    from teile.kern import token_lookup, new_token
    with app.app_context():
        for (app_id,) in verbindung.execute(
            "SELECT id FROM apps WHERE id NOT IN "
            "(SELECT app_id FROM grants WHERE user_id=?)", (admin["id"],)
        ).fetchall():
            verbindung.execute(
                "INSERT INTO grants(user_id, app_id, token_lookup) "
                "VALUES(?,?,?)", (admin["id"], app_id, token_lookup(new_token())))
        verbindung.commit()
    client.get(f"/p/{admin['tokens']['home']}")

    import re
    aktion_re = re.compile(r'data-(?:klick|aendern|eingabe|absenden)="([^"]+)"')
    skript_re = re.compile(r"<script[^>]*>.*?</script>", re.S)
    fehler = []
    geprueft = 0
    for regel in _seiten_routen(app):
        tokenfrei = [str(r) for r in app.url_map.iter_rules(regel.endpoint)
                     if "<token>" not in str(r)]
        if not tokenfrei:
            continue
        seite = client.get(tokenfrei[0]).get_data(as_text=True)
        # Attribute zählen nur im Markup. Ohne diese Trennung findet der Test
        # den Beispiel-Schnipsel im Erklärkommentar des Verteilers in
        # base.html – der steht auf jeder Seite und wäre ein Dauerfehlalarm.
        markup = skript_re.sub("", seite)
        for name in set(aktion_re.findall(markup)):
            geprueft += 1
            # Funktionsdeklaration oder Zuweisung an window.
            if not re.search(r"(function\s+%s\s*\(|window\.%s\s*=)" % (name, name), seite):
                fehler.append(f"{tokenfrei[0]}: '{name}' ist nirgends definiert")

    # Die Schwelle sichert nur ab, dass der Filter oben nicht ins Leere greift
    # (ein kaputtes Muster faende 0-2). Sie lag frueher bei ">20" und wurde mit
    # Wunsch #162 auf ">=15" gesenkt: Bis dahin leerte conftest die
    # Testdatenbank nur teilweise, die Seiten rendersten deshalb Datenreste
    # anderer Tests mit - und damit ein paar Handler mehr. Der Test hing also
    # an genau der Undichtigkeit, die dort behoben wurde. Auf einer sauberen
    # Datenbank sind es deterministisch 20.
    assert geprueft >= 15, f"nur {geprueft} Aktionen geprüft – Filter zu eng?"
    assert not fehler, "\n  ".join([""] + sorted(set(fehler)))


def test_notausstieg_leitet_nicht_mehr_um_aber_verlinkt_token_frei(app, client, admin):
    """`TOKENFREIE_URLS=0` ist seit Stufe 6 nur noch ein halber Notausstieg.

    Bis Stufe 5 stellte der Schalter den Zustand von vorher vollständig
    wieder her: Links trugen wieder Tokens. Das kann er nicht mehr, denn seit
    Stufe 6 gibt es keine Klartext-Tokens, die man einsetzen könnte - die
    App-Kacheln bleiben token-frei, egal wie der Schalter steht.

    Was er weiterhin tut: `/p/<token>` leitet nicht mehr auf `/start` um, die
    Adresse mit Token bleibt also stehen. Das genügt als Rückfallebene, weil
    ein Pfad-Token unverändert Vorrang hat und jede token-freie Adresse
    zusätzlich über das Cookie trägt.

    Der Test hält das ausdrücklich fest, statt stillschweigend gelockert zu
    werden: Wer künftig eine echte Rücknahme von Stufe 4 braucht, muss die
    Datenbanksicherung von vor Stufe 6 einspielen."""
    schluessel = ("SITZUNG_AUSSTELLEN", "SITZUNG_KONSUMIEREN", "TOKENFREIE_URLS")
    vorher = {k: app.config.get(k) for k in schluessel}
    app.config["SITZUNG_AUSSTELLEN"] = "1"
    app.config["SITZUNG_KONSUMIEREN"] = "1"
    app.config["TOKENFREIE_URLS"] = "0"
    try:
        home = admin["tokens"]["home"]
        assert client.get(f"/p/{home}").status_code == 200
        # Zweiter Aufruf: jetzt liegt ein Cookie vor – trotzdem kein Redirect.
        antwort = client.get(f"/p/{home}")
        assert antwort.status_code == 200, "Schalter aus, aber trotzdem umgeleitet"
        # Und die Kacheln sind token-frei – nachweislich, nicht bloss vermutet.
        text = antwort.get_data(as_text=True)
        assert f"/a/einkauf/{admin['tokens']['einkauf']}/" not in text
        assert 'href="/a/einkauf/"' in text
    finally:
        app.config.update(vorher)


def test_leerer_token_wird_nicht_als_none_gerendert(app, client, admin, stufe4):
    """Jinja rendert `None` als die Zeichenkette "None".

    `const TOKEN = '{{ token }}'` ergäbe token-frei wörtlich `'None'` – ein
    truthy Wert, der an `/wunsch`, `/push/*` und `/settings/darkmode` als Token
    ginge, dort nicht auflöst, und weil ein ANGEGEBENER Token bewusst nicht
    aufs Cookie zurückfällt, ein stilles 403 erzeugt. Der Schalter im Menü täte
    dann einfach nichts, ohne Fehlermeldung. Deshalb dieser Test."""
    client.get(f"/p/{admin['tokens']['home']}")
    for pfad in ["/start", "/a/einkauf/", "/a/todo/"]:
        text = client.get(pfad).get_data(as_text=True)
        assert "'None'" not in text and '"None"' not in text, \
            f"{pfad}: None als Zeichenkette in der Seite"


def test_einkauf_hat_den_container_fuer_die_live_aktualisierung(client, admin):
    """Wunsch #146: `#einkauf-liste` ist der Anker, den `listeAustauschen()`
    ersetzt. Verschwindet oder verrutscht er, hört die Liste still auf, sich
    zu aktualisieren – und niemand merkt es, weil die Seite ansonsten normal
    aussieht."""
    seite = client.get(f"/a/einkauf/{admin['tokens']['einkauf']}/").get_data(as_text=True)
    assert seite.count('id="einkauf-liste"') == 1
    # Der Fingerabdruck muss ebenfalls eingebettet sein, sonst vergleicht das
    # Frontend gegen einen leeren Wert und tauscht bei jedem Durchlauf.
    assert "einkaufStandBekannt = '" in seite
