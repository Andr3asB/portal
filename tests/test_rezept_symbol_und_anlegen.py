"""Wünsche #184 und #185 – beide betreffen den Kopf der Rezeptliste.

**#184 – das Symbol folgt der Kategorie.** `rezepte.kategorie` ist schon seit
Wunsch #55 genau `kochen` oder `backen`; es brauchte also kein neues Feld,
nur eine Zuordnung. Die liegt in `11_rezepte.py` und wird vom Essensplan
mitbenutzt – dieselben Rezepte dürfen nicht je nach Seite ein anderes Zeichen
tragen. Genau das prüfen die Tests hier: nicht nur, DASS ein Symbol erscheint,
sondern dass beide Seiten dasselbe zeigen.

**#185 – die drei Anlegewege in eine Zeile.** Bewusst ohne Aufklappen: Es
kostete einen Tipp mehr und würde zwei bisher sichtbare Wege verstecken. Der
Test wacht darüber, dass alle drei Wege erreichbar bleiben – eine „kompakte"
Kopfzeile, die einen Weg einfach weglässt, wäre die naheliegende Verschlimm-
besserung.
"""
import pathlib
import re
from datetime import date

import pytest
from teile.kern import heute_lokal

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"

TOPF   = "\U0001F372"   # 🍲 ohne Kategorie
PFANNE = "\U0001F373"   # 🍳 kochen
KUCHEN = "\U0001F370"   # 🍰 backen


@pytest.fixture()
def rezepte_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='rezepte'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _drei_rezepte(v):
    ids = {}
    for name, kategorie in [("Testlinsen", "kochen"),
                            ("Testkuchen", "backen"),
                            ("Testrest", None)]:
        ids[name] = v.execute(
            "INSERT INTO rezepte(name, kategorie) VALUES(?,?) RETURNING id",
            (name, kategorie)).fetchone()["id"]
    v.commit()
    return ids


# --- #184: die Zuordnung selbst --------------------------------------------

def test_zuordnung_kennt_beide_kategorien():
    from teile.rezepte import kategorie_symbol
    assert kategorie_symbol("kochen") == PFANNE
    assert kategorie_symbol("backen") == KUCHEN


def test_ohne_kategorie_bleibt_der_neutrale_topf():
    """Kein Rezept wird stillschweigend zum Kochrezept erklärt - man soll auf
    der Liste sehen, dass die Kategorie fehlt."""
    from teile.rezepte import kategorie_symbol
    assert kategorie_symbol(None) == TOPF
    assert kategorie_symbol("") == TOPF
    assert kategorie_symbol("quatsch") == TOPF


def test_symbol_und_kategorie_label_verwenden_dasselbe_zeichen():
    """Zwei verschiedene Symbole für dieselbe Sache müsste man erst lernen."""
    from teile.rezepte import KATEGORIE_SYMBOL, KATEGORIEN
    for wert, label in KATEGORIEN.items():
        assert label.startswith(KATEGORIE_SYMBOL[wert]), (
            f"Kategorie {wert}: Filterchip zeigt {label!r}, "
            f"die Liste aber {KATEGORIE_SYMBOL[wert]!r}."
        )


# --- #184: auf den Seiten ---------------------------------------------------

def test_liste_zeigt_je_kategorie_ein_anderes_symbol(client, db, rezepte_token):
    _drei_rezepte(db["verbindung"])
    text = client.get(f"/a/rezepte/{rezepte_token}/").get_data(as_text=True)

    # Je Karte das Paar (Symbol, Name) einsammeln - nicht "steht das Zeichen
    # irgendwo auf der Seite": alle drei Zeichen stehen dort ohnehin, sobald
    # drei Rezepte da sind. Nur die Zuordnung ist die Aussage.
    karten = {
        name: zeichen for zeichen, name in re.findall(
            r'class="rezept-emoji"[^>]*>([^<]+)</span>.*?'
            r'class="rezept-name"[^>]*>([^<\s]+)', text, re.DOTALL)
    }
    assert karten == {"Testkuchen": KUCHEN, "Testlinsen": PFANNE, "Testrest": TOPF}, karten


