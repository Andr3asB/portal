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

# Wunsch #272: Das Morning Briefing (27_briefing.py) fasst Essensplan und
# Geburtstage zusammen und haengt an der Startseite. Es braucht die
# Mahlzeiten-Konstanten (12), die Datumslogik der Geburtstage (23) und den
# Home-Nutzer (01) - alles per Alias statt als Kopie, damit z. B. der
# 29. Februar nur an EINER Stelle behandelt wird. Reihenfolge: erst die
# Lieferanten, dann das Briefing selbst.
_essensplan = importlib.import_module("teile.12_essensplan")
sys.modules.setdefault("teile.essensplan", _essensplan)
_geburtstage = importlib.import_module("teile.23_geburtstage")
sys.modules.setdefault("teile.geburtstage", _geburtstage)
_start_token = importlib.import_module("teile.01_start_token")
sys.modules.setdefault("teile.start_token", _start_token)
_briefing = importlib.import_module("teile.27_briefing")
sys.modules.setdefault("teile.briefing", _briefing)
