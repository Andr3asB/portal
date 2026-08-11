"""
Tierbaukasten-App – eigene Figur aus Bausteinen zusammensetzen
(Wunsch #64, erweitert um Wunsch #66).
URL-Präfix: /a/tierbaukasten/<token>/

Assistent mit drei Schritten (komplett clientseitig, ein einziges Formular
im Hintergrund): 1) Kategorie Mensch/Tier, 2) bei Tier zusätzlich die
Tierart, 3) Anpassen.

Direktes Feedback von Friederike (nicht über die Werkstatt-App, sondern im
Gespräch mit Andi): die Tiere wirkten "wie eine Strichzeichnung aus dem
Kindergarten" – zu einfach für eine Elfjährige, gewünscht war ein
"Memoji-artiger" Baukasten. Für Tiere gibt es dafür kein fertiges Tool
(recherchiert: DiceBear, animal-avatar-generator – keins bietet gezielt
wählbare Tier-Bausteine). Für die Mensch-Figur aber schon: DiceBear/
Avataaars (MIT-Engine + frei lizenzierter Stil von Pablo Stanley,
avataaars.com), komplett offline per `dicebear-core`/`dicebear-styles`
(Python, kein Netzwerkzugriff zur Laufzeit). Die Tier-Seite bleibt
handgezeichnetes SVG (Wunsch #66/#68/#69/#70), nur die Mensch-Seite nutzt
jetzt Avataaars.

Da DiceBear serverseitig rendert (kein JS-Äquivalent im Projekt gebündelt),
hat die Mensch-Vorschau – anders als bei Tieren – einen kleinen Server-
Roundtrip pro Änderung (POST .../vorschau-mensch, JSON mit dem fertigen
SVG). Auch gibt es dafür keine Seiten-/Rückansicht, da Avataaars nur eine
Frontalansicht liefert.

"tier_typ='mensch'" ist bewusst kein eigenes Schema-Feld – die Kategorie
Mensch/Tier lässt sich daraus ableiten. Alle Avataaars-Auswahlwerte landen
gesammelt als JSON in `dicebear_optionen`, um das Tier-Schema nicht mit
fachfremden Spalten zu überladen.

Jeder Nutzer sieht nur seine eigene Galerie, keine gemeinsame Pinnwand.

Wunsch #201: Neben dem Mülleimer steht ein ✏️. Es lädt die gespeicherte Figur
zurück in denselben Assistenten (Schritt 3) und schaltet das Formular auf die
Route `bearbeiten/<id>` um - es gibt also kein zweites Formular, das mit dem
ersten synchron gehalten werden müsste. Auch die Kategorie lässt sich dabei
wechseln, deshalb schreibt das Bearbeiten immer ALLE Spalten (siehe _SPALTEN).
"""
import json
import re
from importlib.resources import files as importlib_files

from flask import Blueprint, render_template, request, redirect, url_for, abort, jsonify
from dicebear import Avatar, Style
from teile.kern import get_db, grant as check_grant, to_int

bp  = Blueprint("tierbaukasten_app", __name__)
APP = "tierbaukasten"

TIERE = {
    "katze": "🐱 Katze", "hund": "🐶 Hund", "hase": "🐰 Hase",
    "baer": "🐻 Bär", "vogel": "🐦 Vogel", "fisch": "🐟 Fisch",
}
KATEGORIEN = {"tier": "🐾 Tier", "mensch": "🧍 Mensch"}
MUSTER = {"keins": "Keins", "streifen": "Streifen", "punkte": "Punkte", "flecken": "Flecken"}
# Wunsch #69: mehrere Accessoires gleichzeitig kombinierbar - "accessoire" in
# der DB ist eine kommagetrennte Liste von Schlüsseln aus diesem Dict, kein
# "Keins"-Eintrag mehr nötig (leere Liste = keins gewählt).
ACCESSOIRES = {"hut": "🎩 Hut", "schleife": "🎀 Schleife", "brille": "🕶️ Brille"}
ALLE_TYPEN = set(TIERE) | {"mensch"}

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_farbe(value, fallback):
    value = (value or "").strip()
    return value if _HEX_RE.match(value) else fallback