def test_essensplan_zeigt_dasselbe_symbol_wie_die_liste(app, client, db):
    """Der eigentliche Punkt: EIN Rezept, ZWEI Seiten, dasselbe Zeichen."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    ids = _drei_rezepte(v)
    tag = date.fromisoformat(heute_lokal()).isoformat()
    v.execute("INSERT INTO essensplan_eintraege(tag, mahlzeit, rezept_id) VALUES(?,?,?)",
              (tag, "abend", ids["Testkuchen"]))
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='essensplan'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
    v.commit()

    plan = client.get(f"/a/essensplan/{klartext}/").get_data(as_text=True)
    assert f"{KUCHEN} Testkuchen" in plan, (
        "Der Essensplan zeigt ein anderes Symbol als die Rezeptliste."
    )
    assert f"{TOPF} Testkuchen" not in plan


def test_der_topf_bleibt_das_zeichen_der_app(client, db, rezepte_token):
    """Die Kopfzeile der App heißt weiter 🍲 Rezepte - das ist das Symbol der
    App, nicht das eines einzelnen Rezepts. Ein Test, der beides vermischt,
    würde jede Kategorie-Änderung fälschlich anmahnen."""
    text = client.get(f"/a/rezepte/{rezepte_token}/").get_data(as_text=True)
    assert f"{TOPF} Rezepte" in text


# --- #185: die Anlegezeile --------------------------------------------------

def test_alle_drei_anlegewege_bleiben_erreichbar(client, db, rezepte_token):
    """Platz sparen darf keinen Weg kosten."""
    text = client.get(f"/a/rezepte/{rezepte_token}/").get_data(as_text=True)
    for ziel in ("neu", "importieren", "importieren-bild"):
        assert f'/a/rezepte/{rezepte_token}/{ziel}"' in text, (
            f"Der Weg '{ziel}' ist aus der Kopfzeile verschwunden (Wunsch #185)."
        )


def test_die_drei_stehen_in_einer_zeile(client, db, rezepte_token):
    """Drei Blockelemente untereinander waren der Ausgangszustand. Geprüft
    wird die gemeinsame Flex-Zeile, nicht nur ihre Existenz: ohne sie fielen
    die Knöpfe wieder in drei Zeilen zurück."""
    text = client.get(f"/a/rezepte/{rezepte_token}/").get_data(as_text=True)
    zeile = re.search(r'<div class="anlegen-zeile">(.*?)</div>', text, re.DOTALL)
    assert zeile, "Die Anlegezeile fehlt."
    assert zeile.group(1).count("<a ") == 3, "Nicht alle drei stehen in der Zeile."

    css = (TPL / "rezepte.html").read_text(encoding="utf-8")
    regel = re.search(r"\.anlegen-zeile\s*\{([^}]*)\}", css).group(1)
    assert "display:flex" in regel.replace(" ", "")


def test_die_importknoepfe_schrumpfen_nicht_den_haupt_knopf(client, db, rezepte_token):
    """`flex:1` beim Hauptknopf, `flex:0 0 auto` bei den Importen - andersherum
    wuerde "+ Neues Rezept" auf einem 375er iPhone zu "+ Neues R…"."""
    css = (TPL / "rezepte.html").read_text(encoding="utf-8")
    haupt = re.search(r"\.btn-neues-rezept\s*\{([^}]*)\}", css).group(1).replace(" ", "")
    neben = re.search(r"\.btn-importieren\s*\{([^}]*)\}", css).group(1).replace(" ", "")
    assert "flex:11auto" in haupt
    assert "flex:00auto" in neben


def test_tippflaeche_der_anlegezeile(client, db, rezepte_token):
    """Links sind keine <button> - die globale 44px-Regel aus base.html
    (Wunsch #169) greift bei ihnen NICHT. Die Zeile muss ihre Hoehe deshalb
    selbst mitbringen."""
    css = (TPL / "rezepte.html").read_text(encoding="utf-8")
    for klasse in (".btn-neues-rezept", ".btn-importieren"):
        regel = re.search(re.escape(klasse) + r"\s*\{([^}]*)\}", css).group(1)
        assert "min-height:44px" in regel.replace(" ", ""), (
            f"{klasse} kann unter 44px hoch werden."
        )
