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

Schritt 3 (#299): Spaeter (Schnell parken, Liste mit ziehSortierung(),
Hervorholen), Parken/Morgen bei Ueberfaelligem mit Rueckgaengig-Meldung.
Schritt 4 (#300): Kacheln ("Sonst noch geholfen?") mit Zuruecknehmen,
"Person wechseln" fuer Eltern, und der KIOSK (Entscheidung 15.2, Abschnitt
5.7 der Spezifikation): ein eigenes Konto mit Rolle `kiosk`. Es sieht nur
sicht='alle', beginnt immer mit der Personenwahl, darf abhaken, "Ich mach's"
und Kacheln tippen - alles andere existiert fuer dieses Konto nicht (404).
Schritt 6 (#302): Gruppenaufgaben (user_id NULL, "Noch zu haben", "Ich
mach's" atomar, Freigeben), Familie, Alle Aufgaben, Pausieren.
Schritt 5 (#301): Regeln (wochentage/intervall) im Formular,
vorschlaege_sicherstellen() beim Aufruf von Heute/Woche/Familie (kein
Hintergrund-Thread, idempotent ueber den Unique-Index), Entscheidung 15.1:
Vorschlaege fuer HEUTE werden beim ersten Aufruf des Tages automatisch
'offen' (auto_bestaetigt=1), vergangene nie freigegebene verfallen zu 'aus'.
Screen Woche mit Bestaetigen, Verlegen, Streichen; Bearbeiten "Nur dieser
Termin / Alle kuenftigen".
"""
import sqlite3
from datetime import UTC, date, datetime, timedelta

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
    utc_zu_lokal_datum,
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
    """Alles, was weder Eltern noch Kind ist - auch der Kiosk. Sieht nur
    `alle`, legt nichts an."""
    return user["rolle"] not in ("eltern", "kind")


def ist_kiosk(user) -> bool:
    """Das Esszimmer-Konto (Abschnitt 5.7). Handelt immer FUER eine gewaehlte
    Person: user_id/erledigt_von = Person, getippt_von = Kiosk-Konto."""
    return user["rolle"] == "kiosk"


def darf_person_waehlen(user) -> bool:
    """Wer `?fuer=<id>` benutzen darf: Eltern am eigenen Geraet ("Person
    wechseln") und der Kiosk (Personenwahl als Einstieg)."""
    return ist_eltern(user) or ist_kiosk(user)


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


def darf_haken(user, termin, person=None) -> bool:
    """Abhaken / zuruecknehmen: Eltern alle sichtbaren (auch "fuer" andere),
    Kinder ihre eigenen Termine, der Kiosk die Termine der gewaehlten Person
    (sichtbar heisst fuer ihn ohnehin sicht='alle')."""
    if ist_eltern(user):
        return True
    if ist_kiosk(user):
        return person is not None and termin["user_id"] == person["id"]
    return ist_kind(user) and termin["user_id"] == user["id"]


def darf_nehmen(user, termin, person=None) -> bool:
    """"Ich mach's" bei einer freien Gruppenaufgabe: wenn die Gruppe zu der
    Person passt, die sie uebernimmt - beim Kiosk und bei "Person wechseln"
    ist das die gewaehlte Person, sonst der Nutzer selbst."""
    if termin["user_id"] is not None or not termin["ziel_gruppe"]:
        return False
    wer = person if (person is not None and darf_person_waehlen(user)) else user
    if ist_kiosk(user) and person is None:
        return False
    return gruppe_passt(wer, termin["ziel_gruppe"])


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
    # Kind wie Kiosk: nur der eigene Tipp (getippt_von), nur heute.
    return ((ist_kind(user) or ist_kiosk(user)) and termin["getippt_von"] == user["id"]
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


def _regel_pruefen(regel_typ, regel_wochentage, regel_intervall):
    """Regel normalisieren: ('wochentage', '0,2,4', None) | ('intervall', None, n) | (None, None, None)."""
    if regel_typ is None or regel_typ == "":
        return None, None, None
    if regel_typ not in REGELN:
        raise AufgabenFehler("Unbekannte Regel.")
    if regel_typ == "wochentage":
        regel_wochentage = wochentage_lesen(regel_wochentage)
        if not regel_wochentage:
            raise AufgabenFehler("Mindestens ein Wochentag.")
        return regel_typ, regel_wochentage, None
    regel_intervall = to_int(regel_intervall, 0)
    if regel_intervall < 2:
        raise AufgabenFehler("Alle ... Tage: mindestens 2.")
    return regel_typ, None, regel_intervall


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

    regel_typ, regel_wochentage, regel_intervall = _regel_pruefen(regel_typ, regel_wochentage, regel_intervall)
    if regel_typ is not None:
        wann = None                      # Termine entstehen aus der Regel (5.1)

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

def termin_haken(db, user, termin, heute=None, erledigt_von=None) -> bool:
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
                  WHERE id=?""", (heute_iso, erledigt_von or user["id"],
                                  float(termin["aufgabe_punkte"] or 0), termin["id"]))
    db.commit()
    return True


def _termin_der_aufgabe(db, aufgabe_id):
    """Der eine Termin einer einmaligen Aufgabe (der juengste ohne spontan)."""
    return db.execute("""SELECT * FROM termine WHERE aufgabe_id=? AND spontan=0
                         ORDER BY id DESC LIMIT 1""", (aufgabe_id,)).fetchone()


def aufgabe_aendern(db, user, aufgabe, *, inhalt, ziel_user=None, ziel_gruppe=None, sicht="alle",
                    wann=None, uhrzeit=None, punkte=0, emoji=None, kachel=None, push=True,
                    heute=None) -> dict:
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
        punkte, emoji, kachel = aufgabe["punkte"], aufgabe["emoji"], aufgabe["kachel"]
        ziel_user, ziel_gruppe = aufgabe["ziel_user"], None
    if kachel is None:
        kachel = aufgabe["kachel"]
    inhalt, ziel_user, ziel_gruppe, sicht, punkte_neu, kachel_neu, emoji_neu = _felder_pruefen(
        db, user, inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji)
    if ist_kind(user):
        punkte_neu, emoji_neu, kachel_neu = aufgabe["punkte"], aufgabe["emoji"], aufgabe["kachel"]

    if inhalt != aufgabe["inhalt"]:
        db.execute("INSERT INTO aufgaben_historie(aufgabe_id, alter_inhalt, geaendert_von) VALUES(?,?,?)",
                   (aufgabe["id"], aufgabe["inhalt"], user["id"]))
    db.execute("""UPDATE aufgaben SET inhalt=?, ziel_user=?, ziel_gruppe=?, sicht=?, punkte=?, emoji=?,
                  kachel=?, geaendert=datetime('now') WHERE id=?""",
               (inhalt, ziel_user, ziel_gruppe, sicht, punkte_neu, emoji_neu, kachel_neu, aufgabe["id"]))

    termin = _termin_der_aufgabe(db, aufgabe["id"])
    termin_id = termin["id"] if termin else None
    if termin and termin["status"] in ("offen", "erledigt", "geparkt"):
        tag, flexibel, status = termin["tag"], termin["flexibel"], termin["status"]
        geparkt_am, position = termin["geparkt_am"], termin["position"]
        if wann == "geparkt":
            if status != "geparkt":
                status, tag, flexibel = "geparkt", None, 0
                geparkt_am, position = _jetzt_utc(), _spaeter_ende(db)
        elif wann:
            if status == "geparkt":
                status, geparkt_am = "offen", None
            tag, flexibel = _tag_aus_wann(wann, heute_d)
        uhrzeit = _uhrzeit_pruefen(uhrzeit)
        # Gruppe: Termin wieder ohne Person ("Noch zu haben"); Person: an sie.
        neuer_user = None if ziel_gruppe else ziel_user
        db.execute("""UPDATE termine SET tag=?, flexibel=?, uhrzeit=?, user_id=?, status=?,
                      geparkt_am=?, position=? WHERE id=?""",
                   (tag, flexibel, uhrzeit, neuer_user, status, geparkt_am, position, termin["id"]))
    elif termin is None and wann and not aufgabe["regel_typ"]:
        termin_id = termin_new_fuer_aufgabe = termin_neu(
            db, aufgabe["id"], "geparkt" if wann == "geparkt" else wann,
            user_id=None if ziel_gruppe else ziel_user, uhrzeit=_uhrzeit_pruefen(uhrzeit), heute=heute_d)
        del termin_new_fuer_aufgabe
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


def _zeile(termin, user, namen, heute_d, person=None) -> dict:
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
        "hakbar": darf_haken(user, termin, person),
        "bearbeitbar": darf_bearbeiten(user, termin),
        "parkbar": darf_parken(user, termin),
        "freigebbar": darf_freigeben(user, termin),
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
    zeilen = [_zeile(t, user, namen, heute_d, person) for t in dran + erledigt]
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


def _jetzt_utc() -> str:
    """SQLite-kompatibler UTC-Zeitstempel (wie datetime('now'))."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _spaeter_ende(db) -> int:
    return db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM termine WHERE status='geparkt'").fetchone()[0]


def _tag_aus_wann(wann, heute_d: date):
    """'heute' | 'woche' | ISO-Tag -> (tag, flexibel); prueft das Fenster."""
    if wann == "heute":
        return heute_d.isoformat(), 0
    if wann == "woche":
        return sonntag_von(heute_d).isoformat(), 1
    try:
        tag_d = date.fromisoformat(str(wann))
    except ValueError:
        raise AufgabenFehler("Ungueltiger Tag.") from None
    if not tag_im_fenster(tag_d, heute_d):
        raise AufgabenFehler("Der Tag liegt ausserhalb des planbaren Zeitraums.")
    return tag_d.isoformat(), 0


# ---------------------------------------------------------------------------
# Schritt 3: Parken, Hervorholen, Verlegen, Spaeter (5.3, 6.5)
# ---------------------------------------------------------------------------

def termin_parken(db, user, termin) -> dict:
    """Parken: status geparkt, kein Tag, ans Ende der Spaeter-Liste, Person
    bleibt. Gibt den vorherigen Stand zurueck - fuer "Rueckgaengig"."""
    if not darf_parken(user, termin):
        raise Verboten("Diesen Termin darfst du nicht parken.")
    if termin["status"] not in ("offen", "vorschlag"):
        raise AufgabenFehler("Nur offene Termine lassen sich parken.")
    vorher = {"tag": termin["tag"], "flexibel": termin["flexibel"]}
    db.execute("""UPDATE termine SET status='geparkt', tag=NULL, flexibel=0, geparkt_am=?, position=?
                  WHERE id=?""", (_jetzt_utc(), _spaeter_ende(db), termin["id"]))
    db.commit()
    return vorher


def termin_hervorholen(db, user, termin, ziel, heute=None) -> dict:
    """Hervorholen aus Spaeter: ziel 'heute' | 'woche' (flexibel, Sonntag) |
    ISO-Tag im Fenster. Rueckgabe: neuer Tag/flexibel und ein Klartext."""
    if not darf_parken(user, termin):
        raise Verboten("Diesen Termin darfst du nicht hervorholen.")
    if termin["status"] != "geparkt":
        raise AufgabenFehler("Der Termin ist nicht geparkt.")
    heute_d = date.fromisoformat(heute or heute_lokal())
    tag, flexibel = _tag_aus_wann(ziel, heute_d)
    db.execute("""UPDATE termine SET status='offen', tag=?, flexibel=?, geparkt_am=NULL WHERE id=?""",
               (tag, flexibel, termin["id"]))
    db.commit()
    return {"tag": tag, "flexibel": flexibel, "text": _wohin_text(tag, flexibel, heute_d)}


def termin_verlegen(db, user, termin, ziel, heute=None) -> dict:
    """"Morgen" in der Zeile oder ein gewaehlter Tag: nur offene Termine,
    Tag im Fenster. Rueckgabe: vorheriger Stand fuer "Rueckgaengig"."""
    if not (darf_parken(user, termin) or (termin["regel_typ"] and darf_vorschlaege(user))):
        raise Verboten("Diesen Termin darfst du nicht verlegen.")
    if termin["status"] not in ("offen", "vorschlag"):
        raise AufgabenFehler("Nur offene Termine lassen sich verlegen.")
    heute_d = date.fromisoformat(heute or heute_lokal())
    if ziel == "morgen":
        ziel = (heute_d + timedelta(days=1)).isoformat()
    tag, flexibel = _tag_aus_wann(ziel, heute_d)
    vorher = {"tag": termin["tag"], "flexibel": termin["flexibel"]}
    try:
        db.execute("UPDATE termine SET tag=?, flexibel=? WHERE id=?", (tag, flexibel, termin["id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        raise AufgabenFehler("An dem Tag steht die Aufgabe schon.") from None
    db.commit()
    return {"vorher": vorher, "tag": tag, "flexibel": flexibel,
            "text": _wohin_text(tag, flexibel, heute_d)}


def _wohin_text(tag, flexibel, heute_d: date) -> str:
    if flexibel:
        return "Diese Woche, ohne festen Tag"
    tag_d = date.fromisoformat(tag)
    if tag_d == heute_d:
        return "Steht jetzt bei Heute"
    if tag_d == heute_d + timedelta(days=1):
        return "Steht jetzt bei Morgen"
    return f"{WOCHENTAGE[tag_d.weekday()]}, {tag_d.day}.{tag_d.month}."


def seit_text(geparkt_am, heute_d: date) -> str:
    """'Geparkt seit heute' / 'seit gestern' / 'seit 4 Tagen' / 'seit 2 Wochen'
    / 'seit 2 Monaten' - aus dem UTC-Zeitstempel, in Familientagen."""
    if not geparkt_am:
        return "Geparkt"
    tag = utc_zu_lokal_datum(geparkt_am)
    try:
        tage = (heute_d - date.fromisoformat(str(tag))).days
    except (TypeError, ValueError):
        return "Geparkt"
    if tage <= 0:
        return "Geparkt seit heute"
    if tage == 1:
        return "Geparkt seit gestern"
    if tage < 14:
        return f"Geparkt seit {tage} Tagen"
    if tage < 60:
        wochen = tage // 7
        return f"Geparkt seit {wochen} Woche{'n' if wochen != 1 else ''}"
    monate = tage // 30
    return f"Geparkt seit {monate} Monat{'en' if monate != 1 else ''}"


def spaeter_daten(db, user, heute_iso=None) -> dict:
    """Die geparkten Termine, die den Nutzer betreffen: eigene und (bei
    Eltern) alle sichtbaren ohne feste Person. Reihenfolge = position."""
    heute_d = date.fromisoformat(heute_iso or heute_lokal())
    zeilen = sichtbare_termine(db, user, status="geparkt")
    zeilen = [t for t in zeilen if t["user_id"] == user["id"] or
              (ist_eltern(user) and t["user_id"] is None)]
    zeilen.sort(key=lambda t: (t["position"], t["id"]))
    return {"geparkt": [{
        "id": t["id"], "aufgabe_id": t["aufgabe_id"],
        "inhalt": t["inhalt"] or t["aufgabe_inhalt"], "emoji": t["emoji"],
        "seit": seit_text(t["geparkt_am"], heute_d),
        "darf": darf_parken(user, t),
        "sicht_marke": SICHT_MARKEN.get(t["sicht"]),
    } for t in zeilen]}


def spaeter_reihenfolge(db, user, ids) -> int:
    """Neue Reihenfolge der Spaeter-Liste; nur geparkte, sichtbare Termine
    mit Parkrecht. Rueckgabe: Zahl der gesetzten Positionen."""
    gesetzt = 0
    for position, tid in enumerate(ids):
        tid = to_int(tid)
        if tid is None:
            continue
        termin = termin_sichtbar(db, user, tid)
        if termin is None or termin["status"] != "geparkt" or not darf_parken(user, termin):
            continue
        db.execute("UPDATE termine SET position=? WHERE id=?", (position, tid))
        gesetzt += 1
    db.commit()
    return gesetzt


# ---------------------------------------------------------------------------
# Schritt 4: Kacheln (5.4)
# ---------------------------------------------------------------------------

KACHEL_TAGE = 30


def kacheln_daten(db, user, person, heute_iso=None) -> list:
    """Kacheln der sichtbaren Aufgaben mit kachel=1 (nicht pausiert), nach
    Haeufigkeit der letzten 30 Tage sortiert, mit "N x heute" der Person und
    ob der letzte heutige Tipp vom Betrachter zurueckgenommen werden darf."""
    heute_iso = heute_iso or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    seit = (heute_d - timedelta(days=KACHEL_TAGE)).isoformat()
    aufgaben = [a for a in sichtbare_aufgaben(db, user) if a["kachel"] and not a["pausiert"]]
    kacheln = []
    for a in aufgaben:
        haeufig = db.execute("""SELECT COUNT(*) FROM termine WHERE aufgabe_id=? AND spontan=1
                                AND status='erledigt' AND erledigt_tag >= ?""", (a["id"], seit)).fetchone()[0]
        heute_tipps = db.execute("""SELECT * FROM termine WHERE aufgabe_id=? AND spontan=1
                                    AND status='erledigt' AND erledigt_tag=? AND user_id=?
                                    ORDER BY id DESC""", (a["id"], heute_iso, person["id"])).fetchall()
        letzter = heute_tipps[0] if heute_tipps else None
        kacheln.append({
            "aufgabe_id": a["id"], "inhalt": a["inhalt"], "emoji": a["emoji"],
            "punkte": float(a["punkte"] or 0), "punkte_text": punkte_text(a["punkte"]),
            "haeufig": haeufig, "heute": len(heute_tipps),
            "zurueck": letzter is not None and darf_kachel_zurueck(user, letzter, heute_iso),
        })
    kacheln.sort(key=lambda k: (-k["haeufig"], k["inhalt"].lower()))
    return kacheln


def kachel_tippen(db, user, person, aufgabe, heute_iso=None) -> dict:
    """Ein Tipp: steht dieselbe Aufgabe heute als offener Termin der Person
    im Plan, wird DER abgehakt (keine Dublette); sonst entsteht ein
    spontaner, erledigter Termin. getippt_von = wer getippt hat."""
    heute_iso = heute_iso or heute_lokal()
    if ist_gast(user) and not ist_kiosk(user):
        raise Verboten("Gaeste tippen keine Kacheln.")
    if not aufgabe["kachel"] or aufgabe["pausiert"]:
        raise AufgabenFehler("Das ist keine Kachel.")
    sonntag = sonntag_von(date.fromisoformat(heute_iso)).isoformat()
    offen = db.execute("""SELECT id FROM termine WHERE aufgabe_id=? AND user_id=? AND spontan=0
                          AND status='offen' AND tag IS NOT NULL
                          AND (tag <= ? OR (flexibel=1 AND tag <= ?))
                          ORDER BY tag LIMIT 1""",
                       (aufgabe["id"], person["id"], heute_iso, sonntag)).fetchone()
    if offen:
        termin = termin_sichtbar(db, user, offen["id"])
        if termin is not None and darf_haken(user, termin, person):
            termin_haken(db, user, termin, heute_iso, erledigt_von=person["id"])
            return {"termin_id": termin["id"], "geplant": True}
    tid = db.execute("""INSERT INTO termine(aufgabe_id, tag, user_id, status, spontan, punkte,
                                            erledigt_am, erledigt_tag, erledigt_von, getippt_von)
                        VALUES (?,?,?,'erledigt',1,?,datetime('now'),?,?,?) RETURNING id""",
                     (aufgabe["id"], heute_iso, person["id"], float(aufgabe["punkte"] or 0),
                      heute_iso, person["id"], user["id"])).fetchone()["id"]
    db.commit()
    return {"termin_id": tid, "geplant": False}


def kachel_zurueck(db, user, person, aufgabe, heute_iso=None) -> bool:
    """Den letzten heutigen Tipp der Person zu dieser Kachel zuruecknehmen
    (Recht: darf_kachel_zurueck). False, wenn es nichts zurueckzunehmen gibt."""
    heute_iso = heute_iso or heute_lokal()
    letzter = db.execute("""SELECT * FROM termine WHERE aufgabe_id=? AND user_id=? AND spontan=1
                            AND status='erledigt' AND erledigt_tag=? ORDER BY id DESC LIMIT 1""",
                         (aufgabe["id"], person["id"], heute_iso)).fetchone()
    if letzter is None:
        return False
    if not darf_kachel_zurueck(user, letzter, heute_iso):
        raise Verboten("Diesen Eintrag darfst du nicht zuruecknehmen.")
    db.execute("DELETE FROM termine WHERE id=?", (letzter["id"],))
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Schritt 6: Gruppenaufgaben, Familie, Alle Aufgaben (5.2, 6.4, 6.6)
# ---------------------------------------------------------------------------

def termin_nehmen(db, user, termin, person=None) -> dict:
    """"Ich mach's" - atomar: UPDATE ... WHERE user_id IS NULL. Trifft das
    keine Zeile, war jemand schneller; die Antwort nennt den Namen."""
    # Rechte wie darf_nehmen - nur dass ein INZWISCHEN vergebener Termin kein
    # Verbot ist, sondern der Wettlauf, den 5.2 beschreibt ("war schneller").
    wer = person if (person is not None and darf_person_waehlen(user)) else user
    if (not termin["ziel_gruppe"] or (ist_kiosk(user) and person is None)
            or not gruppe_passt(wer, termin["ziel_gruppe"])):
        raise Verboten("Diese Aufgabe steht nicht fuer dich bereit.")
    cur = db.execute("UPDATE termine SET user_id=? WHERE id=? AND user_id IS NULL", (wer["id"], termin["id"]))
    db.commit()
    if cur.rowcount == 1:
        return {"genommen": True, "user_id": wer["id"]}
    jetzt = db.execute("SELECT u.name FROM termine t JOIN users u ON u.id=t.user_id WHERE t.id=?",
                       (termin["id"],)).fetchone()
    name = jetzt["name"] if jetzt else "Jemand"
    return {"genommen": False, "text": f"{name} war schneller"}


def termin_freigeben(db, user, termin) -> None:
    if not darf_freigeben(user, termin):
        raise Verboten("Diesen Termin darfst du nicht freigeben.")
    db.execute("UPDATE termine SET user_id=NULL WHERE id=?", (termin["id"],))
    db.commit()


def aufgabe_pausieren(db, user, aufgabe) -> bool:
    """Pausieren / Fortsetzen einer regelmaessigen Aufgabe (5.3). Rueckgabe:
    ist sie jetzt pausiert?"""
    if not darf_bearbeiten(user, aufgabe) or not ist_eltern(user):
        raise Verboten("Pausieren duerfen nur Eltern.")
    if not aufgabe["regel_typ"]:
        raise AufgabenFehler("Nur regelmaessige Aufgaben lassen sich pausieren.")
    neu = 0 if aufgabe["pausiert"] else 1
    db.execute("UPDATE aufgaben SET pausiert=?, geaendert=datetime('now') WHERE id=?", (neu, aufgabe["id"]))
    db.commit()
    return bool(neu)


def noch_zu_haben(db, user, person, heute_iso=None) -> list:
    """Freie Gruppenaufgaben (user_id NULL, offen, bis Ende der Woche), die zu
    der Person passen - "Noch zu haben" auf Heute (5.2)."""
    heute_iso = heute_iso or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    namen = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM users")}
    frei = sichtbare_termine(db, user, status="offen", frei=True, bis=sonntag_von(heute_d).isoformat())
    zeilen = []
    for t in frei:
        if not gruppe_passt(person, t["ziel_gruppe"]):
            continue
        z = _zeile(t, user, namen, heute_d)
        z["info"] = f"Von {namen.get(t['erstellt_von'], 'jemandem')} · " + GRUPPEN_TEXT[t["ziel_gruppe"]]
        zeilen.append(z)
    return zeilen


GRUPPEN_TEXT = {"eltern": "für die Eltern", "kinder": "für die Kinder", "alle": "wer will"}
GRUPPEN_NAME = {"eltern": "Eltern", "kinder": "Kinder", "alle": "Wer will"}


def familie_daten(db, user, heute_iso=None) -> dict:
    """Familie (6.4): Fortschritt je Person (aus heute_daten des BETRACHTERS,
    private Aufgaben der Kinder fehlen also), "Noch ohne Person", Zaehler
    fuer Spaeter und Alle Aufgaben."""
    heute_iso = heute_iso or heute_lokal()
    personen = db.execute("""SELECT id, name, farbe, rolle FROM users WHERE rolle IN ('kind', 'eltern')
                             ORDER BY rolle, name COLLATE NOCASE""").fetchall()
    fortschritt = []
    for p in personen:
        d = heute_daten(db, user, p, heute_iso)
        ueberfaellig = sum(1 for z in d["zeilen"] if z["ueberfaellig"])
        if d["gesamt"] == 0:
            stand = "Heute nichts dran"
        elif d["geschafft"] == d["gesamt"]:
            stand = "Alles erledigt"
        else:
            stand = f"{d['geschafft']} von {d['gesamt']}"
        fortschritt.append({
            "id": p["id"], "name": p["name"] + (" (ich)" if p["id"] == user["id"] else ""),
            "farbe": p["farbe"], "kuerzel": (p["name"] or "?")[:1].upper(),
            "stand": stand, "prozent": d["balken_prozent"] if d["gesamt"] else 0,
            "punkte_woche": d["punkte_woche"],
            "ueberfaellig": ueberfaellig,
            "zeile2": (f"{ueberfaellig} davon überfällig" if ueberfaellig
                       else f"{d['punkte_woche']} Punkte diese Woche"),
        })
    heute_d = date.fromisoformat(heute_iso)
    namen = {p["id"]: p["name"] for p in personen}
    frei = sichtbare_termine(db, user, status="offen", frei=True, bis=sonntag_von(heute_d).isoformat())
    ohne_person = [{"id": t["id"], "inhalt": t["inhalt"] or t["aufgabe_inhalt"],
                    "gruppe": GRUPPEN_NAME.get(t["ziel_gruppe"], ""),
                    "darf": darf_nehmen(user, t),
                    "von": namen.get(t["erstellt_von"], "?")} for t in frei]
    geparkt = len(spaeter_daten(db, user, heute_iso)["geparkt"])
    alle = len(sichtbare_aufgaben(db, user))
    return {"fortschritt": fortschritt, "ohne_person": ohne_person, "geparkt": geparkt,
            "alle": alle, "datum": datum_lang(heute_d)}


def _regel_text(a) -> str:
    if a["regel_typ"] == "wochentage":
        kurz = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        tage = [kurz[int(t)] for t in (a["regel_wochentage"] or "").split(",") if t.strip().isdigit()]
        return "Jeden Tag" if len(tage) == 7 else "Jeden " + ", ".join(tage)
    if a["regel_typ"] == "intervall":
        return f"Alle {a['regel_intervall']} Tage"
    return ""


def katalog_daten(db, user, heute_iso=None) -> list:
    """Alle Aufgaben (6.6): eine Zeile je sichtbarer Aufgabe mit Art
    (regel/einmal/geparkt), Wann-Text, Person, Marken, Punkten. Pausierte
    kommen (gedimmt) ans Ende - sichtbare_aufgaben sortiert schon so."""
    heute_iso = heute_iso or heute_lokal()
    namen = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM users")}
    zeilen = []
    for a in sichtbare_aufgaben(db, user):
        termin = _termin_der_aufgabe(db, a["id"])
        if a["regel_typ"]:
            art, wann = "regel", _regel_text(a)
        elif termin is None:
            art, wann = "einmal", "Ohne Termin"
        elif termin["status"] == "geparkt":
            art, wann = "geparkt", "Geparkt"
        elif termin["status"] == "erledigt":
            art, wann = "einmal", "Erledigt"
        elif termin["flexibel"]:
            art, wann = "einmal", "Diese Woche"
        elif termin["tag"] == heute_iso:
            art, wann = "einmal", "Heute"
        else:
            t = date.fromisoformat(termin["tag"])
            art, wann = "einmal", f"{['Mo','Di','Mi','Do','Fr','Sa','So'][t.weekday()]}, {t.day}.{t.month}."
        if a["ziel_gruppe"]:
            wer = GRUPPEN_NAME[a["ziel_gruppe"]] + (" im Wechsel" if a["regel_typ"] and a["ziel_gruppe"] != "alle" else "")
        else:
            wer = namen.get(a["ziel_user"], "–")
        zeilen.append({
            "id": a["id"], "inhalt": a["inhalt"], "emoji": a["emoji"], "art": art, "wann": wann,
            "wer": wer, "sicht_marke": SICHT_MARKEN.get(a["sicht"]), "kachel": bool(a["kachel"]),
            "punkte": float(a["punkte"] or 0), "punkte_text": punkte_text(a["punkte"]),
            "pausiert": bool(a["pausiert"]), "regel": bool(a["regel_typ"]),
            "suche": (a["inhalt"] or "").lower(),
        })
    return zeilen


# ---------------------------------------------------------------------------
# Schritt 5: Regeln und Vorschlaege (5.1, Entscheidung 15.1), Woche (6.3)
# ---------------------------------------------------------------------------

VORSCHAU_TAGE = 13     # laufende + naechste Woche, ab Montag der laufenden
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _mitglieder(db, gruppe):
    rolle = "eltern" if gruppe == "eltern" else "kind"
    return [z["id"] for z in db.execute("SELECT id FROM users WHERE rolle=? ORDER BY id", (rolle,))]


def _naechste_person(db, aufgabe):
    """Abwechseln bei Gruppe eltern/kinder: fortgesetzt vom letzten Termin
    derselben Aufgabe, der eine Person hatte (5.1)."""
    mitglieder = _mitglieder(db, aufgabe["ziel_gruppe"])
    if not mitglieder:
        return None
    letzter = db.execute("""SELECT user_id FROM termine WHERE aufgabe_id=? AND user_id IS NOT NULL
                            AND spontan=0 ORDER BY tag DESC, id DESC LIMIT 1""", (aufgabe["id"],)).fetchone()
    if letzter is None or letzter["user_id"] not in mitglieder:
        return mitglieder[0]
    return mitglieder[(mitglieder.index(letzter["user_id"]) + 1) % len(mitglieder)]


def _vorschlag_einfuegen(db, aufgabe, tag_iso, status) -> int:
    """Ein Termin aus einer Regel - INSERT OR IGNORE ueber den Unique-Index
    termine_regel_tag: existiert an dem Tag schon einer (auch 'aus' oder
    'erledigt'), passiert nichts. Rueckgabe 1 = neu, 0 = gab es schon."""
    if aufgabe["ziel_user"]:
        user_id = aufgabe["ziel_user"]
    elif aufgabe["ziel_gruppe"] in ("eltern", "kinder"):
        user_id = _naechste_person(db, aufgabe)
    else:
        user_id = None
    cur = db.execute("INSERT OR IGNORE INTO termine(aufgabe_id, tag, user_id, status) VALUES(?,?,?,?)",
                     (aufgabe["id"], tag_iso, user_id, status))
    return cur.rowcount


def vorschlaege_sicherstellen(db, heute=None) -> dict:
    """Laeuft beim Aufruf von Heute, Woche und Familie - fuer die laufende und
    die naechste Woche. Kein Hintergrund-Thread. Idempotent.

    1. Termine aus Regeln erzeugen (ab heute bis Ende naechster Woche):
       wochentage -> ein Termin je Tag; intervall -> ab erledigt_tag des
       letzten erledigten Termins, kein neuer solange einer offen/vorschlag
       ist, ohne Vorgeschichte morgen. Status 'vorschlag', ausser ein Kind
       hat die Regel fuer sich selbst angelegt (dann 'offen'). Pausiert
       erzeugt nichts.
    2. Vergangene, nie freigegebene Vorschlaege verfallen zu 'aus'.
    3. Entscheidung 15.1: Vorschlaege fuer HEUTE werden 'offen' mit
       auto_bestaetigt=1 - auch ohne Person ("Noch zu haben"). Nur heute,
       nie kuenftige Tage. Kein Push."""
    heute_iso = heute or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    ende = montag_von(heute_d) + timedelta(days=VORSCHAU_TAGE)
    ergebnis = {"erzeugt": 0, "verfallen": 0, "freigegeben": 0}
    regeln = db.execute("""SELECT a.*, u.rolle AS ersteller_rolle FROM aufgaben a
                           LEFT JOIN users u ON u.id = a.erstellt_von
                           WHERE a.regel_typ IS NOT NULL AND a.pausiert = 0 ORDER BY a.id""").fetchall()
    for a in regeln:
        status = "offen" if (a["ersteller_rolle"] == "kind" and a["ziel_user"] == a["erstellt_von"]) else "vorschlag"
        if a["regel_typ"] == "wochentage":
            tage = {to_int(t, -1) for t in (a["regel_wochentage"] or "").split(",")}
            tag = heute_d
            while tag <= ende:
                if tag.weekday() in tage:
                    ergebnis["erzeugt"] += _vorschlag_einfuegen(db, a, tag.isoformat(), status)
                tag += timedelta(days=1)
        elif a["regel_typ"] == "intervall":
            offen = db.execute("""SELECT 1 FROM termine WHERE aufgabe_id=? AND spontan=0
                                  AND status IN ('offen', 'vorschlag')""", (a["id"],)).fetchone()
            if offen:
                continue
            letzte = db.execute("""SELECT MAX(erledigt_tag) FROM termine WHERE aufgabe_id=?
                                   AND status='erledigt' AND erledigt_tag IS NOT NULL""", (a["id"],)).fetchone()[0]
            if letzte:
                naechster = date.fromisoformat(letzte) + timedelta(days=to_int(a["regel_intervall"], 2))
            else:
                naechster = heute_d + timedelta(days=1)
            naechster = max(naechster, heute_d)
            if naechster <= ende:
                ergebnis["erzeugt"] += _vorschlag_einfuegen(db, a, naechster.isoformat(), status)
    ergebnis["verfallen"] = db.execute("""UPDATE termine SET status='aus'
                                          WHERE status='vorschlag' AND spontan=0 AND tag < ?""", (heute_iso,)).rowcount
    ergebnis["freigegeben"] = db.execute("""UPDATE termine SET status='offen', auto_bestaetigt=1
                                            WHERE status='vorschlag' AND tag = ?""", (heute_iso,)).rowcount
    db.commit()
    return ergebnis


def termin_ok(db, user, termin) -> None:
    """Vorschlag bestaetigen (nur Eltern, 3.2)."""
    if not darf_vorschlaege(user):
        raise Verboten("Vorschlaege bestaetigen nur Eltern.")
    if termin["status"] != "vorschlag":
        raise AufgabenFehler("Das ist kein Vorschlag mehr.")
    db.execute("UPDATE termine SET status='offen' WHERE id=?", (termin["id"],))
    db.commit()


def termin_aus(db, user, termin, wieder=None) -> dict:
    """"Faellt aus" (status 'aus', die Zeile bleibt - so entsteht sie nicht
    neu). `wieder` = vorheriger Status fuer "Rueckgaengig". Rueckgabe: wie
    viele weitere Termine derselben Aufgabe in derselben Woche noch offen
    sind ("Auch die anderen N streichen")."""
    if not darf_vorschlaege(user):
        raise Verboten("Streichen duerfen nur Eltern.")
    if wieder:
        if wieder not in ("vorschlag", "offen") or termin["status"] != "aus":
            raise AufgabenFehler("Nichts zurueckzunehmen.")
        db.execute("UPDATE termine SET status=? WHERE id=?", (wieder, termin["id"]))
        db.commit()
        return {"status": wieder, "rest": 0}
    if termin["status"] not in ("vorschlag", "offen"):
        raise AufgabenFehler("Nur offene Termine oder Vorschlaege fallen aus.")
    vorher = termin["status"]
    db.execute("UPDATE termine SET status='aus' WHERE id=?", (termin["id"],))
    db.commit()
    return {"status": "aus", "vorher": vorher, "rest": _rest_in_woche(db, termin)}


def _rest_in_woche(db, termin) -> int:
    if not termin["tag"]:
        return 0
    tag_d = date.fromisoformat(termin["tag"])
    return db.execute("""SELECT COUNT(*) FROM termine WHERE aufgabe_id=? AND id != ? AND spontan=0
                         AND status IN ('vorschlag', 'offen') AND tag BETWEEN ? AND ?""",
                      (termin["aufgabe_id"], termin["id"], montag_von(tag_d).isoformat(),
                       sonntag_von(tag_d).isoformat())).fetchone()[0]


def woche_aus(db, user, termin) -> int:
    """"Auch die anderen N streichen": alle weiteren Termine derselben
    Aufgabe in derselben Woche (vorschlag/offen) -> aus."""
    if not darf_vorschlaege(user):
        raise Verboten("Streichen duerfen nur Eltern.")
    if not termin["tag"]:
        return 0
    tag_d = date.fromisoformat(termin["tag"])
    n = db.execute("""UPDATE termine SET status='aus' WHERE aufgabe_id=? AND spontan=0
                      AND status IN ('vorschlag', 'offen') AND tag BETWEEN ? AND ?""",
                   (termin["aufgabe_id"], montag_von(tag_d).isoformat(), sonntag_von(tag_d).isoformat())).rowcount
    db.commit()
    return n


def termin_person(db, user, termin, user_id) -> None:
    """Person eines Termins setzen (Namens-Chip in der Woche). None = frei."""
    if not darf_vorschlaege(user):
        raise Verboten("Die Person aendern nur Eltern.")
    if user_id is not None and not db.execute(
            "SELECT 1 FROM users WHERE id=? AND rolle IN ('eltern', 'kind')", (user_id,)).fetchone():
        raise AufgabenFehler("Diese Person gibt es nicht.")
    if user_id is None and not termin["ziel_gruppe"]:
        raise AufgabenFehler("Ohne Person geht nur bei Gruppenaufgaben.")
    db.execute("UPDATE termine SET user_id=? WHERE id=?", (user_id, termin["id"]))
    db.commit()


def _woche_passt(db, t, wer, eltern_ids) -> bool:
    """Personenfilter der Woche: '' alle | '<id>' | 'eltern'."""
    if not wer:
        return True
    if wer == "eltern":
        return t["user_id"] in eltern_ids or (t["user_id"] is None and t["ziel_gruppe"] == "eltern")
    return t["user_id"] == to_int(wer)


def woche_termine(db, user, montag: date, wer="", heute_iso=None):
    """Die Termine der Woche fuer den Betrachter: Eltern alle sichtbaren
    (vorschlag/offen/erledigt), Kinder nur eigene offene/erledigte - ohne
    Vorschlaege (6.3). Ohne spontane Kachel-Eintraege."""
    sonntag = montag + timedelta(days=6)
    if ist_eltern(user):
        zeilen = sichtbare_termine(db, user, von=montag.isoformat(), bis=sonntag.isoformat(),
                                   status=("vorschlag", "offen", "erledigt"))
    else:
        zeilen = sichtbare_termine(db, user, von=montag.isoformat(), bis=sonntag.isoformat(),
                                   status=("offen", "erledigt"), user_id=user["id"])
    eltern_ids = set(_mitglieder(db, "eltern"))
    return [t for t in zeilen if not t["spontan"] and _woche_passt(db, t, wer, eltern_ids)]


def woche_ok(db, user, montag: date, tag=None, wer="") -> int:
    """Sammelbestaetigung - immer nur das Sichtbare (Filter, ggf. ein Tag)."""
    if not darf_vorschlaege(user):
        raise Verboten("Vorschlaege bestaetigen nur Eltern.")
    ids = [t["id"] for t in woche_termine(db, user, montag, wer)
           if t["status"] == "vorschlag" and (tag is None or t["tag"] == tag)]
    for tid in ids:
        db.execute("UPDATE termine SET status='offen' WHERE id=? AND status='vorschlag'", (tid,))
    db.commit()
    return len(ids)


def _woche_titel(montag: date, heute_d: date) -> str:
    diff = (montag - montag_von(heute_d)).days
    return {0: "Diese Woche", 7: "Nächste Woche", -7: "Letzte Woche"}.get(diff, "Woche")


def _woche_bereich(montag: date) -> str:
    sonntag = montag + timedelta(days=6)
    if montag.month == sonntag.month:
        return f"{montag.day}. bis {sonntag.day}. {MONATE[montag.month - 1]} · KW {montag.isocalendar()[1]}"
    return (f"{montag.day}. {MONATE[montag.month - 1]} bis {sonntag.day}. {MONATE[sonntag.month - 1]}"
            f" · KW {montag.isocalendar()[1]}")


def woche_daten(db, user, montag: date, wer="", heute_iso=None) -> dict:
    heute_iso = heute_iso or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)
    termine = woche_termine(db, user, montag, wer, heute_iso)
    personen = _familienmitglieder(db)
    namen = {p["id"]: p["name"] for p in personen}
    farben = {p["id"]: p["farbe"] for p in personen}
    tage = []
    for i in range(7):
        tag = montag + timedelta(days=i)
        eintraege = []
        for t in termine:
            if t["tag"] != tag.isoformat():
                continue
            vorschlag = t["status"] == "vorschlag"
            if t["regel_typ"]:
                info = _regel_text_aus_termin(db, t)
            else:
                info = "Einmalig"
            if t["uhrzeit"]:
                info += f" · {t['uhrzeit']}"
            if t["status"] == "erledigt":
                info += " · erledigt"
            elif t["auto_bestaetigt"]:
                info += " · automatisch freigegeben"
            elif t["regel_typ"] and t["status"] == "offen":
                info += " · bestätigt"
            eintraege.append({
                "id": t["id"], "aufgabe_id": t["aufgabe_id"],
                "inhalt": t["inhalt"] or t["aufgabe_inhalt"], "emoji": t["emoji"],
                "status": t["status"], "vorschlag": vorschlag, "erledigt": t["status"] == "erledigt",
                "info": info, "regel": bool(t["regel_typ"]),
                "person": namen.get(t["user_id"]) if t["user_id"] else GRUPPEN_NAME.get(t["ziel_gruppe"], "–"),
                "person_id": t["user_id"], "farbe": farben.get(t["user_id"]),
                "sicht_marke": SICHT_MARKEN.get(t["sicht"]),
                "bearbeitbar": darf_vorschlaege(user) and t["status"] != "erledigt",
            })
        tage.append({
            "iso": tag.isoformat(), "kurz": WOCHENTAGE_KURZ[i],
            "titel": f"{WOCHENTAGE[i]}, {tag.day}.{tag.month}.", "name": WOCHENTAGE[i],
            "heute": tag == heute_d, "vergangen": tag < heute_d,
            "eintraege": eintraege,
            "offene": sum(1 for e in eintraege if e["vorschlag"]),
        })
    offene = sum(d["offene"] for d in tage)
    filter_optionen = [{"wert": "", "name": "Alle"}]
    filter_optionen += [{"wert": str(p["id"]), "name": p["name"]} for p in personen if p["rolle"] == "kind"]
    filter_optionen.append({"wert": "eltern", "name": "Eltern"})
    wer_name = next((f["name"] for f in filter_optionen if f["wert"] == wer and wer), "")
    return {
        "tage": tage, "offene": offene, "wer": wer, "wer_name": wer_name,
        "filter_optionen": filter_optionen if ist_eltern(user) else [],
        "montag": montag.isoformat(),
        "vorher": (montag - timedelta(days=7)).isoformat(),
        "nachher": (montag + timedelta(days=7)).isoformat(),
        "titel": _woche_titel(montag, heute_d), "bereich": _woche_bereich(montag),
        "personen": personen, "heute": heute_iso,
    }


def _regel_text_aus_termin(db, t):
    a = db.execute("SELECT regel_typ, regel_wochentage, regel_intervall, ziel_gruppe FROM aufgaben WHERE id=?",
                   (t["aufgabe_id"],)).fetchone()
    text = _regel_text(a) if a else ""
    if a and a["ziel_gruppe"] in ("eltern", "kinder"):
        text += ", im Wechsel"
    return text


def regel_aendern(db, user, aufgabe, *, inhalt, ziel_user=None, ziel_gruppe=None, sicht="alle",
                  punkte=0, emoji=None, kachel=None, regel_typ=None, regel_wochentage=None,
                  regel_intervall=None, heute=None) -> None:
    """"Alle kuenftigen" (5.5): Aufgabe schreiben; aendert sich die Regel,
    werden die Termine ab heute im Status vorschlag/offen neu erzeugt,
    sonst nur ihre Person nachgezogen. Erledigte und 'aus' bleiben."""
    if not darf_bearbeiten(user, aufgabe):
        raise Verboten("Diese Aufgabe darfst du nicht bearbeiten.")
    heute_iso = heute or heute_lokal()
    if ist_kind(user):
        punkte, emoji, kachel = aufgabe["punkte"], aufgabe["emoji"], aufgabe["kachel"]
        ziel_user, ziel_gruppe = aufgabe["ziel_user"], None
    if kachel is None:
        kachel = aufgabe["kachel"]
    inhalt, ziel_user, ziel_gruppe, sicht, punkte_neu, kachel_neu, emoji_neu = _felder_pruefen(
        db, user, inhalt, ziel_user, ziel_gruppe, sicht, punkte, kachel, emoji)
    if ist_kind(user):
        punkte_neu, emoji_neu, kachel_neu = aufgabe["punkte"], aufgabe["emoji"], aufgabe["kachel"]
    regel_typ, regel_wochentage, regel_intervall = _regel_pruefen(
        regel_typ or aufgabe["regel_typ"], regel_wochentage, regel_intervall)
    if regel_typ is None:
        raise AufgabenFehler("Eine regelmaessige Aufgabe braucht eine Regel.")
    if inhalt != aufgabe["inhalt"]:
        db.execute("INSERT INTO aufgaben_historie(aufgabe_id, alter_inhalt, geaendert_von) VALUES(?,?,?)",
                   (aufgabe["id"], aufgabe["inhalt"], user["id"]))
    db.execute("""UPDATE aufgaben SET inhalt=?, ziel_user=?, ziel_gruppe=?, sicht=?, punkte=?, emoji=?, kachel=?,
                  regel_typ=?, regel_wochentage=?, regel_intervall=?, geaendert=datetime('now') WHERE id=?""",
               (inhalt, ziel_user, ziel_gruppe, sicht, punkte_neu, emoji_neu, kachel_neu,
                regel_typ, regel_wochentage, regel_intervall, aufgabe["id"]))
    regel_gleich = (regel_typ == aufgabe["regel_typ"] and regel_wochentage == aufgabe["regel_wochentage"]
                    and regel_intervall == aufgabe["regel_intervall"])
    ziel_gleich = ziel_user == aufgabe["ziel_user"] and ziel_gruppe == aufgabe["ziel_gruppe"]
    if regel_gleich and ziel_gleich:
        db.execute("""UPDATE termine SET inhalt=NULL WHERE aufgabe_id=? AND spontan=0 AND tag >= ?
                      AND status IN ('vorschlag', 'offen')""", (aufgabe["id"], heute_iso))
    else:
        db.execute("""DELETE FROM termine WHERE aufgabe_id=? AND spontan=0 AND tag >= ?
                      AND status IN ('vorschlag', 'offen')""", (aufgabe["id"], heute_iso))
    db.commit()
    vorschlaege_sicherstellen(db, heute_iso)


def termin_einzeln_aendern(db, user, termin, *, inhalt, ziel_user=None, wann=None, uhrzeit=None,
                           heute=None) -> None:
    """"Nur dieser Termin" (5.5): Abweichung im Text (termine.inhalt), Tag,
    Uhrzeit, Person - die Aufgabe bleibt unberuehrt. Nur Eltern."""
    if not darf_vorschlaege(user):
        raise Verboten("Einzelne Termine aendern nur Eltern.")
    if termin["status"] not in ("vorschlag", "offen"):
        raise AufgabenFehler("Erledigte oder gestrichene Termine lassen sich nicht aendern.")
    heute_d = date.fromisoformat(heute or heute_lokal())
    inhalt = (inhalt or "").strip()[:INHALT_MAX]
    if not inhalt:
        raise AufgabenFehler("Was ist zu tun? Der Text fehlt.")
    abweichung = inhalt if inhalt != termin["aufgabe_inhalt"] else None
    tag, flexibel = termin["tag"], termin["flexibel"]
    if wann:
        tag, flexibel = _tag_aus_wann(wann, heute_d)
    if ziel_user is not None and not db.execute("SELECT 1 FROM users WHERE id=?", (ziel_user,)).fetchone():
        raise AufgabenFehler("Diese Person gibt es nicht.")
    if ziel_user is None:
        ziel_user = termin["user_id"]
    try:
        db.execute("UPDATE termine SET inhalt=?, tag=?, flexibel=?, uhrzeit=?, user_id=? WHERE id=?",
                   (abweichung, tag, flexibel, _uhrzeit_pruefen(uhrzeit), ziel_user, termin["id"]))
    except sqlite3.IntegrityError:
        db.rollback()
        raise AufgabenFehler("An dem Tag steht die Aufgabe schon.") from None
    db.commit()


# ---------------------------------------------------------------------------
# Routen - jede mit Token- und token-freier Regel (Wunsch #140, Stufe 4)
# ---------------------------------------------------------------------------

def _user(token):
    u = check_grant(token, APP)
    if not u:
        abort(403)
    return u


def _reiter(user, token, aktiv):
    """Reiterleiste unten (base.html). Kinder: Heute · Woche · Spaeter,
    Eltern: Heute · Woche · Familie. Kiosk und Gast: keine."""
    if ist_kiosk(user) or ist_gast(user):
        return []
    reiter = [{"name": "Heute", "href": url_for("aufgaben_app.heute", token=token), "aktiv": aktiv == "heute"},
              {"name": "Woche", "href": url_for("aufgaben_app.woche", token=token), "aktiv": aktiv == "woche"}]
    if ist_eltern(user):
        reiter.append({"name": "Familie", "href": url_for("aufgaben_app.familie", token=token),
                       "aktiv": aktiv == "familie"})
    else:
        reiter.append({"name": "Später", "href": url_for("aufgaben_app.spaeter", token=token),
                       "aktiv": aktiv == "spaeter"})
    return reiter


def _kein_kiosk(user):
    """Alles ausser Heute, Haken, Nehmen und Kacheln existiert fuer das
    Kiosk-Konto nicht (5.7) - 404, nicht 403."""
    if ist_kiosk(user):
        abort(404)


def _person_fuer(db, user, quelle=None):
    """`fuer=<id>` (Query oder Formular): Eltern sehen/handeln fuer eine
    andere Person, der Kiosk MUSS eine waehlen (sonst None -> Personenwahl).
    Fuer alle anderen ist es die eigene Person."""
    quelle = quelle if quelle is not None else request.args
    fuer = to_int(quelle.get("fuer"))
    if fuer and darf_person_waehlen(user) and fuer != user["id"]:
        zeile = db.execute("SELECT id, name, rolle, farbe FROM users WHERE id=? AND rolle IN ('eltern','kind')",
                           (fuer,)).fetchone()
        if zeile:
            return zeile
    if ist_kiosk(user):
        return None
    return {"id": user["id"], "name": user["name"], "rolle": user["rolle"], "farbe": user["farbe"]}


def _person_aus_formular(db, user):
    """Fuer POSTs: `fuer` aus dem Formular, sonst aus der Adresse. Kiosk ohne
    Person -> 400 (die Seite schickt sie immer mit)."""
    quelle = request.form if request.form.get("fuer") else request.args
    person = _person_fuer(db, user, quelle)
    if person is None:
        abort(400)
    return person


def _familienmitglieder(db):
    return db.execute("""SELECT id, name, farbe, rolle FROM users WHERE rolle IN ('kind', 'eltern')
                         ORDER BY rolle, name COLLATE NOCASE""").fetchall()


@bp.route("/a/aufgaben/", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/")
def heute(token):
    user = _user(token)
    db = get_db()
    person = _person_fuer(db, user)
    if person is None:
        # Kiosk: Personenwahl als Einstieg (5.7)
        return render_template("aufgaben_kiosk.html", user=user, token=token, farbe=user["farbe"],
                               personen=_familienmitglieder(db), datum=datum_lang(date.fromisoformat(heute_lokal())))
    heute_iso = heute_lokal()
    vorschlaege_sicherstellen(db, heute_iso)
    daten = heute_daten(db, user, person, heute_iso)
    return render_template("aufgaben_heute.html", user=user, token=token, farbe=user["farbe"],
                           person=person, fremd=person["id"] != user["id"], kiosk=ist_kiosk(user),
                           darf_anlegen=darf_anlegen(user),
                           personen=_familienmitglieder(db) if ist_eltern(user) else [],
                           frei=noch_zu_haben(db, user, person, heute_iso),
                           kacheln=kacheln_daten(db, user, person, heute_iso),
                           reiter=_reiter(user, token, "heute"), **daten)


def _heute_url(token, person_id=None, user=None, anker=None):
    url = url_for("aufgaben_app.heute", token=token)
    if person_id and user and person_id != user["id"]:
        url += f"?fuer={person_id}"
    return url + (f"#termin-{anker}" if anker else "")


def _termin_oder_404(db, user, tid):
    termin = termin_sichtbar(db, user, tid)
    if termin is None:
        abort(404)
    return termin


def _zaehler(db, user, person):
    d = heute_daten(db, user, person)
    return {"geschafft": d["geschafft"], "gesamt": d["gesamt"], "balken_text": d["balken_text"],
            "balken_prozent": d["balken_prozent"], "punkte_woche": d["punkte_woche"]}


@bp.route("/a/aufgaben/termin/<int:tid>/haken", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/haken", methods=["POST"])
def haken(token, tid):
    """Toggle erledigt. 404 vor 403: unsichtbar und nicht vorhanden sehen
    gleich aus (3.1). Antwort per antwort_oder_weiter() mit den neuen
    Zaehlern, damit die Seite Balken und Punkte ohne Neuladen nachzieht."""
    user = _user(token)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    person = _person_aus_formular(db, user)
    if not darf_haken(user, termin, person):
        abort(403)
    try:
        erledigt = termin_haken(db, user, termin,
                                erledigt_von=person["id"] if ist_kiosk(user) else None)
    except AufgabenFehler:
        abort(400)
    person_id = termin["user_id"] or person["id"]
    ziel = db.execute("SELECT id, name, rolle FROM users WHERE id=?", (person_id,)).fetchone() or person
    return antwort_oder_weiter(_heute_url(token, person_id, user, anker=tid),
                               erledigt=erledigt, **_zaehler(db, user, ziel))


@bp.route("/a/aufgaben/termin/<int:tid>/parken", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/parken", methods=["POST"])
def parken(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    try:
        vorher = termin_parken(db, user, termin)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    inhalt = termin["inhalt"] or termin["aufgabe_inhalt"]
    ziel = vorher["tag"] if not vorher["flexibel"] else "woche"
    return antwort_oder_weiter(
        url_for("aufgaben_app.spaeter", token=token) + f"#termin-{tid}",
        text=f"„{inhalt}“ ist geparkt. Du findest sie unter Später.",
        zurueck={"url": url_for("aufgaben_app.hervorholen", token=token, tid=tid),
                 "daten": {"ziel": ziel or "heute"}})


@bp.route("/a/aufgaben/termin/<int:tid>/hervorholen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/hervorholen", methods=["POST"])
def hervorholen(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    ziel = (request.form.get("ziel") or "heute").strip()
    try:
        ergebnis = termin_hervorholen(db, user, termin, ziel)
    except Verboten:
        abort(403)
    except AufgabenFehler as e:
        if "application/json" in (request.headers.get("Accept") or ""):
            return {"ok": False, "fehler": str(e)}, 400
        abort(400)
    inhalt = termin["inhalt"] or termin["aufgabe_inhalt"]
    return antwort_oder_weiter(
        _heute_url(token, termin["user_id"], user, anker=tid),
        text=ergebnis["text"], inhalt=inhalt, tag=ergebnis["tag"], flexibel=ergebnis["flexibel"],
        zurueck={"url": url_for("aufgaben_app.parken", token=token, tid=tid), "daten": {}})


@bp.route("/a/aufgaben/termin/<int:tid>/verlegen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/verlegen", methods=["POST"])
def verlegen(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    ziel = "morgen" if request.form.get("morgen") else (request.form.get("tag") or "").strip()
    if not ziel:
        abort(400)
    try:
        ergebnis = termin_verlegen(db, user, termin, ziel)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    inhalt = termin["inhalt"] or termin["aufgabe_inhalt"]
    vorher = ergebnis["vorher"]
    return antwort_oder_weiter(
        _heute_url(token, termin["user_id"], user, anker=tid),
        text=f"„{inhalt}“ steht jetzt bei {ergebnis['text'].replace('Steht jetzt bei ', '')}.",
        tag=ergebnis["tag"],
        zurueck={"url": url_for("aufgaben_app.verlegen", token=token, tid=tid),
                 "daten": {"tag": vorher["tag"] or ""}})


@bp.route("/a/aufgaben/spaeter", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/spaeter")
def spaeter(token):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    daten = spaeter_daten(db, user)
    return render_template("aufgaben_spaeter.html", user=user, token=token, farbe=user["farbe"],
                           darf_anlegen=darf_anlegen(user), ist_eltern=ist_eltern(user),
                           heute=heute_lokal(),
                           reiter=_reiter(user, token, "familie" if ist_eltern(user) else "spaeter"), **daten)


@bp.route("/a/aufgaben/spaeter/reihenfolge", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/spaeter/reihenfolge", methods=["POST"])
def spaeter_reihenfolge_route(token):
    user = _user(token)
    _kein_kiosk(user)
    daten = request.get_json(silent=True) or {}
    order = daten.get("order", [])
    if not isinstance(order, list):
        abort(400)
    return {"ok": True, "gesetzt": spaeter_reihenfolge(get_db(), user, order)}


@bp.route("/a/aufgaben/kachel/<int:aid>/tippen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/kachel/<int:aid>/tippen", methods=["POST"])
def kachel_tippen_route(token, aid):
    user = _user(token)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    person = _person_aus_formular(db, user)
    try:
        kachel_tippen(db, user, person, aufgabe)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    return _kachel_antwort(db, user, person, aid, token)


@bp.route("/a/aufgaben/kachel/<int:aid>/zurueck", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/kachel/<int:aid>/zurueck", methods=["POST"])
def kachel_zurueck_route(token, aid):
    user = _user(token)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    person = _person_aus_formular(db, user)
    try:
        kachel_zurueck(db, user, person, aufgabe)
    except Verboten:
        abort(403)
    return _kachel_antwort(db, user, person, aid, token)


def _kachel_antwort(db, user, person, aid, token):
    kachel = next((k for k in kacheln_daten(db, user, person) if k["aufgabe_id"] == aid), None)
    return antwort_oder_weiter(_heute_url(token, person["id"], user) + f"#kachel-{aid}",
                               heute=kachel["heute"] if kachel else 0,
                               zurueck=kachel["zurueck"] if kachel else False,
                               **_zaehler(db, user, person))


@bp.route("/a/aufgaben/termin/<int:tid>/nehmen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/nehmen", methods=["POST"])
def nehmen(token, tid):
    user = _user(token)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    person = _person_aus_formular(db, user)
    try:
        ergebnis = termin_nehmen(db, user, termin, person)
    except Verboten:
        abort(403)
    ziel = request.form.get("zurueck") or ""
    if not ziel.startswith("/a/aufgaben"):
        ziel = _heute_url(token, person["id"], user, anker=tid)
    return antwort_oder_weiter(ziel, **ergebnis)


@bp.route("/a/aufgaben/termin/<int:tid>/freigeben", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/freigeben", methods=["POST"])
def freigeben(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    try:
        termin_freigeben(db, user, termin)
    except Verboten:
        abort(403)
    return redirect(_heute_url(token, termin["user_id"], user))


@bp.route("/a/aufgaben/familie", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/familie")
def familie(token):
    user = _user(token)
    _kein_kiosk(user)
    if not ist_eltern(user):
        abort(403)
    db = get_db()
    heute_iso = heute_lokal()
    vorschlaege_sicherstellen(db, heute_iso)
    heute_d = date.fromisoformat(heute_iso)
    naechster_montag = montag_von(heute_d) + timedelta(days=7)
    diese = [t for t in woche_termine(db, user, montag_von(heute_d)) if t["status"] == "vorschlag"]
    naechste = [t for t in woche_termine(db, user, naechster_montag) if t["status"] == "vorschlag"]
    return render_template("aufgaben_familie.html", user=user, token=token, farbe=user["farbe"],
                           vorschlaege_naechste=len(naechste), vorschlaege_diese=len(diese),
                           naechster_montag=naechster_montag.isoformat(),
                           reiter=_reiter(user, token, "familie"), **familie_daten(db, user, heute_iso))


@bp.route("/a/aufgaben/alle", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/alle")
def alle(token):
    user = _user(token)
    _kein_kiosk(user)
    if not ist_eltern(user):
        abort(403)
    db = get_db()
    return render_template("aufgaben_alle.html", user=user, token=token, farbe=user["farbe"],
                           zeilen=katalog_daten(db, user), reiter=_reiter(user, token, "familie"))


@bp.route("/a/aufgaben/aufgabe/<int:aid>/pausieren", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/aufgabe/<int:aid>/pausieren", methods=["POST"])
def pausieren(token, aid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    try:
        aufgabe_pausieren(db, user, aufgabe)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    return redirect(url_for("aufgaben_app.alle", token=token) + f"#aufgabe-{aid}")


@bp.route("/a/aufgaben/woche", defaults={"token": None})
@bp.route("/a/aufgaben/<token>/woche")
def woche(token):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    heute_iso = heute_lokal()
    vorschlaege_sicherstellen(db, heute_iso)
    heute_d = date.fromisoformat(heute_iso)
    ab = request.args.get("ab") or ""
    try:
        montag = montag_von(date.fromisoformat(ab)) if ab else montag_von(heute_d)
    except ValueError:
        montag = montag_von(heute_d)
    wer = (request.args.get("wer") or "").strip() if ist_eltern(user) else ""
    daten = woche_daten(db, user, montag, wer, heute_iso)
    return render_template("aufgaben_woche.html", user=user, token=token, farbe=user["farbe"],
                           ist_eltern=ist_eltern(user), darf_anlegen=darf_anlegen(user),
                           reiter=_reiter(user, token, "woche"), **daten)


def _woche_url(token, montag, wer=""):
    url = url_for("aufgaben_app.woche", token=token) + f"?ab={montag}"
    return url + (f"&wer={wer}" if wer else "")


@bp.route("/a/aufgaben/woche/ok", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/woche/ok", methods=["POST"])
def woche_ok_route(token):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    try:
        montag = montag_von(date.fromisoformat(request.form.get("ab") or heute_lokal()))
    except ValueError:
        abort(400)
    tag = request.form.get("tag") or None
    wer = (request.form.get("wer") or "").strip()
    try:
        n = woche_ok(db, user, montag, tag, wer)
    except Verboten:
        abort(403)
    ziel = request.form.get("zurueck") or ""
    if not ziel.startswith("/a/aufgaben"):
        ziel = _woche_url(token, montag.isoformat(), wer)
    return antwort_oder_weiter(ziel, bestaetigt=n)


@bp.route("/a/aufgaben/termin/<int:tid>/ok", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/ok", methods=["POST"])
def termin_ok_route(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    try:
        termin_ok(db, user, termin)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    return antwort_oder_weiter(_woche_url(token, montag_von(date.fromisoformat(termin["tag"])).isoformat())
                               + f"#termin-{tid}", status="offen")


@bp.route("/a/aufgaben/termin/<int:tid>/aus", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/aus", methods=["POST"])
def termin_aus_route(token, tid):
    """Faellt aus; `wieder=<status>` nimmt es zurueck; `woche=1` streicht
    auch die anderen Termine derselben Aufgabe in der Woche."""
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    try:
        if request.form.get("woche"):
            n = woche_aus(db, user, termin)
            ergebnis = {"status": "aus", "gestrichen": n, "rest": 0}
        else:
            ergebnis = termin_aus(db, user, termin, wieder=request.form.get("wieder") or None)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    inhalt = termin["inhalt"] or termin["aufgabe_inhalt"]
    tag_d = date.fromisoformat(termin["tag"]) if termin["tag"] else date.fromisoformat(heute_lokal())
    if ergebnis["status"] == "aus" and "gestrichen" in ergebnis:
        text = f"„{inhalt}“ fällt diese Woche ganz aus."
    elif ergebnis["status"] == "aus":
        text = f"„{inhalt}“ am {WOCHENTAGE[tag_d.weekday()]} fällt aus."
    else:
        text = f"„{inhalt}“ steht wieder."
    return antwort_oder_weiter(
        _woche_url(token, montag_von(tag_d).isoformat()) + f"#termin-{tid}",
        text=text, rest=ergebnis.get("rest", 0), status=ergebnis["status"],
        zurueck={"url": url_for("aufgaben_app.termin_aus_route", token=token, tid=tid),
                 "daten": {"wieder": ergebnis.get("vorher", "")}})


@bp.route("/a/aufgaben/termin/<int:tid>/person", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/termin/<int:tid>/person", methods=["POST"])
def termin_person_route(token, tid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    termin = _termin_oder_404(db, user, tid)
    user_id = to_int(request.form.get("user_id"))
    try:
        termin_person(db, user, termin, user_id)
    except Verboten:
        abort(403)
    except AufgabenFehler:
        abort(400)
    name = db.execute("SELECT name FROM users WHERE id=?", (user_id,)).fetchone() if user_id else None
    tag_d = date.fromisoformat(termin["tag"]) if termin["tag"] else date.fromisoformat(heute_lokal())
    return antwort_oder_weiter(_woche_url(token, montag_von(tag_d).isoformat()) + f"#termin-{tid}",
                               person=name["name"] if name else GRUPPEN_NAME.get(termin["ziel_gruppe"], "–"),
                               user_id=user_id)


# ---------------------------------------------------------------------------
# Formular (6.2)
# ---------------------------------------------------------------------------

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
    gruppen = [("gruppe:eltern", "Eltern", "Steht bei beiden Eltern, bis einer „Ich mach’s“ tippt."),
               ("gruppe:kinder", "Kinder", "Steht bei beiden Kindern, bis eines „Ich mach’s“ tippt."),
               ("gruppe:alle", "Wer will", "Steht bei „Noch zu haben“ für alle.")]
    if werte is None:
        werte = {"inhalt": "", "ziel": "ich", "wann": "heute", "tag": "", "uhrzeit": "",
                 "sicht": "alle", "punkte": "0", "emoji": "", "kachel": "",
                 "regel_typ": "wochentage", "wochentage": [], "intervall": "3", "umfang": "kuenftige"}
        vorgabe_tag = request.args.get("tag") or ""
        if vorgabe_tag and vorgabe_tag != heute_iso:
            werte.update(wann="tag", tag=vorgabe_tag)
        if request.args.get("wann") == "spaeter":
            werte.update(wann="spaeter")
        if aufgabe is not None:
            if aufgabe["ziel_gruppe"]:
                ziel = "gruppe:" + aufgabe["ziel_gruppe"]
            elif aufgabe["ziel_user"] in (None, user["id"]):
                ziel = "ich"
            else:
                ziel = str(aufgabe["ziel_user"])
            werte.update(inhalt=aufgabe["inhalt"], sicht=aufgabe["sicht"],
                         punkte=punkte_text(aufgabe["punkte"]), emoji=aufgabe["emoji"] or "",
                         kachel="1" if aufgabe["kachel"] else "", ziel=ziel)
            if aufgabe["regel_typ"]:
                werte.update(wann="regel", regel_typ=aufgabe["regel_typ"],
                             wochentage=(aufgabe["regel_wochentage"] or "").split(","),
                             intervall=str(aufgabe["regel_intervall"] or 3))
                if termin is not None:
                    # "Nur dieser Termin": Text/Tag/Person des einen Termins vorbelegen
                    werte.update(umfang="termin", wann="tag", tag=termin["tag"] or heute_iso,
                                 uhrzeit=termin["uhrzeit"] or "",
                                 inhalt=termin["inhalt"] or aufgabe["inhalt"],
                                 ziel="ich" if termin["user_id"] in (None, user["id"]) else str(termin["user_id"]))
            elif termin is not None:
                werte.update(uhrzeit=termin["uhrzeit"] or "")
                if termin["status"] == "geparkt":
                    werte.update(wann="spaeter")
                elif termin["tag"] and termin["tag"] != heute_iso and not termin["flexibel"]:
                    werte.update(wann="tag", tag=termin["tag"])
    verlauf = []
    if aufgabe is not None:
        namen = {z["id"]: z["name"] for z in db.execute("SELECT id, name FROM users")}
        for h in db.execute("""SELECT * FROM aufgaben_historie WHERE aufgabe_id=?
                               ORDER BY id DESC""", (aufgabe["id"],)):
            verlauf.append({"alter_inhalt": h["alter_inhalt"],
                            "bis": utc_zu_lokal(h["geaendert_am"]),
                            "von": namen.get(h["geaendert_von"], "?")})
    hinweise = {"ich": "Landet auf deiner Liste."}
    for p in personen:
        hinweise[str(p["id"])] = f"{p['name']} bekommt eine Benachrichtigung."
    for wert, _name, text in gruppen:
        hinweise[wert] = text
    return {
        "user": user, "farbe": user["farbe"], "aufgabe": aufgabe, "werte": werte, "fehler": fehler,
        "personen": personen, "gruppen": gruppen, "sichten": sichten, "ist_eltern": ist_eltern(user),
        "wer_hinweis": hinweise.get(werte["ziel"], ""),
        "tag_min": (heute_d - timedelta(days=FENSTER_RUECK)).isoformat(),
        "tag_max": (heute_d + timedelta(days=FENSTER_VOR)).isoformat(),
        "verlauf": verlauf, "heute": heute_iso,
        "darf_loeschen": aufgabe is not None and darf_loeschen(user, aufgabe),
        "regel": aufgabe is not None and bool(aufgabe["regel_typ"]),
        "termin_id": termin["id"] if (termin is not None and aufgabe is not None and aufgabe["regel_typ"]) else None,
        "wochentage_kurz": WOCHENTAGE_KURZ,
    }


def _formular_lesen():
    f = request.form
    return {"inhalt": f.get("inhalt", ""), "ziel": f.get("ziel", "ich"), "wann": f.get("wann", "heute"),
            "tag": f.get("tag", ""), "uhrzeit": f.get("uhrzeit", ""), "sicht": f.get("sicht", "alle"),
            "punkte": f.get("punkte", "0"), "emoji": f.get("emoji", ""), "kachel": f.get("kachel", ""),
            "regel_typ": f.get("regel_typ", "wochentage"), "wochentage": f.getlist("wochentage"),
            "intervall": f.get("intervall", "3"), "umfang": f.get("umfang", "kuenftige"),
            "termin": f.get("termin", "")}


def _wann_aus(werte):
    if werte["wann"] == "tag":
        return werte["tag"] or "heute"
    if werte["wann"] == "spaeter":
        return "geparkt"
    return "heute"


def _ziel_aus(werte):
    """-> (ziel_user, ziel_gruppe)"""
    ziel = werte["ziel"] or "ich"
    if ziel.startswith("gruppe:"):
        return None, ziel.split(":", 1)[1]
    if ziel == "ich":
        return None, None
    return to_int(ziel), None


@bp.route("/a/aufgaben/neu", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/aufgaben/<token>/neu", methods=["GET", "POST"])
def neu(token):
    user = _user(token)
    _kein_kiosk(user)
    if not darf_anlegen(user):
        abort(403)
    db = get_db()
    if request.method == "GET":
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user))
    werte = _formular_lesen()
    ziel_user, ziel_gruppe = _ziel_aus(werte)
    regel = werte["wann"] == "regel"
    try:
        ergebnis = aufgabe_neu(
            db, user, werte["inhalt"], sicht=werte["sicht"], wann=_wann_aus(werte),
            uhrzeit=werte["uhrzeit"] or None, punkte=werte["punkte"], emoji=werte["emoji"],
            kachel=1 if werte["kachel"] else 0, ziel_user=ziel_user, ziel_gruppe=ziel_gruppe,
            regel_typ=werte["regel_typ"] if regel else None,
            regel_wochentage=werte["wochentage"] if regel else None,
            regel_intervall=werte["intervall"] if regel else None)
    except AufgabenFehler as e:
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, werte=werte, fehler=str(e))), 400
    if regel:
        vorschlaege_sicherstellen(db)
        return redirect(url_for("aufgaben_app.woche", token=token))
    if werte["wann"] == "spaeter":
        return redirect(url_for("aufgaben_app.spaeter", token=token) + f"#termin-{ergebnis['termin_id']}")
    return redirect(_heute_url(token, ziel_user, user, anker=ergebnis["termin_id"]))


@bp.route("/a/aufgaben/aufgabe/<int:aid>", defaults={"token": None}, methods=["GET", "POST"])
@bp.route("/a/aufgaben/<token>/aufgabe/<int:aid>", methods=["GET", "POST"])
def bearbeiten(token, aid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    if not darf_bearbeiten(user, aufgabe):
        abort(403)
    termin = _termin_der_aufgabe(db, aid)
    if aufgabe["regel_typ"]:
        # Aus der Woche kommt der eine Termin mit (?termin= bzw. Formularfeld)
        tid = to_int(request.args.get("termin") or request.form.get("termin"))
        termin = termin_sichtbar(db, user, tid) if tid else None
        if termin is not None and termin["aufgabe_id"] != aid:
            termin = None
    if request.method == "GET":
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, aufgabe, termin))
    werte = _formular_lesen()
    ziel_user, ziel_gruppe = _ziel_aus(werte)
    if aufgabe["regel_typ"]:
        try:
            if werte["umfang"] == "termin" and termin is not None:
                termin_einzeln_aendern(db, user, termin, inhalt=werte["inhalt"], ziel_user=ziel_user,
                                       wann=werte["tag"] or None, uhrzeit=werte["uhrzeit"] or None)
                tag_d = date.fromisoformat(werte["tag"] or termin["tag"] or heute_lokal())
                return redirect(_woche_url(token, montag_von(tag_d).isoformat()) + f"#termin-{termin['id']}")
            regel_aendern(db, user, aufgabe, inhalt=werte["inhalt"], ziel_user=ziel_user, ziel_gruppe=ziel_gruppe,
                          sicht=werte["sicht"], punkte=werte["punkte"], emoji=werte["emoji"],
                          kachel=1 if werte["kachel"] else 0,
                          regel_typ=werte["regel_typ"], regel_wochentage=werte["wochentage"],
                          regel_intervall=werte["intervall"])
        except AufgabenFehler as e:
            return render_template("aufgaben_formular.html", token=token,
                                   **_formular_kontext(db, user, aufgabe, termin, werte=werte,
                                                       fehler=str(e))), 400
        return redirect(url_for("aufgaben_app.woche", token=token))
    if werte["wann"] == "regel":
        werte["wann"] = "heute"      # einmalig -> regelmaessig gibt es nicht (neu anlegen)
    try:
        ergebnis = aufgabe_aendern(
            db, user, aufgabe, inhalt=werte["inhalt"], sicht=werte["sicht"], wann=_wann_aus(werte),
            uhrzeit=werte["uhrzeit"] or None, punkte=werte["punkte"], emoji=werte["emoji"],
            kachel=1 if werte["kachel"] else 0, ziel_user=ziel_user, ziel_gruppe=ziel_gruppe)
    except AufgabenFehler as e:
        return render_template("aufgaben_formular.html", token=token,
                               **_formular_kontext(db, user, aufgabe, termin, werte=werte,
                                                   fehler=str(e))), 400
    if werte["wann"] == "spaeter":
        return redirect(url_for("aufgaben_app.spaeter", token=token) + f"#termin-{ergebnis['termin_id']}")
    return redirect(_heute_url(token, ziel_user, user, anker=ergebnis["termin_id"]))


@bp.route("/a/aufgaben/aufgabe/<int:aid>/loeschen", defaults={"token": None}, methods=["POST"])
@bp.route("/a/aufgaben/<token>/aufgabe/<int:aid>/loeschen", methods=["POST"])
def loeschen(token, aid):
    user = _user(token)
    _kein_kiosk(user)
    db = get_db()
    aufgabe = aufgabe_sichtbar(db, user, aid)
    if aufgabe is None:
        abort(404)
    if not darf_loeschen(user, aufgabe):
        abort(403)
    aufgabe_loeschen(db, user, aufgabe)
    ziel = request.form.get("zurueck") or ""
    return redirect(ziel if ziel.startswith("/a/aufgaben") else url_for("aufgaben_app.heute", token=token))


def init_app(app):
    app.register_blueprint(bp)
