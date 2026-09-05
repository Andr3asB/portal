"""Wünsche #254–#257: Feinschliff an TVB-Ansicht und Essensplan.

#254/#255/#256 sind reine Vorlagen-Änderungen an tvb.html – die Daten dazu
kommen von externen Quellen und liegen in keiner Test-DB. Deshalb wächtern
hier statische Prüfungen die Vorlage; #257 (Anker nach dem Speichern) ist
ein echter Funktionstest gegen die Route.
"""
import pathlib
import re
from datetime import date, timedelta

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
TVB = (TPL / "tvb.html").read_text(encoding="utf-8")
# Jinja-Kommentare raus, sonst prüft der Wächter unten die Erklärung statt
# des Codes (dieselbe Falle wie in test_ziehgriff_und_ausfall.py beschrieben).
TVB_CODE = re.sub(r"\{#.*?#\}", " ", TVB, flags=re.DOTALL)


# ── #256: Kein "NoneNone" mehr unter den Spielen ───────────────────────────

def test_spieltag_und_ort_nur_wenn_vorhanden():
    """`{{ s.ort }}` ohne Wächter schrieb wörtlich "NoneNone" unter fast
    jedes Spiel - Jinja rendert Python-None als Text. Jede Zeile, die eines
    der beiden Felder ausgibt, muss es auf derselben Zeile auch prüfen."""
    for feld in ("s.spieltag", "s.ort"):
        ausgaben = [z for z in TVB_CODE.splitlines() if "{{ " + feld + " }}" in z]
        assert ausgaben, f"Muster kaputt? {feld} wird nirgends ausgegeben."
        for zeile in ausgaben:
            assert f"if {feld}" in zeile, (
                f"tvb.html gibt {feld} ungeprüft aus - None landet als "
                f"'None' auf der Seite (Wunsch #256): {zeile.strip()}")


# ── #254: Standard sind die nächsten drei Spiele ───────────────────────────

def test_standard_sind_drei_spiele_plus_aufklappen():
    assert "kommende[:3]" in TVB
    assert "kommende[3:]" in TVB
    assert 'id="mehr-spiele" hidden' in TVB
    # Der Knopf folgt der #248-Konvention: data-panel -> aria-expanded.
    knopf = re.search(r'<button[^>]*id="mehr-spiele-btn"[^>]*>', TVB)
    assert knopf and 'data-panel="mehr-spiele"' in knopf.group(0)


# ── #255: Ergebnisse als Gegenüberstellung ─────────────────────────────────

def test_ergebnis_gegenueberstellung_mit_siegerhervorhebung():
    assert re.search(r"grid-template-columns:\s*1fr auto 1fr", TVB)
    assert "s.heim_tore > s.gast_tore" in TVB and "s.gast_tore > s.heim_tore" in TVB
    # Sieger fett, Verlierer zurückgenommen - beide Regeln müssen existieren.
    assert re.search(r"\.tvb-erg-team\.sieger\s*\{[^}]*font-weight:\s*700", TVB)
    assert re.search(r"\.tvb-erg-team\.verlierer\s*\{[^}]*var\(--text-2\)", TVB)
    # #237-Konvention: TVB-Team in der Kontrast-, nie in der Rohfarbe.
    assert re.search(r"\.tvb-erg-team\.tvb\s*\{[^}]*var\(--farbe-kontrast\)", TVB)


# ── #257: Nach dem Speichern zurück an die bearbeitete Stelle ──────────────

@pytest.fixture()
def plan_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='essensplan'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def test_speichern_springt_zurueck_zum_slot(client, plan_token):
    from teile.kern import heute_lokal
    tag = heute_lokal()
    r = client.post(f"/a/essensplan/{plan_token}/eintrag",
                    data={"tag": tag, "mahlzeit": "abend", "text": "Pfannkuchen"})
    assert r.status_code == 302
    assert r.location.endswith(f"#slot-{tag}_abend")
    # Und das Sprungziel existiert auf der Seite wirklich.
    seite = client.get(f"/a/essensplan/{plan_token}/").get_data(as_text=True)
    assert f'id="slot-{tag}_abend"' in seite


def test_kaputter_tag_bekommt_keinen_anker(client, plan_token):
    """Der Anker entsteht nur aus geprüften Werten - ein beliebiger String
    aus dem Formular gehört nicht in die Redirect-URL."""
    r = client.post(f"/a/essensplan/{plan_token}/eintrag",
                    data={"tag": "kein-datum<script>", "mahlzeit": "abend", "text": "x"})
    assert r.status_code == 302
    assert "#" not in r.location
