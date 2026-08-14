"""Wünsche #217, #218, #219 – Bedienung der Packliste bei langen Listen.

Alle drei kommen aus derselben Beobachtung: sobald eine Packliste länger ist
als ein Bildschirm, ist sie mühsam. #217 erweitert den Filter (bisher nur
Person) um Kategorie und Packstatus, #218 bringt einen Pfeil zurück an den
Anfang, #219 einen Plus-Knopf an jeder Kategorie-Überschrift.

Die Umsetzung ist vollständig im Browser – der Server liefert weiterhin die
ganze Liste. Getestet wird deshalb das, was ohne Browser prüfbar ist und
worauf sich das JavaScript verlässt: dass jeder Eintrag die drei Merkmale
mitbringt, nach denen gefiltert wird, dass die Knöpfe da sind und einen Namen
haben – und dass keiner davon ins Leere zeigt.

**Der Fund beim Bauen** steckt in `test_eintraege_ohne_kategorie_passen_zu_ihrer_ueberschrift`:
Einträge ohne (oder mit abgeschalteter) Kategorie standen unter der
Überschrift „Ohne Kategorie", trugen aber `data-kategorie="None"` – der Wert
kam aus `item.kategorie_id` und nicht aus der Gruppe, in der sie wirklich
landen. Die Überschrift passte damit zu keinem ihrer Einträge: sie liess sich
im Packmodus nicht ausblenden und wäre mit #217 auch nicht filterbar gewesen.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
PACKLISTE = TPL / "packliste.html"


@pytest.fixture()
def liste(app, db):
    """Eine Liste mit allem, was die Filter unterscheiden müssen: zwei
    Kategorien, ein Eintrag ohne Kategorie, ein gepackter, ein persönlicher
    und ein allgemeiner."""
    from teile.kern import token_lookup, new_token
    v = db["verbindung"]
    familie = db["familie"]

    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='packliste'").fetchone()["id"]
        klartext = new_token()
        v.execute("INSERT OR IGNORE INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                  (familie["TestAdmin"]["id"], app_id, token_lookup(klartext)))

    zid = v.execute(
        "INSERT INTO packlisten_ziele(name) VALUES('Sommerurlaub') RETURNING id"
    ).fetchone()["id"]
    kats = v.execute(
        "SELECT id, name FROM packlisten_kategorien WHERE aktiv=1 ORDER BY position, name LIMIT 2"
    ).fetchall()
    assert len(kats) >= 2, "Seed-Kategorien fehlen"

    kind = familie["TestKind"]["id"]
    eintraege = [
        # name,           kategorie,   person, gepackt
        ("Zahnbuerste",   kats[0]["id"], kind,  0),
        ("Reiseapotheke", kats[0]["id"], None,  0),
        ("Badehose",      kats[1]["id"], kind,  0),
        ("Sonnencreme",   kats[1]["id"], None,  1),
        ("Reisepass",     None,          None,  0),
    ]
    for pos, (name, kat, person, gepackt) in enumerate(eintraege):
        v.execute(
            "INSERT INTO packlisten_eintraege"
            "(name, ziel_id, kategorie_id, person_id, gepackt, gepackt_am, position) "
            "VALUES(?,?,?,?,?,CASE WHEN ?=1 THEN datetime('now') ELSE NULL END,?)",
            (name, zid, kat, person, gepackt, gepackt, pos),
        )
    v.commit()
    return {"token": klartext, "ziel": zid, "kategorien": kats}


@pytest.fixture()
def seite(client, liste):
    return client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}") \
                 .get_data(as_text=True)


def _karte(seite, name):
    """Das <div class="item-card …"> eines Eintrags, an seinem Namen gesucht."""
    treffer = re.search(
        r'(<div class="item-card[^>]*>)(?:(?!</div>).)*?'
        r'<span class="item-name">' + re.escape(name) + '</span>',
        seite, re.S)
    assert treffer, f"Eintrag {name!r} nicht auf der Seite"
    return treffer.group(1)


# ── #217: Filter nach Kategorie und Packstatus ─────────────────────────────

def test_filter_hat_alle_drei_zeilen(seite):
    for zeile in ("filter-person-row", "filter-kategorie-row", "filter-status-row"):
        assert f'id="{zeile}"' in seite, f"{zeile} fehlt – Wunsch #217"


def test_jede_aktive_kategorie_ist_waehlbar(seite, liste):
    zeile = re.search(r'id="filter-kategorie-row".*?</div>', seite, re.S).group(0)
    for kat in liste["kategorien"]:
        assert f'data-value="{kat["id"]}"' in zeile, (
            f"Kategorie {kat['name']!r} fehlt im Filter")


def test_packstatus_ist_waehlbar(seite):
    zeile = re.search(r'id="filter-status-row".*?</div>', seite, re.S).group(0)
    assert 'data-value="offen"' in zeile
    assert 'data-value="gepackt"' in zeile


def test_jeder_eintrag_traegt_die_drei_filtermerkmale(seite):
    """Woran das JavaScript filtert. Fehlt eines, filtert der Knopf ins Leere
    – und zwar still, weil ein fehlendes data-Attribut in JS `undefined` ist
    und keinen Fehler wirft."""
    for karte in re.findall(r'<div class="item-card[^>]*>', seite):
        for merkmal in ("data-kategorie=", "data-person=", "data-gepackt="):
            assert merkmal in karte, f"{merkmal} fehlt: {karte}"


def test_gepackt_steht_am_eintrag_und_stimmt(seite):
    assert 'data-gepackt="1"' in _karte(seite, "Sonnencreme")
    assert 'data-gepackt="0"' in _karte(seite, "Zahnbuerste")


def test_eintraege_ohne_kategorie_passen_zu_ihrer_ueberschrift(seite):
    """Der Fund beim Bauen: `data-kategorie` kam aus `item.kategorie_id` und
    stand bei Einträgen ohne Kategorie auf "None" – die Überschrift „Ohne
    Kategorie" trägt aber `data-kategorie-label=""`. Beide müssen
    zusammenpassen, sonst findet weder der Filter noch das Ausblenden im
    Packmodus die Einträge zu ihrer Gruppe."""
    assert 'data-kategorie=""' in _karte(seite, "Reisepass")
    assert 'data-kategorie="None"' not in seite
    assert 'data-kategorie-label=""' in seite


def test_ohne_kategorie_chip_nur_wenn_es_solche_eintraege_gibt(client, liste, db):
    zeile = re.search(r'id="filter-kategorie-row".*?</div>',
                      client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}")
                            .get_data(as_text=True), re.S).group(0)
    assert "Ohne Kategorie" in zeile

    # Denselben Eintrag einsortieren -> der Chip muss verschwinden, sonst
    # bietet der Filter eine Auswahl an, die garantiert nichts findet.
    db["verbindung"].execute(
        "UPDATE packlisten_eintraege SET kategorie_id=? WHERE name='Reisepass'",
        (liste["kategorien"][0]["id"],))
    db["verbindung"].commit()

    zeile = re.search(r'id="filter-kategorie-row".*?</div>',
                      client.get(f"/a/packliste/{liste['token']}/?ziel={liste['ziel']}")
                            .get_data(as_text=True), re.S).group(0)
    assert "Ohne Kategorie" not in zeile


# ── #218: zurück an den Anfang ─────────────────────────────────────────────

def test_der_pfeil_nach_oben_ist_da(seite):
    assert 'id="nach-oben-btn"' in seite, "Wunsch #218"


def test_der_pfeil_braucht_keine_twemoji_grafik():
    """`↑` (U+2191) ohne Varianten-Selektor bleibt normaler Text – Twemoji
    ersetzt es nicht, also braucht es keine SVG-Datei. Steht ein `️`
    dahinter, wäre es plötzlich ein Emoji und die Kachel unter Linux/Chrome
    leer (siehe test_emoji.py). Genau diese Falle hat Wunsch #147 ausgelöst."""
    quelle = PACKLISTE.read_text(encoding="utf-8")
    treffer = re.search(r'id="nach-oben-btn".*?</button>', quelle, re.S)
    assert treffer, "Knopf nicht gefunden"
    assert "↑️" not in treffer.group(0), (
        "Varianten-Selektor hinter dem Pfeil – dann braucht es 2191.svg")


