"""Wunsch #291 (Sicherheitsaudit 16.09.2026, Befund N-13): Standard-Härtung
der drei Container, Digest-Pins, .dockerignore.

Vorher: kein `no-new-privileges`, kein `cap_drop`, keine Wurzel nur lesbar,
kein `pids_limit`; `python:3.12-slim` und `caddy:2-alpine` als schwimmende
Tags - jeder Pull konnte ein anderes Image bringen; `COPY . .` ohne
`.dockerignore`; kein `USER` in den Dockerfiles, der Nicht-root-Betrieb hing
allein an compose.

Derselbe zeilenweise Leser wie in `test_log_grenzen.py` - PyYAML nur für einen
Wächter wäre zu teuer. Was hier wirklich passiert: ein neuer Dienst oder ein
„nur mal kurz" entferntes `read_only`.
"""
import pathlib
import re

WURZEL = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")


def _dienste():
    zeilen = COMPOSE.split("\n")
    beginn = next(i for i, z in enumerate(zeilen) if z.rstrip() == "services:")
    dienste, name, block = {}, None, []
    for zeile in zeilen[beginn + 1:]:
        if zeile and not zeile.startswith(" "):
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


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))


def test_jeder_dienst_hat_die_grundhaertung():
    for name, block in _dienste().items():
        block = _ohne_kommentare(block)
        assert "no-new-privileges:true" in block, f"{name}: security_opt fehlt"
        assert re.search(r"cap_drop:\s*\n\s*- ALL", block), f"{name}: cap_drop ALL fehlt"
        assert re.search(r"pids_limit:\s*\d+", block), f"{name}: pids_limit fehlt"
        assert "read_only: true" in block, f"{name}: Wurzel ist beschreibbar"


def test_caddy_darf_nur_port_443_binden():
    caddy = _ohne_kommentare(_dienste()["caddy"])
    assert re.search(r"cap_add:\s*\n\s*- NET_BIND_SERVICE", caddy)
    assert "/config" in caddy, "Caddy schreibt autosave.json nach /config"
    for anderer in ("portal", "util"):
        assert "cap_add" not in _ohne_kommentare(_dienste()[anderer]), f"{anderer} braucht keine Capability"


def test_util_tmp_ist_kein_tmpfs():
    """backup.py packt das komplette Archiv unter /tmp - als tmpfs zaehlte das
    gegen die 64 MB des Containers."""
    util = _ohne_kommentare(_dienste()["util"])
    assert "util_tmp:/tmp" in util
    assert "tmpfs" not in util
    assert re.search(r"^  util_tmp:", COMPOSE, re.MULTILINE)


def test_images_sind_per_digest_festgenagelt():
    caddy = _ohne_kommentare(_dienste()["caddy"])
    assert re.search(r"image:\s*caddy:\d+\.\d+\.\d+-alpine@sha256:[0-9a-f]{64}", caddy), \
        "caddy ohne Version+Digest"
    for datei in ("src/Dockerfile", "util/Dockerfile"):
        text = (WURZEL / datei).read_text(encoding="utf-8")
        assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}", text, re.MULTILINE), \
            f"{datei}: FROM ohne Digest"
        assert re.search(r"^USER\s+\S+", text, re.MULTILINE), f"{datei}: kein USER"
        assert "compileall" in text, f"{datei}: ohne Bytecode kann eine read_only-Wurzel nichts cachen"


def test_dockerignore_haelt_geheimnisse_aus_dem_kontext():
    """Mit `**/`: Docker-Muster ohne dieses Praefix gelten nur fuer die oberste
    Ebene des Kontexts - `__pycache__/` liess teile/__pycache__ durch, und
    genau so kamen am 17.09.2026 alte cpython-314.pyc ins Image."""
    for ordner in ("src", "util"):
        zeilen = (WURZEL / ordner / ".dockerignore").read_text(encoding="utf-8").splitlines()
        for muster in ("**/__pycache__", "**/*.py[cod]", ".env", ".env.*", "**/.env", "**/*.db"):
            assert muster in zeilen, f"{ordner}/.dockerignore ohne {muster}"


def test_gunicorn_legt_kein_steuer_socket_an():
    """Gunicorn 26 schreibt sonst nach $HOME/.gunicorn - HOME ist fuer UID
    1001 die (read_only-)Wurzel, und jeder Start begann mit einem [ERROR].
    Das Flag heisst `--no-control-socket` (gunicorn/config.py); ein geratenes
    `--control-socket-disable` liess v260 gar nicht erst starten."""
    text = (WURZEL / "src" / "Dockerfile").read_text(encoding="utf-8")
    cmd = [z for z in text.splitlines() if z.startswith("CMD")]
    assert len(cmd) == 1
    assert "--no-control-socket" in cmd[0]
    assert "--control-socket-disable" not in cmd[0]


def test_util_laeuft_in_familienzeit():
    assert "TZ: Europe/Berlin" in _ohne_kommentare(_dienste()["util"])
