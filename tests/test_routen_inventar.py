"""Wächter über das Routen-Inventar.

Zweck: Eine neue Route, die Daten ändert, aber niemanden authentifiziert,
soll hier auffallen – nicht erst im Betrieb. Der Test kennt die vier
bekannten Ausnahmen; alles Weitere muss bewusst eingetragen werden.

Beim Umbau für Wunsch #140 wird dieser Test angepasst werden müssen (dann
gilt auch das Sitzungs-Cookie als Authentifizierung). Genau das ist der
Zweck: die Änderung soll sichtbar sein, nicht stillschweigend passieren.
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
}


def _aendernde_regeln(app):
    for regel in app.url_map.iter_rules():
        if regel.methods & UNSICHERE_METHODEN:
            yield regel


def test_jede_aendernde_route_ist_abgesichert(app):
    """Entweder <token> im Pfad oder ausdrücklich als Ausnahme vermerkt."""
    ungeschuetzt = [
        str(regel)
        for regel in _aendernde_regeln(app)
        if "<token>" not in str(regel) and str(regel) not in BEKANNTE_AUSNAHMEN
    ]
    assert not ungeschuetzt, (
        "Diese Routen ändern Daten, verlangen aber keinen Token:\n  "
        + "\n  ".join(sorted(ungeschuetzt))
        + "\n\nEntweder <token> ergänzen oder – mit Begründung – in "
          "BEKANNTE_AUSNAHMEN aufnehmen."
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
