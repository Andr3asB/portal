"""
Gunicorn-Access-Logger, der Zugangs-Tokens aus den Log-Zeilen entfernt.
Pfade wie /p/<token> und /a/<app>/<token>/... werden zu /p/<redacted> gekürzt.
Betrifft die Atome r (Request-Zeile), U (Pfad) und f (Referer).

Die Regel selbst liegt seit Wunsch #285 in `redaktion.py`, damit das
Anwendungs-Log (teile.kern.log_sicher) dieselbe benutzt - vorher gab es sie
nur hier, und `current_app.logger` schrieb Token-Pfade ungekürzt.
"""
from gunicorn.glogging import Logger

from redaktion import token_kuerzen


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        for k in ("r", "U", "f"):
            val = atoms.get(k)
            if val:
                atoms[k] = token_kuerzen(val)
        return atoms