def _clean_koerperbau(value):
    wert = to_int(value, 50)
    return max(0, min(100, wert))


# ---------------------------------------------------------------------------
# Mensch-Figur per DiceBear/Avataaars (lokal, kein Netzwerkzugriff)
# ---------------------------------------------------------------------------

_AVATAAARS_STYLE = Style.from_json(
    importlib_files("dicebear_styles").joinpath("avataaars.json").read_text("utf-8")
)

MENSCH_HAUT = ["#614335", "#d08b5b", "#ae5d29", "#edb98a", "#ffdbb4", "#fd9841", "#f8d25c"]
MENSCH_HAARFARBEN = [
    "#a55728", "#2c1b18", "#b58143", "#d6b370", "#724133",
    "#4a312c", "#f59797", "#ecdcbf", "#c93305", "#e8e1e1",
]
MENSCH_KLEIDUNGSFARBEN = [
    "#262e33", "#65c9ff", "#5199e4", "#25557c", "#e6e6e6", "#929598", "#3c4f5c",
    "#b1e2ff", "#a7ffc4", "#ffafb9", "#ffffb1", "#ff488e", "#ff5c5c", "#ffffff",
]
MENSCH_ACCESSOIRE_FARBEN = MENSCH_KLEIDUNGSFARBEN + ["#ffdeb5"]

MENSCH_FRISUR = {
    "bigHair": "Große Locken", "bob": "Bob", "bun": "Dutt", "curly": "Lockig",
    "curvy": "Wellig", "dreads": "Dreads", "dreads01": "Dreads 1", "dreads02": "Dreads 2",
    "frida": "Frida-Stil", "frizzle": "Kraus", "fro": "Afro", "froBand": "Afro mit Band",
    "hat": "Mütze", "hijab": "Hijab", "longButNotTooLong": "Lang", "miaWallace": "Bob mit Pony",
    "shaggy": "Zottelig", "shaggyMullet": "Vokuhila", "shavedSides": "Seiten rasiert",
    "shortCurly": "Kurz lockig", "shortFlat": "Kurz glatt", "shortRound": "Kurz rund",
    "shortWaved": "Kurz gewellt", "sides": "Seitenscheitel", "straight01": "Glatt 1",
    "straight02": "Glatt 2", "straightAndStrand": "Glatt mit Strähne",
    "theCaesar": "Caesar-Schnitt", "theCaesarAndSidePart": "Caesar mit Scheitel",
    "turban": "Turban", "winterHat02": "Wintermütze 1", "winterHat03": "Wintermütze 2",
    "winterHat04": "Wintermütze 3", "winterHat1": "Wintermütze 4",
}
MENSCH_AUGEN = {
    "closed": "Geschlossen", "cry": "Weinend", "default": "Normal", "eyeRoll": "Augenrollen",
    "happy": "Fröhlich", "hearts": "Herzchen", "side": "Zur Seite", "squint": "Zusammengekniffen",
    "surprised": "Überrascht", "wink": "Zwinkern", "winkWacky": "Verrücktes Zwinkern", "xDizzy": "Schwindelig",
}
MENSCH_AUGENBRAUEN = {
    "angry": "Wütend", "angryNatural": "Wütend natürlich", "default": "Normal",
    "defaultNatural": "Normal natürlich", "flatNatural": "Flach natürlich",
    "frownNatural": "Stirnrunzeln", "raisedExcited": "Hochgezogen",
    "raisedExcitedNatural": "Hochgezogen natürlich", "sadConcerned": "Besorgt",
    "sadConcernedNatural": "Besorgt natürlich", "unibrowNatural": "Zusammengewachsen",
    "upDown": "Schief", "upDownNatural": "Schief natürlich",
}
MENSCH_MUND = {
    "concerned": "Besorgt", "default": "Normal", "disbelief": "Ungläubig", "eating": "Essend",
    "grimace": "Grimasse", "sad": "Traurig", "screamOpen": "Schreiend", "serious": "Ernst",
    "smile": "Lächeln", "tongue": "Zunge raus", "twinkle": "Verschmitzt", "vomit": "Übel",
}
MENSCH_BART = {
    "beardLight": "Leichter Bart", "beardMajestic": "Voller Bart", "beardMedium": "Mittlerer Bart",
    "moustacheFancy": "Eleganter Schnurrbart", "moustacheMagnum": "Schnurrbart Magnum",
}
MENSCH_KLEIDUNG = {
    "blazerAndShirt": "Blazer & Hemd", "blazerAndSweater": "Blazer & Pulli",
    "collarAndSweater": "Kragen & Pulli", "hoodie": "Hoodie", "overall": "Latzhose",
    "shirtCrewNeck": "Rundhals-Shirt", "shirtScoopNeck": "V-Shirt", "shirtVNeck": "V-Ausschnitt",
}
MENSCH_ACCESSOIRE = {
    "eyepatch": "Augenklappe", "kurt": "Kurt-Brille", "prescription01": "Brille 1",
    "prescription02": "Brille 2", "round": "Runde Brille", "sunglasses": "Sonnenbrille",
    "wayfarers": "Wayfarer-Brille",
}

