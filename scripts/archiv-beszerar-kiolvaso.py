#!/usr/bin/env python3
"""Kiolvassa a szallitoi szamlakrol a TETELES EGYSEGARAT, formatumonkent kulon kezelessel.

ELOZMENY: scripts/archiv-cikkszam-lefedes.py megmondja, MELYIK szamlan van benne egy cikkszam.
Ez a szkript a talalati SORBOL/BLOKKBOL kiolvassa a netto egysegarat, hogy a Next-ben rogzitett
Dev.beszer.ar ELLENORIZHETO legyen.

NINCS EGYETLEN UNIVERZALIS SZABALY. Merve 2026-10-07: a "sor vegen allo utolso szam" heurisztika
CSAK a GT Company francia elrendezesen mukodik. A Dorr tombos (soronkent egy mezo), a K&F
proforma a $-t a szam MOGE irja es vesszos tizedest hasznal, a Transcontinenta (Cullmann) pedig
teljesen osszeragadt szamokat ad. Ezert formatumonkent kulon kezelo van, es amire nincs kezelo,
arra NEM talalunk ki szamot.

HAROM MERT CSAPDA:
1. RESZSZTRING-HAMIS TALALAT: az "AG-APF700" torzse (APF700) RESZE az "APF700WIFI"-nek, tehat a
   WIFI-s sor 37,50-es ara ment volna a nem-WIFI-s tetelre (Next: 29). Javitas: egy soron belul
   csak a MAXIMALIS illeszkedes ervenyes.
2. NEM-SZAMLA DOKUMENTUM: a "Statement of Account" es a "Credit Mutuel" utalasi lista szamai
   harom hamis eltérést adtak. Ezeket nevbol ki kell szurni.
3. A GTC-sornal a MENNYISEG es a REFERENCIA ossze van ragadva ("300.00APF700WIFI"), ezert a
   mennyiseg nem olvashato ki biztonsagosan, az egysegar (a sor vegen allo ket szam kozul az
   utolso, a P.U. Net) viszont igen.
"""
import glob, json, os, re, sys
import pypdf, openpyxl

ARCH = '/mnt/kozos/PÉNZÜGY/Számla Archív'
XLSX = 'store/mm-beszerar/MediaMarkt_eladasok_2026-10-07.xlsx'
FUL = 'Tételenkénti lista'
NEMSZAMLA = re.compile(r'Statement of Account|Credit Mutuel|Egyenleg|Relance|Reminder', re.I)
GTC = re.compile(r'GTC|GT.?Company|Fac_', re.I)

norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())

def oldalak(p):
    return '\n'.join((pg.extract_text() or '') for pg in pypdf.PdfReader(p).pages)

def torzs(c):
    m = re.match(r'^([A-Z]{1,3})-?(.+)$', str(c).strip().upper())
    r = norm(m.group(2)) if m else ''
    return r if len(r) >= 5 else None

def sorvegi_ar(sor):
    """GTC/francia elrendezes: a sor vegen a P.U. HT es a P.U. Net all, az utolso kell."""
    sz = re.findall(r'(?<![\d.,])(\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)(?![\d])', sor)
    if len(sz) < 2: return None
    v = sz[-1].replace(' ', '').replace(' ', '').replace(',', '.')
    try:
        f = float(v)
    except ValueError:
        return None
    return f if f > 0 else None

def gtc_arak(cikk):
    """GT Company szamlak: egy sor = egy tetel, a sor vegen az egysegar."""
    tmap = {}
    for c in cikk:
        for k in filter(None, (torzs(c), norm(c))): tmap.setdefault(k, []).append(c)
    lef = json.load(open('store/mm-beszerar/archiv_cikkszam_lefedes.json'))
    out = {}
    for rel in lef['fajlonkent']:
        nev = os.path.basename(rel)
        if not GTC.search(nev) or NEMSZAMLA.search(nev): continue
        try: t = oldalak(os.path.join(ARCH, rel))
        except Exception: continue
        for sor in t.split('\n'):
            tiszta = norm(sor)
            if len(tiszta) < 5: continue
            ill = [k for k in tmap if k in tiszta]
            if not ill: continue
            ill = [k for k in ill if not any(k != u and k in u for u in ill)]
            ar = sorvegi_ar(sor)
            if ar is None: continue
            for k in ill:
                for c in tmap[k]:
                    out.setdefault(c, []).append({'ar': round(ar, 2), 'fajl': rel,
                                                  'formatum': 'GTC', 'sor': sor.strip()[:150]})
    return out

def dorr_arak(cikk):
    """Dorr szamlak: tombos elrendezes. Rendelesi szam, megnevezes, MENNYISEG, 'STK', AR, afa, osszeg.
    Ellenorizve nyers blokkon: 12 x 1,85 = 22,20."""
    stem = {}
    for c in cikk:
        stem.setdefault(norm(c[1:]) if c.upper().startswith('D') else norm(c), c)
    out = {}
    for p in sorted(glob.glob(f'{ARCH}/*/Dörr_*.pdf')):
        try: s = oldalak(p).split('\n')
        except Exception: continue
        rel = os.path.relpath(p, ARCH)
        for i, x in enumerate(s):
            c = stem.get(norm(x))
            if not c: continue
            for j in range(i+1, min(i+10, len(s))):
                if s[j].strip().upper() in ('STK', 'PCS', 'PAA', 'SET'):
                    for m in range(j+1, min(j+3, len(s))):
                        v = s[m].strip().replace(',', '.')
                        if re.fullmatch(r'\d+(\.\d{1,3})?', v) and float(v) > 0:
                            out.setdefault(c, []).append({'ar': round(float(v), 2), 'fajl': rel,
                                                          'formatum': 'Dörr', 'sor': x.strip()})
                            break
                    break
    return out

def main():
    w = openpyxl.load_workbook(XLSX, data_only=True)[FUL]
    cikk, nx = [], {}
    for r in w.iter_rows(min_row=2, values_only=True):
        if not r[0]: continue
        c = str(r[0]).strip(); cikk.append(c); nx[c] = (r[4], r[5])
    out = gtc_arak(cikk)
    for c, v in dorr_arak(cikk).items(): out.setdefault(c, []).extend(v)
    eq = el = 0
    for c, v in out.items():
        n = nx[c][0]; arak = sorted({x['ar'] for x in v})
        if isinstance(n, (int, float)) and any(abs(a-n) <= max(0.02, 0.01*n) for a in arak): eq += 1
        else: el += 1
    print(f'cikkszam szamlas arral: {len(out)} / {len(cikk)}')
    print(f'Next-tel EGYEZIK: {eq} | ELTER: {el}')
    json.dump(out, open('store/mm-beszerar/archiv_beszerar.json', 'w'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    main()
