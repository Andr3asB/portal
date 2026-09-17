"""Wunsch #281 (Sicherheitsaudit 16.09.2026, Befund N-02): Das Auslieferungs-
paket wird aus einer Positivliste gebaut.

Der alte `tar czf … --exclude=… .` aus server.md packte alles, was nicht
ausdrücklich ausgeschlossen war. So landeten `SECURITY_REVIEW.md` (bewusst
gitignoriert: Anleitung mit offenen Findings) und `.claude/settings.local.json`
(mit alten Zugangs-URLs samt Token) in jedem Paket seit v206 – und entpackt
unter /srv/familienportal/ auf home02.

Zwei Prüfungen: das Skript gegen ein künstliches Repo (jede Regel einzeln)
und gegen das ECHTE Repo (das Paket, das wirklich rausgeht, enthält nichts
davon).
"""
import importlib.util
import pathlib
import tarfile

import pytest

WURZEL = pathlib.Path(__file__).resolve().parents[1]
SKRIPT = WURZEL / "scripts" / "paket_bauen.py"


@pytest.fixture()
def paket():
    spec = importlib.util.spec_from_file_location("paket_bauen_test", SKRIPT)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def _repo(tmp_path):
    """Ein Mini-Repo mit allem, was mit muss - und allem, was nie mit darf."""
    for pfad, inhalt in {
        "src/app.py": "app",
        "src/teile/00_kern.py": "kern",
        "src/__pycache__/app.cpython-312.pyc": "bytecode",
        "src/.env": "GEHEIM=1",
        "src/portal.db": "db",
        "util/scheduler.py": "takt",
        "Caddyfile": "caddy",
        "docker-compose.yml": "compose",
        ".env.example": "VORLAGE=",
        ".env": "SECRET_KEY=echt",
        "SECURITY_REVIEW.md": "Findings",
        ".claude/settings.local.json": "{}",
        ".claude/scheduled_tasks.lock": "1",
        "tests/test_x.py": "test",
        "journal.md": "journal",
        "deploy/portal-v3.tar.gz": "alt",
        "deploy/portal-v12.tar.gz": "alt",
    }.items():
        ziel = tmp_path / pfad
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(inhalt)
    return tmp_path


def test_positivliste_packt_nur_was_der_server_braucht(paket, tmp_path):
    repo = _repo(tmp_path / "repo")
    ziel = tmp_path / "paket.tar.gz"
    gepackt = set(paket.paket_bauen(ziel, wurzel=repo))

    with tarfile.open(ziel) as tar:
        im_archiv = set(tar.getnames())
    assert im_archiv == gepackt

    for muss in ("src/app.py", "src/teile/00_kern.py", "util/scheduler.py",
                 "Caddyfile", "docker-compose.yml", ".env.example"):
        assert muss in gepackt, f"{muss} fehlt im Paket"

    for nie in ("SECURITY_REVIEW.md", ".claude/settings.local.json",
                ".claude/scheduled_tasks.lock", ".env", "tests/test_x.py",
                "journal.md", "deploy/portal-v3.tar.gz",
                "src/__pycache__/app.cpython-312.pyc", "src/.env", "src/portal.db"):
        assert nie not in gepackt, f"{nie} darf nie ins Paket"
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in gepackt)


def test_naechste_nummer_zaehlt_hoch_und_ueberschreibt_nie(paket, tmp_path):
    repo = _repo(tmp_path / "repo")
    assert paket.naechste_nummer(repo / "deploy") == 13
    assert paket.naechste_nummer(tmp_path / "leer") == 1

    ziel = repo / "deploy" / "portal-v12.tar.gz"
    with pytest.raises(FileExistsError):
        paket.paket_bauen(ziel, wurzel=repo)


def test_fehlender_pflichtteil_bricht_ab(paket, tmp_path):
    repo = _repo(tmp_path / "repo")
    (repo / "Caddyfile").unlink()
    with pytest.raises(FileNotFoundError, match="Caddyfile"):
        paket.paket_bauen(tmp_path / "x.tar.gz", wurzel=repo)


def test_das_echte_paket_leckt_nichts(paket, tmp_path):
    """Gegen das echte Repo: genau das Paket, das per scp auf home02 geht."""
    gepackt = paket.paket_bauen(tmp_path / "echt.tar.gz")
    verboten = [n for n in gepackt
                if n.startswith((".claude", "tests", "docs", "deploy", "scripts"))
                or n.endswith((".md", ".pyc", ".db"))
                or n == ".env" or n.startswith(".env.") and n != ".env.example"
                or "__pycache__" in n or "SECURITY_REVIEW" in n]
    assert not verboten, verboten
    for muss in ("src/app.py", "src/manage.py", "src/glogging_redact.py",
                 "src/redaktion.py", "util/scheduler.py", "util/cert_watcher.py",
                 "Caddyfile", "docker-compose.yml", ".env.example"):
        assert muss in gepackt, f"{muss} fehlt im echten Paket"
