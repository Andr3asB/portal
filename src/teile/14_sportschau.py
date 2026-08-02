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

Wunsch #95: Zeitraum ist waehlbar (?tage=14/30/60/90, Default 14 wie bisher)
statt fest verdrahtet - `_TAGE_ANZAHL` wurde zur Konstante `_TAGE_STANDARD`,
`_TAGE_OPTIONEN` definiert die erlaubten Werte fuer den Knopf-Umschalter im
Template. Heatmap-Zellen und Schritte-Balken werden bei mehr Tagen einfach
schmaler (bestehendes flex:1 je Zelle/Balken, kein Sonderlayout noetig).

Wunsch #98: Durchschnitt der Schritte im gewaehlten Zeitraum rechts neben
der Überschrift "Schritte je Tag" - der heutige Tag zaehlt bewusst nicht
mit, da er meist noch nicht vorbei ist und den Schnitt nach unten verzerren
wuerde.

Wunsch #99: Die Y-Achsen-Beschriftung (Gridline-Labels) im Schritte-Chart
sass bisher rechts (`right:0`) und ueberlagerte damit die interessantesten
Balken (vorgestern/gestern/heute, da `tage` aeltesten zuerst sortiert und
der heutige Tag rechts steht). Auf `left:0` umgestellt - ueberlagert jetzt
die aeltesten (uninteressanteren) Tage links, Balkenreihenfolge/-ausrichtung
zum Trainings-Chart darueber bleibt unveraendert.

Wunsch #102: Der Trainingsanteil im Schritte-Balken (`.steps-bar-training`
in sportschau.html) faerbt sich jetzt fest gruen (#34c759, derselbe Wert
wie `.heatmap-cell.gruen`) statt `var(--farbe)` - vorher zufaellig blau,
weil das Andis persoenliche Nutzerfarbe ist. Reine CSS-Aenderung, keine
Python-Logik betroffen.

Wunsch #108: 0-Linie im Schritte-Chart per neuem `_gridlines()`-Helper -
vorher gab es erst ab 2000 Schritten ueberhaupt eine Gridline.

Wunsch #109: Heatmap-Zellen stecken jetzt in einer `.heatmap-cell-col`
(streckt sich wie `.steps-bar-col`), die sichtbare Zelle selbst ist
begrenzt+zentriert - vorher hatte die Zelle SELBST das max-width, wodurch
die Zeile auf breiten Bildschirmen nicht die volle Breite ausfuellte und
nicht mehr mit dem Schritte-Chart darunter uebereinanderlag. Gleicher
gap-Wert (3px) wie `.steps-bars` fuer pixelgenaue Ausrichtung.

