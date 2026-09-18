#!/usr/bin/env bash
#
# PreToolUse-Hook für Claude Code – Familienportal auf home02.
#
# Zweck: Gefährliche Kommandos abfangen, AUCH wenn sie als Nutzlast in
# einem ssh-Aufruf stecken. Präfix-basierte Deny-Regeln greifen dort
# nicht, weil die Zeile mit "ssh" beginnt.
#
# Installation:
#   cp guardrails.sh  .claude/guardrails.sh
#   chmod +x          .claude/guardrails.sh
#
# Rückgabe: exit 0 = erlaubt, exit 2 = blockiert (stderr geht an Claude).
#
# Wunsch #290 (Sicherheitsaudit 16.09.2026, Befund N-12): Der Hook ist seit
# dem 18.09.2026 FAIL-CLOSED (unlesbare Nutzlast = blockiert, vorher = alles
# durch), kennt Regeln gegen den ABFLUSS von Geheimnissen (nicht nur gegen
# Zerstörung) und wird von tests/test_guardrails.py mit Beispielen durch-
# gefahren - ein Wächter, der nicht anschlagen kann, ist schlimmer als keiner.

set -uo pipefail

INPUT="$(cat)"

block() {
  echo "GUARDRAIL: $1" >&2
  echo "Blockierter Befehl: ${CMD:-<nicht lesbar>}" >&2
  echo "Wenn das wirklich nötig ist, erkläre Andi warum und lass es ihn selbst ausführen." >&2
  exit 2
}

# Nutzlast lesen. Erst python3, dann python (Windows-Store-Alias ohne
# Installation, PATH-Unterschiede). Klappt beides nicht: blockieren - nicht
# durchwinken.
_lesen() {
  printf '%s' "$INPUT" | "$1" -c '
import sys, json
try:
    d = json.load(sys.stdin)
    c = d.get("tool_input", {}).get("command", "")
    if not isinstance(c, str):
        raise ValueError("command ist kein Text")
    sys.stdout.write("OK:" + c)
except Exception:
    sys.stdout.write("ERR")
' 2>/dev/null
}
ROH="$(_lesen python3 2>/dev/null || true)"
[[ "$ROH" == OK:* ]] || ROH="$(_lesen python 2>/dev/null || true)"
[[ "$ROH" == OK:* ]] || { CMD=""; block "Nutzlast nicht lesbar - fail-closed (Wunsch #290)."; }
CMD="${ROH#OK:}"

# Leerer Befehl: nichts zu prüfen, nichts zu blockieren.
[[ -z "$CMD" ]] && exit 0

# Wortgrenze für Kommandonamen: Zeilenanfang, Trenner, Anführungszeichen oder
# ein Backslash (`\sudo` umgeht Aliasse, nicht diesen Hook).
G='(^|[;&|[:space:]"'\''\\])'

# ── Host-Ebene: nichts installieren, nichts umkonfigurieren ──────────────
grep -Eq "${G}sudo([[:space:]]|$)"      <<<"$CMD" && block "sudo ist tabu (Bauplan Abschnitt 0)."
grep -Eq "${G}(apt|apt-get|dpkg|snap|yum|dnf|pacman)([[:space:]]|$)" <<<"$CMD" && block "Keine Paketinstallation auf dem Host."
grep -Eq "${G}systemctl[[:space:]]+(start|stop|restart|reload|enable|disable|mask|kill|edit|set-property|daemon-reload|daemon-reexec)" <<<"$CMD" && block "Keine Änderung an Host-Diensten."
grep -Eq "${G}(crontab|timedatectl|ufw|iptables|nft)([[:space:]]|$)" <<<"$CMD" && block "Host-Konfiguration (Cron/Zeit/Firewall) ist tabu."

# ── Geteiltes macvlan-Netz: fremde Stacks nicht zerreißen ────────────────
grep -Eq 'docker[[:space:]]+network[[:space:]]+(rm|prune|disconnect)' <<<"$CMD" && block "Das macvlan-Netz ist geteilte Infrastruktur – nie entfernen oder trennen."
grep -Eq 'docker[[:space:]]+network[[:space:]]+create'                <<<"$CMD" && block "Kein neues Netz anlegen – das bestehende wird als external eingebunden."

# ── Volumes: fremde Daten und Zertifikate ───────────────────────────────
grep -Eq 'docker[[:space:]]+volume[[:space:]]+(rm|prune)'  <<<"$CMD" && block "Volumes werden nicht gelöscht."
grep -Eq 'docker[[:space:]]+system[[:space:]]+prune'       <<<"$CMD" && block "system prune räumt fremde Ressourcen mit ab."
grep -Eq 'iobroker-certs' <<<"$CMD" && grep -Eq '(rm|mv|chmod|chown|tee|>>?[[:space:]]*/certs)' <<<"$CMD" \
  && block "Das Zertifikats-Volume gehört iobroker und ist nur lesbar."

# ── compose: die zerstörerischen Flags ──────────────────────────────────
grep -Eq 'docker[[:space:]]+compose.*(down|rm).*(-v|--volumes|--remove-orphans)' <<<"$CMD" \
  && block "compose down mit -v/--remove-orphans trifft auch fremde Objekte."

# ── Container-Ausbruch (Wunsch #290) ────────────────────────────────────
grep -Eq 'docker[[:space:]]+(container[[:space:]]+)?(run|create)[^|;&]*(--privileged|/var/run/docker\.sock|-v[[:space:]]+/:|--mount[^|;&]*source=/,|--pid[[:space:]=]+host|--network[[:space:]=]+host|--cap-add[[:space:]=]+(ALL|SYS_ADMIN))' <<<"$CMD" \
  && block "Container mit Host-Zugriff (privileged/Docker-Socket/Host-Wurzel) – nein."
