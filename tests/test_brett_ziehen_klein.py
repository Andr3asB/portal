"""Wunsch #262: Ziehen auf dem Brett, wenn eine Spalte fast den ganzen
Bildschirm einnimmt (iPhone).

Vom Telefon gemeldet: "funktioniert nicht sauber". Beim Lesen von
`ziehSortierung()` in base.html fanden sich vier Gruende, alle in derselben
Funktion:

1. Ein Zug begann erst nach 8 px in der HOEHE. Wer eine Karte seitlich in
   die Nachbarspalte schob, ohne dabei nach oben oder unten zu wandern, zog
   gar nicht - der Finger lag auf dem Griff, und nichts passierte.
2. Der Schatten folgte nur senkrecht; er klebte in seiner Spalte, waehrend
   der Finger laengst in der naechsten war. Nichts zeigte an, wohin die Karte
   faellt.
3. Das Brett scrollte waehrend des Zuges nicht mit. Auf dem Telefon ist die
   Nachbarspalte nur ein schmaler Streifen am Rand, die uebernaechste gar
   nicht zu erreichen.
4. Eine Spalte galt nur als Ziel, wenn der Finger auch in ihrer HOEHE lag -
   unterhalb einer kurzen Spalte war man "nirgends".

Die Tests hier lesen das Skript, wie alle Zieh-Tests des Projekts (#227/
#228): jede der vier Ursachen bekommt einen Wächter, dazu einer dafuer, dass
das Einrasten (scroll-snap) waehrend des Zuges aus- und danach wieder
eingeschaltet wird - sonst springt das mitscrollende Brett bei jedem Schritt
auf eine Spaltenkante zurueck.
"""
import pathlib
import re

TPL = pathlib.Path(__file__).resolve().parents[1] / "src" / "teile" / "templates"
BASE = (TPL / "base.html").read_text(encoding="utf-8")
BRETT = (TPL / "todo_kanban.html").read_text(encoding="utf-8")


def _zieh_skript():
    anfang = BASE.index("window.ziehSortierung = function")
    ende = BASE.index("window.tastaturSortierung = function", anfang)
    return BASE[anfang:ende]


def test_der_zug_beginnt_auch_bei_seitlicher_bewegung():
    skript = _zieh_skript()
    assert "startX" in skript
    assert re.search(r"Math\.hypot\(e\.clientX - zustand\.startX, e\.clientY - zustand\.startY\) > 8",
                     skript), "Schwelle muss beide Richtungen zaehlen"
    assert "Math.abs(e.clientY - zustand.startY) > 8" not in skript


def test_der_schatten_folgt_auch_seitlich():
    skript = _zieh_skript()
    assert "abstandX" in skript
    assert re.search(r"schatten\.style\.left = `\$\{e\.clientX - abstandX\}px`", skript)


def test_das_brett_rollt_am_rand_mit():
    skript = _zieh_skript()
    assert "function scrollElternteil" in skript, "der scrollbare Vorfahre der Spalte"
    assert "brett.scrollLeft += rollDx" in skript
    assert "requestAnimationFrame(rollen)" in skript
    # Nach jedem Schritt wandert der Platzhalter mit - sonst liegt er in einer
    # Spalte, die nicht mehr unter dem Finger ist. Das synthetische Ereignis
    # darf keinen zweiten Roll-Takt ausloesen.
    assert "folge({ clientX: letztes.x, clientY: letztes.y, synthetisch: true })" in skript
    assert "if (!e.synthetisch)" in skript


def test_das_einrasten_ist_waehrend_des_zuges_aus_und_danach_wieder_an():
    skript = _zieh_skript()
    assert "brett.style.scrollSnapType = 'none'" in skript
    assert "zustand.brett.style.scrollSnapType = zustand.snapVorher" in skript
    # ... und zwar in ende() UND abbruch(), sonst bleibt das Brett nach einem
    # abgebrochenen Zug ohne Einrasten.
    assert skript.count("ziehenAufraeumen();") >= 2


def test_die_spalte_zaehlt_ueber_die_ganze_hoehe():
    skript = _zieh_skript()
    folge = skript[skript.index("function folge"):]
    spaltenwahl = folge[:folge.index("const ziel = spalte")]
    assert "e.clientX >= r.left && e.clientX <= r.right" in spaltenwahl
    assert "clientY >= r.top" not in spaltenwahl, "die Hoehe darf keine Rolle spielen"


def test_das_brett_scrollt_weiterhin_waagerecht():
    """Die Voraussetzung fuer das Mitrollen: das Brett ist der scrollbare
    Vorfahre. Wer das auf `overflow:hidden` stellt, schaltet #262 aus."""
    assert re.search(r"\.brett\s*\{[^}]*overflow-x:auto", BRETT)
    assert re.search(r"\.brett\s*\{[^}]*scroll-snap-type:x", BRETT)


def test_listen_ohne_spalten_bleiben_unberuehrt():
    """Packliste und Einkauf verlassen sich darauf, dass nicht quer gezogen
    wird (#181) - das Mitrollen gilt nur mit `opt.spalten`."""
    skript = _zieh_skript()
    starte = skript[skript.index("function starte"):skript.index("function rollen")]
    assert "if (opt.spalten)" in starte
    folge = skript[skript.index("function folge"):skript.index("Wunsch #181")]
    assert "if (opt.spalten)" in folge and "randRollen(e)" in folge
