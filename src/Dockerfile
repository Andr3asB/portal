# Wunsch #291 (Sicherheitsaudit 16.09.2026, Befund N-13): Basisimage per
# Digest festgenagelt, nicht nur per Tag - ein Tag kann sich unter der Hand
# aendern, ein Digest nicht. Stand 17.09.2026 = python:3.12-slim (3.12.14,
# Debian 13). Aktualisieren: `docker buildx imagetools inspect python:3.12-slim`
# auf home02 nennt den aktuellen Digest; bewusst von Hand, damit ein Rebuild
# nie ungefragt ein anderes Image einzieht.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Einfache PWA-Icons (kein Pillow nötig)
COPY . .
# Wunsch #291: Bytecode beim Bauen erzeugen - der Container laeuft mit
# read_only-Wurzel (docker-compose.yml), zur Laufzeit kann Python keine
# __pycache__ mehr schreiben. Ohne diesen Schritt wuerde jeder Start alles
# neu uebersetzen (harmlos, aber langsam).
RUN python3 generate_icons.py && python3 -m compileall -q .

# Wunsch #291: zweiter Riegel neben `user:` in docker-compose.yml - auch ein
# Start ohne compose laeuft nicht als root.
USER 1001

# Wunsch #128: umask 077 - die App legt Dateien unter /data an (SQLite-WAL,
# Vokabel-Audio); die duerfen nicht weltlesbar entstehen. sh -c, weil "umask"
# ein Shell-Builtin ist und eine reine CMD-Liste keine Shell startet.
# --no-control-socket (Wunsch #291): Gunicorn 26 legt sonst beim Start ein
# Steuer-Socket unter $HOME/.gunicorn/ an - HOME ist fuer UID 1001 "/", die
# Wurzel ist read_only, und im Log stand bei jedem Start "[ERROR] Control
# server error: Read-only file system". Wir benutzen das Steuer-Interface
# nicht. Der Flag-Name kommt aus gunicorn/config.py (`control_socket_disable`,
# cli = ["--no-control-socket"]) - der erste Versuch mit einem geratenen
# `--control-socket-disable` liess den Container in einer Neustart-Schleife
# enden, v260 lief deshalb nie.
CMD ["sh", "-c", "umask 077 && exec gunicorn --bind 0.0.0.0:8000 --workers 1 --threads 4 --timeout 120 --worker-tmp-dir /tmp --no-control-socket --access-logfile - --logger-class glogging_redact.RedactingLogger app:app"]
