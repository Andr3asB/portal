"""Wunsch #208 (Sicherheitsaudit 11.08.2026): Fehlende Isolations-Header.

Die übrigen Sicherheits-Header (Referrer-Policy, X-Content-Type-Options,
HSTS, CSP) stehen bereits sehr sorgfältig im `Caddyfile` bzw. in
`21_csp.py`. `Permissions-Policy` fehlte noch – ohne ihn darf grundsätzlich
jede eingebettete oder eingeschleuste Ressource Kamera, Mikrofon, Standort
etc. anfragen. Das Portal selbst braucht fast keine dieser APIs: Fotos laufen
über den normalen Datei-Upload-Dialog, nicht über `getUserMedia`.

**Ausnahme seit Wunsch #258 (05.09.2026): das Mikrofon.** Das Aussprache-
Training im Vokabeltrainer nimmt per `getUserMedia` auf. `microphone=(self)`
erlaubt das nur Seiten dieser Herkunft – ein eingebetteter fremder Rahmen
bekäme es weiterhin nicht. Ein eigener Test hält genau diesen Wert fest:
`microphone=()` würde das Training lautlos abschalten (der Browser meldet nur
„NotAllowedError“), `microphone=*` gäbe mehr frei als nötig.

**Was diese Datei NICHT prüfen kann:** ob Caddy den Header tatsächlich
ausliefert – dafür bräuchte es den echten, laufenden Container. Das ist
Sache der Live-Prüfung nach dem Ausrollen (`server.md`/`journal.md`), nicht
dieser Testsuite, die nie gegen ein echtes Caddy läuft. Geprüft wird hier nur
statisch: dass der Header im Caddyfile steht und die relevanten APIs nennt -
das fängt eine spätere versehentliche Löschung ab, auch ohne echtes Caddy.

**Cross-Origin-Opener-Policy/-Resource-Policy fehlen absichtlich** – sie
könnten das Einbetten im Home-Assistant-iFrame (Kiosk) stören und lassen
sich nur an einem echten Gerät prüfen. Ein eigener Test hält das fest, damit
ein spätere Ergänzung bewusst passiert, nicht als Kopiervorlage von einer
Checkliste.
"""
import pathlib
import re

CADDYFILE = pathlib.Path(__file__).resolve().parents[1] / "Caddyfile"


def _header_zeile(name: str) -> str:
    inhalt = CADDYFILE.read_text(encoding="utf-8")
    m = re.search(rf'{re.escape(name)}\s+"([^"]*)"', inhalt)
    assert m, f"{name} steht nicht (mehr) im Caddyfile"
    return m.group(1)


def test_permissions_policy_steht_im_caddyfile():
    assert _header_zeile("Permissions-Policy")


GESPERRT = ("camera", "geolocation", "payment", "usb")


def test_die_ungenutzten_apis_sind_gesperrt():
    """Genau die APIs, die das Portal nachweislich nicht braucht - keine
    Kamera (Fotos laufen über <input type=file>), keine Bezahl-API,
    kein USB, kein Standort."""
    wert = _header_zeile("Permissions-Policy")
    for api in GESPERRT:
        assert f"{api}=()" in wert, f"{api} ist nicht gesperrt"


def test_die_direktiven_sind_wirklich_leer():
    """`camera=(self)` sperrt NICHTS (self bleibt erlaubt) - hier zählt die
    leere Klammer, nicht nur das Vorkommen des Namens."""
    wert = _header_zeile("Permissions-Policy")
    for api in GESPERRT:
        treffer = re.search(rf"{api}=\(([^)]*)\)", wert)
        assert treffer, f"{api} kommt gar nicht vor"
        assert treffer.group(1).strip() == "", (
            f"{api}=({treffer.group(1)}) ist nicht leer - erlaubt also doch etwas"
        )


def test_mikrofon_ist_genau_fuer_self_frei():
    """Wunsch #258: Das Aussprache-Training braucht getUserMedia. `self` -
    nicht leer (dann waere der Knopf im Trainer tot), nicht `*` (dann duerfte
    auch ein eingebetteter fremder Rahmen mithoeren)."""
    wert = _header_zeile("Permissions-Policy")
    treffer = re.search(r"microphone=\(([^)]*)\)", wert)
    assert treffer, "microphone kommt gar nicht vor"
    assert treffer.group(1).strip() == "self", (
        f"microphone=({treffer.group(1)}) - erwartet wird genau (self)"
    )


def test_bestehende_header_stehen_noch():
    """Der neue Header darf keinen der alten verdrängt haben."""
    inhalt = CADDYFILE.read_text(encoding="utf-8")
    for name in ("Referrer-Policy", "X-Content-Type-Options",
                 "Strict-Transport-Security"):
        assert name in inhalt, f"{name} fehlt - versehentlich mit entfernt?"


def test_coop_und_corp_fehlen_noch_absichtlich():
    """Hält den bewussten Verzicht fest. Kommen sie doch dazu, muss dieser
    Test angepasst werden - das ist gewollt: eine stillschweigende Ergänzung
    ohne Kiosk-Test soll auffallen.

    Geprüft wird die echte Header-ZEILE, nicht jedes Vorkommen der
    Zeichenkette - die steht selbst im erklärenden Kommentar direkt darüber
    und ließ den ersten Versuch dieses Tests an sich selbst scheitern."""
    ohne_kommentare = "\n".join(
        z for z in CADDYFILE.read_text(encoding="utf-8").splitlines()
        if not z.strip().startswith("#")
    )
    assert not re.search(r"^\s*Cross-Origin-Opener-Policy\s", ohne_kommentare, re.MULTILINE)
    assert not re.search(r"^\s*Cross-Origin-Resource-Policy\s", ohne_kommentare, re.MULTILINE)
