"""
Tägliches Backup: /data → NAS per SSH (tar + pipe, kein rsync-Daemon nötig).
Auf dem NAS werden die letzten 7 Tages-Tarballs behalten.

Konfiguration via .env:
  BACKUP_NAS_HOST   IP des NAS         (default: 10.60.0.4)
  BACKUP_NAS_USER   SSH-User auf NAS   (default: familienportal)
  BACKUP_NAS_PATH   Zielpfad auf NAS   (default: /volume2/portal.16schwaben.de_Backup)
  BACKUP_NAS_PORT   SSH-Port           (default: 2222)
"""
import logging, os, subprocess
from datetime import datetime

log = logging.getLogger("util.backup")

NAS_HOST = os.environ.get("BACKUP_NAS_HOST", "10.60.0.4")
NAS_USER = os.environ.get("BACKUP_NAS_USER", "familienportal")
NAS_PATH = os.environ.get("BACKUP_NAS_PATH", "/volume2/portal.16schwaben.de_Backup")
NAS_PORT = os.environ.get("BACKUP_NAS_PORT", "2222")
SSH_KEY  = "/ssh/id_ed25519"
DATA_DIR = os.environ.get("DATA_DIR", "/data")

SSH_OPTS = [
    "ssh", "-i", SSH_KEY, "-p", NAS_PORT,
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=20",
    f"{NAS_USER}@{NAS_HOST}",
]


def run():
    if not os.path.exists(SSH_KEY):
        log.warning("SSH-Key %s fehlt – Backup übersprungen", SSH_KEY)
        return

    stamp   = datetime.utcnow().strftime("%Y%m%d-%H%M")
    tarname = f"portal-{stamp}.tar.gz"

    log.info("Backup → %s:%s/%s", NAS_HOST, NAS_PATH, tarname)
    try:
        _transfer(tarname)
        _cleanup()
        log.info("Backup OK – %s", tarname)
    except Exception as e:
        log.error("Backup fehlgeschlagen: %s", e)


def _transfer(tarname: str):
    tar = subprocess.Popen(
        ["tar", "czf", "-", "-C", DATA_DIR, "."],
        stdout=subprocess.PIPE,
    )
    ssh = subprocess.Popen(
        SSH_OPTS + [f"cat > {NAS_PATH}/{tarname}"],
        stdin=tar.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    tar.stdout.close()
    _, stderr = ssh.communicate(timeout=600)
    tar.wait()

    if ssh.returncode != 0:
        raise RuntimeError(f"SSH exit {ssh.returncode}: {stderr.decode()[:200]}")
    if tar.returncode != 0:
        raise RuntimeError(f"tar exit {tar.returncode}")


def _cleanup():
    """Behält die 7 neuesten Backups, löscht ältere."""
    remote_cmd = (
        f"ls -t {NAS_PATH}/portal-*.tar.gz 2>/dev/null "
        f"| tail -n +8 | xargs -r rm -f"
    )
    result = subprocess.run(
        SSH_OPTS + [remote_cmd],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        log.warning("Cleanup fehlgeschlagen: %s", result.stderr[:100])
