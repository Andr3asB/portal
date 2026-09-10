#!/usr/bin/env python3
"""Welche Metriken liefert der hae-Server? Läuft IM Container (Wunsch #274):

    ssh -p 2222 claude@10.0.0.100 "docker exec -i portal python -" < scripts/hae_metriken.py

Nur lesend. Fragt für jeden Kandidaten `/api/metrics/<name>` die letzten
90 Tage ab und zeigt Status, Anzahl und die ersten zwei Einträge - so sieht
man, wie ein Metrik-Name heißt und welche Felder (qty, units, date, source)
die Antwort trägt, bevor man ein Diagramm darauf baut. Der API-Schlüssel wird
nie ausgegeben.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KANDIDATEN = sys.argv[1:] or [
    "weight_body_mass", "body_mass_index", "body_fat_percentage",
    "lean_body_mass", "step_count",
]

basis = os.environ.get("HAE_API_URL", "").rsplit("/", 1)[0]
schluessel = os.environ.get("HAE_API_KEY", "")
if not basis or not schluessel:
    raise SystemExit("HAE_API_URL/HAE_API_KEY fehlen im Container")

jetzt_ms = int(time.time() * 1000)
von_ms = jetzt_ms - 90 * 86400 * 1000
for name in KANDIDATEN:
    frage = urllib.parse.urlencode({"from": von_ms, "to": jetzt_ms})
    anfrage = urllib.request.Request(f"{basis}/metrics/{name}?{frage}",
                                     headers={"api-key": schluessel})
    try:
        with urllib.request.urlopen(anfrage, timeout=8) as antwort:
            daten = json.loads(antwort.read())
    except urllib.error.HTTPError as fehler:
        print(f"{name:22s} HTTP {fehler.code}")
        continue
    except Exception as fehler:
        print(f"{name:22s} FEHLER {fehler}")
        continue
    if isinstance(daten, list):
        print(f"{name:22s} {len(daten):5d} Einträge  {json.dumps(daten[:2], ensure_ascii=False)[:300]}")
    else:
        print(f"{name:22s} {json.dumps(daten, ensure_ascii=False)[:300]}")
