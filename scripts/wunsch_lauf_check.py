"""Was hat der stuendliche Lauf (#157) jetzt zu tun? – eine Antwort, drei Listen.

Laeuft NICHT hier, sondern im Portal-Container, und wird per stdin dorthin
geschoben, damit keine Zeile SQL durch zwei Anfuehrungszeichen-Ebenen muss:

    ssh -p 2222 claude@10.0.0.100 "docker exec -i portal python -" < scripts/wunsch_lauf_check.py

Nur lesend. Es entscheidet nichts, es beantwortet genau eine Frage: gibt es
gerade Arbeit? Wenn die drei Zaehler 0 sind, ist der Lauf fertig und darf
nichts weiter tun – das ist die Regel aus journal.md (08.08.2026), ohne die
24 Fortschrittsberichte am Tag herauskaemen.

Drei Kategorien, absichtlich getrennt:

* ANTWORTEN – Andi hat auf eine Rueckfrage geantwortet (juengste 'antwort'
  neuer als die juengste 'frage'). Das hat Vorrang: hier wartet jemand.
* FREIGEGEBEN – offen, Prioritaet gesetzt und nicht 'zurueckgestellt'.
  Wuensche ohne Prioritaet (NULL) sind NICHT freigegeben (Wunsch #152/#157),
  'zurueckgestellt' ist unantastbar (Wunsch #61).
* WARTET – Rueckfrage gestellt, noch keine Antwort. Nur zur Information,
  damit nicht dieselbe Frage ein zweites Mal gestellt wird.
"""
import os
import sqlite3

db = sqlite3.connect(os.environ.get("DB_PATH", "/data/portal.db"))
db.row_factory = sqlite3.Row

PRIO = """
    CASE prioritaet WHEN 'sehr_hoch' THEN 1 WHEN 'hoch' THEN 2
                    WHEN 'mittel'    THEN 3 WHEN 'niedrig' THEN 4 ELSE 5 END
"""

rows = db.execute(f"""
    SELECT w.id, w.titel, w.text, w.app_slug, w.ansicht, w.prioritaet,
           (SELECT max(erstellt) FROM wunsch_aktionen
             WHERE wunsch_id = w.id AND art = 'frage')   AS letzte_frage,
           (SELECT max(erstellt) FROM wunsch_aktionen
             WHERE wunsch_id = w.id AND art = 'antwort') AS letzte_antwort
    FROM   wuensche w
    WHERE  w.erledigt = 0
    ORDER  BY {PRIO} ASC, w.erstellt ASC
""").fetchall()


def ist_frei(r):
    return r["prioritaet"] not in (None, "", "zurueckgestellt")


antworten = [r for r in rows if r["letzte_frage"] and r["letzte_antwort"]
             and r["letzte_antwort"] > r["letzte_frage"]]
wartet    = [r for r in rows if r["letzte_frage"]
             and (not r["letzte_antwort"] or r["letzte_antwort"] < r["letzte_frage"])]
# Ueber IDs ausschliessen, nicht ueber die Row-Objekte: sqlite3.Row vergleicht
# sich der Reihe nach ueber die Werte, ein `not in` darauf ist nur zufaellig
# richtig, solange keine zwei Wuensche gleich aussehen.
schon = {r["id"] for r in antworten} | {r["id"] for r in wartet}
freigegeben = [r for r in rows if ist_frei(r) and r["id"] not in schon]


def zeile(r):
    ort = r["ansicht"] or r["app_slug"] or "-"
    titel = r["titel"] or (r["text"] or "")[:70]
    return f"  #{r['id']} [{r['prioritaet'] or 'ohne'}] ({ort}) {titel}"


print(f"ARBEIT: {len(antworten) + len(freigegeben)}"
      f"  (antworten={len(antworten)} freigegeben={len(freigegeben)}"
      f" wartet_auf_andi={len(wartet)})")

print("\n=== NEUE ANTWORTEN (zuerst lesen) ===")
for r in antworten:
    print(zeile(r))
    for a in db.execute("""
        SELECT art, text, erstellt FROM wunsch_aktionen
        WHERE wunsch_id = ? ORDER BY erstellt DESC LIMIT 4
    """, (r["id"],)).fetchall():
        print(f"      {a['erstellt'][:16]} {a['art']}: {(a['text'] or '')[:300]}")

print("\n=== FREIGEGEBEN (umsetzen) ===")
for r in freigegeben:
    print(zeile(r))
    print(f"      {(r['text'] or '')[:500]}")

print("\n=== WARTET AUF ANDI (nicht anfassen, nicht nochmal fragen) ===")
for r in wartet:
    print(zeile(r))

db.close()
