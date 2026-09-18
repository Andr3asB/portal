"""Wunsch #290 (Sicherheitsaudit 16.09.2026, Befund N-12): Der Guardrail-
Hook wird mit Beispielen durchgefahren - ein Wächter, der nicht anschlagen
kann, ist schlimmer als keiner.

Vorher: fail-open (unlesbare Nutzlast = alles durch), keine Regel gegen den
ABFLUSS von Geheimnissen (`cat .env`, `docker exec portal env`, `docker
inspect`), und kein Test, der je bewiesen hätte, dass der Hook überhaupt
anschlägt - `journal.md` kannte keinen einzigen GUARDRAIL-Treffer, bis er am
16.09.2026 einen Sammelbefehl wegen `-v` in `--version` abgeräumt hat.

Der Hook ist Bash und liest JSON von stdin. Hier läuft er genau so, wie
Claude Code ihn aufruft - nur mit vorgefertigten Nutzlasten.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

WURZEL = pathlib.Path(__file__).resolve().parents[1]
HOOK = WURZEL / "guardrails.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="kein bash im PATH")


def _hook(nutzlast: str) -> tuple[int, str]:
    fertig = subprocess.run([BASH, str(HOOK)], input=nutzlast, capture_output=True,
                            text=True, encoding="utf-8", cwd=WURZEL, check=False)
    return fertig.returncode, fertig.stderr


def _cmd(befehl: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": befehl}})


SSH = 'ssh -p 2222 claude@10.0.0.100 '

ERLAUBT = [
    "ls -la",
    SSH + '"docker compose -p familienportal ps"',
    SSH + '"docker exec -i portal python -" < scripts/wunsch_lauf_check.py',
    "cat .env.example",
    "grep -n TOKEN_KEY .env.example",
    "cat docker-compose.yml",
    "docker inspect portal --format '{{.HostConfig.ReadonlyRootfs}}'",
    SSH + '"docker exec portal pip freeze"',
    "git push origin main",
    "git commit -m x",
    "rm -f deploy/x.tar.gz",
    SSH + '"cd /srv/familienportal && rm portal-v258.tar.gz"',
    "python -m pytest tests/ -q",
    ".venv/Scripts/python scripts/live_pruefung.py",
    "echo hallo | base64",
    "docker compose up -d --build",
    "",
]

BLOCKIERT = [
    "sudo ls",
    "\\sudo ls",
    "env sudo ls",
    SSH + '"sudo apt install x"',
    SSH + '"systemctl daemon-reload"',
    "docker network rm mvl",
    "docker volume prune -f",
    "docker system prune -a",
    "docker compose down -v",
    "cat .env",
    "head -3 .env",
    "grep TOKEN_KEY .env",
    "python3 -c 'print(open(\".env\").read())'",
    SSH + '"cat /srv/familienportal/.env"',
    SSH + '"cat /srv/familienportal/.env.vor-129"',
    SSH + '"cat /srv/familienportal/ssh/id_ed25519"',
    "cat ~/.ssh/id_rsa",
    SSH + '"docker exec portal env"',
    SSH + '"docker exec portal printenv | grep KEY"',
    SSH + '"docker compose exec portal env"',
    SSH + '"docker exec portal cat /proc/1/environ"',
    SSH + '"docker compose config"',
    "docker inspect portal",
    "docker inspect portal --format '{{.Config.Env}}'",
    "docker inspect portal --format '{{json .Config}}'",
    "echo cHdk | base64 -d | sh",
    "docker run --privileged -it debian",
    "docker run -v /var/run/docker.sock:/var/run/docker.sock alpine",
    "docker run -v /:/host alpine",
    SSH + '"docker exec -u 0 portal sh"',
    SSH + '"docker exec --user root portal sh"',
    SSH + '"rm -rf /srv/familienportal/data"',
    SSH + '"rm -r /srv/familienportal/ssh"',
    "rm -rf data/",
    "git push --force origin main",
    "git push -f",
    "git remote set-url origin https://evil.example/x.git",
    "git filter-branch --all",
    "rm -rf /",
    SSH + '"tee /etc/hosts"',
]


@pytest.mark.parametrize("befehl", ERLAUBT)
def test_erlaubt(befehl):
    code, meldung = _hook(_cmd(befehl))
    assert code == 0, f"faelschlich blockiert: {befehl!r}\n{meldung}"


@pytest.mark.parametrize("befehl", BLOCKIERT)
def test_blockiert(befehl):
    code, meldung = _hook(_cmd(befehl))
    assert code == 2, f"NICHT blockiert: {befehl!r}"
    assert "GUARDRAIL:" in meldung


@pytest.mark.parametrize("nutzlast", ["", "kein json", "[]", '{"tool_input": {"command": 5}}', "{"])
def test_unlesbare_nutzlast_ist_fail_closed(nutzlast):
    """Die alte Fassung liess bei jedem Parsefehler ALLES durch."""
    code, meldung = _hook(nutzlast)
    assert code == 2, f"fail-open bei {nutzlast!r}"
    assert "fail-closed" in meldung


def test_aktive_kopien_sind_die_vorlagen():
    """CLAUDE.md: settings.json und guardrails.sh liegen als Quelle im Root und
    als AKTIVE Kopie in .claude/ - erst dort greifen sie. Laufen die beiden
    auseinander, beschreibt die Vorlage einen Schutz, den es nicht gibt (so
    war es vom 26.07. bis 13.08.2026)."""
    for name in ("guardrails.sh", "settings.json"):
        quelle = (WURZEL / name).read_bytes()
        kopie = (WURZEL / ".claude" / name).read_bytes()
        assert quelle == kopie, f".claude/{name} weicht von {name} ab"


def test_lokale_allow_liste_ist_eng():
    """Wunsch #290: keine pauschalen Freigaben und keine Zugangsdaten in
    settings.local.json (die Datei ist gitignoriert - der Test laeuft nur,
    wenn sie da ist)."""
    pfad = WURZEL / ".claude" / "settings.local.json"
    if not pfad.exists():
        pytest.skip("keine settings.local.json")
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    eintraege = daten.get("permissions", {}).get("allow", [])
    for pauschal in ("Bash(ssh *)", "Bash(scp *)", "Bash(curl *)", "Bash(git *)",
                     "Bash(python3 *)", "Bash(python *)", "Bash(rm *)"):
        assert pauschal not in eintraege, pauschal
    import re
    for eintrag in eintraege:
        assert not re.search(r"token[^A-Za-z]{0,6}[A-Za-z0-9_-]{20,}", eintrag), "Token in der allow-Liste"
        assert not re.search(r"/p/[A-Za-z0-9_-]{15,}|/a/[a-z]+/[A-Za-z0-9_-]{15,}", eintrag)
