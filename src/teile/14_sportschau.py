"""
Sportschau-App – Trainings-Heatmap aus Andis hae-Server (Health Auto Export).
URL-Präfix: /a/sportschau/<token>/

Wunsch #62: Daten kommen ausschließlich on-the-fly per REST-API (kein
Speichern in portal.db) von HAE_API_URL (Endpoint /api/workouts, Read-Token
HAE_API_KEY aus .env, Header "api-key"). Ist der hae-Server nicht erreichbar
oder nicht konfiguriert, zeigt die Seite einen Hinweis statt eines Fehlers.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, render_template
from teile.kern import grant as check_grant

bp  = Blueprint("sportschau_app", __name__)
APP = "sportschau"

_TZ = ZoneInfo("Europe/Berlin")


def _hae_workouts(start_date, end_date):
    """Ruft Trainings im Zeitraum ab. None bei Konfigurations-/Netzwerkfehler."""
    url = current_app.config.get("HAE_API_URL", "")
    key = current_app.config.get("HAE_API_KEY", "")
    if not url or not key:
        return None
    query = urllib.parse.urlencode({
        "startDate": start_date.isoformat(),
        "endDate":   end_date.isoformat(),
    })
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


@bp.route("/a/sportschau/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    heute = date.today()
    tage  = [(heute - timedelta(days=i)).isoformat() for i in range(9, -1, -1)]

    workouts = _hae_workouts(heute - timedelta(days=9), heute)
    fehler = workouts is None

    # {trainingsart: {tag, tag, ...}} – lokale Zeitzone, da start_time als UTC kommt.
    trainings_tage = {}
    for w in (workouts or []):
        art = w.get("workout_type") or "Sonstiges"
        try:
            start_utc = datetime.fromisoformat((w.get("start_time") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        tag = start_utc.astimezone(_TZ).date().isoformat()
        trainings_tage.setdefault(art, set()).add(tag)

    trainingsarten = sorted(trainings_tage.keys())

    return render_template("sportschau.html",
        user=user, token=token, farbe=user["farbe"],
        tage=tage, trainingsarten=trainingsarten, trainings_tage=trainings_tage,
        fehler=fehler,
    )


def init_app(app):
    app.register_blueprint(bp)
