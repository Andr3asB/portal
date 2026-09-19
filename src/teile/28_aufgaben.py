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
"""
from datetime import date, timedelta

from teile.kern import emoji_grafik_vorhanden, heute_lokal, push_send, to_int

APP = "aufgaben"

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
                      aufgabe_id=None, termin_id=None, frei=False):
    """Die Termine, die `user` sehen darf - mit optionalen Filtern.

    von/bis: Familientag ISO (inklusiv); status: str oder Folge;
    user_id: nur Termine dieser Person; frei=True: nur Termine ohne Person
    (Gruppenaufgaben, "Noch zu haben"). Sortiert nach Tag, Uhrzeit, id."""
    bedingung, params = _sicht_sql(user)
    where = [bedingung]
    if von is not None:
        where.append("t.tag >= ?"); params.append(von)
    if bis is not None:
        where.append("t.tag <= ?"); params.append(bis)
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
    inhalt = (inhalt or "").strip()[:INHALT_MAX]
    if not inhalt:
        raise AufgabenFehler("Was ist zu tun? Der Text fehlt.")
    heute_iso = heute or heute_lokal()
    heute_d = date.fromisoformat(heute_iso)

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
