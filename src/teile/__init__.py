import importlib, sys

# 00_kern als 'teile.kern' verfügbar machen, damit andere Module
# `from teile.kern import get_db` schreiben können.
_kern = importlib.import_module("teile.00_kern")
sys.modules.setdefault("teile.kern", _kern)

# 04_todo als 'teile.todo' verfügbar machen (Wunsch #90) - kinderplan
# braucht serien_pool_fuer_tag()/serie_einsortieren() für den Aufgaben-Pool.
_todo = importlib.import_module("teile.04_todo")
sys.modules.setdefault("teile.todo", _todo)
