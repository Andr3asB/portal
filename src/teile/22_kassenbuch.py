"""
Kassenbuch – Taschengeld-Buchführung je Kind (Wunsch #144).
URL-Präfix: /a/kassenbuch/<token>/

Jedes Kind (users.rolle='kind') hat sein eigenes Kassenbuch: Einnahmen und
Ausgaben eintragen, den aktuellen Bargeldbetrag ("Sparschwein") immer sehen.
Eltern und Admin bekommen automatisch denselben App-Grant (wie hilfe/einkauf,
siehe _auto_grant_all in 00_kern.py) - der Wunsch verlangt ausdrücklich, dass
alles "auditiert" wird, das setzt eine Aufsichtsmöglichkeit voraus. Sie sehen
darüber eine Übersicht aller Kinder und deren Kassenbücher READ-ONLY; Kinder
sehen nur ihr eigenes und ausschließlich das.

Buchhaltungsprinzip statt CRUD: Ein Eintrag ist nach dem Speichern
UNVERÄNDERLICH - kein Bearbeiten von Betrag/Zweck/Datum im Nachhinein, wie in
einem echten Kassenbuch. "Löschen" heißt Stornieren (kassenbuch_eintraege.
storniert): die Zeile bleibt für immer in der Datenbank stehen, zählt aber
nicht mehr zum Kontostand. Damit sind "wer hat's angelegt" und "wer hat's
storniert" bereits auf der Zeile selbst protokolliert (erstellt_von/erstellt,
storniert_von/storniert_am) - eine zusätzliche Änderungs-Historie bräuchte es
erst, wenn Einträge auch bearbeitbar wären, was hier nicht verlangt ist.

Empfänger/Absender (O-Ton des Wunsches: "finde da bessere Begriffe"): EIN
Feld `person`, dessen Beschriftung im Formular sich nach der Art richtet -
"Von wem?" bei einer Einnahme, "An wen?" bei einer Ausgabe. Zwei Fachbegriffe
für dieselbe Spalte wären für Kinder nur verwirrend gewesen.

Der Startbetrag (Wunsch: "beim ersten Starten einen Startbetrag eintragen")
ist selbst ein Eintrag mit art='start' - kein Sonderfeld auf der Tabelle,
sondern derselbe Ledger-Mechanismus, nur mit eigener Art. Genau ein
Start-Eintrag pro Kind, niemals stornierbar (sonst wäre der gesamte
folgende Kontostand rückwirkend bedeutungslos).
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, request, redirect, url_for, abort
from teile.kern import (get_db, grant as check_grant, heute_lokal, utc_zu_lokal,
                        utc_zu_lokal_datum, antwort_oder_weiter)

bp  = Blueprint("kassenbuch_app", __name__)
APP = "kassenbuch"


def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _euro_zu_cent(text: str):
    """'12,50' oder '12.50' -> 1250. None bei leer/ungültig/<= 0.

    Decimal statt float - ein Taschengeld-Kassenbuch darf keine
    Rundungsfehler durch Fließkommazahlen einschleppen."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        wert = Decimal(text)
    except InvalidOperation:
        return None
    if wert <= 0:
        return None
    return int((wert * 100).to_integral_value())


def _cent_zu_euro_text(cent: int) -> str:
    vorzeichen = "-" if cent < 0 else ""
    cent = abs(cent)
    return f"{vorzeichen}{cent // 100},{cent % 100:02d} €"


def _datum_text(iso: str) -> str:
    """'2026-08-02' -> '02.08.2026'. Unbekanntes Format bleibt unveraendert -
    lieber roh anzeigen als eine Ausnahme mitten in einer Pruefliste."""
    teile = (iso or "").split("-")
    if len(teile) != 3:
        return iso or ""
    jahr, monat, tag = teile
    return f"{tag}.{monat}.{jahr}"


def _kind_oder_404(db, kid_id: int):
    row = db.execute(
        "SELECT id, name, farbe FROM users WHERE id=? AND rolle='kind'", (kid_id,)
    ).fetchone()
    if not row:
        abort(404)
    return row


def _eintraege_laden(db, kid_id: int):
    return db.execute("""
        SELECT id, art, betrag_cent, person, zweck, datum, erstellt,
               storniert, storniert_am
        FROM   kassenbuch_eintraege
        WHERE  user_id = ?
        ORDER  BY datum DESC, id DESC
    """, (kid_id,)).fetchall()


