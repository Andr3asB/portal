"""Die neue TVB-Datenschicht nach dem handball.net-Relaunch (#191/#192/#193).

Loest `test_tvb_wettbewerbe.py` ab. Jene Datei prueft das Spielformat der
alten Widget-API und die Eigenheit, dass handball.net je Wettbewerb eine
eigene Team-ID vergab (`sr.competitor.6272-143352` in der Liga, `-143228` im
Pokal). Beides gibt es nicht mehr: die Widget-API ist abgeschaltet, und im
Handball360-System hat eine Mannschaft genau eine ID. Ein Test auf ein
Format, das keine Quelle mehr liefert, kann nichts mehr finden - er bliebe
nur gruen, bis ihn jemand loescht.

Geprueft wird hier stattdessen das, was jetzt schiefgehen kann: die
Umwandlung der ZWEI neuen Quellformate (handball.net /api/new/ fuer
Amateur/Jugend, Sportradar fuer die Profis) in das EINE Anzeigeformat, das
Vorlage und Datenbank erwarten.
"""
import importlib

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.18_tvb")


def _neues_spiel(**abweichung):
    roh = {
        "id": 414830,
        "round": 3,
        "date": "2026-08-30T17:00:00+00:00",
        "status": {"is_finished": True, "is_live": False},
        "result": {"local": 35, "visitor": 26},
        "local": {"id": 87345, "name": "RHEIN-NECKAR LOEWEN II"},
        "visitor": {"id": 87353, "name": "TV BITTENFELD II"},
        "field": {"name": "ERICH-BAMBERGER STADTHALLE"},
        "phase": {"id": 14056, "competition": {"name": "3. Liga Maenner"}},
    }
    roh.update(abweichung)
    return roh


# --- Quelle 1: handball.net /api/new/ --------------------------------------

def test_spiel_wird_vollstaendig_uebernommen(modul):
    s = modul._spiel_aus_neu(_neues_spiel(), "87353")
    assert s["heim"] == "RHEIN-NECKAR LOEWEN II"
    assert s["gast"] == "TV BITTENFELD II"
    assert (s["heim_tore"], s["gast_tore"]) == (35, 26)
    assert s["status"] == "Ended"
    assert s["wettbewerb"] == "3. Liga Maenner"
    assert s["spieltag"] == "3. Spieltag"
    assert s["ort"] == "ERICH-BAMBERGER STADTHALLE"


def test_anstoss_kommt_in_ortszeit_an(modul):
    """Die API liefert UTC mit Offset. Die Liste sortiert und vergleicht
    gegen die lokale Zeit - stuende hier UTC, laege die Trennung zwischen
    'kommend' und 'vergangen' im Sommer zwei Stunden daneben."""
    s = modul._spiel_aus_neu(_neues_spiel(), "87353")
    assert s["anstoss"].startswith("2026-08-30T19:00")


def test_noch_nicht_gespieltes_spiel_hat_keine_tore(modul):
    s = modul._spiel_aus_neu(
        _neues_spiel(status={"is_finished": False}, result={}), "87353")
    assert s["heim_tore"] is None and s["gast_tore"] is None
    assert s["status"] == "Pre"


def test_kaputtes_datum_wirft_nicht(modul):
    """Ein einzelnes unlesbares Spiel darf nicht die ganze Seite kippen."""
    s = modul._spiel_aus_neu(_neues_spiel(date="uebermorgen"), "87353")
    assert s["anstoss"] == "uebermorgen"


def test_id_traegt_ein_quellen_praefix(modul):
    """Beide Quellen schreiben in dieselbe Tabelle. Ohne Praefix koennten
    eine handball.net-Spielnummer und eine Sportradar-UUID kollidieren -
    und tvb_spiele.id ist der Primaerschluessel."""
    assert modul._spiel_aus_neu(_neues_spiel(), "87353")["id"].startswith("n")


# --- Quelle 2: Sportradar (Profis) -----------------------------------------

def _sr_antwort(heim="TVB Stuttgart", gast="THW Kiel", final=True):
    return {"data": {"fixtures": [{
        "competitors": [
            {"name": heim, "isHome": True, "score": 30},
            {"name": gast, "isHome": False, "score": 28},
        ],
        "fixture": {"date": "2026-09-05T17:30:00", "isFinal": final,
                    "fixtureId": "d803da2c-79f2-11f1"},
    }]}}


