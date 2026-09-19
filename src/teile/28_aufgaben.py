"""
Aufgaben (neu) – Schritt 1 der Umsetzung: Datenzugriff, Sichtbarkeit, Rechte.

Grundlage: docs/aufgaben_neu/spezifikation.md (19.09.2026). Diese App ersetzt
auf Sicht Aufgaben (todo), Geholfen und Aufgabenplan (kinderplan) mit EIGENEN
Tabellen (`aufgaben`, `termine`, `aufgaben_historie`, `aufgaben_migration`);
die alten drei Apps bleiben eingefroren bestehen, bis die Familie umzieht.

Dieses Modul hat in Schritt 1 keine Routen und keine Kachel. Es liefert die
Bausteine, auf denen alles Weitere aufsetzt - und zwar so, dass sie sich
NICHT umgehen lassen:

* `sichtbare_termine()` / `sichtbare_aufgaben()` sind die einzigen
  Sichtbarkeitsfunktionen (Spezifikation 3.1). Jede Route, jeder Zaehler,
  jede Summe baut darauf auf - die Lehre aus Audit-Befund F-06, wo Sicht und
  Aenderungsrecht in zwei Funktionen auseinanderliefen.
* Die `darf_*`-Funktionen bilden die Matrix aus 3.2 ab. `is_admin` gibt in
  dieser App KEIN Sonderrecht (Entscheidung 7: privat heisst privat, auch
  gegenueber Eltern und Admin); Aufsicht ist allein `rolle == 'eltern'`.
* `aufgabe_neu()` ist die einzige Schreibschnittstelle fuer andere Module
  (kein direktes INSERT, Abschnitt 10). Sie validiert, dass das Ziel die
  Aufgabe sehen darf, ignoriert bei Kindern Punkte/Kachel/Symbol und setzt
  deren Ziel immer auf "ich".

Zeit: nur die Kern-Helfer (`heute_lokal()`), Tage werden als Familientag
gespeichert - nirgends `date(zeitstempel)` oder `date.today()` (5.6).

Schritt 2 (Wunsch #298) bringt die ersten Routen (Blueprint `aufgaben_app`,
Slug `aufgaben`): "Heute" mit Abhaken und Zuruecknehmen, das Formular fuer
einmalige Aufgaben (anlegen, bearbeiten, loeschen, Verlauf), dazu in
base.html die Reiterleiste unten und die Rueckgaengig-Meldung. Was noch
fehlt, kommt in der Reihenfolge von Abschnitt 14: Spaeter/Parken (3),
Kacheln und "Person wechseln" (4), Regeln und Woche (5), Gruppen und
Familie (6). Das Formular zeigt deshalb bewusst nur die Knoepfe, deren
Ergebnis man auf einer vorhandenen Seite auch wiederfindet - "Spaeter"
und "Regelmaessig" erscheinen erst mit ihren Ansichten.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, redirect, render_template, request, url_for

from teile.geburtstage import MONATE
from teile.kern import (
    antwort_oder_weiter,
    emoji_grafik_vorhanden,
    get_db,
    heute_lokal,
    push_send,
    to_int,
    utc_zu_lokal,
)
from teile.kern import grant as check_grant

bp = Blueprint("aufgaben_app", __name__)
APP = "aufgaben"
WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
SICHT_MARKEN = {"eltern": "Nur Eltern", "kinder": "Nur Kinder", "ich": "Nur ich"}

SICHTEN = ("alle", "eltern", "kinder", "ich")
STATUS = ("vorschlag", "offen", "erledigt", "aus", "geparkt")
GRUPPEN = ("eltern", "kinder", "alle")
REGELN = ("wochentage", "intervall")
INHALT_MAX = 300
PUNKTE_MAX = 10.0
# Termine liegen nur in diesem Fenster um heute (Spezifikation 7).
FENSTER_RUECK = 7
FENSTER_VOR = 60
DEEP_LINK = "https://portal.16schwaben.de/a/aufgaben/"


class AufgabenFehler(ValueError):
    """Ungueltige Eingabe - die Meldung ist fuer den Nutzer gedacht."""


class Verboten(PermissionError):
    """Die Rolle darf das nicht."""


# ---------------------------------------------------------------------------
# Rollen
# ---------------------------------------------------------------------------

def ist_eltern(user) -> bool:
    """Aufsicht. Bewusst NICHT `or is_admin` - Entscheidung 7."""
    return user["rolle"] == "eltern"


def ist_kind(user) -> bool:
    return user["rolle"] == "kind"


def ist_gast(user) -> bool:
    """Alles, was weder Eltern noch Kind ist. Darf nur lesen, nur `alle`."""
    return user["rolle"] not in ("eltern", "kind")


def gruppe_passt(user, gruppe) -> bool:
    """Gehoert der Nutzer zur Zielgruppe einer Aufgabe?"""
    if gruppe == "alle":
        return not ist_gast(user)
    if gruppe == "eltern":
        return ist_eltern(user)
    if gruppe == "kinder":
        return ist_kind(user)
    return False


# ---------------------------------------------------------------------------
# Sichtbarkeit (3.1) - EINE Bedingung, ueberall dieselbe
# ---------------------------------------------------------------------------

def _sicht_sql(user, termin_alias="t", aufgabe_alias="a"):
    """SQL-Bedingung + Parameter: Aufgabe/Termin ist fuer `user` sichtbar.

    Sichtbar, wenn mindestens eines gilt: selbst angelegt, ein Termin ist
    ihm zugewiesen, sicht='alle', sicht='eltern' und Rolle eltern,
    sicht='kinder' und Rolle kind. `sicht='ich'` oeffnet nichts ueber
    Ersteller und Zugewiesene hinaus. Gast: nur sicht='alle'."""
    a, t = aufgabe_alias, termin_alias
    if ist_gast(user):
        return f"{a}.sicht = 'alle'", []
    teile = [f"{a}.erstellt_von = ?", f"{a}.sicht = 'alle'"]
    params = [user["id"]]
    if t:
        teile.append(f"{t}.user_id = ?")
        params.append(user["id"])
    else:
        teile.append(f"EXISTS (SELECT 1 FROM termine tx WHERE tx.aufgabe_id = {a}.id AND tx.user_id = ?)")
        params.append(user["id"])
    if ist_eltern(user):
        teile.append(f"{a}.sicht = 'eltern'")
    if ist_kind(user):
        teile.append(f"{a}.sicht = 'kinder'")
    return "(" + " OR ".join(teile) + ")", params


_TERMIN_SELECT = """
    SELECT t.*,
           a.inhalt AS aufgabe_inhalt, a.emoji, a.punkte AS aufgabe_punkte,
           a.erstellt_von, a.ziel_user, a.ziel_gruppe, a.sicht, a.regel_typ,
           a.kachel, a.pausiert
    FROM   termine t
    JOIN   aufgaben a ON a.id = t.aufgabe_id
