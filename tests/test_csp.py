"""Wunsch #142, Stufe 5: CSP mit Nonce statt 'unsafe-inline'.

Der wichtigste Test hier ist `test_keine_inline_handler_mehr`: Er liest die
Vorlagen im Quelltext und lässt keinen neuen `onclick=` zu. Ohne ihn wäre der
ganze Umbau in ein paar Wochen still wieder zunichte – ein einziges neues
`onclick` genügt, und der Knopf funktioniert im Modus `scharf` einfach nicht
mehr. Genau diese Sorte Fehler fällt beim Entwickeln nicht auf, weil dort
`CSP_MODUS=aus` steht.
"""
import glob
import io
import os
import re

import pytest

VORLAGEN = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "teile", "templates", "*.html",
)


@pytest.fixture()
def scharf(app):
    vorher = app.config.get("CSP_MODUS")
    app.config["CSP_MODUS"] = "scharf"
    yield
    app.config["CSP_MODUS"] = vorher


@pytest.fixture()
def beobachten(app):
    vorher = app.config.get("CSP_MODUS")
    app.config["CSP_MODUS"] = "beobachten"
    yield
    app.config["CSP_MODUS"] = vorher


# --- Der Wächter über die Vorlagen ----------------------------------------

def _ohne_skriptbloecke(text: str) -> str:
    """Skriptinhalte durch Leerzeilen ersetzen, Zeilennummern erhalten.

    Nötig, weil `btn.onclick = fn` in JavaScript völlig in Ordnung ist – eine
    aus einem Skript gesetzte DOM-Eigenschaft blockiert die CSP nicht. Verboten
    ist allein das Attribut im Markup. Ohne diese Trennung meldet der Test
    Fehlalarme, und ein Test, dem man nicht glaubt, wird abgeschaltet."""
    def leeren(m):
        return m.group(0)[:0] + "\n" * m.group(0).count("\n")
    return re.sub(r"<script[^>]*>.*?</script>", leeren, text, flags=re.S)


# Attribut im Markup: Leerzeichen davor, Anführungszeichen dahinter. Damit
# fallen `.onclick = fn` (Punkt davor) und Erwähnungen in Kommentaren
# (Backtick davor, kein Anführungszeichen) heraus.
_ATTRIBUT = re.compile(r'\son(click|submit|change|input|load|error)\s*=\s*["\']')


def test_keine_inline_handler_mehr():
    """Kein `onclick=`/`onsubmit=`/`onchange=`/`oninput=` in den Vorlagen.

    Ersatz ist der Verteiler in `base.html`:
        <button data-klick="fnName" data-args='[1, "text"]'>
    Formulare: `data-bestaetigen="Text?"` für die Sicherheitsabfrage,
    `data-absenden="fnName"` für eine eigene Prüfung."""
    treffer = []
    for pfad in sorted(glob.glob(VORLAGEN)):
        text = _ohne_skriptbloecke(io.open(pfad, encoding="utf-8").read())
        for nr, zeile in enumerate(text.split("\n"), 1):
            for m in _ATTRIBUT.finditer(zeile):
                treffer.append(f"{os.path.basename(pfad)}:{nr} {m.group(0).strip()}")
    assert not treffer, (
        "Inline-Handler gefunden – die verhindern eine CSP ohne "
        "'unsafe-inline':\n  " + "\n  ".join(treffer)
        + "\n\nStattdessen data-klick/data-aendern/data-eingabe bzw. "
          "data-bestaetigen/data-absenden verwenden (Verteiler in base.html)."
    )


def test_jeder_inline_skriptblock_hat_ein_nonce():
    """Ein vergessenes Nonce heisst: dieser Block läuft im Modus `scharf`
    nicht mehr. Das fällt beim Entwickeln nicht auf."""
    ohne = []
    for pfad in sorted(glob.glob(VORLAGEN)):
        text = io.open(pfad, encoding="utf-8").read()
        for m in re.finditer(r"<script(?![^>]*\bsrc=)([^>]*)>", text):
            if "csp_nonce" not in m.group(1):
                nr = text[:m.start()].count("\n") + 1
                ohne.append(f"{os.path.basename(pfad)}:{nr}  {m.group(0)[:60]}")
    assert not ohne, (
        "Diese Inline-Skriptblöcke haben kein Nonce:\n  " + "\n  ".join(ohne)
        + "\n\nRichtig ist: <script{{ csp_nonce }}>"
    )