def _saldo_cent(eintraege) -> int:
    saldo = 0
    for e in eintraege:
        if e["storniert"]:
            continue
        saldo += -e["betrag_cent"] if e["art"] == "ausgabe" else e["betrag_cent"]
    return saldo


def _buch_rendern(user, token, db, kind_row, eigenes_buch: bool):
    eintraege = _eintraege_laden(db, kind_row["id"])
    hat_start = any(e["art"] == "start" for e in eintraege)
    return render_template("kassenbuch.html",
        user=user, token=token, farbe=user["farbe"],
        kind=kind_row, eigenes_buch=eigenes_buch, hat_start=hat_start,
        saldo_cent=_saldo_cent(eintraege), saldo_text=_cent_zu_euro_text(_saldo_cent(eintraege)),
        eintraege=eintraege, heute=heute_lokal(),
    )


@bp.route("/a/kassenbuch/", defaults={"token": None})
@bp.route("/a/kassenbuch/<token>/")
def index(token):
    user = _user(token)
    db   = get_db()

    if user["rolle"] == "kind":
        return _buch_rendern(user, token, db, user, eigenes_buch=True)

    # Eltern/Admin: Übersicht aller Kinder mit ihrem jeweiligen Kontostand.
    kinder_rows = db.execute(
        "SELECT id, name, farbe FROM users WHERE rolle='kind' ORDER BY name COLLATE NOCASE"
    ).fetchall()
    kinder = []
    for k in kinder_rows:
        eintraege = _eintraege_laden(db, k["id"])
        kinder.append({
            "kind": k,
            "hat_start": any(e["art"] == "start" for e in eintraege),
            "saldo_text": _cent_zu_euro_text(_saldo_cent(eintraege)),
        })
    return render_template("kassenbuch_uebersicht.html",
        user=user, token=token, farbe=user["farbe"], kinder=kinder)


@bp.route("/a/kassenbuch/kind/<int:kid_id>", defaults={"token": None})
@bp.route("/a/kassenbuch/<token>/kind/<int:kid_id>")
def kind_buch(token, kid_id):
    user = _user(token)
    db   = get_db()
    kind_row = _kind_oder_404(db, kid_id)

    eigenes_buch = user["id"] == kid_id
    if user["rolle"] == "kind" and not eigenes_buch:
        # Kinder sehen NUR ihr eigenes Kassenbuch - keine Einsicht bei
        # Geschwistern, anders als bei Eltern/Admin (Aufsicht).
        abort(403)

    return _buch_rendern(user, token, db, kind_row, eigenes_buch=eigenes_buch)


