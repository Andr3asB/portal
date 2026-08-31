"""Wunsch #224: Kanban-Brett für die Aufgaben.

Die vier Status gibt es seit Wunsch #20 – neu sind die Ansicht und die
Reihenfolge INNERHALB einer Spalte (`todos.position`), also die Priorisierung
von Hand.

Der Kern liegt in zwei Rechten, die bewusst auseinanderfallen und die dieser
Test auseinanderhält:

* **Spalte wechseln** ändert den Zustand einer Aufgabe und verlangt deshalb
  dasselbe wie das Abhaken (`_darf_erledigen`, geschärft durch Audit-Befund
  F-06 in Wunsch #214).
* **Umsortieren** innerhalb einer Spalte ist Arbeitsorganisation und steht
  jedem offen, der das Brett sieht – dasselbe Muster wie `reorder()` in
  17_packliste.py („wer packen darf, darf auch sortieren").

Der zweite Schwerpunkt ist der geteilte Zieh-Helfer in `base.html`. Er wurde
für dieses Brett um Spaltenwechsel erweitert – **additiv**, denn Packliste
(#181) und Einkauf verlassen sich ausdrücklich darauf, dass man dort NICHT
quer ziehen kann. `test_der_spaltenwechsel_ist_optional` hält das fest.
"""
import pathlib
import re

import pytest

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = TPL / "base.html"
BRETT = TPL / "todo_kanban.html"


@pytest.fixture()
def brett(app, db):
    """Vier Aufgaben in zwei Spalten, dazu eine private fremde."""
    from teile.kern import new_token, token_lookup
    v = db["verbindung"]
    familie = db["familie"]
    tokens = {}
    with app.app_context():
        app_id = v.execute("SELECT id FROM apps WHERE slug='todo'").fetchone()["id"]
        for name, daten in familie.items():
            if "todo" in daten["tokens"]:
                tokens[name] = daten["tokens"]["todo"]
                continue
            klartext = new_token()
            v.execute("INSERT INTO grants(user_id, app_id, token_lookup) VALUES(?,?,?)",
                      (daten["id"], app_id, token_lookup(klartext)))
            tokens[name] = klartext

    kind = familie["TestKind"]["id"]
    eltern = familie["TestEltern"]["id"]
    ids = {}
    for schluessel, inhalt, status, pos, von, fuer, privat in [
        ("a", "Müll rausbringen", "offen",     0, eltern, kind,   0),
        ("b", "Spülmaschine",     "offen",     1, eltern, kind,   0),
        ("c", "Rasen mähen",      "in_arbeit", 0, eltern, eltern, 0),
        ("d", "Geschenk besorgen", "backlog",  0, eltern, None,   0),
        ("geheim", "Überraschung", "offen",    2, eltern, eltern, 1),
    ]:
        ids[schluessel] = v.execute(
            "INSERT INTO todos(inhalt, status, position, erstellt_von, zugewiesen_an, privat) "
            "VALUES(?,?,?,?,?,?) RETURNING id",
            (inhalt, status, pos, von, fuer, privat)).fetchone()["id"]
    v.commit()
    return {"tokens": tokens, "ids": ids, "kind": kind, "eltern": eltern}


def _verschieben(client, token, tid, status, order):
    return client.post(f"/a/todo/{token}/kanban/verschieben",
                       json={"id": tid, "status": status, "order": order})


def _status(db, tid):
    return db["verbindung"].execute(
        "SELECT status, erledigt, position FROM todos WHERE id=?", (tid,)).fetchone()


# ── Das Brett selbst ───────────────────────────────────────────────────────

def test_alle_vier_spalten_stehen_da(client, brett):
    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    for status in ("backlog", "offen", "in_arbeit", "erledigt"):
        assert f'data-status="{status}"' in seite, status


def test_die_liste_verlinkt_das_brett(client, brett):
    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/").get_data(as_text=True)
    assert "kanban" in seite, "Von der Liste führt kein Weg aufs Brett"


