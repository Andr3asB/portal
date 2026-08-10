import importlib, sys

# 00_kern als 'teile.kern' verfügbar machen, damit andere Module
# `from teile.kern import get_db` schreiben können.
_kern = importlib.import_module("teile.00_kern")
sys.modules.setdefault("teile.kern", _kern)

# 04_todo als 'teile.todo' verfügbar machen (Wunsch #90) - kinderplan
# braucht serien_pool_fuer_tag()/serie_einsortieren() für den Aufgaben-Pool.
_todo = importlib.import_module("teile.04_todo")
sys.modules.setdefault("teile.todo", _todo)

# 11_rezepte als 'teile.rezepte' verfügbar machen (Wunsch #184) - der
# Essensplan zeigt dieselben Rezepte und braucht dasselbe Symbol je
# Kategorie. Eine zweite Kopie der Zuordnung waere genau die Art
# Duplikat, die irgendwann auseinanderlaeuft.
_rezepte = importlib.import_module("teile.11_rezepte")
sys.modules.setdefault("teile.rezepte", _rezepte)
