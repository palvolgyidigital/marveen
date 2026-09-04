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
# A csatorna-tulajdonos MEGJELENITETT neve. A gate uzenetebe ez kerul, mert egy
# chat_id-t senki nem ismer fel ranezesre, egy nevet igen.
NEV = {
    '8668856531': 'Marci',
    '8616857946': 'Zoli',
    '8918812779': 'David',
    '8321555318': 'Abel',
    '8238768700': 'Csucsu',
    '6871312283': 'Monika',
}
# A masodik szint (lassito) alsó hosszkorlatja. MERT ERTEK, nem tipp: a sajat
# kimeno naplon (conversation_log, direction=out, 2037 sor) a "nincs megszolitas
# + mas tulajdonos nevet emliti + cimzett-valtas" szabaly 10.8%-ot jelolne meg,
# 600 karakter folott viszont 7.2%-ot, es a hibaosztaly (hosszu, szemelyre szolo
# osszefoglalo rossz csatornan) a hosszu vegen ul.
LASSITO_MIN_HOSSZ = 600

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

def cimzett_neve(chat_id):
    """A chat_id tulajdonosanak megjelenitett neve, vagy None ha ismeretlen csatorna."""
    return NEV.get(str(chat_id))


def emlitett_tulajok(chat_id, szoveg):
    """Mely MAS csatorna-tulajdonos neve szerepel a szovegben. [(chat_id, nev)]."""
    e = ekezettelen(szoveg or '')
    talalat = []
    for cid, nevek in TULAJ.items():
        if str(cid) == str(chat_id):
            continue
        for n in nevek:
            if re.search(r'\b' + re.escape(n) + r'\b', e):
                talalat.append((cid, NEV.get(cid, n)))
                break
    return talalat


def lassito(chat_id, szoveg):
    """MASODIK SZINT. Nem allit hibat, mert nincs mibol: ha a szoveg nem szolit
    meg senkit, akkor NINCS ellentmondas a cimzettel, csak hianyzik a jel.

    MIERT KELL: 2026-09-04-en egy Zolinak szant osszefoglalo Marci csatornajara
    ment. A szoveg helyes volt, a cimzett rossz, es megszolitas hijan az elso
    szintu kapunak nem volt mit osszevetnie -- helyesen engedte at. Egy okosabb
    szovegelemzes sem fogta volna meg: a szovegben David neve szerepelt, tehat
    egy "emlitett nev" heurisztika egy HARMADIK emberre mutatott volna.

    EZERT NEM AZONOSITUNK, CSAK MEGALLITUNK EGYSZER: kiirjuk, KINEK a csatornaja
    ez (nev szerint), es hogy a szoveg kinek a nevet emlegeti. A dontes a
    kuldoe; a valtozatlan ujrakuldes atmegy.

    Visszaad: (cimzett_nev, [(chat_id, nev), ...]) vagy None.
    """
    szoveg = szoveg or ''
    if megszolitott_nev(szoveg):
        return None  # van megszolitas: az elso szintu kapu mar dontott rola
    if len(szoveg.strip()) < LASSITO_MIN_HOSSZ:
        return None
    cim = cimzett_neve(chat_id)
    if not cim:
        return None  # ismeretlen csatorna: nincs nev, amit szembe lehetne tenni
    emlitett = emlitett_tulajok(chat_id, szoveg)
    if not emlitett:
        return None
    return (cim, emlitett)


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
