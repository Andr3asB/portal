"""Auslieferungspaket bauen - aus einer POSITIVLISTE, nicht per Ausschluss.

    python scripts/paket_bauen.py            # naechste freie Nummer
    python scripts/paket_bauen.py 258        # feste Nummer (muss frei sein)

Wunsch #281 (Sicherheitsaudit 16.09.2026, Befund N-02): Der bisherige
`tar czf ... --exclude=... .` aus server.md packte alles, was nicht
ausdruecklich ausgeschlossen war - und so landeten `SECURITY_REVIEW.md`
(bewusst gitignoriert, weil Anleitung mit offenen Findings) und
`.claude/settings.local.json` (mit alten Zugangs-URLs samt Token) in jedem
Paket seit v206 und entpackt unter /srv/familienportal/ auf home02.

Eine Ausschlussliste ist dafuer das falsche Werkzeug: Jede neue Datei im
Repo ist automatisch drin, bis jemand daran denkt, sie auszuschliessen.
Eine Positivliste dreht das um - was der Server nicht braucht, kommt gar
nicht erst mit, und eine vergessene Datei faellt auf, weil sie fehlt, nicht
weil sie leckt.

Was der Server braucht, ist genau das, was `docker compose up -d --build`
liest: die beiden Build-Kontexte (src/, util/), die Compose-Datei, das
bind-gemountete Caddyfile und .env.example als Vorlage. Sonst nichts -
Tests, Doku, Skripte und Werkzeugkonfiguration laufen alle von diesem
Rechner aus.
"""
import re
import sys
import tarfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ZIEL_ORDNER = WURZEL / "deploy"

# Was mit muss. Verzeichnisse werden rekursiv gepackt.
INHALT = ("src", "util", "Caddyfile", "docker-compose.yml", ".env.example")

# Was auch INNERHALB der Verzeichnisse nie mit darf - Laufzeitreste und
# alles, was nach Geheimnis oder Datenbank aussieht. Zweiter Riegel hinter
# der Positivliste, nicht deren Ersatz.
_NIE = re.compile(
    r"(^|/)(__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache)(/|$)"
    r"|\.py[cod]$"
    r"|(^|/)\.env($|\.)(?!example$)"
    r"|\.(db|sqlite3?|db-wal|db-shm|pem|key|crt)$"
    r"|(^|/)(id_rsa|id_ed25519)"
)


def _erlaubt(relpfad: str) -> bool:
    return not _NIE.search(relpfad)


def naechste_nummer(ordner: Path = ZIEL_ORDNER) -> int:
    """Hoechste vorhandene portal-vN.tar.gz plus eins - Nummern zaehlen hoch
    und werden nie wiederverwendet (CLAUDE.md)."""
    nummern = [int(m.group(1)) for p in ordner.glob("portal-v*.tar.gz")
               if (m := re.fullmatch(r"portal-v(\d+)\.tar\.gz", p.name))]
    return (max(nummern) + 1) if nummern else 1


def paket_bauen(ziel: Path, wurzel: Path = WURZEL) -> list[str]:
    """Schreibt das Archiv und gibt die gepackten Pfade (relativ) zurueck."""
    if ziel.exists():
        raise FileExistsError(f"{ziel} gibt es schon - Pakete werden nie ueberschrieben.")
    gepackt: list[str] = []

    def filter_(info: tarfile.TarInfo):
        if not _erlaubt(info.name):
            return None
        gepackt.append(info.name)
        return info

    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ziel, "w:gz") as tar:
        for name in INHALT:
            quelle = wurzel / name
            if not quelle.exists():
                raise FileNotFoundError(f"{quelle} fehlt - Paket unvollstaendig.")
            tar.add(quelle, arcname=name, filter=filter_)
    return gepackt


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        nummer = int(argv[1])
    else:
        nummer = naechste_nummer()
    ziel = ZIEL_ORDNER / f"portal-v{nummer}.tar.gz"
    gepackt = paket_bauen(ziel)
    print(f"{ziel.relative_to(WURZEL)}: {len(gepackt)} Eintraege, "
          f"{ziel.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
