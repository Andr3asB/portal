"""Log-Redaktion: Zugangstokens kürzen, Steuerzeichen entfernen.

Bewusst ein winziges Modul ohne jede Abhängigkeit, weil zwei sehr
verschiedene Stellen dieselbe Regel brauchen:

* `glogging_redact.py` - der Gunicorn-Access-Logger. Er wird vom
  Gunicorn-Arbiter geladen, BEVOR die App existiert, und darf deshalb weder
  Flask noch `teile.kern` importieren.
* `teile/00_kern.py` - stellt `log_sicher()` allen App-Modulen bereit
  (CSRF-Verdacht in 20_csrf.py, CSP-Berichte in 21_csp.py).

Wunsch #285 (Sicherheitsaudit 16.09.2026, Befund N-06): Vorher kürzte nur
der Access-Logger Tokens; `current_app.logger.warning(... request.path ...)`
in 20_csrf.py schrieb einen Token-Pfad ungekürzt ins Anwendungs-Log, und ein
`%0a` im Pfad erzeugte dort eine zweite, gefälschte Zeile - genau das
Muster, das Wunsch #205 am CSP-Endpunkt schon geschlossen hatte, nur eine
Datei weiter.
"""
import re

# /p/<token> und /a/<slug>/<token>/... - der Token ist token_urlsafe(18),
# also 24 Zeichen; ab 10 zusammenhängenden Token-Zeichen wird gekürzt.
# Kurze Pfadteile wie /a/todo/status bleiben lesbar.
TOKEN_RE = re.compile(r'(/(?:p|a/[a-z]+))/[A-Za-z0-9_\-]{10,}')

# Zeilenumbrüche, ASCII-Steuerzeichen, DEL und die Unicode-Zeilentrenner -
# alles, womit sich im Log eine neue Zeile vortäuschen liesse.
_STEUERZEICHEN = re.compile(r"[\r\n\x00-\x1f\x7f  ]+")


def token_kuerzen(text: str) -> str:
    """`/a/todo/AbCdEf…/status` -> `/a/todo/<redacted>/status`."""
    return TOKEN_RE.sub(r"\1/<redacted>", text)


def log_sicher(wert, laenge: int = 120) -> str:
    """Einen Wert log-tauglich machen: str, Token gekürzt, Steuerzeichen zu
    Leerzeichen, auf `laenge` gekappt. `None` wird zu '?'."""
    text = str(wert if wert is not None else "?")
    return token_kuerzen(_STEUERZEICHEN.sub(" ", text))[:laenge]
