"""Wunsch #213 (Sicherheitsaudit, Befund F-05): Bildbombe beim Barcode-Foto.

Alle vorhandenen Grenzen messen die DATEI - 8 MB in der Route,
MAX_CONTENT_LENGTH, Caddy. Keine misst die entpackte Fläche. Ein PNG von
wenigen Kilobyte kann zu hundert Megapixeln aufgehen; bei 4 Byte je Pixel sind
das mehrere hundert MB gegen ein Containerlimit von 256 MB. Das Portal läuft
ins OOM, `restart: unless-stopped` fängt es Sekunden später wieder - wer weiter
sendet, hält es unten.

**Warum Pillows eigene Sperre nicht reicht:** `MAX_IMAGE_PIXELS` löst dort nur
eine WARNUNG aus; hart abgebrochen wird erst beim Doppelten. Das Fenster
dazwischen wird tatsächlich alloziert. Deshalb misst der Code selbst nach -
zwischen `Image.open()` (liest nur den Kopf) und dem ersten echten Zugriff.

Die Testbombe ist deshalb auch keine echte Bombe: ein handgebauter PNG-Kopf,
der 20000x20000 behauptet, mit einem Byte Bilddaten. Genau das ist der Punkt -
wäre die Prüfung hinter dem Entpacken, würde dieser Test die Testmaschine
treffen statt den Fehler zu finden.
"""
import binascii
import importlib
import io
import struct

import pytest


@pytest.fixture()
def modul(app):
    return importlib.import_module("teile.10_einkauf")


def _png_kopf(breite, hoehe):
    """Ein PNG, das `breite`x`hoehe` BEHAUPTET, ohne sie zu enthalten."""
    def chunk(typ, daten):
        return (struct.pack(">I", len(daten)) + typ + daten
                + struct.pack(">I", binascii.crc32(typ + daten) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", b"\x00") + chunk(b"IEND", b""))


def _echtes_bild(breite=40, hoehe=40):
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (breite, hoehe), "white").save(puffer, format="PNG")
    return puffer.getvalue()


# --- Die Grenze greift ------------------------------------------------------

def test_bombe_wird_abgelehnt(modul):
    """20000x20000 = 400 Megapixel, als Datei rund 100 Byte."""
    rohdaten = _png_kopf(20000, 20000)
    assert len(rohdaten) < 1000, "Die Testbombe soll winzig sein - sonst prüft sie das Falsche"
    with pytest.raises(modul._BildZuGross):
        modul._barcode_aus_bild(rohdaten)


# Der Fall knapp UNTER der Grenze laeuft absichtlich weiter bis zu zxing und
# scheitert dort an den fehlenden Bilddaten. Pillow wirft die zugehoerige
# OSError beim Aufraeumen, was pytest als "unraisable" meldet - erwartetes
# Rauschen dieses einen Tests, kein Befund.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
@pytest.mark.filterwarnings("ignore::UserWarning")
def test_die_grenze_liegt_wo_sie_soll(modul):
    """Knapp darüber fliegt es, knapp darunter nicht - sonst könnte die
    Prüfung auch an etwas ganz anderem hängen."""
    grenze = modul._BARCODE_MAX_PIXEL
    kante = int(grenze ** 0.5)

    with pytest.raises(modul._BildZuGross):
        modul._barcode_aus_bild(_png_kopf(kante + 100, kante + 100))

    # Knapp darunter: kein _BildZuGross. Dass das Entpacken danach an den
    # fehlenden Bilddaten scheitert, ist hier egal - es geht um die Grenze.
    try:
        modul._barcode_aus_bild(_png_kopf(kante - 100, kante - 100))
    except modul._BildZuGross:
        pytest.fail("Ein Bild UNTER der Grenze wurde als zu gross abgelehnt")
    except Exception:
        pass


def test_normales_foto_geht_durch(modul):
    """Gegenprobe mit einem echten, kleinen Bild: kein Barcode drauf, also
    None - aber eben keine Ablehnung."""
    assert modul._barcode_aus_bild(_echtes_bild()) is None


# --- Die Route sagt, was los ist -------------------------------------------

def test_route_antwortet_mit_eigener_meldung(client, admin):
    """"Konnte nicht gelesen werden" wäre bei einem legitimen
    50-Megapixel-Foto irreführend - der Nutzer soll wissen, dass er die
    Auflösung herunterdrehen muss."""
    token = admin["tokens"]["einkauf"]
    antwort = client.post(
        f"/a/einkauf/{token}/barcode",
        data={"foto": (io.BytesIO(_png_kopf(20000, 20000)), "bombe.png")},
        content_type="multipart/form-data")
    assert antwort.status_code == 400
    assert "Bildpunkte" in antwort.get_json()["fehler"]


def test_die_pruefung_steht_vor_dem_entpacken(modul):
    """Der eigentliche Nachweis. Läge sie dahinter, hätte der Aufruf oben
    hunderte Megabyte angefordert, statt eine Ausnahme zu werfen - und dieser
    Test wäre nicht rot, sondern der Rechner wäre weg.

    Geprüft am Ort: nach `Image.open` (liest nur den Kopf) und vor `convert`
    bzw. `read_barcodes`.
    """
    import inspect
    # Nur die Anweisungen, keine Kommentare - die erwähnen `convert()` und
    # `read_barcodes()` erklärend und lägen sonst vor der Prüfung.
    quelle = "\n".join(
        z for z in inspect.getsource(modul._barcode_aus_bild).split("\n")
        if not z.strip().startswith("#"))
    pruefung = quelle.index("raise _BildZuGross(f")
    assert pruefung > quelle.index("Image.open"), "Prüfung steht vor Image.open"
    assert pruefung < quelle.index("bild.convert("), "Prüfung steht hinter dem Entpacken"
    assert pruefung < quelle.index("zxingcpp.read_barcodes"), "Prüfung steht hinter zxing"