MENSCH_FELDER = {
    "haut": MENSCH_HAUT, "haarfarbe": MENSCH_HAARFARBEN,
    "kleidungsfarbe": MENSCH_KLEIDUNGSFARBEN, "accessoirefarbe": MENSCH_ACCESSOIRE_FARBEN,
    "frisur": MENSCH_FRISUR, "augen": MENSCH_AUGEN, "augenbrauen": MENSCH_AUGENBRAUEN,
    "mund": MENSCH_MUND, "bart": MENSCH_BART, "kleidung": MENSCH_KLEIDUNG,
    "accessoire": MENSCH_ACCESSOIRE,
}


def _mensch_optionen_lesen(form):
    """Liest+validiert alle Avataaars-Auswahlwerte aus einem Formular (POST-Daten).
    Unbekannte/fehlende Werte fallen auf den jeweils ersten gültigen Wert zurück,
    "keins" bei Bart/Accessoire wird als leere Auswahl behandelt."""
    optionen = {}
    for feld, erlaubt in MENSCH_FELDER.items():
        wert = form.get(f"mensch_{feld}", "")
        if feld in ("bart", "accessoire") and wert == "keins":
            optionen[feld] = "keins"
            continue
        optionen[feld] = wert if wert in erlaubt else next(iter(erlaubt))
    return optionen


def _mensch_svg_rendern(optionen):
    """Baut aus den gespeicherten/übermittelten Auswahlwerten ein Avataaars-SVG.
    Läuft komplett lokal (dicebear-core + dicebear-styles), keine Netzwerkanfrage."""
    dicebear_optionen = {
        "skinColor": [optionen["haut"]],
        "topVariant": [optionen["frisur"]],
        "hairColor": [optionen["haarfarbe"]],
        "eyesVariant": [optionen["augen"]],
        "eyebrowsVariant": [optionen["augenbrauen"]],
        "mouthVariant": [optionen["mund"]],
        "clothesVariant": [optionen["kleidung"]],
        "clothesColor": [optionen["kleidungsfarbe"]],
    }
    if optionen.get("bart") == "keins":
        dicebear_optionen["facialHairProbability"] = 0
    else:
        dicebear_optionen["facialHairVariant"] = [optionen["bart"]]
        dicebear_optionen["facialHairProbability"] = 100
    if optionen.get("accessoire") == "keins":
        dicebear_optionen["accessoriesProbability"] = 0
    else:
        dicebear_optionen["accessoriesVariant"] = [optionen["accessoire"]]
        dicebear_optionen["accessoriesColor"] = [optionen["accessoirefarbe"]]
        dicebear_optionen["accessoriesProbability"] = 100
    avatar = Avatar(_AVATAAARS_STYLE, dicebear_optionen)
    return avatar.to_string()