def test_das_brett_fuehrt_zurueck(client, brett):
    """Projektkonvention: keine Sackgassen – jede Unterseite braucht einen
    eigenen Zurück-Link, der ⌂-Knopf ist kein Ersatz.

    Seit #225 muss der Link `?ansicht=liste` tragen: Ohne den Zusatz schickte
    die gemerkte Ansicht („Brett") einen sofort wieder hierher zurück, und man
    käme nie mehr in die Liste."""
    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    assert re.search(r'href="/a/todo/[^"]*\?ansicht=liste"', seite), (
        "Kein Weg zurück in die Liste - oder einer, der sofort zurückspringt")


def _spalte(seite, status):
    """Der Markup-Block EINER Brett-Spalte.

    Die Grenze hängt an `class="spalte" data-status=` und nicht nur an
    `data-status=`: Seit #225 tragen auch die KARTEN ein `data-status`
    (der geteilte Filter arbeitet daran), und mit dem kürzeren Muster endete
    die Spalte schon bei ihrer ersten Karte."""
    treffer = re.search(
        rf'<div class="spalte" data-status="{status}">'
        rf'.*?(?=<div class="spalte" data-status=|</div>\s*</main>)', seite, re.DOTALL)
    assert treffer, f"Spalte {status} nicht gefunden"
    return treffer.group(0)


def test_aufgaben_stehen_in_ihrer_spalte(client, brett):
    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    spalte = _spalte(seite, "in_arbeit")
    assert "Rasen mähen" in spalte
    assert "Müll rausbringen" not in spalte


def test_die_reihenfolge_folgt_der_position(client, brett, db):
    db["verbindung"].execute("UPDATE todos SET position=5 WHERE id=?", (brett["ids"]["a"],))
    db["verbindung"].commit()
    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    assert seite.index("Spülmaschine") < seite.index("Müll rausbringen")


def test_bei_gleicher_position_steht_das_neuere_oben(client, brett, db):
    """Nach der Migration hat JEDE bestehende Aufgabe position=0 (der
    DEFAULT). Ohne einen Gleichstand-Entscheider stünde das Brett anfangs
    komplett auf dem Kopf – älteste zuerst, während die Liste daneben neueste
    zuerst zeigt. Zwei Ansichten desselben Bestands in gegenläufiger
    Reihenfolge sind genau die Sorte Kleinigkeit, die Vertrauen kostet."""
    v = db["verbindung"]
    v.execute("UPDATE todos SET position=0")
    v.execute("UPDATE todos SET erstellt='2026-01-01 08:00:00' WHERE id=?",
              (brett["ids"]["a"],))
    v.execute("UPDATE todos SET erstellt='2026-06-01 08:00:00' WHERE id=?",
              (brett["ids"]["b"],))
    v.commit()

    seite = client.get(f"/a/todo/{brett['tokens']['TestAdmin']}/kanban").get_data(as_text=True)
    assert seite.index("Spülmaschine") < seite.index("Müll rausbringen"), (
        "Bei gleicher Position steht die ältere Aufgabe oben - das Brett läuft "
        "der Liste entgegen")


def _kartentexte(seite):
    """Nur die Aufgabentexte der Karten.

    Bewusst nicht die ganze Seite durchsuchen: Seit #225 steht das geteilte
    JavaScript samt seiner deutschen Kommentare mit im Quelltext, und dort kam
    zufällig das Wort „Überraschung" vor – der Test schlug an, obwohl die
    Aufgabe nirgends gerendert war. Ein Wächter, der an einem Kommentar
    hängenbleibt, sagt beim nächsten Mal nichts mehr aus."""
    return re.findall(r'<div class="karte-text">\s*([^<]*)', seite)


def test_fremde_private_aufgaben_stehen_nicht_auf_dem_brett(client, brett):
    """Dieselbe Sichtbarkeitsregel wie die Liste – das Brett darf kein
    Schlupfloch daneben sein."""
    seite = client.get(f"/a/todo/{brett['tokens']['TestKind']}/kanban").get_data(as_text=True)
    texte = " ".join(_kartentexte(seite))
    assert texte, "Gar keine Karten gefunden - Muster kaputt?"
    assert "Überraschung" not in texte


# ── Spalte wechseln = Status ───────────────────────────────────────────────

def test_verschieben_aendert_den_status(client, brett, db):
    antwort = _verschieben(client, brett["tokens"]["TestAdmin"],
                           brett["ids"]["a"], "in_arbeit", [brett["ids"]["a"]])
    assert antwort.status_code == 200
    assert _status(db, brett["ids"]["a"])["status"] == "in_arbeit"