grep -Eq 'docker[[:space:]]+(compose[[:space:]]+)?exec[^|;&]*(-u|--user)[[:space:]=]+(0|root)([[:space:]:]|$)' <<<"$CMD" \
  && block "Kein exec als root in den Containern."

# ── Geheimnisse: nichts davon in eine Ausgabe (Wunsch #290) ─────────────
# Jede Ausgabe landet im Sitzungs-Transkript und beim Modellanbieter. Die
# .env, die SSH-Schlüssel, die Umgebung der Container und /proc/*/environ
# sind genau das, was .env.example "im Passwortmanager" sehen will.
# `.env.example` bleibt erlaubt (Vorlage ohne Werte); `.env.vor-*` ist eine
# alte Sicherung mit Werten.
S='(\.env([[:space:]"'\''&;|)]|$)|\.env\.vor|/srv/familienportal/ssh/|(^|[/[:space:]"'\''])id_(ed25519|rsa)([[:space:]"'\''&;|)]|$)|/proc/(self|[0-9]+)/environ)'
grep -Eq "${G}(cat|less|more|head|tail|tac|nl|grep|egrep|fgrep|rg|sed|awk|cut|sort|uniq|wc|strings|xxd|od|hexdump|base64|cp|scp|rsync|tee|python[0-9.]*|sqlite3|source|\.)[^|;&]*${S}" <<<"$CMD" \
  && block "Lesen oder Kopieren von .env / SSH-Schlüsseln / Prozessumgebung – Geheimnisse gehören in keine Ausgabe."
# Das Wortende schliesst auch das Anführungszeichen ein, mit dem eine
# ssh-Nutzlast endet: `ssh ... "docker exec portal env"`.
E='([[:space:]"'\''|;&)]|$)'
grep -Eq "docker[[:space:]]+(compose[[:space:]]+)?exec[^|;&]*[[:space:]](env|printenv)${E}" <<<"$CMD" \
  && block "env/printenv im Container zeigt TOKEN_KEY, SECRET_KEY und alle API-Schlüssel."
grep -Eq "docker[[:space:]]+compose[[:space:]]+config${E}" <<<"$CMD" \
  && block "compose config löst die .env auf und druckt jeden Wert."
if grep -Eq 'docker[[:space:]]+(container[[:space:]]+)?inspect' <<<"$CMD"; then
  if ! grep -Eq -- '--format' <<<"$CMD" || grep -Eq '\.Env\b|Config\.Env|json[[:space:]]+\.Config([[:space:]}]|$)|json[[:space:]]+\.([[:space:]}]|$)' <<<"$CMD"; then
    block "docker inspect ohne engen --format zeigt die komplette Umgebung (env_file)."
  fi
fi

# ── Verschleierung ──────────────────────────────────────────────────────
grep -Eq 'base64[[:space:]]+(-d|-D|--decode)[^|;&]*\|[[:space:]]*(ba|z|da)?sh([[:space:]]|$)' <<<"$CMD" \
  && block "Dekodierter Code direkt in eine Shell – nein."

# ── Schreibzugriffe außerhalb des Projektverzeichnisses auf home02 ──────
if grep -Eq "${G}ssh([[:space:]]|$)" <<<"$CMD"; then
  grep -Eq '(rm|mv|cp|tee|chmod|chown|mkdir|touch|sed -i)[[:space:]]+[^|;&]*(/etc/|/usr/|/var/|/boot/|/opt/|/root/|/home/)' <<<"$CMD" \
    && block "Schreibzugriff außerhalb /srv/familienportal/ auf home02."
fi

# ── Die Familiendaten selbst (Wunsch #290) ──────────────────────────────
grep -Eq "${G}rm[[:space:]]+[^|;&]*/srv/familienportal/(data|ssh)" <<<"$CMD" \
  && block "Das Datenverzeichnis wird nicht gelöscht – dort liegen die Familiendaten und das Backup-Ziel."
grep -Eq "${G}rm[[:space:]]+(-[a-zA-Z]+[[:space:]]+)*([^|;&]*[[:space:]])?\.?/?data/?${E}" <<<"$CMD" \
  && block "Ein lokales data/ wäre eine zurückgespielte Sicherung – wird nicht gelöscht."

# ── Git: nichts, was Andi selbst nachziehen müsste ──────────────────────
grep -Eq 'git[[:space:]]+push[^|;&]*([[:space:]]-f([[:space:]]|$)|--force)' <<<"$CMD" && block "Kein force-push (CLAUDE.md: ein Branch, keine Umschreibung)."
grep -Eq 'git[[:space:]]+remote[[:space:]]+(set-url|remove|rm|rename)' <<<"$CMD" && block "Das Remote bleibt, wie es ist."
grep -Eq 'git[[:space:]]+(filter-branch|filter-repo)' <<<"$CMD" && block "Historie umschreiben ist Andis Entscheidung (siehe #281)."

# ── Klassiker ───────────────────────────────────────────────────────────
grep -Eq 'rm[[:space:]]+(-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+)+/([[:space:]]|$|\*)' <<<"$CMD" && block "rm -rf auf / – nein."
grep -Eq 'mkfs|dd[[:space:]]+if=.*of=/dev/' <<<"$CMD" && block "Blockgeräte werden nicht angefasst."
grep -Eq ':\(\)\{.*\};:' <<<"$CMD" && block "Fork-Bombe."

exit 0
