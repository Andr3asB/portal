"""
Sportschau-App – Trainings-Heatmap aus Andis hae-Server (Health Auto Export).
URL-Präfix: /a/sportschau/<token>/

Wunsch #62: Daten kommen ausschließlich on-the-fly per REST-API (kein
Speichern in portal.db) von HAE_API_URL (Endpoint /api/workouts, Read-Token
HAE_API_KEY aus .env, Header "api-key"). Ist der hae-Server nicht erreichbar
oder nicht konfiguriert, zeigt die Seite einen Hinweis statt eines Fehlers.

Wunsch #77: Zusätzlich Schritte je Tag als gestapeltes Balkendiagramm, Daten
vom Endpoint /api/metrics/step_count (gleicher Host/Key wie /api/workouts,
Pfad abgeleitet aus HAE_API_URL). Anders als /api/workouts erwartet dieser
Endpoint "from"/"to" als Unix-Millisekunden statt ISO-Datum (live geprüft,
kein Fehler - andere Konvention). Antwort: stündliche Buckets
{"date": ISO-UTC, "qty": Schrittzahl, ...}, mehrere "source"-Werte möglich
(Watch/iPhone), werden pro Stunde aufsummiert. Ob eine Stunde "Trainings-
Schritte" sind, wird per Zeitüberlappung mit den Workout-Fenstern aus
/api/workouts bestimmt (grobe Näherung auf Stundenbasis, feinere Daten
liefert die API nicht).
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, render_template
from teile.kern import grant as check_grant

bp  = Blueprint("sportschau_app", __name__)
APP = "sportschau"

_TZ = ZoneInfo("Europe/Berlin")
_TAGE_ANZAHL = 14  # Wunsch #78 (vorher 10)

# Wunsch #75: Der hae-Server liefert workout_type bereits deutsch lokalisiert,
# aber mit schlechter Wortwahl ("Ausführen" statt "Laufen" fuer Run, analog
# "Spaziergang" statt "Gehen" fuer Walk) - vermutlich eine generische
# HealthKit-Uebersetzung, die "Run" als Verb ("ausfuehren") statt als
# Trainingsart liest. Wird hier korrigiert statt am hae-Server (fremdes
# System, siehe bauplan.md); unbekannte Werte (z.B. "Wandern") bleiben
# unveraendert. Neue Fehluebersetzungen kommen per Wunsch dazu.
_ART_KORREKTUREN = {
    "Ausführen":  "Laufen",
    "Spaziergang": "Gehen",
}


def _art_anzeige(roh):
    for falsch, richtig in _ART_KORREKTUREN.items():
        if falsch in roh:
            return roh.replace(falsch, richtig)
    return roh


def _hae_workouts(start_date, end_date):
    """Ruft Trainings im Zeitraum ab. None bei Konfigurations-/Netzwerkfehler.

    Wunsch #88: end_date bekommt einen Tag aufgeschlagen, bevor er an den
    hae-Server geht. Der parst ein bare-date endDate als Mitternacht
    (00:00 UTC) jenes Tages - endDate=heute hätte also JEDES Training des
    laufenden Tages ausgeschlossen (start_time > Mitternacht), nicht nur
    an Randfällen, sondern grundsätzlich jeden Tag aufs Neue. Live per
    hae-Server-eigenen Logs bestätigt (Server loggt das geparste Start/Ende
    als vollen ISO-Zeitstempel). Ein zusätzlich geholter "morgen"-Tag ist
    unschädlich, da das Template nur über `tage` iteriert und das nie über
    heute hinausreicht."""
    url = current_app.config.get("HAE_API_URL", "")
    key = current_app.config.get("HAE_API_KEY", "")
    if not url or not key:
        return None
    query = urllib.parse.urlencode({
        "startDate": start_date.isoformat(),
        "endDate":   (end_date + timedelta(days=1)).isoformat(),
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


def _hae_steps(start_ms, end_ms):
    """Ruft stündliche Schrittzahlen ab. None bei Konfigurations-/Netzwerkfehler."""
    url = current_app.config.get("HAE_API_URL", "")
    key = current_app.config.get("HAE_API_KEY", "")
    if not url or not key:
        return None
    steps_url = url.rsplit("/", 1)[0] + "/metrics/step_count"
    query = urllib.parse.urlencode({"from": start_ms, "to": end_ms})
    req = urllib.request.Request(f"{steps_url}?{query}", headers={"api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _tages_schritte(steps_roh, workout_fenster, tage):
    """{tag_iso: {"gesamt": float, "training": float}} - ordnet jeden
    stündlichen Schritte-Eintrag (UTC) seinem lokalen Kalendertag zu und
    summiert als "training", wenn die Stunde ein Workout-Fenster berührt."""
    ergebnis = {t: {"gesamt": 0.0, "training": 0.0} for t in tage}
    for eintrag in (steps_roh or []):
        try:
            stunde_start = datetime.fromisoformat(eintrag["date"].replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        stunde_ende = stunde_start + timedelta(hours=1)
        tag = stunde_start.astimezone(_TZ).date().isoformat()
        if tag not in ergebnis:
            continue
        qty = float(eintrag.get("qty") or 0)
        ergebnis[tag]["gesamt"] += qty
        if any(start < stunde_ende and stunde_start < ende for start, ende in workout_fenster):
            ergebnis[tag]["training"] += qty
    return ergebnis


@bp.route("/a/sportschau/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    heute = date.today()
    tage  = [(heute - timedelta(days=i)).isoformat() for i in range(_TAGE_ANZAHL - 1, -1, -1)]

    workouts = _hae_workouts(heute - timedelta(days=_TAGE_ANZAHL - 1), heute)
    fehler = workouts is None

    # {trainingsart: {tag, tag, ...}} – lokale Zeitzone, da start_time als UTC kommt.
    # workout_fenster sammelt dieselben Zeitfenster zusätzlich als (start,ende)-
    # Paare für den Schritte/Training-Abgleich unten (Wunsch #77).
    trainings_tage = {}
    workout_fenster = []
    for w in (workouts or []):
        art = _art_anzeige(w.get("workout_type") or "Sonstiges")
        try:
            start_utc = datetime.fromisoformat((w.get("start_time") or "").replace("Z", "+00:00"))
            ende_utc  = datetime.fromisoformat((w.get("end_time")   or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        tag = start_utc.astimezone(_TZ).date().isoformat()
        trainings_tage.setdefault(art, set()).add(tag)
        workout_fenster.append((start_utc, ende_utc))

    trainingsarten = sorted(trainings_tage.keys())

    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - _TAGE_ANZAHL * 24 * 3600 * 1000
    steps_roh = _hae_steps(start_ms, now_ms)
    fehler_schritte = steps_roh is None
    tages_schritte = _tages_schritte(steps_roh, workout_fenster, tage) if not fehler_schritte else {}

    max_schritte = max((d["gesamt"] for d in tages_schritte.values()), default=0)
    schritte_balken = []
    for t in tage:
        werte = tages_schritte.get(t, {"gesamt": 0.0, "training": 0.0})
        gesamt = werte["gesamt"]
        schritte_balken.append({
            "tag": t,
            "tag_kurz": datetime.fromisoformat(t).strftime("%d."),
            "gesamt": round(gesamt),
            "training": round(werte["training"]),
            "nicht_training": round(gesamt - werte["training"]),
            "pct_gesamt": (gesamt / max_schritte * 100) if max_schritte else 0,
            "pct_training": (werte["training"] / gesamt * 100) if gesamt else 0,
        })
    gridlines = []
    if max_schritte >= 2000:
        schwelle = 2000
        while schwelle <= max_schritte:
            gridlines.append({"wert": schwelle, "pct": schwelle / max_schritte * 100})
            schwelle += 2000

    return render_template("sportschau.html",
        user=user, token=token, farbe=user["farbe"],
        tage=tage, trainingsarten=trainingsarten, trainings_tage=trainings_tage,
        fehler=fehler,
        fehler_schritte=fehler_schritte, schritte_balken=schritte_balken, gridlines=gridlines,
    )


def init_app(app):
    app.register_blueprint(bp)