def test_in_die_erledigt_spalte_hakt_ab(client, brett, db):
    """Sonst stünde die Aufgabe im Brett auf „Erledigt", in der Liste aber
    weiter als offen – zwei Wahrheiten über dieselbe Aufgabe."""
    _verschieben(client, brett["tokens"]["TestAdmin"],
                 brett["ids"]["a"], "erledigt", [brett["ids"]["a"]])
    zeile = _status(db, brett["ids"]["a"])
    assert zeile["status"] == "erledigt" and zeile["erledigt"] == 1


def test_zurueck_aus_erledigt_hebt_das_abhaken_auf(client, brett, db):
    tid = brett["ids"]["a"]
    _verschieben(client, brett["tokens"]["TestAdmin"], tid, "erledigt", [tid])
    _verschieben(client, brett["tokens"]["TestAdmin"], tid, "offen", [tid])
    zeile = _status(db, tid)
    assert zeile["status"] == "offen" and zeile["erledigt"] == 0


def test_unbekannter_status_wird_abgelehnt(client, brett, db):
    antwort = _verschieben(client, brett["tokens"]["TestAdmin"],
                           brett["ids"]["a"], "erfunden", [brett["ids"]["a"]])
    assert antwort.status_code == 400
    assert _status(db, brett["ids"]["a"])["status"] == "offen"


# ── Umsortieren = Priorität ────────────────────────────────────────────────

def test_umsortieren_wird_gespeichert(client, brett, db):
    """„Wenn ich die Aufgaben umpriorisiere, dann soll diese Information
    gespeichert werden" – wörtlich aus dem Wunsch."""
    a, b = brett["ids"]["a"], brett["ids"]["b"]
    _verschieben(client, brett["tokens"]["TestAdmin"], b, "offen", [b, a])
    assert _status(db, b)["position"] == 0
    assert _status(db, a)["position"] == 1


def test_umsortieren_darf_jeder_der_das_brett_sieht(client, brett, db):
    """Wie bei der Packliste (#178): Die Reihenfolge ist Arbeitsorganisation,
    kein Eingriff in fremde Aufgaben. Das Kind darf „Rasen mähen" nicht in
    eine andere Spalte schieben – die Reihenfolge seiner eigenen Spalte aber
    sehr wohl bestimmen."""
    a, b = brett["ids"]["a"], brett["ids"]["b"]
    antwort = _verschieben(client, brett["tokens"]["TestKind"], b, "offen", [b, a])
    assert antwort.status_code == 200
    assert _status(db, b)["position"] == 0


def test_eine_fremde_id_in_der_reihenfolge_bewirkt_nichts(client, brett, db):
    """Untergeschobene IDs dürfen keine fremden Aufgaben umsortieren – und die
    eigene Sortierung muss trotzdem heil durchkommen."""
    vorher = _status(db, brett["ids"]["geheim"])["position"]
    a = brett["ids"]["a"]
    antwort = _verschieben(client, brett["tokens"]["TestKind"], a, "offen",
                           [brett["ids"]["geheim"], a])
    assert antwort.status_code == 200
    assert _status(db, brett["ids"]["geheim"])["position"] == vorher
    assert _status(db, a)["position"] == 1


# ── Wer darf die Spalte wechseln ───────────────────────────────────────────

def test_kind_darf_fremde_aufgabe_nicht_verschieben(client, brett, db):
    """„Geschenk besorgen" ist niemandem zugewiesen und nicht privat – das
    Kind SIEHT es also (dritte Bedingung in `_visible_todos`), darf es aber
    nicht abhaken und damit auch nicht verschieben.

    Genau diese Kombination ist die interessante: Sichtbarkeit und
    Änderungsrecht fallen hier auseinander. „Rasen mähen" taugt dafür nicht –
    das ist den Eltern zugewiesen und für das Kind gar nicht sichtbar, es
    bekäme 404 statt 403 (siehe `test_unsichtbare_aufgabe_gibt_404_nicht_403`)."""
    antwort = _verschieben(client, brett["tokens"]["TestKind"],
                           brett["ids"]["d"], "erledigt", [brett["ids"]["d"]])
    assert antwort.status_code == 403
    assert _status(db, brett["ids"]["d"])["status"] == "backlog"