# ── #219: Plus-Knopf an der Kategorie ──────────────────────────────────────

def test_jede_kategorie_mit_eintraegen_hat_einen_plus_knopf(seite, liste):
    for kat in liste["kategorien"]:
        block = re.search(
            r'<div class="kat-label" data-kategorie-label="%d">.*?</div>' % kat["id"],
            seite, re.S)
        assert block, f"Überschrift für {kat['name']!r} fehlt"
        assert 'class="kat-plus"' in block.group(0), (
            f"Kein Plus-Knopf bei {kat['name']!r} – Wunsch #219")
        assert f"[{kat['id']}]" in block.group(0), (
            "Der Knopf gibt die Kategorie nicht weiter, kann also nichts vorbelegen")


def test_ohne_kategorie_hat_keinen_plus_knopf(seite):
    """„Ohne Kategorie" ist nichts, was man auswählen kann – das Formular
    verlangt eine Kategorie. Ein Knopf, der nichts vorbelegen kann, wäre eine
    Sackgasse."""
    block = re.search(r'<div class="kat-label" data-kategorie-label="">.*?</div>',
                      seite, re.S)
    assert block, 'Überschrift „Ohne Kategorie“ fehlt'
    assert "kat-plus" not in block.group(0)


def test_der_plus_knopf_sagt_welche_kategorie(seite, liste):
    """Ein Icon-Knopf braucht einen Namen (Wunsch #175) – und „Hinzufügen"
    allein hilft nicht, wenn er zehnmal auf der Seite steht."""
    name = liste["kategorien"][0]["name"]
    block = re.search(
        r'<button[^>]*class="kat-plus".*?</button>', seite, re.S).group(0)
    aria = re.search(r'aria-label="([^"]*)"', block)
    titel = re.search(r'title="([^"]*)"', block)
    assert aria and titel, "aria-label oder title fehlt"
    assert aria.group(1) == titel.group(1)
    assert name in aria.group(1), (
        f"Der Name nennt die Kategorie nicht: {aria.group(1)!r}")


