#!/usr/bin/env python3
"""Open kanban cards whose last comment says a message to a NAMED colleague was
withheld -- the items the per-person daily message budget keeps postponing.

Marci approved the weekly consolidated list on 2026-10-28 (Telegram 10890), after
asking what the backlog was (10887). The measured problem: when a card's marker
expires, the round checks whether a message already went to that colleague that day
and, if so, writes a new date instead of sending a second one. Nobody decides to
drop the item; it simply is never the most important thing that day. Card a1f94572
slipped four consecutive rounds that way (10-01, 10-08, 10-20, 10-27).

THE RECIPIENT IS READ FROM AN EXPLICIT MARKER, NOT INFERRED FROM PROSE, and that
is the whole point of this script. A line of its own in a card comment or in the
card description:

    VAR: David

Accepted names: David, Csucsu, Abel, Marci, Zoli (accents optional). The newest
marker wins, comments beat the description, exactly like the CSEND marker.

WHY NOT INFER IT, measured 2026-10-28 while building this: a regex over the card's
prose got the recipient WRONG, and three separate ways.
 1. The newest comment is often a ROUND REPORT copied onto many cards (15 such
    texts across 44 open cards that day), and it lists the daily message budget for
    EVERY colleague by name. On any card it sits on it looks like a blocker
    statement. That alone produced a fictitious 12-item "Zoli" group.
 2. Even on a card-specific comment, the budget sentence names people who are not
    the blocker: "Abel ma ot uzenetet kapott ..., Marci ..." matched as the blocker
    on 52ac3a11, whose actual blocker is an owner decision.
 3. Case split the groups ("David" vs "DAVID") until it was normalised.
A wrong recipient here is not a cosmetic bug: the line goes to the wrong colleague.
So the blocker is DECLARED, by whoever names it, and this script only reads it.

The round that names a blocker writes the marker; the kanban-audit skill says so.
A card with no marker is simply not on any list, which is the safe direction.
Usage:
  python3 scripts/visszatartott-tetelek.py            # human-readable, grouped
  python3 scripts/visszatartott-tetelek.py --json     # machine-readable
"""
import collections
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / 'store' / 'claudeclaw.db'

# Marker-only lines are not substantive; they must not count as the newest comment.
MARKER = re.compile(r'^\s*CSEND-\d{4}-\d{2}-\d{2}\s*[.)\]]?\s*$')

# The declared blocker. Alone on its own line, like the CSEND marker, so a mention
# inside running text can never be mistaken for a declaration.
VAR_SOR = re.compile(r'^\s*VAR:\s*([A-Za-z\u00c0-\u017f]+)\s*[.)\]]?\s*$', re.I)

# The declared state, for cards that are NOT waiting on a colleague. Alone on its own
# line, same shape as VAR. Without it a card counts as unclassified, and the point of
# the backfill (card b7e8265d) is to drive that count to zero, so that "not on the
# weekly list" means "declared not to belong there" instead of "nobody looked yet".
#   ALLAPOT: parkolt        -- the owner or the requester parked it, by name and date
#   ALLAPOT: sajat-munka    -- mine to do, nobody is waiting on an answer
#   ALLAPOT: nyilvantartas  -- a record with no action
#   ALLAPOT: esemeny        -- an event brings it back, no date to chase
ALLAPOT_SOR = re.compile(r'^\s*ALLAPOT:\s*([a-z\-]+)\s*[.)\]]?\s*$', re.I)
ALLAPOTOK = ('parkolt', 'sajat-munka', 'nyilvantartas', 'esemeny')

# Canonical spelling per lowercase key, so "DAVID" and "David" do not split groups.
KANONIKUS = {'david': 'David', 'd\u00e1vid': 'David', 'csucsu': 'Csucsu',
             'abel': '\u00c1bel', '\u00e1bel': '\u00c1bel',
             'marci': 'Marci', 'zoli': 'Zoli'}

# Who gets a weekly list. Marci asked for his own items in conversation instead
# (2026-10-28), and Zoli already has a weekly round of his own, so neither is
# mailed a list -- their items are reported, not sent.
CIMZETT = {
    'David': '8918812779',
    'Csucsu': '8238768700',
    '\u00c1bel': '8321555318',
}


def var_jelolo(con, card_id, description):
    """The declared blocker: newest marker-bearing comment wins, else description."""
    for r in con.execute(
            "SELECT content FROM kanban_comments WHERE card_id=? "
            "ORDER BY created_at DESC", (card_id,)):
        for sor in (r['content'] or '').split('\n'):
            m = VAR_SOR.match(sor)
            if m and m.group(1).lower() in KANONIKUS:
                return KANONIKUS[m.group(1).lower()], 'komment'
    for sor in (description or '').split('\n'):
        m = VAR_SOR.match(sor)
        if m and m.group(1).lower() in KANONIKUS:
            return KANONIKUS[m.group(1).lower()], 'leiras'
    return None, None