def _pruefprotokoll(db, kid_id: int):
    """Wunsch #153: das Kassenbuch als Ereignisstrom statt als Kontoauszug.

    Der Unterschied ist der ganze Zweck. Das Kassenbuch sortiert nach `datum`
    - dem Tag, an dem das Geld geflossen ist. Ein Prüfer will die andere
    Reihenfolge: wann wurde was ERFASST. Nur so faellt auf, dass ein Eintrag
    drei Tage spaeter nachgetragen oder kurz nach dem Anlegen wieder storniert
    wurde; im Kontoauszug sieht beides voellig unauffaellig aus.

    Deshalb erzeugt eine Zeile bis zu ZWEI Ereignisse - angelegt und
    storniert. Das Storno ist eine eigene Handlung mit eigener Zeit und
    eigenem Urheber, und genau die interessiert.
    """
    zeilen = db.execute("""
        SELECT k.id, k.art, k.betrag_cent, k.person, k.zweck, k.datum,
               k.erstellt, k.storniert, k.storniert_am,
               k.user_id, k.erstellt_von, k.storniert_von,
               ue.name AS erstellt_von_name,
               us.name AS storniert_von_name
        FROM   kassenbuch_eintraege k
        LEFT   JOIN users ue ON ue.id = k.erstellt_von
        LEFT   JOIN users us ON us.id = k.storniert_von
        WHERE  k.user_id = ?
    """, (kid_id,)).fetchall()

    ereignisse = []
    for z in zeilen:
        gemeinsam = {
            "eintrag_id": z["id"],
            "eintrag_art": z["art"],
            "betrag_text": _cent_zu_euro_text(z["betrag_cent"]),
            "vorzeichen": "−" if z["art"] == "ausgabe" else "+",
            "person": z["person"],
            "zweck": z["zweck"],
            "datum": z["datum"],
            # "gebucht auf den 2026-08-02" liest sich im Fliesstext falsch -
            # das ISO-Format ist zum Sortieren da, nicht zum Vorlesen.
            "datum_text": _datum_text(z["datum"]),
        }
        # "Nachgetragen" heisst: der Geldfluss liegt vor dem Tag der Erfassung.
        # Verglichen wird in Ortszeit, sonst waere jeder Eintrag zwischen
        # Mitternacht und 2 Uhr faelschlich als nachgetragen markiert.
        erfasst_am = utc_zu_lokal_datum(z["erstellt"])
        ereignisse.append({**gemeinsam,
            "was": "angelegt",
            "zeitstempel": z["erstellt"],
            "zeit_text": utc_zu_lokal(z["erstellt"]),
            "wer": z["erstellt_von_name"] or "unbekannt",
            "nachgetragen": bool(erfasst_am and z["datum"] < erfasst_am),
            # Heute kann nur das Kind selbst buchen. Faende sich hier je ein
            # fremder Urheber, waere das der wichtigste Befund der Seite -
            # deshalb wird es geprueft und nicht bloss angenommen.
            "fremd": z["erstellt_von"] != z["user_id"],
        })
        if z["storniert"]:
            ereignisse.append({**gemeinsam,
                "was": "storniert",
                "zeitstempel": z["storniert_am"] or z["erstellt"],
                "zeit_text": utc_zu_lokal(z["storniert_am"]) or "Zeitpunkt nicht erfasst",
                "wer": z["storniert_von_name"] or "unbekannt",
                "nachgetragen": False,
                "fremd": z["storniert_von"] is not None
                         and z["storniert_von"] != z["user_id"],
            })

    ereignisse.sort(key=lambda e: (e["zeitstempel"] or "", e["eintrag_id"]), reverse=True)
    return ereignisse


def _rechenprobe(eintraege):
    """Die Zahlen, mit denen sich der Kontostand nachrechnen laesst.

    Ein Pruefprotokoll, das den Saldo nur behauptet, ist wertlos - hier stehen
    die Summanden einzeln, damit man sie zusammenzaehlen kann."""
    start = einnahmen = ausgaben = 0
    storniert_anzahl = storniert_summe = 0
    for e in eintraege:
        if e["storniert"]:
            storniert_anzahl += 1
            storniert_summe += e["betrag_cent"]
            continue
        if e["art"] == "start":
            start += e["betrag_cent"]
        elif e["art"] == "einnahme":
            einnahmen += e["betrag_cent"]
        else:
            ausgaben += e["betrag_cent"]
    saldo = start + einnahmen - ausgaben
    return {
        "start_text":     _cent_zu_euro_text(start),
        "einnahmen_text": _cent_zu_euro_text(einnahmen),
        "ausgaben_text":  _cent_zu_euro_text(ausgaben),
        "saldo_text":     _cent_zu_euro_text(saldo),
        "storniert_anzahl": storniert_anzahl,
        "storniert_text":   _cent_zu_euro_text(storniert_summe),
        "anzahl": len(eintraege),
        # Muss immer True sein. Steht trotzdem da: eine Rechenprobe, die man
        # nicht scheitern sehen kann, beweist nichts.
        "stimmt": saldo == _saldo_cent(eintraege),
    }


@bp.route("/a/kassenbuch/kind/<int:kid_id>/pruefung", defaults={"token": None})
@bp.route("/a/kassenbuch/<token>/kind/<int:kid_id>/pruefung")
def pruefprotokoll(token, kid_id):
    """Wunsch #153: „Wie Wirtschaftsprüfer brauchen die Eltern Zugriff auf das
    Audit Log des Kassenbuchs."

    Bewusst NICHT fuer Kinder freigegeben, auch nicht fuer das eigene Buch.
    Das Kassenbuch selbst zeigt dem Kind bereits alles, was es angeht,
    einschliesslich der stornierten Zeilen. Die Pruefsicht fuegt nichts
    Eigenes hinzu ausser der Perspektive der Aufsicht - und die gehoert
    laut Wunsch den Eltern."""
    user = _user(token)
    if user["rolle"] == "kind":
        abort(403)
    db = get_db()
    kind_row = _kind_oder_404(db, kid_id)
    return render_template("kassenbuch_pruefung.html",
        user=user, token=token, farbe=user["farbe"], kind=kind_row,
        ereignisse=_pruefprotokoll(db, kid_id),
        probe=_rechenprobe(_eintraege_laden(db, kid_id)),
    )


