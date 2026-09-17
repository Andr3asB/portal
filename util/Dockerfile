# Wunsch #291: Digest-Pin wie in src/Dockerfile (derselbe Stand, gleiche
# Aktualisierungsregel).
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
WORKDIR /app
# age (Wunsch #130/#211): verschluesselt den Backup-Strom gegen einen
# oeffentlichen Schluessel. Debian 13 (trixie) liefert 1.2.1. Bewusst das
# Paket aus der Distribution statt eines Binaerdownloads - dann haengt die
# Vertrauenskette an derselben apt-Signatur wie der Rest des Images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync openssh-client age \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1001 -m -s /bin/sh portal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
RUN python3 -m compileall -q .
# Wunsch #291: nicht als root, auch ohne compose (dort steht user: zusaetzlich).
USER portal
# Wunsch #128: umask 077 - Snapshots und Backup-Archive enthalten die komplette
# Datenbank inklusive aller Zugangstokens und duerfen nicht mit 0644 entstehen.
# Als sh -c, weil eine reine CMD-Liste keine Shell startet und "umask" ein
# Shell-Builtin ist (kein Programm, das man per exec aufrufen koennte).
CMD ["sh", "-c", "umask 077 && exec python3 scheduler.py"]
