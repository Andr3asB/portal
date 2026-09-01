"""Wunsch #187: Keine Wunsch-Karte ohne Überschrift.

Die Bestandsaufnahme zuerst, weil sie die Lösung bestimmt: Von 187 Wünschen
hatten 140 keine Überschrift – **alle davon älter als Wunsch #161**, der die
KI-Überschrift eingeführt hat. Seit #162 hat jeder Wunsch eine. Es war also
kein Fehler in der Vergabe, sondern eine Lücke im Bestand.

Trotzdem ist „bekommt beim Anlegen eine KI-Überschrift" keine Garantie: Der
Titel entsteht in einem Hintergrund-Thread, braucht ein bekanntes Konto
(anonyme Wünsche haben keins), ein Kontingent und eine erreichbare
Gegenstelle. Deshalb zwei Dinge:

* `ersatz_titel()` leitet eine Überschrift aus dem Text ab – **Anzeigewert,
  nicht gespeichert.** Trägt die KI später doch etwas nach, gewinnt es sofort;
  es gibt kein Provisorium in der Datenbank aufzuräumen.
* `manage.py titel_nachtragen` holt echte KI-Titel für den Altbestand.

Die Tests unten prüfen deshalb vor allem den Fall, der bisher nicht
abgedeckt war: **kein Titel da.**
"""
import re

import pytest
from teile.werkstatt import ersatz_titel

# --- Die abgeleitete Überschrift -------------------------------------------

def test_kurzer_wunsch_wird_ganz_zur_ueberschrift():
    assert ersatz_titel("Die Einträge sollen editierbar sein") == \
        "Die Einträge sollen editierbar sein"


def test_der_erste_satz_zaehlt():
    """Bei einem Wunsch steht die Kernaussage vorn, der Rest ist Begründung."""
    assert ersatz_titel(
        "Die Liste soll sortierbar sein. Sonst findet man nichts wieder, "
        "wenn viele Einträge da sind."
    ) == "Die Liste soll sortierbar sein"


def test_langer_erster_satz_wird_am_wortende_gekuerzt():
    """Mitten im Wort abzuschneiden liest sich wie ein Fehler."""
    lang = ("Das Symbol vor einem Rezept soll abhängig davon anders dargestellt "
            "sein ob gekocht oder gebacken wird")
    aus = ersatz_titel(lang)
    assert aus.endswith(" …")
    assert len(aus) <= 64
    # Die eigentliche Aussage: hinter dem behaltenen Stueck steht im Original
    # ein Leerzeichen. Der erste Versuch riet stattdessen an konkreten
    # Wortenden herum ("endet nicht auf 'ab' oder 'dar'") - und blieb gruen,
    # als die Kuerzung wieder stumpf bei 60 Zeichen schnitt.
    kern = aus.rstrip(" …")
    assert lang.startswith(kern)
    assert lang[len(kern)] == " ", f"mitten im Wort abgeschnitten: {aus!r}"


def test_zeilenumbrueche_werden_zu_leerzeichen():
    assert ersatz_titel("Zeile eins\n   Zeile zwei") == "Zeile eins Zeile zwei"


def test_leerer_text_gibt_leere_ueberschrift():
    """Kein Absturz und kein '…' aus dem Nichts."""
    assert ersatz_titel("") == ""
    assert ersatz_titel(None) == ""
    assert ersatz_titel("   \n ") == ""


def test_doppelpunkt_trennt_gerade_nicht():
    """Beim ersten Lauf trennte die Ableitung auch am Doppelpunkt. Aus
    „UI: Die Knöpfe hängen am Header" (so beginnt Wunsch #155 wörtlich) wurde
    dann die Überschrift „UI" – schlechter als gar keine. Wünsche fangen oft
    mit einer Einordnung an; die Aussage steht dahinter."""
    assert ersatz_titel("UI: Die Knöpfe hängen am Header") ==         "UI: Die Knöpfe hängen am Header"


# --- Auf der Seite ----------------------------------------------------------

@pytest.fixture()
def werkstatt_token(app, db):
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='werkstatt'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) "
                  "VALUES(?,?,?)",
                  (db["familie"]["TestAdmin"]["id"], app_id, token_lookup(klartext)))
        v.commit()
    return klartext


def _wunsch(v, text, titel=None, erledigt=0):
    wid = v.execute(
        "INSERT INTO wuensche(text, titel, erledigt) VALUES(?,?,?) RETURNING id",
        (text, titel, erledigt)).fetchone()["id"]
    v.commit()
    return wid


def test_wunsch_ohne_titel_bekommt_trotzdem_eine_ueberschrift(client, db, werkstatt_token):
    _wunsch(db["verbindung"],
            "Der Kalender soll Feiertage kennen. Sonst plant man daneben.")
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert re.search(r'class="wunsch-titel ersatz"[^>]*>Der Kalender soll Feiertage kennen<', text)


def test_jede_karte_hat_eine_ueberschrift(client, db, werkstatt_token):
    """Der eigentliche Wunsch, als Zählung: so viele Überschriften wie Karten.

    Ein Test auf „irgendwo steht eine Überschrift" wäre schon durch den einen
    Wunsch MIT Titel erfüllt.
    """
    v = db["verbindung"]
    _wunsch(v, "Mit Titel", titel="Ein richtiger Titel")
    _wunsch(v, "Ohne Titel, offen")
    _wunsch(v, "Ohne Titel, erledigt", erledigt=1)

    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    karten = len(re.findall(r'class="wunsch-card[ "]', text))
    titel  = len(re.findall(r'class="wunsch-titel', text))
    assert karten == 3, f"{karten} Karten gefunden - Muster kaputt?"
    assert titel == karten, f"{titel} Ueberschriften auf {karten} Karten."


def test_echter_titel_schlaegt_die_ableitung(client, db, werkstatt_token):
    _wunsch(db["verbindung"], "Ein sehr langer Wunschtext ohne Aussagekraft",
            titel="Feiertage im Kalender")
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert re.search(r'class="wunsch-titel"[^>]*>Feiertage im Kalender<', text)
    assert "wunsch-titel ersatz" not in text


def test_die_ableitung_ist_sichtbar_zweite_wahl(client, db, werkstatt_token):
    """Sonst hält man den abgeschnittenen ersten Satz für eine Formulierung."""
    tpl = (pytest.importorskip("pathlib").Path(__file__).resolve().parents[1]
           / "src" / "teile" / "templates" / "werkstatt_app.html"
           ).read_text(encoding="utf-8")
    regel = re.search(r"\.wunsch-titel\.ersatz\s*\{([^}]*)\}", tpl)
    assert regel, "Die Ersatz-Ueberschrift sieht aus wie eine echte."
    assert "var(--text-2)" in regel.group(1)


def test_der_volle_text_bleibt_unter_der_ueberschrift(client, db, werkstatt_token):
    """Die Überschrift ersetzt den Wunsch nicht - sie steht darüber.

    Geprüft wird das Element, nicht nur das Vorkommen des Satzes: Der Text
    steht ausserdem in der aufklappbaren Detailansicht. Ohne diese Genauigkeit
    blieb der Test grün, als die Vorschauzeile ganz verschwunden war."""
    voll = ("Der Kalender soll Feiertage kennen. Sonst plant man "
            "versehentlich am Feiertag ein.")
    _wunsch(db["verbindung"], voll)
    text = client.get(f"/a/werkstatt/{werkstatt_token}/").get_data(as_text=True)
    assert re.search(r'class="wunsch-text secondary"[^>]*>' + re.escape(voll) + '<', text)
