import os, importlib, secrets
from pathlib import Path
from flask import Flask

app = Flask(
    __name__,
    template_folder="teile/templates",
    static_folder="static",
)
app.config["DB_PATH"]          = os.environ.get("DB_PATH",  "/data/portal.db")
app.config["DATA_DIR"]         = os.environ.get("DATA_DIR", "/data")
app.config["VAPID_PRIVATE_KEY"] = os.environ.get("VAPID_PRIVATE_KEY", "")
app.config["VAPID_PUBLIC_KEY"]  = os.environ.get("VAPID_PUBLIC_KEY",  "")
app.config["VAPID_SUBJECT"]     = os.environ.get("VAPID_SUBJECT", "mailto:portal@16schwaben.de")
app.config["OPENROUTER_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")
app.config["HAE_API_URL"]       = os.environ.get("HAE_API_URL", "")
app.config["HAE_API_KEY"]       = os.environ.get("HAE_API_KEY", "")
# Wunsch #129: Schluessel, mit dem die Zugangstokens in der DB
# verschluesselt sind. Ohne ihn kommt niemand mehr rein - siehe .env.example.
app.config["TOKEN_KEY"]         = os.environ.get("TOKEN_KEY", "")
# Wunsch #140, Stufe 1: Schalter fuer das Ausstellen von Sitzungs-Cookies.
# 0 = aus. Zuruecknehmen der Stufe ist damit eine Zeile in der .env und ein
# "docker compose up -d portal" - kein Rebuild, kein Paket.
app.config["SITZUNG_AUSSTELLEN"] = os.environ.get("SITZUNG_AUSSTELLEN", "0")
# Wunsch #140, Stufe 2: CSRF-Riegel. "aus" | "beobachten" | "scharf".
# "beobachten" protokolliert nur und blockiert nichts - so laesst sich vor
# dem Scharfschalten pruefen, ob echte Anfragen faelschlich auffallen.
app.config["CSRF_MODUS"]        = os.environ.get("CSRF_MODUS", "aus")
# Erwartete eigene Herkunft fuer die CSRF-Pruefung. Leer = aus der Anfrage
# ableiten (die geht durch Caddy, das nur diese eine Site bedient).
app.config["PORTAL_ORIGIN"]     = os.environ.get("PORTAL_ORIGIN", "")
# Wunsch #140, Stufe 3: Darf das Sitzungs-Cookie als Nachweis gelten?
# 0 = nein, nur der Token in der Adresse zaehlt (Zustand der Stufen 1-2).
app.config["SITZUNG_KONSUMIEREN"] = os.environ.get("SITZUNG_KONSUMIEREN", "0")
# Wunsch #140, Stufe 4: Bauen die Vorlagen Adressen OHNE Token?
# 0 = nein, jeder Link traegt den Token wie vorher. Die token-freien Routen
# existieren dann zwar, werden aber von nichts verlinkt - der Schalter nimmt
# die ganze Stufe zurueck, ohne eine einzige Route zu entfernen.
app.config["TOKENFREIE_URLS"]    = os.environ.get("TOKENFREIE_URLS", "0")
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Wunsch #133: Obergrenze für den Anfrage-Body. Die Foto-Importe (Rezepte,
# Vokabeln) lasen die Datei bisher erst komplett per .read() in den Speicher
# und prüften DANACH auf 8 MB - bei 256 MB RAM-Limit reichen ein paar
# parallele Riesen-Uploads, um den Container ins OOM zu schicken. Mit
# MAX_CONTENT_LENGTH bricht Flask schon beim Empfangen mit 413 ab, bevor
# etwas im Speicher landet. 10 MB liegt bewusst über dem 8-MB-Limit der
# Foto-Importe, damit deren eigene, freundlichere Meldung weiterhin greift.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Nummerierte Module in teile/ der Reihe nach laden
_here = Path(__file__).parent / "teile"
for _path in sorted(_here.glob("[0-9][0-9]_*.py")):
    _mod = importlib.import_module(f"teile.{_path.stem}")
    if hasattr(_mod, "init_app"):
        _mod.init_app(app)
