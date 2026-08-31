"""Wunsch #147: Jedes verwendete Emoji braucht seine lokale Twemoji-Grafik.

Hintergrund: `twemoji.parse()` ersetzt jedes erkannte Emoji-Zeichen durch ein
lokal gebündeltes SVG (`/static/twemoji/svg/<codepoint>.svg`). Fehlt die Datei,
bleibt ein kaputtes Bild stehen.

**Warum das immer wieder passiert:** Unter iOS und macOS fällt es kaum auf -
dort sind gute System-Emoji vorhanden, und der Fehler wirkt wie ein
Darstellungsdetail. Unter Linux/Chrome (dem Esszimmer-Kiosk und Andis Rechner)
ist die Kachel dagegen sofort leer. Genau so wurde das Kassenbuch-Icon 🐷
gemeldet - da fehlten in Wahrheit NEUN Grafiken, acht davon aus den
Änderungen der Tage davor.

`server.md` warnte bereits ausdrücklich davor (Stolperfalle aus Wunsch #122,
◀ ▶). Eine Warnung in der Dokumentation hat es nicht verhindert - dieser Test
schon.

Vorgehen bei einem Treffer: Die Datei von
`raw.githubusercontent.com/twitter/twemoji/master/assets/svg/<cp>.svg`
holen und unter `src/static/twemoji/svg/` ablegen.
"""
import glob
import os
import re

import pytest

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_DIR = os.path.join(WURZEL, "src", "static", "twemoji", "svg")

# Grober Emoji-Bereich. Bewusst breit: lieber ein Zeichen zu viel prüfen und
# über die Textsymbol-Regel unten wieder aussortieren, als eines übersehen.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF←-⇿⌀-➿⬀-⯿〰〽"
    "㊗㊙©®™]"
)
_VS16 = "️"


def _quelldateien():
    for muster in ("src/teile/templates/*.html", "src/teile/*.py", "src/manage.py"):
        yield from glob.glob(os.path.join(WURZEL, muster))


def _verwendete_emoji():
    """(codepoint, datei, zeile, zeichen) für jedes Zeichen, das Twemoji
    tatsächlich ersetzen würde."""
    for pfad in _quelldateien():
        with open(pfad, encoding="utf-8") as f:
            text = f.read()
        for nr, zeile in enumerate(text.split("\n"), 1):
            for treffer in _EMOJI.finditer(zeile):
                zeichen = treffer.group(0)
                # Reine Textsymbole (← ↑ → ▲ ▼ ★ ☰ ✓ ✕ …) wandelt Twemoji nur
                # um, wenn ein Varianten-Selektor dahintersteht. Ohne den
                # bleiben sie normaler Text und brauchen keine Grafik.
                # ACHTUNG: Ob ein Zeichen Textsymbol oder Emoji ist, lässt
                # sich NICHT am Aussehen ablesen - ◀ ▶ (U+25C0/U+25B6) sehen
                # aus wie ▲ ▼, werden aber sehr wohl ersetzt. Deshalb hängt
                # die Unterscheidung hier an der Codepoint-Grenze, nicht an
                # einer handgepflegten Liste.
                folgt_vs16 = zeile[treffer.end():treffer.end() + 1] == _VS16
                if ord(zeichen) < 0x1F000 and not folgt_vs16:
                    continue
                yield (f"{ord(zeichen):x}", os.path.basename(pfad), nr, zeichen)


def test_svg_verzeichnis_ist_da():
    """Fängt ab, dass der Test wegen eines falschen Pfades stillschweigend
    nichts prüft - der unangenehmste Zustand für einen Wächter."""
    assert os.path.isdir(SVG_DIR), SVG_DIR
    assert len(glob.glob(os.path.join(SVG_DIR, "*.svg"))) > 50


def test_es_werden_ueberhaupt_emoji_gefunden():
    """Zweite Sicherung gegen einen Test, der nichts tut: Das Portal ist voll
    von Emoji, wenn hier nichts ankommt, ist der Filter kaputt."""
    assert len(list(_verwendete_emoji())) > 100


def test_jedes_verwendete_emoji_hat_eine_lokale_grafik():
    vorhanden = {os.path.basename(p)[:-4]
                 for p in glob.glob(os.path.join(SVG_DIR, "*.svg"))}
    fehlend = {}
    for codepoint, datei, nr, zeichen in _verwendete_emoji():
        if codepoint not in vorhanden:
            fehlend.setdefault(codepoint, []).append(f"{datei}:{nr}")

    if fehlend:
        zeilen = []
        for cp, orte in sorted(fehlend.items()):
            gekuerzt = ", ".join(orte[:4])
            if len(orte) > 4:
                gekuerzt += f" (+{len(orte) - 4} weitere)"
            zeilen.append(f"  {cp}  ->  {gekuerzt}")
        pytest.fail(
            "Diese Emoji haben keine lokale Twemoji-Grafik und bleiben unter "
            "Linux/Chrome leer:\n" + "\n".join(zeilen) +
            "\n\nHolen mit:\n  curl -o src/static/twemoji/svg/<cp>.svg \\\n"
            "    https://raw.githubusercontent.com/twitter/twemoji/master/assets/svg/<cp>.svg"
        )


def test_alle_app_emoji_haben_eine_grafik(app, db):
    """Die App-Kacheln der Startseite sind der sichtbarste Fall - genau dort
    wurde der Fehler gemeldet (Kassenbuch, Wunsch #147). Diese Prüfung geht
    über die Datenbank, erwischt also auch Apps, deren Emoji nur dort steht
    und in keiner Vorlage vorkommt."""
    vorhanden = {os.path.basename(p)[:-4]
                 for p in glob.glob(os.path.join(SVG_DIR, "*.svg"))}
    fehlend = []
    for slug, emoji in db["verbindung"].execute("SELECT slug, emoji FROM apps"):
        for zeichen in emoji or "":
            if zeichen == _VS16 or ord(zeichen) < 0x1F000:
                continue
            if f"{ord(zeichen):x}" not in vorhanden:
                fehlend.append(f"{slug}: {ord(zeichen):x}")
    assert not fehlend, (
        "App-Kacheln ohne lokale Grafik (unter Linux/Chrome leer):\n  "
        + "\n  ".join(fehlend))
