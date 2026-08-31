---
name: web-design-guidelines
description: UI-Review der Portal-Vorlagen gegen die Vercel Web Interface Guidelines (eingefrorene lokale Kopie). Nutzen bei "UI-Review", "Templates pruefen", "Design-Audit", "Accessibility-Check".
---

# Web Interface Guidelines (lokal eingefroren)

Prüfe die angegebenen Dateien (ohne Angabe: `src/teile/templates/*.html`)
gegen die Regeln in [`regeln.md`](regeln.md) im selben Ordner.

**Warum eine lokale Kopie:** Das Original
(vercel-labs/web-interface-guidelines, Commit `e3d624b` vom 17.08.2026,
MIT-Lizenz) lädt seine Regeln zur Laufzeit von GitHub – Anweisungen, die
sich jederzeit ändern könnten, führen wir hier nicht aus. Aktualisieren
heißt: neue Fassung holen, **komplett lesen**, dann diese Datei ersetzen
und den Commit-Stand oben nachziehen. Nie auf Laufzeit-Fetch zurückbauen.

## Hausregeln gehen vor

Bei Widerspruch gilt CLAUDE.md, nicht die Checkliste:

- **Title Case (Chicago)**: entfällt – das Portal ist deutsch, es gilt
  normale deutsche Groß-/Kleinschreibung.
- **React/Next/Tailwind-Spezifisches** (`hydration`, `nuqs`, `priority`,
  `focus-visible:ring-*`, controlled inputs): sinngemäß auf
  servergerendertes Jinja + Inline-CSS übertragen oder überspringen.
- **`<link rel="preconnect">` für CDNs**: entfällt – Projekt-Konvention ist
  lokales Bündeln, nie CDNs.
- **„URL reflects state"**: Filter-Persistenz über localStorage ist hier
  eine bewusste Entscheidung (Wunsch #223), kein Finding.
- **Tippflächen, Kontrast, Schriftgrößen, Löschen-Symbol, Fokus-Ring**:
  dafür gelten die (strengeren) eigenen Konventionen samt Wächter-Tests.

## Ablauf

1. `regeln.md` lesen.
2. Die Ziel-Dateien lesen und gegen alle anwendbaren Regeln prüfen.
3. Findings im `datei:zeile`-Format ausgeben, gruppiert nach Datei –
   knapp, ein Finding pro Zeile, `✓ pass` wenn nichts gefunden.
4. Bestätigte Findings werden zu Wünschen in der Werkstatt
   (`manage.py wunsch_neu`, ohne Priorität – Andi priorisiert),
   nicht direkt umgesetzt.