# ── #223: Der Filter bleibt, bis er zurückgesetzt wird ─────────────────────

def _skript():
    return PACKLISTE.read_text(encoding="utf-8")


def test_der_filter_ueberlebt_das_verlassen_der_app():
    """„Also auch wenn man die App verlässt und wieder zurückkommt, soll der
    Filter noch immer da sein" – das ist localStorage, nicht sessionStorage.

    Die Vokabel-App macht es bewusst andersherum (Wunsch #220 verlangte dort
    wörtlich „solange der Benutzer die App nicht verlässt"). Zwei Apps, zwei
    Zusagen – deshalb prüft dieser Test ausdrücklich das Gegenteil dessen,
    was `test_vokabeln_filter.py` prüft."""
    quelle = _skript()
    assert "localStorage.setItem(FILTER_KEY" in quelle
    assert "sessionStorage.setItem(FILTER_KEY" not in quelle


def test_der_gemerkte_filter_wird_beim_laden_angewandt():
    """Ohne diesen Aufruf läge der Filter zwar gespeichert vor, die Liste
    zeigte aber wieder alles – und nach dem Anlegen eines Eintrags (Redirect,
    also Neuladen) wäre er jedes Mal weg. Genau das war die Beschwerde."""
    quelle = _skript()
    assert re.search(r"^\s*filterWiederherstellen\(\);", quelle, re.M), (
        "filterWiederherstellen() wird beim Laden nicht aufgerufen")


