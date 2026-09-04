#!/usr/bin/env python3
"""Tudunk-e mar errol? Egy kereses a SAJAT feljegyzeseinken, mielott kerdezel vagy allitasz.

MIERT LETEZIK: 2026-09-02-an ot kulon alkalommal allitottam vagy kerdeztem olyat, aminek a
valasza mar le volt irva nalunk (a GitHub token a szefben, egy kartya sajat leirasaban a dontes,
egy skill sajat szovegeben a hipotezis). A baj nem az volt, hogy nincs leirva. Az, hogy nem
neztem meg, mielott beszeltem. Ez a szkript teszi olcsova a megnezest.

Hasznalat:
    python3 scripts/tudunk-e-rola.py "github token"
    python3 scripts/tudunk-e-rola.py leiratkozas mailerlite
"""
import os, re, sqlite3, sys, unicodedata

GYOKER = '/home/pdb/marveen'
HELYEK = [
    ('memoria-fajl', os.path.expanduser('~/.claude/projects/-home-pdb-marveen/memory')),
    ('skill',        os.path.expanduser('~/.claude/skills')),
    ('utemezett',    os.path.expanduser('~/.claude/scheduled-tasks')),
]

def ekezettelen(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower())
                   if unicodedata.category(c) != 'Mn')

def talalatok_fajlokban(kifejezesek):
    ki = []
    for cimke, gyoker in HELYEK:
        if not os.path.isdir(gyoker):
            continue
        for tovabb, _, fajlok in os.walk(gyoker):
            for f in fajlok:
                if not f.endswith('.md'):
                    continue
                ut = os.path.join(tovabb, f)
                try:
                    sorok = open(ut, encoding='utf-8', errors='replace').read().splitlines()
                except OSError:
                    continue
                for i, sor in enumerate(sorok, 1):
                    n = ekezettelen(sor)
                    if all(k in n for k in kifejezesek):
                        ki.append((cimke, os.path.relpath(ut, os.path.expanduser('~')), i, sor.strip()[:160]))
    return ki

def talalatok_kartyakon(kifejezesek):
    ki = []
    db = os.path.join(GYOKER, 'store/claudeclaw.db')
    if not os.path.exists(db):
        return ki
    c = sqlite3.connect(db).cursor()
    c.execute("SELECT id,title,COALESCE(description,'') FROM kanban_cards WHERE archived_at IS NULL")
    for cid, cim, leiras in c.fetchall():
        for mezo, szoveg in (('cim', cim), ('leiras', leiras)):
            n = ekezettelen(szoveg)
            if all(k in n for k in kifejezesek):
                ki.append(('kartya-' + mezo, cid[:8], 0, szoveg.strip()[:160]))
                break
    c.execute("""SELECT card_id,content FROM kanban_comments ORDER BY created_at DESC LIMIT 400""")
    for cid, tartalom in c.fetchall():
        n = ekezettelen(tartalom)
        if all(k in n for k in kifejezesek):
            ki.append(('kartya-komment', cid[:8], 0, tartalom.strip().replace('\n', ' ')[:160]))
    return ki

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    kif = [ekezettelen(a) for a in sys.argv[1:]]
    ki = talalatok_fajlokban(kif) + talalatok_kartyakon(kif)
    if not ki:
        print(f"NINCS TALALAT erre: {' + '.join(sys.argv[1:])}")
        print("Ez NEM bizonyitja, hogy nem tudunk rola. Csak azt, hogy ezekkel a szavakkal nincs leirva.")
        return 1
    print(f"{len(ki)} TALALAT erre: {' + '.join(sys.argv[1:])}\n")
    for cimke, hol, sor, szoveg in ki[:25]:
        hely = f"{hol}:{sor}" if sor else hol
        print(f"  [{cimke}] {hely}\n      {szoveg}")
    if len(ki) > 25:
        print(f"\n  ... es meg {len(ki)-25} talalat.")
    return 0

if __name__ == '__main__':
    sys.exit(main())