"""


def sichtbare_termine(db, user, *, von=None, bis=None, status=None, user_id=None,
                      aufgabe_id=None, termin_id=None, frei=False,
                      erledigt_von=None, erledigt_bis=None):
    """Die Termine, die `user` sehen darf - mit optionalen Filtern.

    von/bis: Familientag ISO (inklusiv) fuer `tag`; erledigt_von/erledigt_bis
    dasselbe fuer `erledigt_tag` (Tagesbalken, Wochenpunkte); status: str
    oder Folge; user_id: nur Termine dieser Person; frei=True: nur Termine
    ohne Person (Gruppenaufgaben, "Noch zu haben"). Sortiert nach Tag,
    Uhrzeit, id."""
    bedingung, params = _sicht_sql(user)
    where = [bedingung]
    if von is not None:
        where.append("t.tag >= ?"); params.append(von)
    if bis is not None:
        where.append("t.tag <= ?"); params.append(bis)
    if erledigt_von is not None:
        where.append("t.erledigt_tag >= ?"); params.append(erledigt_von)
    if erledigt_bis is not None:
        where.append("t.erledigt_tag <= ?"); params.append(erledigt_bis)
    if status is not None:
        stati = (status,) if isinstance(status, str) else tuple(status)
        platzhalter = ",".join("?" * len(stati))
        where.append(f"t.status IN ({platzhalter})"); params.extend(stati)
    if user_id is not None:
        where.append("t.user_id = ?"); params.append(user_id)
    if frei:
        where.append("t.user_id IS NULL")
    if aufgabe_id is not None:
        where.append("t.aufgabe_id = ?"); params.append(aufgabe_id)
    if termin_id is not None:
        where.append("t.id = ?"); params.append(termin_id)
    return db.execute(
        _TERMIN_SELECT + " WHERE " + " AND ".join(where)
        + " ORDER BY t.tag IS NULL, t.tag, t.uhrzeit IS NULL, t.uhrzeit, t.position, t.id",
        params,
    ).fetchall()


def termin_sichtbar(db, user, termin_id):
    """Eine Termin-Zeile (mit Aufgabenfeldern) oder None - None heisst fuer
    die Route: 404, egal ob es den Termin nicht gibt oder er unsichtbar ist."""
    zeilen = sichtbare_termine(db, user, termin_id=termin_id)
    return zeilen[0] if zeilen else None


def sichtbare_aufgaben(db, user, *, aufgabe_id=None):
    bedingung, params = _sicht_sql(user, termin_alias=None)
    where = [bedingung]
    if aufgabe_id is not None:
        where.append("a.id = ?"); params.append(aufgabe_id)
    return db.execute(
        "SELECT a.* FROM aufgaben a WHERE " + " AND ".join(where)
        + " ORDER BY a.pausiert, a.inhalt COLLATE NOCASE, a.id",
        params,
    ).fetchall()


def aufgabe_sichtbar(db, user, aufgabe_id):
    zeilen = sichtbare_aufgaben(db, user, aufgabe_id=aufgabe_id)
    return zeilen[0] if zeilen else None


# ---------------------------------------------------------------------------
# Rechte (3.2) - setzen Sichtbarkeit voraus, pruefen sie NICHT noch einmal
# ---------------------------------------------------------------------------

def darf_anlegen(user) -> bool:
    return not ist_gast(user)


def darf_punkte_setzen(user) -> bool:
    """Punkte, Kachel, Symbol: nur Eltern. Bei Kindern ignoriert der Server
    die Felder still (kein Fehler - das Formular zeigt sie gar nicht)."""
    return ist_eltern(user)


def darf_bearbeiten(user, aufgabe) -> bool:
    """Text, Wann, Sicht: Eltern alle sichtbaren, Kinder nur selbst angelegte."""
    if ist_eltern(user):
        return True
    return ist_kind(user) and aufgabe["erstellt_von"] == user["id"]


def darf_haken(user, termin) -> bool:
    """Abhaken / zuruecknehmen: Eltern alle sichtbaren (auch "fuer" andere),
    Kinder ihre eigenen Termine."""
    if ist_eltern(user):
        return True
    return ist_kind(user) and termin["user_id"] == user["id"]


def darf_nehmen(user, termin) -> bool:
    """"Ich mach's" bei einer freien Gruppenaufgabe: wenn die Gruppe passt."""
    if termin["user_id"] is not None or not termin["ziel_gruppe"]:
        return False
    return gruppe_passt(user, termin["ziel_gruppe"])


def darf_freigeben(user, termin) -> bool:
    """Wieder freigeben: Eltern alle sichtbaren, Kinder selbst uebernommene
    (der Termin gehoert ihnen UND die Aufgabe hat eine Gruppe)."""
    if termin["user_id"] is None or not termin["ziel_gruppe"]:
        return False
    if ist_eltern(user):
        return True
    return ist_kind(user) and termin["user_id"] == user["id"]


def darf_parken(user, termin) -> bool:
    """"Morgen" / "Parken": Eltern alle sichtbaren, Kinder nur selbst
    angelegte eigene. Regelmaessige Aufgaben parkt man nicht (5.3)."""
    if termin["regel_typ"]:
        return False
    if ist_eltern(user):
        return True
    return (ist_kind(user) and termin["erstellt_von"] == user["id"]
            and termin["user_id"] == user["id"])


def darf_loeschen(user, aufgabe) -> bool:
    """Eltern alle sichtbaren, Kinder selbst angelegte ohne Punkte."""
    if ist_eltern(user):
        return True
    return (ist_kind(user) and aufgabe["erstellt_von"] == user["id"]
            and float(aufgabe["punkte"] or 0) == 0)


def darf_vorschlaege(user) -> bool:
    """Vorschlaege bestaetigen, verschieben, streichen: nur Eltern."""
    return ist_eltern(user)


def darf_kachel_zurueck(user, termin, heute: str) -> bool:
    """Kachel-Tipp zuruecknehmen: Eltern jeden Eintrag jederzeit, Kinder den
    eigenen Tipp (getippt_von) und nur heute. "Immer der letzte" regelt die
    Route ueber die Auswahl des Termins, nicht dieses Recht."""
    if not termin["spontan"]:
        return False
    if ist_eltern(user):
        return True
    return (ist_kind(user) and termin["getippt_von"] == user["id"]
            and termin["erledigt_tag"] == heute)


# ---------------------------------------------------------------------------
# Kalender-Helfer (alles Familientag)
# ---------------------------------------------------------------------------

def montag_von(tag: date) -> date:
    return tag - timedelta(days=tag.weekday())


def sonntag_von(tag: date) -> date:
    return montag_von(tag) + timedelta(days=6)


def tag_im_fenster(tag: date, heute: date) -> bool:
    return heute - timedelta(days=FENSTER_RUECK) <= tag <= heute + timedelta(days=FENSTER_VOR)


def punkte_runden(wert) -> float:
    """0..10 in Schritten von 0,5; alles andere wird auf den naechsten
    gueltigen Wert gezogen."""
    try:
        zahl = float(str(wert).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
    zahl = max(0.0, min(PUNKTE_MAX, zahl))
    return round(zahl * 2) / 2


def wochentage_lesen(wert) -> str | None:
    """'0,2,4' bzw. Folge von Zahlen -> normalisierte Zeichenkette oder None."""
    if wert is None:
        return None
    if isinstance(wert, str):
        roh = [w.strip() for w in wert.split(",") if w.strip()]
    else:
        roh = list(wert)
    tage = sorted({to_int(w, -1) for w in roh})
    if not tage or any(t < 0 or t > 6 for t in tage):
        return None
    return ",".join(str(t) for t in tage)


# ---------------------------------------------------------------------------
# aufgabe_neu() - die einzige Schreibschnittstelle
# ---------------------------------------------------------------------------

def _ziel_darf_sehen(db, sicht, ziel_user, ziel_gruppe, erstellt_von) -> bool:
    """Validierung beim Speichern (3.1): Das Ziel muss die Aufgabe sehen
    duerfen. "Fuer Johannes" mit "Nur Eltern" wird abgelehnt."""
    if sicht == "alle":
        return True
    if ziel_gruppe:
        if ziel_gruppe == "alle":
            return False                     # 'ich'/'eltern'/'kinder' passt nie zu "alle"
        return sicht == ziel_gruppe          # Gruppe eltern <-> sicht eltern usw.
    if sicht == "ich":
        return ziel_user == erstellt_von
    rolle = db.execute("SELECT rolle FROM users WHERE id = ?", (ziel_user,)).fetchone()
    if not rolle:
        return False
    return (sicht == "eltern" and rolle["rolle"] == "eltern") or \
           (sicht == "kinder" and rolle["rolle"] == "kind")


def _felder_pruefen(db, user, inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji):
    """Gemeinsame Pruefung fuer Anlegen UND Bearbeiten (Lehre aus #158: eine
    Grenze, die nur beim Anlegen gilt, laesst sich per Bearbeiten umgehen).
    Gibt die normalisierten Werte zurueck oder wirft AufgabenFehler."""
    inhalt = (inhalt or "").strip()[:INHALT_MAX]
    if not inhalt:
        raise AufgabenFehler("Was ist zu tun? Der Text fehlt.")
    if ist_kind(user):
        ziel_user, ziel_gruppe = user["id"], None
        if sicht not in ("alle", "kinder", "ich"):
            raise AufgabenFehler("Diese Sichtbarkeit gibt es fuer dich nicht.")
        punkte, kachel, emoji = 0, 0, None
    else:
        if ziel_user is not None and ziel_gruppe:
            raise AufgabenFehler("Entweder eine Person oder eine Gruppe, nicht beides.")
        if ziel_gruppe and ziel_gruppe not in GRUPPEN:
            raise AufgabenFehler("Unbekannte Gruppe.")
        if ziel_user is None and not ziel_gruppe:
            ziel_user = user["id"]
        if ziel_user is not None and not db.execute(
                "SELECT 1 FROM users WHERE id = ?", (ziel_user,)).fetchone():
            raise AufgabenFehler("Diese Person gibt es nicht.")
        punkte = punkte_runden(punkte) if darf_punkte_setzen(user) else 0
        kachel = 1 if (kachel and darf_punkte_setzen(user)) else 0
        emoji = (emoji or "").strip() or None
        if emoji and not emoji_grafik_vorhanden(emoji):
            emoji = None
    if sicht not in SICHTEN:
        raise AufgabenFehler("Unbekannte Sichtbarkeit.")
    if not _ziel_darf_sehen(db, sicht, ziel_user, ziel_gruppe, user["id"]):
        raise AufgabenFehler("Das Ziel duerfte diese Aufgabe nicht sehen - Sichtbarkeit anpassen.")
    return inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji


def aufgabe_neu(db, user, inhalt, *, ziel_user=None, ziel_gruppe=None, sicht="alle",
                wann="heute", uhrzeit=None, punkte=0, kachel=0, emoji=None,
                regel_typ=None, regel_wochentage=None, regel_intervall=None,
                keine_dublette=False, push=True, heute=None) -> dict:
    """Legt eine Aufgabe und - je nach `wann` - ihren ersten Termin an.

    `wann`: 'heute' | 'geparkt' | 'woche' (flexibel, Sonntag der Woche) |
    ISO-Tag im Fenster | None (nur Kachel / nur Regel, kein Termin jetzt).
    Rueckgabe: {"aufgabe_id": int, "termin_id": int | None, "neu": bool}.

    Wirft Verboten (Gast), AufgabenFehler (ungueltige Eingabe). Kinder:
    Ziel immer sie selbst, Sicht nur alle/kinder/ich, Punkte/Kachel/Symbol
    werden still verworfen (3.2). `keine_dublette`: existiert schon ein
    offener Termin derselben Aufgabe (gleicher Text, gleicher Ersteller),
    wird der zurueckgegeben statt ein zweiter angelegt - fuer Aufrufer wie
    das KI-Budget (Abschnitt 10)."""
    if not darf_anlegen(user):
        raise Verboten("Gaeste koennen keine Aufgaben anlegen.")
    heute_iso = heute or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji = _felder_pruefen(
        db, user, inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji)

    if regel_typ is not None:
        if regel_typ not in REGELN:
            raise AufgabenFehler("Unbekannte Regel.")
        if regel_typ == "wochentage":
            regel_wochentage = wochentage_lesen(regel_wochentage)
            if not regel_wochentage:
                raise AufgabenFehler("Mindestens ein Wochentag.")
            regel_intervall = None
        else:
            regel_intervall = to_int(regel_intervall, 0)
            if regel_intervall < 2:
                raise AufgabenFehler("Alle ... Tage: mindestens 2.")
            regel_wochentage = None
        wann = None                      # Termine entstehen aus der Regel (5.1)
    else:
        regel_wochentage = regel_intervall = None

    if keine_dublette:
        vorhanden = db.execute("""
            SELECT t.id AS termin_id, a.id AS aufgabe_id FROM termine t
            JOIN aufgaben a ON a.id = t.aufgabe_id
            WHERE a.inhalt = ? AND a.erstellt_von = ? AND t.status IN ('offen', 'vorschlag', 'geparkt')
            ORDER BY t.id DESC LIMIT 1
        """, (inhalt, user["id"])).fetchone()
        if vorhanden:
            return {"aufgabe_id": vorhanden["aufgabe_id"],
                    "termin_id": vorhanden["termin_id"], "neu": False}

    aufgabe_id = db.execute("""
        INSERT INTO aufgaben(inhalt, emoji, punkte, erstellt_von, ziel_user, ziel_gruppe, sicht,
                             regel_typ, regel_wochentage, regel_intervall, kachel)
        VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id
    """, (inhalt, emoji, punkte, user["id"], ziel_user, ziel_gruppe, sicht,
          regel_typ, regel_wochentage, regel_intervall, kachel)).fetchone()["id"]

    termin_id = None
    if wann is not None:
        termin_id = termin_neu(db, aufgabe_id, wann, user_id=ziel_user,
                               uhrzeit=uhrzeit, heute=heute_d)
    db.commit()

    if push and ziel_user is not None and ziel_user != user["id"] and termin_id is not None:
        push_send(ziel_user, "📝 Neue Aufgabe", f"{user['name']}: {inhalt[:120]}",
                  APP, DEEP_LINK, dedup_key=f"aufgabe-{aufgabe_id}")
    return {"aufgabe_id": aufgabe_id, "termin_id": termin_id, "neu": True}


def termin_neu(db, aufgabe_id, wann, *, user_id=None, uhrzeit=None, status="offen",
               heute=None) -> int:
    """Ein Termin zu einer Aufgabe. `wann` wie bei aufgabe_neu(); ohne commit."""
    heute_d = heute or date.fromisoformat(heute_lokal())
    tag, flexibel, geparkt_am, position = None, 0, None, 0
    if wann == "geparkt":
        status = "geparkt"
        geparkt_am = "datetime('now')"
        position = (db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM termine WHERE status = 'geparkt'")
                    .fetchone()[0])
    elif wann == "heute":
        tag = heute_d.isoformat()
    elif wann == "woche":
        tag, flexibel = sonntag_von(heute_d).isoformat(), 1
    else:
        try:
            tag_d = date.fromisoformat(str(wann))
        except ValueError:
            raise AufgabenFehler("Ungueltiger Tag.") from None
        if not tag_im_fenster(tag_d, heute_d):
            raise AufgabenFehler("Der Tag liegt ausserhalb des planbaren Zeitraums.")
        tag = tag_d.isoformat()
    if uhrzeit:
        uhrzeit = str(uhrzeit).strip()[:5]
        if len(uhrzeit) != 5 or uhrzeit[2] != ":" or not (uhrzeit[:2] + uhrzeit[3:]).isdigit():
            raise AufgabenFehler("Uhrzeit bitte als HH:MM.")
    if status not in STATUS:
        raise AufgabenFehler("Unbekannter Status.")
    return db.execute(f"""
        INSERT INTO termine(aufgabe_id, tag, flexibel, uhrzeit, user_id, status, geparkt_am, position)
        VALUES (?,?,?,?,?,?,{geparkt_am or 'NULL'},?) RETURNING id
    """, (aufgabe_id, tag, flexibel, uhrzeit or None, user_id, status, position)).fetchone()["id"]


# ---------------------------------------------------------------------------
# Schritt 2: Aendern - Abhaken, Bearbeiten, Loeschen
# ---------------------------------------------------------------------------

def termin_haken(db, user, termin, heute=None) -> bool:
    """Toggle offen <-> erledigt. Rueckgabe: ist der Termin jetzt erledigt?

    Beim Erledigen wird `punkte` als Schnappschuss aus der Aufgabe kopiert
    (spaetere Aenderung der Aufgabe aendert vergebene Punkte nicht), beim
    Zuruecknehmen wieder geleert. Kachel-Tipps (spontan) laufen nicht
    hierueber - die nimmt Schritt 4 ueber "zurueck" heraus."""
    if termin["spontan"]:
        raise AufgabenFehler("Ein Kachel-Eintrag wird ueber die Kachel zurueckgenommen.")
    heute_iso = heute or heute_lokal()
    if termin["status"] == "erledigt":
        db.execute("""UPDATE termine SET status='offen', erledigt_am=NULL, erledigt_tag=NULL,
                      erledigt_von=NULL, punkte=NULL WHERE id=?""", (termin["id"],))
        db.commit()
        return False
    if termin["status"] != "offen":
        raise AufgabenFehler("Nur offene Termine lassen sich abhaken.")
    db.execute("""UPDATE termine SET status='erledigt', erledigt_am=datetime('now'),
                  erledigt_tag=?, erledigt_von=?, punkte=?
                  WHERE id=?""", (heute_iso, user["id"], float(termin["aufgabe_punkte"] or 0), termin["id"]))
    db.commit()
    return True


def _termin_der_aufgabe(db, aufgabe_id):
    """Der eine Termin einer einmaligen Aufgabe (der juengste ohne spontan)."""
    return db.execute("""SELECT * FROM termine WHERE aufgabe_id=? AND spontan=0
                         ORDER BY id DESC LIMIT 1""", (aufgabe_id,)).fetchone()


def aufgabe_aendern(db, user, aufgabe, *, inhalt, ziel_user=None, sicht="alle", wann=None,
                    uhrzeit=None, punkte=0, emoji=None, push=True, heute=None) -> dict:
    """Bearbeiten einer einmaligen Aufgabe (Spezifikation 6.2). Dieselbe
    Pruefung wie beim Anlegen; eine Textaenderung landet als alte Fassung in
    `aufgaben_historie`. Kinder aendern Text, Wann und Sicht - Ziel, Punkte
    und Symbol bleiben, wie sie sind (das Formular zeigt sie nicht).
    `wann` None laesst den Termin, wie er ist."""
    if not darf_bearbeiten(user, aufgabe):
        raise Verboten("Diese Aufgabe darfst du nicht bearbeiten.")
    if aufgabe["regel_typ"]:
        raise AufgabenFehler("Regelmaessige Aufgaben kommen mit Schritt 5.")
    heute_iso = heute or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    if ist_kind(user):
        # Werte, die ein Kind nicht setzen darf, kommen aus dem Bestand -
        # sonst wuerde _felder_pruefen sie auf 0/None ziehen.
        punkte, emoji = aufgabe["punkte"], aufgabe["emoji"]
        ziel_user = aufgabe["ziel_user"]
    inhalt, ziel_user, _, sicht, punkte_neu, _, emoji_neu = _felder_pruefen(
        db, user, inhalt, ziel_user, None, sicht, punkte, aufgabe["kachel"], emoji)
    if ist_kind(user):
        punkte_neu, emoji_neu = aufgabe["punkte"], aufgabe["emoji"]

    if inhalt != aufgabe["inhalt"]:
        db.execute("INSERT INTO aufgaben_historie(aufgabe_id, alter_inhalt, geaendert_von) VALUES(?,?,?)",
                   (aufgabe["id"], aufgabe["inhalt"], user["id"]))
    db.execute("""UPDATE aufgaben SET inhalt=?, ziel_user=?, sicht=?, punkte=?, emoji=?,
                  geaendert=datetime('now') WHERE id=?""",
               (inhalt, ziel_user, sicht, punkte_neu, emoji_neu, aufgabe["id"]))

    termin = _termin_der_aufgabe(db, aufgabe["id"])
    termin_id = termin["id"] if termin else None
    if termin and termin["status"] in ("offen", "erledigt"):
        tag, flexibel = termin["tag"], termin["flexibel"]
        if wann == "heute":
            tag, flexibel = heute_iso, 0
        elif wann == "woche":
            tag, flexibel = sonntag_von(heute_d).isoformat(), 1
        elif wann:
            try:
                tag_d = date.fromisoformat(str(wann))
            except ValueError:
                raise AufgabenFehler("Ungueltiger Tag.") from None
            if not tag_im_fenster(tag_d, heute_d):
                raise AufgabenFehler("Der Tag liegt ausserhalb des planbaren Zeitraums.")
            tag, flexibel = tag_d.isoformat(), 0
        uhrzeit = _uhrzeit_pruefen(uhrzeit)
        db.execute("UPDATE termine SET tag=?, flexibel=?, uhrzeit=?, user_id=? WHERE id=?",
                   (tag, flexibel, uhrzeit, ziel_user, termin["id"]))
    db.commit()

    if (push and ziel_user is not None and ziel_user != user["id"]
            and ziel_user != aufgabe["ziel_user"] and termin_id is not None):
        push_send(ziel_user, "📝 Neue Aufgabe", f"{user['name']}: {inhalt[:120]}",
                  APP, DEEP_LINK, dedup_key=f"aufgabe-{aufgabe['id']}")
    return {"aufgabe_id": aufgabe["id"], "termin_id": termin_id}


def aufgabe_loeschen(db, user, aufgabe) -> None:
    """Echtes Loeschen (Termine und Verlauf haengen per CASCADE daran)."""
    if not darf_loeschen(user, aufgabe):
        raise Verboten("Diese Aufgabe darfst du nicht loeschen.")
    db.execute("DELETE FROM aufgaben WHERE id=?", (aufgabe["id"],))
    db.commit()


def _uhrzeit_pruefen(uhrzeit):
    if not uhrzeit:
        return None
    uhrzeit = str(uhrzeit).strip()[:5]
    if len(uhrzeit) != 5 or uhrzeit[2] != ":" or not (uhrzeit[:2] + uhrzeit[3:]).isdigit():
        raise AufgabenFehler("Uhrzeit bitte als HH:MM.")
    return uhrzeit


# ---------------------------------------------------------------------------
# Schritt 2: Lesen - die Daten der Seite "Heute" (6.1)
# ---------------------------------------------------------------------------

def punkte_text(wert) -> str:
    """1.0 -> '1', 1.5 -> '1,5' - deutsches Komma, keine Nachkommanull."""
    zahl = float(wert or 0)
    if zahl == int(zahl):
        return str(int(zahl))
    return f"{zahl:.1f}".replace(".", ",")


def datum_lang(tag: date) -> str:
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE[tag.month - 1]}"


def _ueberfaellig_seit(termin, heute_d: date) -> int:
    """0 = nicht ueberfaellig, sonst Tage seit dem Faelligkeitstag. Flexible
    Termine ("diese Woche") werden erst nach Ablauf der Woche ueberfaellig."""
    if termin["status"] != "offen" or not termin["tag"]:
        return 0
    tag_d = date.fromisoformat(termin["tag"])
    return max(0, (heute_d - tag_d).days)


def _zeile(termin, user, namen, heute_d) -> dict:
    """Eine Termin-Zeile fuer die Vorlage - alles vorgerechnet, damit die
    Vorlage keine Rechte-Logik enthaelt."""
    seit = _ueberfaellig_seit(termin, heute_d)
    info = []
    if termin["erstellt_von"] == user["id"]:
        info.append("Von mir")
    else:
        info.append(f"Von {namen.get(termin['erstellt_von'], 'jemandem')}")
    if termin["flexibel"] and not seit:
        info.append("Diese Woche")
    elif termin["tag"] and termin["tag"] != heute_d.isoformat() and not seit:
        info.append(termin["tag"])
    if termin["uhrzeit"]:
        info.append(termin["uhrzeit"])
    if seit == 1:
        seit_text = "Seit gestern offen"
    elif seit > 1:
        seit_text = f"Seit {seit} Tagen offen"
    else:
        seit_text = ""
    punkte = float((termin["punkte"] if termin["status"] == "erledigt" else termin["aufgabe_punkte"]) or 0)
    return {
        "id": termin["id"], "aufgabe_id": termin["aufgabe_id"],
        "inhalt": termin["inhalt"] or termin["aufgabe_inhalt"],
        "emoji": termin["emoji"],
        "erledigt": termin["status"] == "erledigt",
        "ueberfaellig": seit > 0, "seit_text": seit_text,
        "info": " · ".join(info),
        "sicht_marke": SICHT_MARKEN.get(termin["sicht"]),
        "punkte": punkte, "punkte_text": punkte_text(punkte),
        "hakbar": darf_haken(user, termin),
        "bearbeitbar": darf_bearbeiten(user, termin),
    }


def heute_daten(db, user, person, heute_iso=None) -> dict:
    """Alles fuer "Heute dran", den Tagesbalken und die Wochenpunkte einer
    Person - gerechnet ueber sichtbare_termine() des BETRACHTERS, deshalb
    fehlen private Aufgaben der Person in fremden Zaehlern (3.1)."""
    heute_iso = heute_iso or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    montag, sonntag = montag_von(heute_d), sonntag_von(heute_d)
    morgen_iso = (heute_d + timedelta(days=1)).isoformat()
    namen = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM users")}

    offen = sichtbare_termine(db, user, user_id=person["id"], status="offen",
                              bis=sonntag.isoformat())
    dran = [t for t in offen if t["tag"] and (t["tag"] <= heute_iso or t["flexibel"])]
    erledigt = [t for t in sichtbare_termine(db, user, user_id=person["id"], status="erledigt",
                                             erledigt_von=heute_iso, erledigt_bis=heute_iso)
                if not t["spontan"]]                     # Kacheln fuellen den Balken nicht (5.4)
    zeilen = [_zeile(t, user, namen, heute_d) for t in dran + erledigt]
    # Ueberfaellige zuerst, dann nach Uhrzeit (ohne Uhrzeit hinten), dann Reihenfolge.
    uhr = {t["id"]: t["uhrzeit"] for t in dran + erledigt}
    zeilen.sort(key=lambda z: (not z["ueberfaellig"], uhr[z["id"]] is None, uhr[z["id"]] or "", z["id"]))

    gesamt = len(zeilen)
    geschafft = sum(1 for z in zeilen if z["erledigt"])
    if gesamt == 0:
        balken_text = "Heute ist nichts dran"
    elif geschafft == gesamt:
        balken_text = "Alles geschafft"
    else:
        balken_text = f"{geschafft} von {gesamt} geschafft"
    woche = sichtbare_termine(db, user, user_id=person["id"], status="erledigt",
                              erledigt_von=montag.isoformat(), erledigt_bis=sonntag.isoformat())
    punkte_woche = sum(float(t["punkte"] or 0) for t in woche)
    morgen = sum(1 for t in offen if t["tag"] == morgen_iso and not t["flexibel"])
    return {
        "zeilen": zeilen, "gesamt": gesamt, "geschafft": geschafft,
        "balken_text": balken_text,
        "balken_prozent": round(geschafft / gesamt * 100) if gesamt else 100,
        "punkte_woche": punkte_text(punkte_woche),
        "morgen": morgen, "datum": datum_lang(heute_d), "heute": heute_iso,
    }


# ---------------------------------------------------------------------------
# Routen - jede mit Token- und token-freier Regel (Wunsch #140, Stufe 4)
# ---------------------------------------------------------------------------

def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _reiter(token, aktiv):
    """Reiterleiste unten (base.html). Kinder: Heute · Woche · Spaeter,
    Eltern: Heute · Woche · Familie - jeder Reiter erscheint mit seinem
    Schritt; in Schritt 2 gibt es nur Heute."""
    return [{"name": "Heute", "href": url_for("aufgaben_app.heute", token=token), "aktiv": aktiv == "heute"}]


def _person_fuer(db, user):
    """`?fuer=<id>`: Eltern sehen "Heute" einer anderen Person (Familie,
    Schritt 6; Kiosk, Schritt 4). Fuer alle anderen ist es die eigene."""
    fuer = to_int(request.args.get("fuer"))
    if fuer and ist_eltern(user) and fuer != user["id"]:
        zeile = db.execute("SELECT id, name, rolle FROM users WHERE id=?", (fuer,)).fetchone()
        if zeile:
            return zeile
    return {"id": user["id"], "name": user["name"], "rolle": user["rolle"]}


@bp.route("/a/aufgaben/", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/")
def heute(token):
    user = _user(token)
    db = get_db()
    person = _person_fuer(db, user)
    daten = heute_daten(db, user, person)
    return render_template("aufgaben_heute.html", user=user, token=token, farbe=user["farbe"],
                           person=person, fremd=person["id"] != user["id"],
                           darf_anlegen=darf_anlegen(user),
                           reiter=_reiter(token, "heute"), **daten)


def _heute_url(token, person_id=None, user=None, anker=None):
    url = url_for("aufgaben_app.heute", token=token)
    if person_id and user and person_id != user["id"]:
        url += f"?fuer={person_id}"
    return url + (f"#termin-{anker}" if anker else "")


@bp.route("/a/aufgaben/termin/<int:tid>/haken", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/haken", methods=["POST"])
def haken(token, tid):
    """Toggle erledigt. 404 vor 403: unsichtbar und nicht vorhanden sehen
    gleich aus (3.1). Antwort per antwort_oder_weiter() mit den neuen
    Zaehlern, damit die Seite Balken und Punkte ohne Neuladen nachzieht."""
    user = _user(token)
    db = get_db()
    termin = termin_sichtbar(db, user, tid)
    if termin is None:
        abort(404)
    if not darf_haken(user, termin):
        abort(403)
    try:
        erledigt = termin_haken(db, user, termin)
    except AufgabenFehler:
        abort(400)
    person_id = termin["user_id"] or user["id"]
    person = db.execute("SELECT id, name, rolle FROM users WHERE id=?", (person_id,)).fetchone()
    daten = heute_daten(db, user, person)
    return antwort_oder_weiter(
        _heute_url(token, person_id, user, anker=tid),
        erledigt=erledigt, geschafft=daten["geschafft"], gesamt=daten["gesamt"],
        balken_text=daten["balken_text"], balken_prozent=daten["balken_prozent"],
        punkte_woche=daten["punkte_woche"])


def _formular_kontext(db, user, aufgabe=None, termin=None, werte=None, fehler=None):
    """Alles, was aufgaben_formular.html braucht - fuer GET wie fuer den
    Wiederaufruf nach einem Fehler (dann mit den eingegebenen Werten)."""
    heute_iso = heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    personen = []
    if ist_eltern(user):
        personen = db.execute("""SELECT id, name, farbe, rolle FROM users
                                 WHERE id != ? AND rolle IN ('eltern', 'kind')
                                 ORDER BY rolle, name COLLATE NOCASE""", (user["id"],)).fetchall()
    sichten = [("alle", "Alle", "Die ganze Familie sieht die Aufgabe.")]
    if ist_eltern(user):
        sichten += [("eltern", "Nur Eltern", "Die Kinder sehen sie nirgends."),
                    ("kinder", "Nur Kinder", "Die Kinder und du. Der andere Elternteil nicht."),
                    ("ich", "Nur ich", "Niemand sonst, auch nicht der andere Elternteil.")]
    else:
        sichten += [("kinder", "Nur Kinder", "Du und die anderen Kinder. Mama und Papa sehen sie nicht."),
                    ("ich", "Nur ich", "Niemand sonst, auch Mama und Papa nicht.")]
    if werte is None:
        werte = {"inhalt": "", "ziel": "ich", "wann": "heute", "tag": "", "uhrzeit": "",
                 "sicht": "alle", "punkte": "0", "emoji": ""}
        vorgabe_tag = request.args.get("tag") or ""
        if vorgabe_tag and vorgabe_tag != heute_iso:
            werte.update(wann="tag", tag=vorgabe_tag)
        if aufgabe is not None:
            werte.update(inhalt=aufgabe["inhalt"], sicht=aufgabe["sicht"],
                         punkte=punkte_text(aufgabe["punkte"]), emoji=aufgabe["emoji"] or "",
                         ziel="ich" if aufgabe["ziel_user"] in (None, user["id"]) else str(aufgabe["ziel_user"]))
            if termin is not None:
                werte.update(uhrzeit=termin["uhrzeit"] or "")
                if termin["tag"] and termin["tag"] != heute_iso and not termin["flexibel"]:
                    werte.update(wann="tag", tag=termin["tag"])
    verlauf = []
    if aufgabe is not None:
        namen = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM users")}
        for h in db.execute("""SELECT * FROM aufgaben_historie WHERE aufgabe_id=?
                               ORDER BY id DESC""", (aufgabe["id"],)):
            verlauf.append({"alter_inhalt": h["alter_inhalt"],
                            "bis": utc_zu_lokal(h["geaendert_am"]),
                            "von": namen.get(h["geaendert_von"], "?")})
    return {
        "user": user, "farbe": user["farbe"], "aufgabe": aufgabe, "werte": werte, "fehler": fehler,
        "personen": personen, "sichten": sichten, "ist_eltern": ist_eltern(user),
        "tag_min": (heute_d - timedelta(days=FENSTER_RUECK)).isoformat(),
        "tag_max": (heute_d + timedelta(days=FENSTER_VOR)).isoformat(),
        "verlauf": verlauf, "heute": heute_iso,
        "darf_loeschen": aufgabe is not None and darf_loeschen(user, aufgabe),
    }


def _formular_lesen():
    f = request.form
    return {"inhalt": f.get("inhalt", ""), "ziel": f.get("ziel", "ich"), "wann": f.get("wann", "heute"),
            "tag": f.get("tag", ""), "uhrzeit": f.get("uhrzeit", ""), "sicht": f.get("sicht", "alle"),
            "punkte": f.get("punkte", "0"), "emoji": f.get("emoji", "")}


def _wann_aus(werte):
    if werte["wann"] == "tag":
        return werte["tag"] or "heute"
    return "heute"


@bp.route("/a/aufgaben/neu", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/aufgaben/<token>/neu", methods=["GET", "POST"])
def neu(token):
    user = _user(token)
    if not darf_anlegen(user):
        abort(403)
    db = get_db()
    if request.method == "GET":
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user))
    werte = _formular_lesen()
    try:
        ergebnis = aufgabe_neu(
            db, user, werte["inhalt"], sicht=werte["sicht"], wann=_wann_aus(werte),
            uhrzeit=werte["uhrzeit"] or None, punkte=werte["punkte"], emoji=werte["emoji"],
            ziel_user=None if werte["ziel"] == "ich" else to_int(werte["ziel"]))
    except AufgabenFehler as e:
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, werte=werte, fehler=str(e))), 400
    ziel = None if werte["ziel"] == "ich" else to_int(werte["ziel"])
    return redirect(_heute_url(token, ziel, user, anker=ergebnis["termin_id"]))


@bp.route("/a/aufgaben/aufgabe/<int:aid>", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/aufgaben/<token>/aufgabe/<int:aid>", methods=["GET", "POST"])
def bearbeiten(token, aid):
    user = _user(token)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    if not darf_bearbeiten(user, aufgabe):
        abort(403)
    termin = _termin_der_aufgabe(db, aid)
    if request.method == "GET":
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, aufgabe, termin))
    werte = _formular_lesen()
    try:
        ergebnis = aufgabe_aendern(
            db, user, aufgabe, inhalt=werte["inhalt"], sicht=werte["sicht"], wann=_wann_aus(werte),
            uhrzeit=werte["uhrzeit"] or None, punkte=werte["punkte"], emoji=werte["emoji"],
            ziel_user=None if werte["ziel"] == "ich" else to_int(werte["ziel"]))
    except AufgabenFehler as e:
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, aufgabe, termin, werte=werte,
                                                   fehler=str(e))), 400
    ziel = None if werte["ziel"] == "ich" else to_int(werte["ziel"])
    return redirect(_heute_url(token, ziel, user, anker=ergebnis["termin_id"]))


@bp.route("/a/aufgaben/aufgabe/<int:aid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/aufgabe/<int:aid>/loeschen", methods=["POST"])
def loeschen(token, aid):
    user = _user(token)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    if not darf_loeschen(user, aufgabe):
        abort(403)
    aufgabe_loeschen(db, user, aufgabe)
    return redirect(url_for("aufgaben_app.heute", token=token))


def init_app(app):
    app.register_blueprint(bp)