def test_kind_darf_die_eigene_aufgabe_verschieben(client, brett, db):
    antwort = _verschieben(client, brett["tokens"]["TestKind"],
                           brett["ids"]["a"], "in_arbeit", [brett["ids"]["a"]])
    assert antwort.status_code == 200
    assert _status(db, brett["ids"]["a"])["status"] == "in_arbeit"


def test_unsichtbare_aufgabe_gibt_404_nicht_403(client, brett, db):
    """Wer eine Aufgabe nicht sehen darf, soll auch nicht erfahren, dass es
    sie gibt – 403 wäre eine Existenzbestätigung."""
    antwort = _verschieben(client, brett["tokens"]["TestKind"],
                           brett["ids"]["geheim"], "erledigt", [brett["ids"]["geheim"]])
    assert antwort.status_code == 404


def test_ohne_grant_kein_brett(client, brett, db):
    fremd = db["familie"]["TestKind"]["tokens"]["einkauf"]
    assert client.get(f"/a/todo/{fremd}/kanban").status_code == 403
    assert _verschieben(client, fremd, brett["ids"]["a"], "offen", []).status_code == 403


# ── Neue Aufgaben stören die Sortierung nicht ──────────────────────────────

def test_neue_aufgabe_landet_am_ende_ihrer_spalte(client, brett, db):
    """Dieselbe Lehre wie bei der Packliste (#178): Landet jede neue Aufgabe
    oben, schiebt sie die von Hand gesetzte Priorität jedes Mal durcheinander
    – und genau die ist hier der Sinn der Übung."""
    client.post(f"/a/todo/{brett['tokens']['TestAdmin']}/neu",
                data={"inhalt": "Ganz neu", "ziel_typ": "person"})
    neu = db["verbindung"].execute(
        "SELECT position, status FROM todos WHERE inhalt='Ganz neu'").fetchone()
    hoechste = db["verbindung"].execute(
        "SELECT MAX(position) m FROM todos WHERE status=? AND inhalt<>'Ganz neu'",
        (neu["status"],)).fetchone()["m"]
    assert neu["position"] > hoechste


# ── Der geteilte Zieh-Helfer ───────────────────────────────────────────────

def test_der_spaltenwechsel_ist_optional():
    """Der wichtigste Test dieser Datei für alles ANDERE im Portal.

    `ziehSortierung()` in base.html wird von Packliste und Einkauf mitbenutzt,
    und dort ist ein Wechsel der Gruppe ausdrücklich unerwünscht (#181: eine
    Vokabel… eine Packlisten-Zeile in eine fremde Kategorie zu ziehen würde
    ihre Kategorie nicht mitändern, sie spränge beim nächsten Laden zurück).

    Die Erweiterung für das Brett muss deshalb an `opt.spalten` hängen – ist
    die Option nicht gesetzt, bleibt alles wie vorher.

    **Erste Fassung dieses Tests war wertlos** und das ist die eigentliche
    Lehre: Er prüfte nur, ob die Zeichenkette `if (opt.spalten)` irgendwo in
    `ziehSortierung` steht. Sie steht dort ZWEIMAL (in `folge` und in `ende`) –
    beim Gegenprobe-Versuch, eine davon zu entfernen, blieb der Test grün.
    Jetzt hängt er an den einzelnen Funktionen."""
    quelle = BASE.read_text(encoding="utf-8")

    def koerper(name):
        block = quelle[quelle.index(f"function {name}(e) {{"):]
        return block[:block.index("\n    }")]

    for name, was in [("folge", "das Einsortieren in eine fremde Spalte"),
                      ("ende",  "das Speichern der Zielspalte")]:
        rumpf = koerper(name)
        assert "opt.spalten" in rumpf, f"{name}() kennt die Option gar nicht"
        assert "if (opt.spalten)" in rumpf, (
            f"In {name}() haengt {was} an keiner Bedingung - dann koennte man "
            f"auch in der Packliste quer ziehen")

    # Und die bestehenden Aufrufer duerfen die Option NICHT setzen.
    for datei in ("packliste.html", "einkauf.html"):
        pfad = TPL / datei
        if pfad.exists():
            assert "spalten:" not in pfad.read_text(encoding="utf-8"), datei