def test_zuruecksetzen_loescht_auch_das_gemerkte():
    """Der Fehler, der sich sonst einschleicht: Die Chips gehen aus, die
    Liste ist wieder vollständig – und beim nächsten Öffnen ist der Filter
    zurück, weil nur die Anzeige zurückgesetzt wurde."""
    quelle = _skript()
    block = quelle[quelle.index("function filterZuruecksetzen"):]
    block = block[:block.index("\n}")]
    assert "removeItem(FILTER_KEY)" in block, (
        "Zurücksetzen entfernt den gemerkten Filter nicht - er käme beim "
        "nächsten Öffnen wieder")


def test_ein_aktiver_filter_ist_ueber_der_liste_sichtbar(seite):
    """Ein Filter, der Tage überdauert, muss sich zeigen. Wer zurückkommt,
    erinnert sich nicht – und eine Liste, die die Hälfte verschweigt, sieht
    aus wie verlorene Einträge."""
    assert 'id="filter-banner"' in seite
    assert 'id="filter-banner-reset"' in seite, (
        "Das Band nennt keinen Ausweg - „bis man den Filter zurück setzt“ "
        "braucht eine Stelle, an der man genau das tut")


def test_konstanten_stehen_vor_ihrer_benutzung():
    """`const` liegt bis zur Deklaration in der temporalen Todeszone: Wer sie
    weiter unten deklariert und oben benutzt, bekommt keinen `undefined`-Wert,
    sondern einen ReferenceError – und der reisst den GESAMTEN Skriptblock
    mit, nicht nur die eine Zeile.

    Genau das ist beim Bauen von #223 passiert: `FILTER_KEY` brauchte `TOKEN`,
    das 100 Zeilen weiter unten stand. Die Seite hätte gar kein JavaScript
    mehr ausgeführt – kein Filter, kein Umsortieren, kein Abhaken."""
    quelle = _skript()
    skript = quelle[quelle.index("{% block extra_scripts %}"):]
    # Kommentare heraus, sonst zaehlt der Test seine eigene Erklaerung mit -
    # genau darueber ist er beim Schreiben gestolpert. Die Positionen bleiben
    # erhalten (gleiche Laenge, Inhalt durch Leerzeichen ersetzt), damit der
    # Vergleich unten weiter stimmt.
    def _ohne(muster, text):
        return re.sub(muster, lambda m: " " * len(m.group(0)), text, flags=re.S | re.M)
    skript = _ohne(r"/\*.*?\*/", _ohne(r"//[^\n]*", skript))

    for name in ("TOKEN", "TP"):
        deklaration = skript.index(f"const {name}")
        erste_nutzung = min(
            (m.start() for m in re.finditer(rf"\b{name}\b", skript)), default=deklaration)
        assert erste_nutzung >= deklaration, (
            f"{name} wird vor seiner Deklaration benutzt - ReferenceError beim Laden")


# ── Kein Knopf zeigt ins Leere ─────────────────────────────────────────────

def test_jede_verdrahtete_aktion_existiert_auch():
    """`data-klick="…"` löst der Verteiler in base.html über `window[name]`
    auf. Ein Tippfehler ergibt einen Knopf, der nichts tut – der Verteiler
    schreibt zwar in die Konsole, aber die sieht im Betrieb niemand.

    Gegenprobe beim Schreiben gemacht: mit `data-klick="neuInKategorieX"`
    schlägt der Test an."""
    quelle = PACKLISTE.read_text(encoding="utf-8")
    verdrahtet = set(re.findall(r'data-(?:klick|aendern|eingabe)="(\w+)"', quelle))
    assert verdrahtet, "Muster kaputt – es wurde gar keine Aktion gefunden"
    for name in verdrahtet:
        assert re.search(r'function\s+%s\s*\(' % re.escape(name), quelle), (
            f"data-klick=\"{name}\" zeigt auf eine Funktion, die es in "
            f"packliste.html nicht gibt")