def test_profispiel_wird_erkannt(modul, monkeypatch):
    monkeypatch.setattr(modul, "_sr_get", lambda p: _sr_antwort())
    spiele = modul._profi_spiele()
    assert len(spiele) == 1
    s = spiele[0]
    assert s["heim"] == "TVB Stuttgart" and s["gast"] == "THW Kiel"
    assert (s["heim_tore"], s["gast_tore"]) == (30, 28)
    assert s["team_id"] == modul._PROFI_TEAM_ID
    assert s["wettbewerb"] == "Opel HBL"


def test_fremde_paarung_wird_nicht_eingesammelt(modul, monkeypatch):
    """Das Embed liefert den Spieltag ALLER 18 Mannschaften. Ohne Filter
    stuenden 17 fremde Begegnungen im Spielplan der Familie."""
    monkeypatch.setattr(modul, "_sr_get",
                        lambda p: _sr_antwort(heim="SC Magdeburg", gast="THW Kiel"))
    assert modul._profi_spiele() == []


def test_profispiel_auch_auswaerts(modul, monkeypatch):
    monkeypatch.setattr(modul, "_sr_get",
                        lambda p: _sr_antwort(heim="THW Kiel", gast="TVB Stuttgart"))
    spiele = modul._profi_spiele()
    assert len(spiele) == 1 and spiele[0]["gast"] == "TVB Stuttgart"


def test_sportradar_zeit_gilt_als_utc(modul, monkeypatch):
    """Sportradar liefert die Zeit OHNE Zeitzone. Wird sie als Ortszeit
    gelesen, verschiebt sich jeder Anwurf um zwei Stunden."""
    monkeypatch.setattr(modul, "_sr_get", lambda p: _sr_antwort())
    assert modul._profi_spiele()[0]["anstoss"].startswith("2026-09-05T19:30")


def test_quelle_weg_ergibt_leere_liste(modul, monkeypatch):
    monkeypatch.setattr(modul, "_sr_get", lambda p: None)
    assert modul._profi_spiele() == []


# --- Tabellen --------------------------------------------------------------

def test_tabelle_der_neuen_api(modul):
    antwort = {"data": [{"position": 1, "team": {"name": "TV BITTENFELD II"},
                         "played": 2, "won": 2, "drawn": 0, "lost": 0,
                         "goals_for": 60, "goals_against": 50, "goals_diff": 10,
                         "points": 4}]}
    zeilen = modul._tabelle_aus_neu(antwort, "TV Bittenfeld II")
    assert zeilen[0]["punkte"] == 4 and zeilen[0]["tordifferenz"] == 10
    # Gross-/Kleinschreibung weicht zwischen Tabelle und Mannschaftsname ab.
    assert zeilen[0]["hervorgehoben"] is True


def test_nur_der_aktuelle_spieltag_steht_in_der_tabelle(modul):
    """Der teuerste Fund des Neubaus: Die API liefert die Tabelle JE
    SPIELTAG. Fuer die 3. Liga sind das 30 Runden a 16 Mannschaften - ohne
    Auswahl stuenden 480 Zeilen untereinander auf der Seite.

    Genommen wird die Runde mit den meisten ausgetragenen Spielen. Nicht die
    hoechste Rundennummer: die Runden sind fuer die ganze Saison vorangelegt
    und tragen bis dahin denselben Zwischenstand."""
    def zeile(runde, gespielt, punkte, name):
        return {"position": 1, "round": runde, "team": {"name": name},
                "played": gespielt, "won": 0, "drawn": 0, "lost": 0,
                "goals_for": 0, "goals_against": 0, "goals_diff": 0,
                "points": punkte}

    antwort = {"data": [
        zeile(1, 1, 2, "A"), zeile(1, 1, 0, "B"),
        zeile(9, 3, 6, "A"), zeile(9, 3, 0, "B"),   # der aktuelle Stand
        zeile(30, 1, 2, "A"), zeile(30, 1, 0, "B"), # vorangelegt
    ]}
    zeilen = modul._tabelle_aus_neu(antwort, "A")
    assert len(zeilen) == 2, f"{len(zeilen)} Zeilen statt einer Tabelle"
    assert zeilen[0]["punkte"] == 6, "nicht der weiteste Spieltag genommen"


