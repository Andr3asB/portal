"""
Gunicorn-Access-Logger, der Zugangs-Tokens aus den Log-Zeilen entfernt.
Pfade wie /p/<token> und /a/<app>/<token>/... werden zu /p/<redacted> gekürzt.
Betrifft die Atome r (Request-Zeile), U (Pfad) und f (Referer).
"""
import re

from gunicorn.glogging import Logger

_TOKEN_RE = re.compile(r'(/(?:p|a/[a-z]+))/[A-Za-z0-9_\-]{10,}')


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        for k in ("r", "U", "f"):
            val = atoms.get(k)
            if val:
                atoms[k] = _TOKEN_RE.sub(r"\1/<redacted>", val)
        return atoms