def allapot_jelolo(con, card_id, description):
    """The declared state: newest marker-bearing comment wins, else description."""
    for r in con.execute(
            "SELECT content FROM kanban_comments WHERE card_id=? "
            "ORDER BY created_at DESC", (card_id,)):
        for sor in (r['content'] or '').split('\n'):
            m = ALLAPOT_SOR.match(sor)
            if m and m.group(1).lower() in ALLAPOTOK:
                return m.group(1).lower()
    for sor in (description or '').split('\n'):
        m = ALLAPOT_SOR.match(sor)
        if m and m.group(1).lower() in ALLAPOTOK:
            return m.group(1).lower()
    return None


def deklaracio(con, card_id, description):
    """The card's current declaration: whichever marker is NEWEST wins.

    Both markers can sit on the same card, and an older one must not beat a newer
    one. Measured 2026-10-28 on c0f541ec: it carried `VAR: Marci` from the morning,
    then Marci decided and the card became our own work. The first version of this
    function checked VAR unconditionally before ALLAPOT, so the stale VAR won and
    the card stayed on Marci's list after he had answered. Same failure class as a
    card whose description and comments diverge: the layers must be ordered by TIME,
    not by type.

    Returns ('var', <nev>) or ('allapot', <allapot>) or (None, None).
    """
    for r in con.execute(
            "SELECT content FROM kanban_comments WHERE card_id=? "
            "ORDER BY created_at DESC", (card_id,)):
        for sor in (r['content'] or '').split('\n'):
            m = VAR_SOR.match(sor)
            if m and m.group(1).lower() in KANONIKUS:
                return 'var', KANONIKUS[m.group(1).lower()]
            m = ALLAPOT_SOR.match(sor)
            if m and m.group(1).lower() in ALLAPOTOK:
                return 'allapot', m.group(1).lower()
    for sor in (description or '').split('\n'):
        m = VAR_SOR.match(sor)
        if m and m.group(1).lower() in KANONIKUS:
            return 'var', KANONIKUS[m.group(1).lower()]
        m = ALLAPOT_SOR.match(sor)
        if m and m.group(1).lower() in ALLAPOTOK:
            return 'allapot', m.group(1).lower()
    return None, None


def lefedettseg():
    """How many open cards carry a declaration of either kind."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    szam = collections.Counter()
    osztalyozatlan = []
    for c in con.execute("SELECT id, title, status, description FROM kanban_cards "
                         "WHERE archived_at IS NULL AND status != 'done'"):
        fajta, ertek = deklaracio(con, c['id'], c['description'])
        if fajta:
            szam[fajta + ': ' + ertek] += 1
            continue
        szam['OSZTALYOZATLAN'] += 1
        osztalyozatlan.append((c['id'], c['status'], c['title']))
    return szam, osztalyozatlan


def gyujt():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    out = []
    for c in con.execute("SELECT id, title, status, description FROM kanban_cards "
                         "WHERE archived_at IS NULL AND status != 'done'"):
        fajta, nev = deklaracio(con, c['id'], c['description'])
        if fajta != 'var':
            continue
        honnan = var_jelolo(con, c['id'], c['description'])[1]
        out.append({
            'id': c['id'],
            'title': c['title'],
            'status': c['status'],
            'var': nev,
            'jelolo_helye': honnan,
            'chat_id': CIMZETT.get(nev),
        })
    out.sort(key=lambda x: (x['var'], x['title']))
    return out


def main():
    if '--lefedettseg' in sys.argv:
        szam, osztalyozatlan = lefedettseg()
        ossz = sum(szam.values())
        print(f'NYITOTT KARTYA: {ossz}')
        for k in sorted(szam):
            print(f'  {szam[k]:4}  {k}')
        if '--lista' in sys.argv:
            print('\nOSZTALYOZATLAN:')
            for cid, st, t in osztalyozatlan:
                print(f'  {cid[:10]:11} {st[:11]:12} {t[:76]}')
        return
    tetelek = gyujt()
    if '--json' in sys.argv:
        print(json.dumps(tetelek, ensure_ascii=False, indent=2))
        return
    if not tetelek:
        print('VISSZATARTOTT TETEL: 0')
        return
    print(f'VISSZATARTOTT TETEL: {len(tetelek)}')
    csoport = collections.OrderedDict()
    for t in tetelek:
        csoport.setdefault(t['var'], []).append(t)
    for nev, lst in csoport.items():
        cel = (f'-> lista megy, chat_id {CIMZETT[nev]}' if nev in CIMZETT
               else '-> NEM megy lista, szobeli')
        print(f'\n{nev} ({len(lst)}) {cel}')
        for i, t in enumerate(lst, 1):
            print(f'  {i}. [{t["id"]}] {t["title"]}  ({t["jelolo_helye"]})')


if __name__ == '__main__':
    main()
