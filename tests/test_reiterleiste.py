"""Wunsch #298: Reiterleiste unten und Rueckgaengig-Meldung in base.html.

Zwei Bausteine, die die neue Aufgaben-App braucht und die jede App nutzen
darf (Spezifikation 12). Beide leben ZENTRAL in base.html - eine Vorlage,
die sich eine eigene Leiste baut, waere die Bauart, bei der Safe-Area,
z-Reihenfolge und aria-current in jeder Kopie ein bisschen anders sind.

Abgrenzung zur Regel "Aktionsknoepfe oben als .top-aktionen" (Wunsch #155):
Die Reiterleiste ist NAVIGATION zwischen den Ansichten einer App, keine
Aktion. Aktionen bleiben oben im <main>.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")


def _regel(selektor):
    treffer = re.search(re.escape(selektor) + r"\s*\{([^}]*)\}", BASE)
    assert treffer, f"Regel {selektor} fehlt in base.html."
    return treffer.group(1).replace(" ", "").replace("\n", "")


# --- Reiterleiste ----------------------------------------------------------

def test_reiterleiste_ist_navigation_mit_namen():
    assert '<nav class="reiter" aria-label="Ansichten">' in BASE
    assert 'aria-current="page"' in BASE


def test_reiterleiste_klebt_unten_mit_safe_area():
    regel = _regel(".reiter")
    assert "position:fixed" in regel and "bottom:0" in regel
    assert "var(--sb)" in regel, "iPhone-Balken: padding-bottom braucht die Safe-Area."


def test_der_inhalt_endet_nicht_unter_der_leiste():
    regel = _regel("body.mit-reiter")
    assert "padding-bottom" in regel and "var(--sb)" in regel
    assert "mit-reiter" in BASE.split("<body", 1)[1].split(">", 1)[0]


def test_reiter_liegt_ueber_inhalt_unter_menue_und_dialog():
    reiter = int(re.search(r"z-index:(\d+)", _regel(".reiter")).group(1))
    kopf = int(re.search(r"z-index:(\d+)", _regel(".app-header")).group(1))
    menue = int(re.search(r"z-index:\s*(\d+)", BASE[BASE.index(".menu-overlay"):]).group(1))
    assert kopf <= reiter < menue, (kopf, reiter, menue)


@pytest.mark.parametrize("datei", sorted(TPL.glob("*.html")), ids=lambda p: p.name)
def test_keine_vorlage_baut_eine_eigene_leiste(datei):
    if datei.name == "base.html":
        return
    inhalt = re.sub(r"\{#.*?#\}", "", datei.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert 'class="reiter"' not in inhalt and ".reiter {" not in inhalt, (
        f"{datei.name} baut eine eigene Reiterleiste - die kommt aus base.html "
        f"(render_template(..., reiter=[...]))."
    )


# --- Rueckgaengig-Meldung --------------------------------------------------

def _meldung_markup():
    start = BASE.index('id="rueckgaengig"')
    return BASE[BASE.rfind("<div", 0, start):BASE.index("</div>", start)]


def test_meldung_ist_ein_status_mit_genau_einem_knopf():
    markup = _meldung_markup()
    assert 'role="status"' in markup
    assert markup.count("<button") == 1, "Ein Knopf. Zwei waeren ein Dialog."
    assert "hidden" in markup.split(">", 1)[0], "startet unsichtbar"


def test_meldung_verschwindet_nach_sechs_sekunden():
    assert "RUECKGAENGIG_MS = 6000" in BASE
    assert "window.rueckgaengigMeldung = function" in BASE


def test_meldung_bleibt_ueber_der_reiterleiste():
    """Sonst laege der Rueckgaengig-Knopf genau unter den Reitern."""
    regel = _regel("body.mit-reiter .rueckgaengig")
    assert "bottom:calc(" in regel and "var(--sb)" in regel


# --- Wirkung -----------------------------------------------------------------

def test_aufgaben_seite_hat_die_leiste_andere_nicht(app, client, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    admin = db["familie"]["TestAdmin"]
    app_id = v.execute("SELECT id FROM apps WHERE slug='aufgaben'").fetchone()["id"]
    tok = new_token()
    with app.app_context():
        v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (admin["id"], app_id, token_lookup(tok)))
    v.commit()
    mit = client.get(f"/a/aufgaben/{tok}/").get_data(as_text=True)
    ohne = client.get(f"/a/hilfe/{admin['tokens']['hilfe']}/").get_data(as_text=True)
    # Die Klasse steht auch im Erklaerkommentar des Stils - deshalb den
    # body-Tag selbst pruefen, nicht die ganze Seite.
    def body_klassen(seite):
        return seite.split("<body", 1)[1].split(">", 1)[0]
    assert '<nav class="reiter"' in mit and "mit-reiter" in body_klassen(mit)
    assert '<nav class="reiter"' not in ohne and "mit-reiter" not in body_klassen(ohne)
    # Die Meldung steht auf JEDER Seite bereit (verborgen)
    assert 'id="rueckgaengig" role="status"' in mit and 'id="rueckgaengig" role="status"' in ohne
