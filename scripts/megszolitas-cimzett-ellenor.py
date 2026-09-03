#!/usr/bin/env python3
"""Megszolitas kontra cimzett: elkapja, ha a szoveg mas nevet szolit meg, mint akinek kuldjuk.

MIERT LETEZIK: 2026-08-31-en harom egymast koveto uzenet ment ki "Szia Zoli" megszolitassal
Abel csatornajara. Nem a routing volt rossz onmagaban: a SZOVEG es a CIMZETT mondott mast.
Negyvenot percig eszrevetlen maradt, es csak azert derult ki, mert Abel szolt ("en nem Zoli
vagyok"). Egy gep ezt egy pillanat alatt eszreveszi, egy ember nem feltetlenul.

Hasznalat:
    python3 scripts/megszolitas-cimzett-ellenor.py <chat_id> <szoveg-fajl>
    ... | python3 scripts/megszolitas-cimzett-ellenor.py <chat_id> -
    python3 scripts/megszolitas-cimzett-ellenor.py --onteszt     # a teljes naplon meri a talalatokat
"""
import re, sqlite3, sys, unicodedata

# A csatorna-tulajdonosok. Egy nev tobb alakban is elofordulhat.
TULAJ = {
    '8668856531': ['marci', 'marcell', 'muller'],
    '8616857946': ['zoli', 'zoltan', 'palvolgyi'],
    '8918812779': ['david', 'dave', 'bajcsi'],
    '8321555318': ['abel', 'kondics'],
    '8238768700': ['csucsu', 'jozsef', 'pasztor'],
    '6871312283': ['monika', 'moni'],
}
# Csak ezeket tekintjuk megszolitasnak, es CSAK a szoveg elejen.
KOSZONES = r'(?:szia|kedves|hello|hali|udv|udvozollek|jo reggelt|jo napot|jo estet)'

def ekezettelen(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower())
                   if unicodedata.category(c) != 'Mn')

def megszolitott_nev(szoveg):
    """A szoveg ELSO 80 karakterebol adja vissza a megszolitott nevet, vagy None-t."""
    eleje = ekezettelen(szoveg.strip())[:80]
    # CSAK valodi megszolitas szamit: "Szia Zoli" vagy "Szia, Zoli".
    # A "Szia! Marci keresere..." NEM az: ott a koszones ! vagy . jellel LEZARUL,
    # es a kovetkezo szo mar uj mondat. Ez a ket eset kulonbozteti meg oket, es
    # ezen a kulonbsegen bukott el az elso valtozatom ket hamis talalattal.
    if re.match(rf'^{KOSZONES}\s*[!.]', eleje):
        return None
    m = re.match(rf'^{KOSZONES}[\s,]+([a-z]+)', eleje)
    return m.group(1) if m else None

def ellenoriz(chat_id, szoveg):
    nev = megszolitott_nev(szoveg)
    if not nev:
        return None
    sajat = TULAJ.get(str(chat_id), [])
    if nev in sajat:
        return None
    # Csak akkor jelzunk, ha a nev EGY MASIK ismert csatorna tulajdonosa.
    for cid, nevek in TULAJ.items():
        if nev in nevek and cid != str(chat_id):
            return (nev, cid)
    return None

def onteszt():
    c = sqlite3.connect('/home/pdb/marveen/store/claudeclaw.db').cursor()
    c.execute("SELECT id,chat_id,ts,text FROM conversation_log WHERE direction='out'")
    sorok = c.fetchall()
    talalat = []
    for i, cid, ts, szoveg in sorok:
        r = ellenoriz(cid, szoveg or '')
        if r:
            talalat.append((i, cid, ts, r[0], r[1], (szoveg or '').strip().replace('\n', ' ')[:80]))
    print(f"atvizsgalt kimeno uzenet: {len(sorok)}")
    print(f"JELZETT: {len(talalat)}\n")
    for i, cid, ts, nev, helyes, elonezet in talalat:
        print(f"  #{i} {ts} | kuldve: {cid} | megszolitva: {nev} (az o csatornaja: {helyes})")
        print(f"      {elonezet}")
    return talalat

def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--onteszt':
        onteszt()
        return 0
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    chat_id, forras = sys.argv[1], sys.argv[2]
    szoveg = sys.stdin.read() if forras == '-' else open(forras, encoding='utf-8').read()
    r = ellenoriz(chat_id, szoveg)
    if r:
        nev, helyes = r
        print(f"NE KULDD EL. A szoveg '{nev}'-t szolitja meg, de a cimzett {chat_id}.")
        print(f"'{nev}' csatornaja: {helyes}. Vagy a cimzettet javitsd, vagy a megszolitast.")
        return 1
    print("rendben: a megszolitas es a cimzett nem mond ellent")
    return 0

if __name__ == '__main__':
    sys.exit(main())
