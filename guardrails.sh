#!/usr/bin/env bash
#
# PreToolUse-Hook für Claude Code – Familienportal auf home02.
#
# Zweck: Gefährliche Kommandos abfangen, AUCH wenn sie als Nutzlast in
# einem ssh-Aufruf stecken. Präfix-basierte Deny-Regeln greifen dort
# nicht, weil die Zeile mit "ssh" beginnt.
#
# Installation:
#   cp guardrails.sh  Serveradmin/.claude/guardrails.sh
#   chmod +x          Serveradmin/.claude/guardrails.sh
#
# Rückgabe: exit 0 = erlaubt, exit 2 = blockiert (stderr geht an Claude).

set -uo pipefail

INPUT="$(cat)"

CMD="$(printf '%s' "$INPUT" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get("tool_input", {}).get("command", ""))
except Exception:
    print("")
' 2>/dev/null)"

[[ -z "$CMD" ]] && exit 0

block() {
  echo "GUARDRAIL: $1" >&2
  echo "Blockierter Befehl: $CMD" >&2
  echo "Wenn das wirklich nötig ist, erkläre Andi warum und lass es ihn selbst ausführen." >&2
  exit 2
}

# ── Host-Ebene: nichts installieren, nichts umkonfigurieren ──────────────
grep -Eq '(^|[;&|[:space:]"'\''])sudo([[:space:]]|$)'      <<<"$CMD" && block "sudo ist tabu (Bauplan Abschnitt 0)."
grep -Eq '(^|[;&|[:space:]"'\''])(apt|apt-get|dpkg|snap|yum|dnf|pacman)([[:space:]]|$)' <<<"$CMD" && block "Keine Paketinstallation auf dem Host."
grep -Eq '(^|[;&|[:space:]"'\''])systemctl[[:space:]]+(start|stop|restart|reload|enable|disable|mask)' <<<"$CMD" && block "Keine Änderung an Host-Diensten."
grep -Eq '(^|[;&|[:space:]"'\''])(crontab|timedatectl|ufw|iptables|nft)([[:space:]]|$)' <<<"$CMD" && block "Host-Konfiguration (Cron/Zeit/Firewall) ist tabu."

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

# ── Schreibzugriffe außerhalb des Projektverzeichnisses auf home02 ──────
if grep -Eq '(^|[;&|[:space:]"'\''])ssh([[:space:]]|$)' <<<"$CMD"; then
  grep -Eq '(rm|mv|cp|tee|chmod|chown|mkdir|touch|sed -i)[[:space:]]+[^|;&]*(/etc/|/usr/|/var/|/boot/|/opt/|/root/)' <<<"$CMD" \
    && block "Schreibzugriff außerhalb /srv/familienportal/ auf home02."
fi

# ── Klassiker ───────────────────────────────────────────────────────────
grep -Eq 'rm[[:space:]]+(-[a-zA-Z]*[rf][a-zA-Z]*[[:space:]]+)+/([[:space:]]|$|\*)' <<<"$CMD" && block "rm -rf auf / – nein."
grep -Eq 'mkfs|dd[[:space:]]+if=.*of=/dev/' <<<"$CMD" && block "Blockgeräte werden nicht angefasst."
grep -Eq ':\(\)\{.*\};:' <<<"$CMD" && block "Fork-Bombe."

exit 0