# --- Die Kopfzeile ---------------------------------------------------------

def test_modus_aus_liefert_die_alte_regel(client, admin):
    """Notausstieg: `aus` muss den Zustand von vor #142 herstellen."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    regel = antwort.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" in regel.split("style-src")[0], \
        "script-src muss im Modus 'aus' weiterhin 'unsafe-inline' erlauben"
    assert "Content-Security-Policy-Report-Only" not in antwort.headers


def test_scharf_verbietet_inline_und_setzt_nonce(client, admin, scharf):
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    regel = antwort.headers["Content-Security-Policy"]
    script_teil = regel.split("style-src")[0]
    assert "'unsafe-inline'" not in script_teil
    assert "'nonce-" in script_teil


def test_nonce_der_kopfzeile_steht_auch_in_der_seite(client, admin, scharf):
    """Der eigentliche Punkt: Kopfzeile und Seite müssen dasselbe Nonce
    tragen. Weichen sie ab, läuft kein einziges Skript mehr."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    aus_kopf = re.search(r"'nonce-([^']+)'", antwort.headers["Content-Security-Policy"])
    assert aus_kopf, "kein Nonce in der Kopfzeile"
    seite = antwort.get_data(as_text=True)
    assert f'<script nonce="{aus_kopf.group(1)}">' in seite


def test_nonce_ist_je_anfrage_verschieden(client, admin, scharf):
    """Ein wiederverwendetes Nonce wäre so gut wie keines."""
    werte = set()
    for _ in range(3):
        antwort = client.get(f"/p/{admin['tokens']['home']}")
        werte.add(re.search(r"'nonce-([^']+)'",
                            antwort.headers["Content-Security-Policy"]).group(1))
    assert len(werte) == 3, f"Nonce wiederholt sich: {werte}"


def test_beobachten_blockiert_nichts(client, admin, beobachten):
    """Im Beobachtungsmodus gilt die alte Regel; die strenge geht nur als
    Report-Only mit. Sonst wäre der Modus wertlos – er soll Verstösse
    sichtbar machen, nicht welche verursachen."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert "'unsafe-inline'" in antwort.headers["Content-Security-Policy"]
    nur_bericht = antwort.headers["Content-Security-Policy-Report-Only"]
    assert "'nonce-" in nur_bericht
    assert "report-uri /csp-bericht" in nur_bericht


def test_frame_ancestors_bleibt_in_jedem_modus(client, admin, scharf):
    """Fällt das weg, ist der Esszimmerbildschirm schwarz."""
    antwort = client.get(f"/p/{admin['tokens']['home']}")
    assert "frame-ancestors https://wir4.16schwaben.de" in \
        antwort.headers["Content-Security-Policy"]


# --- Der Meldeendpunkt -----------------------------------------------------

def test_meldeendpunkt_nimmt_berichte_an(client):
    """Muss ohne Anmeldung funktionieren – der Browser schickt die Meldung,
    nicht eine angemeldete Seite."""
    antwort = client.post("/csp-bericht", json={
        "csp-report": {
            "document-uri": "https://portal.16schwaben.de/start",
            "blocked-uri": "inline",
            "violated-directive": "script-src",
        }
    })
    assert antwort.status_code == 204


def test_meldeendpunkt_ueberlebt_muell(client):
    """Der Browser ist nicht die einzige mögliche Quelle. Ein Absturz hier
    wäre ein Fehler in jeder Antwort, nicht nur in dieser."""
    assert client.post("/csp-bericht", data="kein json").status_code == 204
    assert client.post("/csp-bericht", json={"unerwartet": True}).status_code == 204