@bp.route("/a/tierbaukasten/vorschau-mensch", defaults={"token": None}, methods=["POST"])
@bp.route("/a/tierbaukasten/<token>/vorschau-mensch", methods=["POST"])
def vorschau_mensch(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    optionen = _mensch_optionen_lesen(request.form)
    return jsonify(ok=True, svg=_mensch_svg_rendern(optionen))


# ---------------------------------------------------------------------------
# Anlegen und Bearbeiten teilen sich eine Lesefunktion (Wunsch #201)
# ---------------------------------------------------------------------------

# Reihenfolge egal, aber EINE Liste: Anlegen und Bearbeiten schreiben beide
# ALLE diese Spalten. Sonst bliebe beim Wechsel Mensch->Tier das alte
# `dicebear_optionen` stehen und die Galerie zeichnete weiter den Avatar.
_SPALTEN = ("tier_typ", "koerper_farbe", "muster", "muster_farbe",
            "accessoire", "koerperbau", "dicebear_optionen", "name")


def _kreation_aus_form(form):
    """Formular -> vollständiger Spaltensatz, oder None bei unbekanntem Typ.

    Warum gemeinsam für Anlegen und Bearbeiten (Wunsch #201): Zwei Kopien
    derselben Prüfung laufen auseinander, und die Kopie, die zuerst vergessen
    wird, ist die im selteneren Weg - hier also im Bearbeiten. Dann liesse
    sich per Bearbeiten speichern, was beim Anlegen abgelehnt wird.
    """
    tier_typ = form.get("tier_typ", "")
    if tier_typ not in ALLE_TYPEN:
        return None
    name = form.get("name", "").strip()[:40] or None

    if tier_typ == "mensch":
        return {
            "tier_typ": tier_typ, "name": name,
            "dicebear_optionen": json.dumps(_mensch_optionen_lesen(form)),
            # Die Tier-Spalten auf ihre Vorgabe zurück statt sie stehen zu
            # lassen: eine Mensch-Figur hat kein Muster und keinen Körperbau.
            "koerper_farbe": "#e8b04b", "muster": None, "muster_farbe": None,
            "accessoire": None, "koerperbau": 50,
        }

    muster = form.get("muster", "keins")
    if muster not in MUSTER:
        muster = "keins"
    accessoire_liste = [a for a in form.get("accessoire", "").split(",") if a in ACCESSOIRES]
    return {
        "tier_typ": tier_typ, "name": name,
        "dicebear_optionen": None,
        "koerper_farbe": _clean_farbe(form.get("koerper_farbe"), "#e8b04b"),
        "muster": None if muster == "keins" else muster,
        "muster_farbe": _clean_farbe(form.get("muster_farbe"), "#ffffff") if muster != "keins" else None,
        "accessoire": ",".join(accessoire_liste) or None,
        "koerperbau": _clean_koerperbau(form.get("koerperbau")),
    }


def _figur_fuer_js(k):
    """Eine gespeicherte Figur so, wie das Bearbeiten-Formular sie braucht.

    Geht als JSON in die Seite und wird per `.value`/`classList` eingesetzt -
    nie per innerHTML, `name` ist Nutzertext."""
    return {
        "tier_typ": k["tier_typ"],
        "name": k["name"] or "",
        "koerper_farbe": k["koerper_farbe"],
        "muster": k["muster"] or "keins",
        "muster_farbe": k["muster_farbe"] or "#ffffff",
        "accessoire": k["accessoire"] or "",
        "koerperbau": k["koerperbau"],
        "mensch": json.loads(k["dicebear_optionen"]) if k["dicebear_optionen"] else None,
    }


@bp.route("/a/tierbaukasten/", defaults={"token": None})
@bp.route("/a/tierbaukasten/<token>/")
def index(token):
    user = check_grant(token, APP)
    if not user:
        return render_template("denied.html", reason="invalid"), 403
    db = get_db()
    eigene = db.execute(
        "SELECT * FROM tierbaukasten_kreationen WHERE user_id=? ORDER BY erstellt DESC",
        (user["id"],),
    ).fetchall()
    mensch_svgs = {}
    for k in eigene:
        if k["tier_typ"] == "mensch" and k["dicebear_optionen"]:
            mensch_svgs[k["id"]] = _mensch_svg_rendern(json.loads(k["dicebear_optionen"]))
    return render_template("tierbaukasten.html",
        user=user, token=token, farbe=user["farbe"],
        kategorien=KATEGORIEN, tiere=TIERE, muster=MUSTER, accessoires=ACCESSOIRES,
        eigene=eigene, mensch_svgs=mensch_svgs,
        figuren={k["id"]: _figur_fuer_js(k) for k in eigene},
        mensch_frisur=MENSCH_FRISUR, mensch_augen=MENSCH_AUGEN, mensch_augenbrauen=MENSCH_AUGENBRAUEN,
        mensch_mund=MENSCH_MUND, mensch_bart=MENSCH_BART, mensch_kleidung=MENSCH_KLEIDUNG,
        mensch_accessoire=MENSCH_ACCESSOIRE, mensch_haut=MENSCH_HAUT, mensch_haarfarben=MENSCH_HAARFARBEN,
        mensch_kleidungsfarben=MENSCH_KLEIDUNGSFARBEN, mensch_accessoirefarben=MENSCH_ACCESSOIRE_FARBEN,
    )


@bp.route("/a/tierbaukasten/speichern", defaults={"token": None}, methods=["POST"])
@bp.route("/a/tierbaukasten/<token>/speichern", methods=["POST"])
def speichern(token):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    werte = _kreation_aus_form(request.form)
    if werte is None:
        return redirect(url_for("tierbaukasten_app.index", token=token))
    db = get_db()
    db.execute(
        f"""INSERT INTO tierbaukasten_kreationen(user_id, {", ".join(_SPALTEN)})
            VALUES ({", ".join("?" * (len(_SPALTEN) + 1))})""",
        (user["id"], *(werte[s] for s in _SPALTEN)),
    )
    db.commit()
    return redirect(url_for("tierbaukasten_app.index", token=token))


@bp.route("/a/tierbaukasten/bearbeiten/<int:kid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/tierbaukasten/<token>/bearbeiten/<int:kid>", methods=["POST"])
def bearbeiten(token, kid):
    """Wunsch #201: eine gespeicherte Figur ändern statt löschen und neu bauen.

    `erstellt` wird bewusst nicht angefasst - die Galerie sortiert danach, und
    eine Figur soll beim Nachbessern nicht nach vorne springen.
    """
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    # Jeder sieht nur seine eigene Galerie - eine fremde Figur ist kein
    # "nicht gefunden", sondern ein Zugriff auf etwas, das einem nicht gehört.
    if not db.execute("SELECT 1 FROM tierbaukasten_kreationen WHERE id=? AND user_id=?",
                      (kid, user["id"])).fetchone():
        abort(403)
    werte = _kreation_aus_form(request.form)
    if werte is not None:
        db.execute(
            f"""UPDATE tierbaukasten_kreationen
                SET {", ".join(s + "=?" for s in _SPALTEN)}
                WHERE id=? AND user_id=?""",
            (*(werte[s] for s in _SPALTEN), kid, user["id"]),
        )
        db.commit()
    return redirect(url_for("tierbaukasten_app.index", token=token))


@bp.route("/a/tierbaukasten/loeschen/<int:kid>", defaults={"token": None}, methods=["POST"])
@bp.route("/a/tierbaukasten/<token>/loeschen/<int:kid>", methods=["POST"])
def loeschen(token, kid):
    user = check_grant(token, APP)
    if not user:
        abort(403)
    db  = get_db()
    row = db.execute(
        "SELECT id FROM tierbaukasten_kreationen WHERE id=? AND user_id=?",
        (kid, user["id"]),
    ).fetchone()
    if row:
        db.execute("DELETE FROM tierbaukasten_kreationen WHERE id=?", (kid,))
        db.commit()
    return redirect(url_for("tierbaukasten_app.index", token=token))


def init_app(app):
    app.register_blueprint(bp)