def test_tabelle_vor_dem_saisonstart_gilt_als_leer(modul):
    """Am laufenden Portal gefunden: Die API legt die Tabelle schon vor dem
    ersten Spieltag an - mit `position` 0 und ueberall Nullen. Ausgegeben
    saehe das aus wie eine Tabelle, in der zehn Mannschaften gemeinsam auf
    Rang 0 stehen. Der vorhandene Hinweis 'noch keine Tabelle' sagt die
    Wahrheit besser."""
    antwort = {"data": [
        {"position": 0, "round": 1, "team": {"name": "A"}, "played": 0, "points": 0},
        {"position": 0, "round": 1, "team": {"name": "B"}, "played": 0, "points": 0},
    ]}
    assert modul._tabelle_aus_neu(antwort, "A") == []


def test_ein_einziges_gespieltes_spiel_genuegt(modul):
    """Gegenprobe: sobald irgendwo angeworfen wurde, ist die Tabelle echt."""
    antwort = {"data": [
        {"position": 1, "round": 1, "team": {"name": "A"}, "played": 1, "points": 2},
        {"position": 2, "round": 1, "team": {"name": "B"}, "played": 0, "points": 0},
    ]}
    assert len(modul._tabelle_aus_neu(antwort, "A")) == 2


def test_tabelle_kommt_nach_rang_sortiert(modul):
    """Die Vorlage gibt die Liste unveraendert aus."""
    antwort = {"data": [
        {"position": 3, "round": 1, "team": {"name": "C"}, "played": 1},
        {"position": 1, "round": 1, "team": {"name": "A"}, "played": 1},
        {"position": 2, "round": 1, "team": {"name": "B"}, "played": 1},
    ]}
    assert [z["rang"] for z in modul._tabelle_aus_neu(antwort, "A")] == [1, 2, 3]


def test_leere_tabelle_ist_kein_fehler(modul):
    """Amateur- und Jugendligen haben vor dem Saisonstart keine Tabelle.
    Leere Liste heisst 'noch nichts da', None heisst 'Stoerung' - die
    Vorlage zeigt nur Letzteres als Fehler an."""
    assert modul._tabelle_aus_neu({"data": []}, "X") == []
    assert modul._tabelle_aus_neu(None, "X") is None


def test_profi_tabelle_rechnet_die_punkte_um(modul):
    antwort = {"data": {"standings": [{"rows": [
        {"position": 4, "team": {"name": "TVB Stuttgart"},
         "results": {"played": 3, "wins": 2, "draws": 0, "losses": 1,
                     "scoredFor": 90, "scoredAgainst": 85, "pointDifference": 5,
                     "combinedStandingPoints": "4:2"}},
    ]}]}}
    zeile = modul._tabelle_aus_sr(antwort)[0]
    assert zeile["punkte"] == 4, "Plus- und Minuspunkte nicht getrennt"
    assert zeile["hervorgehoben"] is True
    assert zeile["spiele"] == 3


def test_profi_tabelle_ohne_daten(modul):
    assert modul._tabelle_aus_sr(None) is None
    assert modul._tabelle_aus_sr({"data": {"standings": []}}) == []


# --- Altersklassen ---------------------------------------------------------

@pytest.mark.parametrize("alters,geschlecht,erwartet", [
    ("ERWACHSENE", "M", "Herren"),
    ("ERWACHSENE", "F", "Damen"),
    ("A-JUGEND", "M", "mA"),
    ("B-JUGEND", "F", "wB"),
    ("E-JUGEND", "X", "gE"),
])
def test_klassen_kuerzel_bleibt_beim_alten_schema(modul, alters, geschlecht, erwartet):
    """Die pro Nutzer ausgeblendeten Altersklassen (#124) sind unter genau
    diesen Kuerzeln gespeichert. Ein neues Schema haette jedem
    stillschweigend seine Einstellungen zurueckgesetzt."""
    assert modul._klassen_kuerzel(alters, geschlecht) == erwartet


def test_jedes_kuerzel_hat_einen_anzeigenamen(modul):
    """Sonst stuende auf der Einstellungsseite ein leerer Haken."""
    for alters in ("ERWACHSENE", "A-JUGEND", "B-JUGEND", "C-JUGEND",
                   "D-JUGEND", "E-JUGEND", "F-JUGEND"):
        for geschlecht in ("M", "F", "X"):
            assert modul._klassen_kuerzel(alters, geschlecht) in modul._KLASSEN_NAMEN
