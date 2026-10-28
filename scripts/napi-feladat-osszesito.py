#!/usr/bin/env python3
"""Napi feladat-összesítő a PDB kollégáknak, emailben.

David kérése, 2026-10-15 (Telegram 9786 1. pont, majd 9796, 9799, 9801, 9804):
  - "a nyitott feladatokról minden felelős kapjon összesítőt"
  - "Mindenkinek emailben a sajátjára! ... Napi 1x, reggel, 8:01-kor"
  - "MIndenki kapja meg a sajátját, Zoli pedig mindenkiét"
  - "Ügynök feladatokról nem kell levelezni"
  - "Ha nincs feladata akkor csak azt, hogy jelenleg nincs feladata, így tudjuk hogy
    műkdöik a rendszer"
  - "Egyenlőre senki ne kapjon holnap még. ... SZólok ha kezdődhet a levélküldés"

EZÉRT A KÜLDÉS ALAPBÓL KI VAN KAPCSOLVA. A szkript próba-módban fut, és csak a
`--kuldes` kapcsolóval küld bármit. Ez nem kényelmi kérdés: David kimondta, hogy
addig senki ne kapjon levelet, amíg nem szól, és egy ütemezett kör könnyen
elindítaná a küldést egy véletlen paraméterrel.

HATÓKÖR: David a 2026-10-15 12:14-es körben NEM döntötte el, hogy a levél a
PARTNERHEZ KÖTÖTT feladatokról szóljon-e, vagy MINDEN nyitott feladatról. A
default az `osszes`, és ez KIMONDOTT FELTEVÉS, nem mérés: partner-hatókörrel ma
öt emberből négynek üres levél menne, ami pont azt nem mutatná meg, hogy a
rendszer működik. A `--hatokor partner` alak a másik olvasatot adja.

Használat:
  python3 scripts/napi-feladat-osszesito.py                      # proba, mind az ot ember
  python3 scripts/napi-feladat-osszesito.py --cim david.bajcsi@pdb.hu
  python3 scripts/napi-feladat-osszesito.py --hatokor partner
  python3 scripts/napi-feladat-osszesito.py --kuldes             # ELES kuldes, csak engedellyel
"""
import argparse
import datetime as dt
import sqlite3
import subprocess
import sys

DB = '/home/pdb/marveen/store/claudeclaw.db'

# A cimek a store/verified-recipients.json-ban allnak forrassal (David megerositese,
# Telegram 9799, 2026-10-15), es mindegyik egyezik a megfelelo .m365 kulcsfajl
# MAILBOX soraval. Itt a felelos-kulcs -> cim parositas van, semmi tobb.
EMBEREK = [
    ('david', 'david.bajcsi@pdb.hu', 'Dávid'),
    ('abel', 'abel.kondics@pdb.hu', 'Ábel'),
    ('marci', 'marketing@pdb.hu', 'Marci'),
    ('csucsu', 'csucsu@pdb.hu', 'Csucsu'),
    ('zoli', 'palvolgyi@pdb.hu', 'Zoli'),
]
ZOLI_CIM = 'palvolgyi@pdb.hu'

STATUSZ = {'planned': 'tervezett', 'in_progress': 'folyamatban', 'waiting': 'várakozik'}


def tetelek(cur, felelos: str, hatokor: str):
    q = ("SELECT k.id, k.title, k.status, k.due_date, p.name AS partner "
         "FROM kanban_cards k LEFT JOIN partners p ON p.id = k.partner_id "
         "WHERE k.assignee = ? AND k.archived_at IS NULL AND k.status != 'done'")
    if hatokor == 'partner':
        q += " AND k.partner_id IS NOT NULL"
    q += " ORDER BY (k.due_date IS NULL) ASC, k.due_date ASC, k.created_at ASC"
    return cur.execute(q, (felelos,)).fetchall()


def datum_cimke(due: str | None, ma: dt.date) -> str:
    if not due:
        return 'határidő nélkül'
    try:
        d = dt.date.fromisoformat(due)
    except ValueError:
        return 'határidő nélkül'
    nap = (d - ma).days
    if nap < 0:
        return f'{-nap} napja lejárt ({due})'
    if nap == 0:
        return f'MA esedékes ({due})'
    if nap == 1:
        return f'holnap ({due})'
    return due


def sorok(rows, ma) -> list[str]:
    ki = []
    for r in rows:
        p = f' [{r["partner"]}]' if r['partner'] else ''
        ki.append(f'- {r["title"]}{p}')
        ki.append(f'  {STATUSZ.get(r["status"], r["status"])}, {datum_cimke(r["due_date"], ma)}')
    return ki


def torzs(nev: str, rows, ma, masok=None) -> str:
    if rows:
        t = [f'Szia {nev},', '', f'{len(rows)} nyitott feladatod van:', '']
        t += sorok(rows, ma)
    else:
        t = [f'Szia {nev},', '', 'Jelenleg nincs nyitott feladatod.']
    if masok is not None:
        t += ['', '---', '', 'A többiek nyitott feladatai:']
        for nev2, rows2 in masok:
            t += ['', f'{nev2}: {len(rows2) if rows2 else "nincs nyitott feladat"}'
                  + (' nyitott feladat' if rows2 else '')]
            t += ['  ' + s for s in sorok(rows2, ma)]
    t += ['', 'A listát a CRM nyitott feladataiból állítottam össze.']
    return '\n'.join(t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hatokor', choices=['osszes', 'partner'], default='osszes')
    ap.add_argument('--cim', help='csak ez az egy cimzett')
    ap.add_argument('--kuldes', action='store_true',
                    help='ELES kuldes. Enelkul csak kiirja, amit kuldene.')
    a = ap.parse_args()

    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    cur = c.cursor()
    ma = dt.date.today()
    targy = f'Nyitott feladatok, {ma.isoformat()}'

    osszes = [(kulcs, cim, nev, tetelek(cur, kulcs, a.hatokor)) for kulcs, cim, nev in EMBEREK]
    masok = [(nev, rows) for kulcs, cim, nev, rows in osszes if kulcs != 'zoli']

    for kulcs, cim, nev, rows in osszes:
        if a.cim and cim != a.cim:
            continue
        test = torzs(nev, rows, ma, masok if cim == ZOLI_CIM else None)
        print('=' * 72)
        print(f'CIMZETT: {cim}  ({nev}, felelos-kulcs: {kulcs}, hatokor: {a.hatokor})')
        print(f'TARGY:   {targy}')
        print('-' * 72)
        print(test)
        if a.kuldes:
            p = subprocess.run(
                ['npx', 'tsx', 'scripts/graph-mail.ts', 'send', '--signature', 'hu',
                 '--to', cim, '--subject', targy, '--body', '-'],
                input=test, text=True, capture_output=True,
                cwd='/home/pdb/marveen',
                env={**__import__('os').environ,
                     'MARVEEN_MAIL_CREDS': '/home/pdb/marveen/store/.m365-innova-credentials'})
            print(f'[KULDES] exit={p.returncode} {p.stdout.strip()[:120]} {p.stderr.strip()[:200]}')
    if not a.kuldes:
        print('=' * 72)
        print('PROBA-MOD: semmi nem ment ki. Eles kuldeshez --kuldes kell, ES David engedelye.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
