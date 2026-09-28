#!/usr/bin/env python3
"""Leiratkozasi lanc allapot-olvaso (Marci kerese, 2026-09-25 13:36, msg 7400).

A lanc lepesei megvoltak kulon-kulon, de nem volt olyan futtathato folyamat, ami
sorban vegigviszi oket es megall, ha egy visszaolvasas nem igazol. Ez a script a
kovetes fele: kiolvassa, MELYIK kerelemnel MELYIK lepes a soron kovetkezo, es mi
akadt be. Nem ir semmit es nem hivja meg a kulso API-kat -- azt az ugynok teszi.

Allapot-tarolo: kanban kartya kerelmenkent, cim "LEIRATKOZAS: <email>".
A lepeseket a kommentek jelolik, soronkent:

    LEIRATKOZAS-LEPES: <lepes>=<allapot> [szabad szoveg]

  lepes   : cel | unas | mailerlite | level
  allapot : ok | fail | pending | skip

A LEGUTOLJARA IRT marker nyer lepesenkent (ugyanaz a szabaly, mint a CSEND-nel).
A "skip" akkor helyes, ha a cim az adott rendszerben nem szerepelt -- a lanc
attol meg vegigmegy, mert a level allitasa igy is igaz marad.

Kimenet: soronkent egy kerelem, a soron kovetkezo lepessel. Ures kimenet = nincs
nyitott leiratkozas.
"""
import re
import sqlite3
import sys
import time

DB = "/home/pdb/marveen/store/claudeclaw.db"
LEPESEK = ["cel", "unas", "mailerlite", "level"]
MARKER = re.compile(r"LEIRATKOZAS-LEPES:\s*(cel|unas|mailerlite|level)\s*=\s*(ok|fail|pending|skip)", re.I)

# Ennyi ora utan tekintjuk beakadtnak a tarsugynoknek kiadott lepest. Nem
# onkenyes: Sam es Marti is percekben valaszol, ha fut; 4 ora mar azt jelenti,
# hogy vagy all az ugynok, vagy elveszett az uzenet.
BEAKADT_ORA = 4


def allapotok(cur, card_id):
    """Lepesenkent a LEGUTOLJARA irt marker allapota es ideje."""
    out = {}
    rows = cur.execute(
        "SELECT content, created_at FROM kanban_comments WHERE card_id=? ORDER BY created_at",
        (card_id,)).fetchall()
    for content, ts in rows:
        for m in MARKER.finditer(content or ""):
            out[m.group(1).lower()] = (m.group(2).lower(), ts)
    return out


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    now = int(time.time())
    cards = cur.execute(
        "SELECT id, title, status, updated_at FROM kanban_cards "
        "WHERE title LIKE 'LEIRATKOZAS: %' AND status != 'done' AND archived_at IS NULL "
        "ORDER BY created_at").fetchall()
    for cid, title, status, upd in cards:
        st = allapotok(cur, cid)
        kovetkezo, gond = None, []
        for lepes in LEPESEK:
            allapot, ts = st.get(lepes, (None, None))
            if allapot in ("ok", "skip"):
                continue
            if allapot == "fail":
                gond.append(f"{lepes}=FAIL")
                kovetkezo = lepes
                break
            if allapot == "pending":
                ora = (now - (ts or now)) / 3600.0
                if ora >= BEAKADT_ORA:
                    gond.append(f"{lepes} {ora:.1f} oraja pending")
                kovetkezo = lepes
                break
            kovetkezo = lepes            # nincs marker: ez a soron kovetkezo
            break
        if kovetkezo is None:
            print(f"{cid[:8]}  {title}  -> MINDEN LEPES KESZ, a kartya lezarhato (status=done)")
        else:
            jel = ("  [" + "; ".join(gond) + "]") if gond else ""
            print(f"{cid[:8]}  {title}  -> kovetkezo lepes: {kovetkezo}{jel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