def test_nur_wer_darf_bekommt_einen_griff(client, brett):
    """Ein Griff, der zu 403 führt, wäre schlechte Bedienung – die Sperre
    steht serverseitig ohnehin."""
    seite = client.get(f"/a/todo/{brett['tokens']['TestKind']}/kanban").get_data(as_text=True)
    karte = re.search(r'<div class="karte"[^>]*>.*?Geschenk besorgen', seite, re.DOTALL)
    assert karte, "Aufgabe fehlt auf dem Brett"
    # Nur die Karte selbst ansehen, nicht alles davor: der Treffer beginnt bei
    # der LETZTEN Karten-Eroeffnung vor dem Text.
    letzte = karte.group(0)[karte.group(0).rindex('<div class="karte"'):]
    assert "karte-griff" not in letzte, (
        "Das Kind bekommt einen Ziehgriff für eine Aufgabe, die es nicht "
        "verschieben darf")
    assert "karte-fest" in letzte, "Es fehlt der Hinweis, warum nichts geht"

    # Gegenprobe, damit der Test nicht bloss deshalb gruen ist, weil er die
    # falsche Karte ansieht: die EIGENE Aufgabe hat sehr wohl einen Griff.
    eigene = re.search(r'<div class="karte"[^>]*>.*?Müll rausbringen', seite, re.DOTALL).group(0)
    assert "karte-griff" in eigene[eigene.rindex('<div class="karte"'):]


def test_jede_verdrahtete_aktion_existiert_auch():
    """Ein Tippfehler im `data-klick` ergibt einen Knopf, der still nichts tut.

    Seit #225 kann die Funktion auch in `todo_teile.html` stehen – die
    gemeinsamen Bausteine bringen ihr JavaScript selbst mit. Geprüft wird
    deshalb gegen beide Dateien; die Zusage bleibt dieselbe."""
    quelle = BRETT.read_text(encoding="utf-8")
    gemeinsam = (TPL / "todo_teile.html").read_text(encoding="utf-8")
    verdrahtet = set(re.findall(r'data-(?:klick|aendern|eingabe)="(\w+)"',
                                quelle + gemeinsam))
    assert verdrahtet, "Muster kaputt - gar keine Aktion gefunden"
    for name in verdrahtet:
        assert re.search(rf"function\s+{re.escape(name)}\s*\(", quelle + gemeinsam), name


# --- Wunsch #236: Spaltenbreite auf dem Desktop ----------------------------

def test_spalten_haben_auf_dem_desktop_eine_mindestbreite():
    """Vier Spalten in 720px ergaben je ~165px - Woerter brachen mitten im
    Wort um. Jede Spalte braucht ab 700px mindestens 240px Basisbreite;
    reicht das Fenster nicht, scrollt das Brett waagerecht weiter."""
    quelle = BRETT.read_text(encoding="utf-8")
    block = quelle[quelle.index("@media (min-width:700px)"):]
    block = block[:block.index("}\n}") + 3]
    m = re.search(r"\.spalte\s*\{[^}]*flex:\s*\d+\s+\d+\s+(\d+)px", block)
    assert m and int(m.group(1)) >= 240, (
        "Die Desktop-Mindestbreite der Spalten fehlt (Wunsch #236)."
    )


def test_brett_tritt_aus_der_lesebreite_heraus():
    """Der Full-Bleed (margin: 50% - 50vw) ist der Kern von #236: Ohne ihn
    zwaengt .main die vier Spalten wieder in 720px. .main selbst bleibt
    unangetastet - die Regel aus #173 gilt weiter."""
    quelle = BRETT.read_text(encoding="utf-8")
    assert "calc(50% - 50vw)" in quelle
    styles = quelle.split("{% block extra_styles %}")[1].split("{% endblock %}")[0]
    assert not re.search(r"^\s*\.main\s*[{,]", styles, re.MULTILINE), (
        "Die Vorlage uebersteuert .main - verboten (Wunsch #173); der "
        "Full-Bleed gehoert ans .brett."
    )
