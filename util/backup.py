"""
Tägliches rsync-Backup: /data → NAS.

Konfiguration via .env:
  BACKUP_NAS_HOST   IP des NAS         (default: 10.60.0.4)
  BACKUP_NAS_USER   SSH-User auf NAS   (default: admin)
  BACKUP_NAS_PATH   Zielpfad auf NAS   (default: /home/admin/portal-backup)
  BACKUP_NAS_PORT   SSH-Port           (default: 22)
"""
import logging, os, subprocess
from datetime import datetime

log = logging.getLogger("util.backup")

NAS_HOST = os.environ.get("BACKUP_NAS_HOST", "10.60.0.4")
NAS_USER = os.environ.get("BACKUP_NAS_USER", "admin")
NAS_PATH = os.environ.get("BACKUP_NAS_PATH", "/home/admin/portal-backup")
NAS_PORT = os.environ.get("BACKUP_NAS_PORT", "22")
SSH_KEY  = "/ssh/id_ed25519"
DATA_DIR = os.environ.get("DATA_DIR", "/data")


def run():
    if not os.path.exists(SSH_KEY):
        log.warning("SSH-Key %s fehlt – Backup übersprungen", SSH_KEY)
        return

    target  = f"{NAS_USER}@{NAS_HOST}:{NAS_PATH}/"
    ssh_opt = (
        f"ssh -i {SSH_KEY} -p {NAS_PORT} "
        f"-o StrictHostKeyChecking=no -o ConnectTimeout=20 -o BatchMode=yes"
    )
    cmd = ["rsync", "-az", "--delete", "-e", ssh_opt, f"{DATA_DIR}/", target]

    log.info("Backup → %s", target)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            log.info("Backup OK (%s)", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
        else:
            log.error("Backup fehlgeschlagen (exit %d): %s",
                      result.returncode, (result.stderr or result.stdout)[:300])
    except subprocess.TimeoutExpired:
        log.error("Backup-Timeout (10 min)")
    except FileNotFoundError:
        log.error("rsync nicht gefunden im Container")
    except Exception as e:
        log.error("Backup-Exception: %s", e)
