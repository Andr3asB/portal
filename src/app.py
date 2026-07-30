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
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Nummerierte Module in teile/ der Reihe nach laden
_here = Path(__file__).parent / "teile"
for _path in sorted(_here.glob("[0-9][0-9]_*.py")):
    _mod = importlib.import_module(f"teile.{_path.stem}")
    if hasattr(_mod, "init_app"):
        _mod.init_app(app)
