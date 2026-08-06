"""Wächter über das Routen-Inventar.

Zweck: Eine neue Route, die Daten ändert, aber niemanden authentifiziert,
soll hier auffallen – nicht erst im Betrieb. Der Test kennt die vier
bekannten Ausnahmen; alles Weitere muss bewusst eingetragen werden.

Wunsch #140, Stufe 4: Der Maßstab ist jetzt der **Endpunkt**, nicht die
einzelne Regel. Jede Route hat seit Stufe 4 zwei Regeln – eine mit `<token>`
im Pfad und eine token-freie Zwillingsregel, die über das Sitzungs-Cookie
autorisiert. Beide landen in derselben View-Funktion, die als Erstes `grant()`
bzw. `_home_user()` aufruft; die Autorisierung hängt also am Endpunkt.

Der Test verlangt deshalb: zu jeder ändernden token-freien Regel muss es eine
Schwesterregel MIT `<token>` am selben Endpunkt geben. Eine neu hinzugefügte
Route ohne jede Token-Regel fällt weiterhin auf – genau wie vorher. Was den
Zwilling zusätzlich absichert, ist der CSRF-Riegel aus Stufe 2
(`20_csrf.py`): ohne ihn wäre eine cookie-autorisierte POST-Route angreifbar.
"""

UNSICHERE_METHODEN = {"POST", "PUT", "PATCH", "DELETE"}

# Routen, die Daten ändern, aber kein <token> im Pfad haben. Sie holen ihn
# stattdessen aus dem JSON-Body und prüfen ihn gegen irgendeinen Grant.
# Aufgeräumt wird das in Stufe 2 des Umbaus (gemeinsamer Helfer
# `aktueller_nutzer()`), siehe Plan.
BEKANNTE_AUSNAHMEN = {
    "/wunsch",
    "/push/subscribe",
    "/push/unsubscribe",
    "/settings/darkmode",
    # Wunsch #142: Ziel der CSP-Verstossmeldungen des Browsers. Bewusst ohne
    # Autorisierung - die Meldung kommt vom Browser selbst, nicht von einer
    # Seite, und der Endpunkt aendert keine Daten.
    "/csp-bericht",
}


def _aendernde_regeln(app):
    for regel in app.url_map.iter_rules():
        if regel.methods & UNSICHERE_METHODEN:
            yield regel


def _endpunkte_mit_tokenregel(app):
    return {r.endpoint for r in app.url_map.iter_rules() if "<token>" in str(r)}


def test_jede_aendernde_route_ist_abgesichert(app):
    """<token> im Pfad, eine Schwesterregel mit <token>, oder Ausnahme."""
    mit_token = _endpunkte_mit_tokenregel(app)
    ungeschuetzt = [
        str(regel)
        for regel in _aendernde_regeln(app)
        if "<token>" not in str(regel)
        and regel.endpoint not in mit_token
        and str(regel) not in BEKANNTE_AUSNAHMEN
    ]
    assert not ungeschuetzt, (
        "Diese Routen ändern Daten, verlangen aber keinen Token und haben\n"
        "auch keine Schwesterregel mit <token>:\n  "
        + "\n  ".join(sorted(ungeschuetzt))
        + "\n\nEntweder <token> ergänzen oder – mit Begründung – in "
          "BEKANNTE_AUSNAHMEN aufnehmen."
    )


def test_jede_tokenroute_hat_einen_tokenfreien_zwilling(app):
    """Wunsch #140, Stufe 4: der Umbau darf keine Route vergessen haben.

    Ohne Zwilling bliebe ein Endpunkt an den Token in der Adresse gekettet –
    genau das, was Stufe 4 abschaffen soll. Der Test findet vergessene Routen
    zuverlässiger als Durchklicken, weil er auch die POST-Endpunkte sieht."""
    ohne_zwilling = []
    for endpunkt in sorted(_endpunkte_mit_tokenregel(app)):
        regeln = [str(r) for r in app.url_map.iter_rules(endpunkt)]
        if not any("<token>" not in r for r in regeln):
            ohne_zwilling.append(endpunkt)
    assert not ohne_zwilling, (
        "Diese Endpunkte gibt es nur mit Token in der Adresse:\n  "
        + "\n  ".join(ohne_zwilling)
        + '\n\nFehlt @bp.route("…", defaults={"token": None})?'
    )


def test_ausnahmeliste_ist_nicht_verwaist(app):
    """Verschwindet eine Ausnahme-Route, soll die Liste mitgepflegt werden."""
    vorhanden = {str(r) for r in app.url_map.iter_rules()}
    verwaist = BEKANNTE_AUSNAHMEN - vorhanden
    assert not verwaist, f"Ausnahmen ohne zugehörige Route: {sorted(verwaist)}"


def test_gesundheitscheck_bleibt_offen(app):
    """/health muss ohne Token erreichbar bleiben – der Docker-Healthcheck
    hängt daran."""
    pfade = {str(r) for r in app.url_map.iter_rules()}
    assert "/health" in pfade


def test_routen_bestand_ist_plausibel(app):
    """Grobe Klammer: fällt der Bestand drastisch, ist beim Laden der Module
    etwas schiefgegangen (app.py lädt teile/NN_*.py dynamisch – ein
    Importfehler würde sonst still ganze Apps verschlucken)."""
    regeln = [r for r in app.url_map.iter_rules() if r.endpoint != "static"]
    assert len(regeln) > 80, f"Nur {len(regeln)} Routen geladen – Modul nicht importiert?"


def test_alle_module_wurden_geladen(app):
    """Jede App muss mindestens eine Route registriert haben."""
    endpunkte = {r.endpoint.split(".")[0] for r in app.url_map.iter_rules()}
    erwartet = {
        "start", "admin_app", "todo_app", "werkstatt_app", "geholfen_app",
        "einkauf_app", "hilfe_app", "rezepte_app", "essensplan_app",
        "kinderplan_app", "sportschau_app", "tierbaukasten_app",
        "vokabeln_app", "packliste_app", "tvb_app",
    }
    fehlend = erwartet - endpunkte
    assert not fehlend, f"Diese Module haben keine Routen registriert: {sorted(fehlend)}"