Wunsch #110: Zusaetzliche Wochenansicht (`_wochen_ansicht()`, GitHub-Stil:
7 Zeilen Mo-So, eine Spalte je ISO-Kalenderwoche) fuer schmale Bildschirme,
auf denen die Tagesansicht zu eng wird. Schritte werden pro Woche
aufsummiert, ein Balken je Woche statt je Tag. Rein CSS-gesteuert per
Media Query (Umschaltpunkt haengt von `tage_anzahl` ab, siehe
sportschau.html) - Server liefert immer BEIDE Ansichten, kein
Server-Roundtrip beim Umschalten noetig. Bewusst OHNE eigene Wochentag-
Beschriftungsspalte links neben dem Grid (Wochentag/Datum nur per Tooltip)
- eine solche Spalte wuerde den Grid-Start nach rechts verschieben und die
Ausrichtung mit dem darunterliegenden Schritte-Wochenchart brechen (genau
die Regression, die Wunsch #109 fuer die Tagesansicht behoben hat).
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, render_template, request
from teile.kern import grant as check_grant, to_int

bp  = Blueprint("sportschau_app", __name__)
APP = "sportschau"

_TZ = ZoneInfo("Europe/Berlin")
_TAGE_STANDARD  = 14  # Wunsch #78 (vorher 10)
_TAGE_OPTIONEN  = [14, 30, 60, 90]  # Wunsch #95

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


def _gridlines(max_wert, schritt):
    """0-Linie (Wunsch #108) plus weitere Linien im Abstand `schritt`, bis
    max_wert erreicht ist. `schritt` unterscheidet sich zwischen Tages- und
    Wochenansicht (Wunsch #110), da Wochensummen deutlich groesser ausfallen
    und mit demselben 2000er-Abstand viel zu viele Linien ergeben wuerden."""
    linien = [{"wert": 0, "pct": 0}]
    if max_wert >= schritt:
        w = schritt
        while w <= max_wert:
            linien.append({"wert": w, "pct": w / max_wert * 100})
            w += schritt
    return linien


def _wochen_ansicht(tage, schritte_balken):
    """Wunsch #110: gruppiert tage/schritte_balken nach ISO-Kalenderwoche fuer
    die GitHub-artige Wochenansicht (7 Zeilen Mo-So, eine Spalte je Woche) -
    fuer schmale Bildschirme, auf denen die Tagesansicht zu eng wird. Schritte
    werden pro Woche aufsummiert und als EIN gemeinsamer Balken je Woche
    dargestellt, statt eines Balkens je Tag. Tage ausserhalb des angefragten
    Zeitraums (z.B. Anfang einer angeschnittenen ersten Woche) bleiben als
    None-Slot leer, genau wie bei GitHubs eigenem Kalender."""
    wochen_reihenfolge = []
    wochen_tage = {}  # (iso_jahr, iso_woche) -> {wochentag_index(0-6): iso_datum}
    for t in tage:
        d = date.fromisoformat(t)
        iso_jahr, iso_woche, iso_wochentag = d.isocalendar()
        key = (iso_jahr, iso_woche)
        if key not in wochen_tage:
            wochen_tage[key] = {}
            wochen_reihenfolge.append(key)
        wochen_tage[key][iso_wochentag - 1] = t

    schritte_je_tag = {b["tag"]: b for b in schritte_balken}
    wochen = []
    for key in wochen_reihenfolge:
        slots = wochen_tage[key]
        gesamt    = sum(schritte_je_tag[t]["gesamt"]   for t in slots.values() if t in schritte_je_tag)
        training  = sum(schritte_je_tag[t]["training"] for t in slots.values() if t in schritte_je_tag)
        wochen.append({
            "label": f"KW{key[1]}",
            "tage": [slots.get(i) for i in range(7)],
            "gesamt": round(gesamt),
            "training": round(training),
        })

    max_wochen_schritte = max((w["gesamt"] for w in wochen), default=0)
    for w in wochen:
        w["pct_gesamt"]    = (w["gesamt"] / max_wochen_schritte * 100) if max_wochen_schritte else 0
        w["pct_training"]  = (w["training"] / w["gesamt"] * 100) if w["gesamt"] else 0

    return wochen, max_wochen_schritte


@bp.route("/a/sportschau/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403

    tage_anzahl = to_int(request.args.get("tage"))
    if tage_anzahl not in _TAGE_OPTIONEN:
        tage_anzahl = _TAGE_STANDARD

    heute = date.today()
    tage  = [(heute - timedelta(days=i)).isoformat() for i in range(tage_anzahl - 1, -1, -1)]

    workouts = _hae_workouts(heute - timedelta(days=tage_anzahl - 1), heute)
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
    start_ms = now_ms - tage_anzahl * 24 * 3600 * 1000
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

    # Wunsch #98: Durchschnitt fuer den gewaehlten Zeitraum, OHNE den heutigen
    # Tag - der ist meist noch nicht zu Ende und wuerde den Schnitt nach unten
    # verzerren.
    schritte_ohne_heute = [b["gesamt"] for b in schritte_balken if b["tag"] != heute.isoformat()]
    schritte_schnitt = round(sum(schritte_ohne_heute) / len(schritte_ohne_heute)) if schritte_ohne_heute else 0
    gridlines = _gridlines(max_schritte, 2000)

    # Wunsch #110: Wochenansicht fuer schmale Bildschirme - wird immer mit
    # berechnet (nicht nur bei Bedarf), da rein CSS-gesteuert per Media Query
    # zwischen Tages-/Wochenansicht umgeschaltet wird (kein Server-Roundtrip).
    wochen, max_wochen_schritte = _wochen_ansicht(tage, schritte_balken)
    wochen_gridlines = _gridlines(max_wochen_schritte, 10000)

    return render_template("sportschau.html",
        user=user, token=token, farbe=user["farbe"],
        tage=tage, trainingsarten=trainingsarten, trainings_tage=trainings_tage,
        fehler=fehler, tage_anzahl=tage_anzahl, tage_optionen=_TAGE_OPTIONEN,
        fehler_schritte=fehler_schritte, schritte_balken=schritte_balken, gridlines=gridlines,
        schritte_schnitt=schritte_schnitt,
        wochen=wochen, wochen_gridlines=wochen_gridlines,
    )


def init_app(app):
    app.register_blueprint(bp)