@bp.route("/a/kassenbuch/start", defaults={"token": None}, methods=["POST"])
@bp.route("/a/kassenbuch/<token>/start", methods=["POST"])
def start(token):
    """Startbetrag festlegen - immer für den EIGENEN Bestand, nie für ein
    fremdes Kind (kein kid_id-Parameter nötig/möglich)."""
    user = _user(token)
    if user["rolle"] != "kind":
        abort(403)
    db = get_db()
    bereits_da = db.execute(
        "SELECT 1 FROM kassenbuch_eintraege WHERE user_id=? AND art='start'", (user["id"],)
    ).fetchone()
    if bereits_da:
        # Kein zweiter Start-Eintrag - auch nicht nach einem (unmöglichen,
        # weil Start nie stornierbar ist) Storno-Versuch.
        return redirect(url_for("kassenbuch_app.index", token=token))

    cent = _euro_zu_cent(request.form.get("betrag"))
    if cent is None:
        return redirect(url_for("kassenbuch_app.index", token=token))

    db.execute("""
        INSERT INTO kassenbuch_eintraege
            (user_id, art, betrag_cent, zweck, datum, erstellt_von)
        VALUES (?, 'start', ?, 'Startguthaben', ?, ?)
    """, (user["id"], cent, heute_lokal(), user["id"]))
    db.commit()
    return redirect(url_for("kassenbuch_app.index", token=token))


@bp.route("/a/kassenbuch/eintrag", defaults={"token": None}, methods=["POST"])
@bp.route("/a/kassenbuch/<token>/eintrag", methods=["POST"])
def eintrag_neu(token):
    user = _user(token)
    if user["rolle"] != "kind":
        abort(403)
    db = get_db()

    art = request.form.get("art")
    if art not in ("einnahme", "ausgabe"):
        return redirect(url_for("kassenbuch_app.index", token=token))

    cent = _euro_zu_cent(request.form.get("betrag"))
    if cent is None:
        return redirect(url_for("kassenbuch_app.index", token=token))

    person = (request.form.get("person") or "").strip()[:80] or None
    zweck  = (request.form.get("zweck")  or "").strip()[:200] or None

    datum = (request.form.get("datum") or "").strip()
    heute = heute_lokal()
    if not datum or datum > heute:
        datum = heute  # kein Nachtragen in die Zukunft

    db.execute("""
        INSERT INTO kassenbuch_eintraege
            (user_id, art, betrag_cent, person, zweck, datum, erstellt_von)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user["id"], art, cent, person, zweck, datum, user["id"]))
    db.commit()
    return redirect(url_for("kassenbuch_app.index", token=token))


@bp.route("/a/kassenbuch/eintrag/<int:eid>/stornieren",
          defaults={"token": None}, methods=["POST"])
@bp.route("/a/kassenbuch/<token>/eintrag/<int:eid>/stornieren", methods=["POST"])
def stornieren(token, eid):
    user = _user(token)
    if user["rolle"] != "kind":
        abort(403)
    db = get_db()
    row = db.execute(
        "SELECT art, storniert FROM kassenbuch_eintraege WHERE id=? AND user_id=?",
        (eid, user["id"]),
    ).fetchone()
    if not row:
        abort(404)
    storniert = False
    if row["art"] != "start" and not row["storniert"]:
        db.execute("""
            UPDATE kassenbuch_eintraege
            SET storniert=1, storniert_von=?, storniert_am=datetime('now')
            WHERE id=?
        """, (user["id"], eid))
        db.commit()
        storniert = True
    # Wunsch #171: ohne Seitensprung. Der neue Kontostand geht mit zurueck -
    # er ist der eigentliche Grund, warum man storniert, und muss sich sofort
    # aendern, sonst wirkt das Storno folgenlos.
    eintraege = _eintraege_laden(db, user["id"])
    return antwort_oder_weiter(url_for("kassenbuch_app.index", token=token),
                               storniert=storniert,
                               saldo_text=_cent_zu_euro_text(_saldo_cent(eintraege)))


def init_app(app):
    app.register_blueprint(bp)
