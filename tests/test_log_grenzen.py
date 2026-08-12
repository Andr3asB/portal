"""Wunsch #210, zweiter Teil: Die Container-Logs brauchen eine Obergrenze.

`json-file` ohne Optionen waechst unbegrenzt. Nachgesehen am 12.08.2026: In
`/etc/docker/daemon.json` auf home02 steht **keine** globale Grenze (nur
data-root, iptables, dns), und alle drei Container liefen mit leerem
LogConfig - die Frage war im Befund als offen markiert.

Das ist nicht nur unser Problem: `/opt/docker` liegt auf derselben Platte wie
iobroker, Paperless, Pi-hole und Portainer. Ein volllaufendes Portal-Log
nimmt die mit.

Der Test liest `docker-compose.yml` zeilenweise statt per PyYAML - eine
Abhaengigkeit nur fuer diesen einen Waechter waere zu teuer, und die Datei ist
flach genug. Er prueft, dass **jeder** Dienst eine Grenze hat: Der Fehler, der
hier wirklich passiert, ist ein neuer Dienst ohne `logging:`.
"""
import pathlib
import re

COMPOSE = (pathlib.Path(__file__).resolve().parents[1] / "docker-compose.yml"
           ).read_text(encoding="utf-8")


def _dienste():
    """{name: block} fuer jeden Eintrag unter `services:`."""
    zeilen = COMPOSE.split("\n")
    beginn = next(i for i, z in enumerate(zeilen) if z.rstrip() == "services:")
    dienste, name, block = {}, None, []
    for zeile in zeilen[beginn + 1:]:
        if zeile and not zeile.startswith(" "):        # naechster Abschnitt
            break
        treffer = re.match(r"^  (\w[\w-]*):\s*$", zeile)
        if treffer:
            if name:
                dienste[name] = "\n".join(block)
            name, block = treffer.group(1), []
        elif name:
            block.append(zeile)
    if name:
        dienste[name] = "\n".join(block)
    return dienste


def test_die_datei_wird_ueberhaupt_verstanden():
    """Ohne diese Zusicherung waeren alle Pruefungen unten leer und gruen."""
    dienste = _dienste()
    assert set(dienste) == {"portal", "caddy", "util"}, sorted(dienste)


def test_jeder_dienst_hat_eine_log_grenze():
    fehlend = [name for name, block in _dienste().items() if "logging:" not in block]
    assert not fehlend, (
        f"Diese Dienste schreiben ihr Log ohne Obergrenze: {fehlend}. "
        f"json-file waechst sonst unbegrenzt, und /opt/docker teilen sich "
        f"iobroker, Paperless, Pi-hole und Portainer."
    )


def test_die_grenze_ist_auch_beziffert():
    """`logging:` allein reicht nicht - ohne max-size bleibt es unbegrenzt.
    Der Anker `&log_grenzen` steht bei genau einem Dienst, die anderen
    verweisen darauf; geprueft wird deshalb die Datei als Ganzes."""
    assert re.search(r'max-size:\s*"?10m"?', COMPOSE), COMPOSE[:0]
    assert re.search(r'max-file:\s*"?3"?', COMPOSE)
    assert COMPOSE.count("*log_grenzen") == 2, (
        "Erwartet: ein Anker und zwei Verweise. Stimmt das nicht mehr, hat "
        "ein Dienst womoeglich eine eigene, abweichende Grenze bekommen."
    )
