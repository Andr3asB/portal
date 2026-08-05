FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends rsync openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -u 1001 -m -s /bin/sh portal
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
# Wunsch #128: umask 077 - Snapshots und Backup-Archive enthalten die komplette
# Datenbank inklusive aller Zugangstokens und duerfen nicht mit 0644 entstehen.
# Als sh -c, weil eine reine CMD-Liste keine Shell startet und "umask" ein
# Shell-Builtin ist (kein Programm, das man per exec aufrufen koennte).
CMD ["sh", "-c", "umask 077 && exec python3 scheduler.py"]
