FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Einfache PWA-Icons (kein Pillow nötig)
COPY . .
RUN python3 generate_icons.py

# Wunsch #128: umask 077 - die App legt Dateien unter /data an (SQLite-WAL,
# Vokabel-Audio); die duerfen nicht weltlesbar entstehen. sh -c, weil "umask"
# ein Shell-Builtin ist und eine reine CMD-Liste keine Shell startet.
CMD ["sh", "-c", "umask 077 && exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 120 --worker-tmp-dir /tmp --access-logfile - --logger-class glogging_redact.RedactingLogger app:app"]
