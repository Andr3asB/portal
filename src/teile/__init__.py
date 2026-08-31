import importlib
import sys

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

# 02_werkstatt als 'teile.werkstatt' verfügbar machen (Wunsch #187) - die
# Werkstatt-App (05) zeigt die Wünsche an und braucht die Ersatz-Überschrift
# aus demselben Modul, in dem der KI-Titel entsteht.
_werkstatt = importlib.import_module("teile.02_werkstatt")
sys.modules.setdefault("teile.werkstatt", _werkstatt)

# 05_werkstatt_app als 'teile.werkstatt_app' - `manage.py wunsch_aktion`
# benutzt AKTIONS_ARTEN und _admins_benachrichtigen von dort, damit eine
# Rueckfrage von der Kommandozeile genau dieselbe Push-Nachricht ausloest
# wie eine aus der Weboberflaeche.
_werkstatt_app = importlib.import_module("teile.05_werkstatt_app")
sys.modules.setdefault("teile.werkstatt_app", _werkstatt_app)

# 16_vokabeln als 'teile.vokabeln' (Wunsch #194) - die Abfrageformen und der
# Aufgabenbau werden von den Tests direkt geprueft, ohne Umweg ueber HTTP.
_vokabeln = importlib.import_module("teile.16_vokabeln")
sys.modules.setdefault("teile.vokabeln", _vokabeln)
