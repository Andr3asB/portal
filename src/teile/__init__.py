import importlib, sys

# 00_kern als 'teile.kern' verfügbar machen, damit andere Module
# `from teile.kern import get_db` schreiben können.
_kern = importlib.import_module("teile.00_kern")
sys.modules.setdefault("teile.kern", _kern)
