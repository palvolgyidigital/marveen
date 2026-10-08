#!/usr/bin/env python3
"""Megmeri, hogy egy cikkszam-lista tetelei megjelennek-e a kozos PENZUGY szamla-archivumban.

MIERT: a Next-ben rogzitett beszerar ELLENORZESEHEZ a szallito vegszamlaja kell. A
/mnt/kozos/PÉNZÜGY/Számla Archív evenkenti mappaiban a fajlnev SZALLITO_DATUM_SZAMLASZAM
semat kovet, tehat a szallitoi es a vevoi szamla a NEVBOL szetvalaszthato.

KULCSKEPZES (merve 2026-10-07): a sajat "Gyartoi cikkszam" nem azonos a szallito
szamlajan allo kodddal, de a torzse igen. A DORR D306246 a szallitonal 306246, a KODAK
KO-9891161 a GT Company szamlajan 9891161. Ezert minden cikkszamra KETFELE mintat
keresunk: a teljes normalizalt alakot, es az 1-3 betus markajelzo elotag nelkulit, ha
a maradek legalabb 5 karakter (ennel rovidebb szam alaposan hamis talalatot ad).
"""
import glob, json, os, re, sys, time
import pypdf, openpyxl

XLSX = sys.argv[1] if len(sys.argv) > 1 else 'store/mm-beszerar/MediaMarkt_eladasok_2026-10-07.xlsx'
FUL = sys.argv[2] if len(sys.argv) > 2 else 'Tételenkénti lista'
ARCH = '/mnt/kozos/PÉNZÜGY/Számla Archív'
EVEK = ('2025', '2026')

VEVO = re.compile(r'Auchan|Corwell|media.?markt|Pepita|Emag|Lidl|Vöröskő|Ipon|Alza|Praktiker|'
                  r'eDigital|Zupp|Reményi|Webshippy|Foxpost|GLS|DPD|Telekom|MOL|Microsoft|'
                  r'Google|Meta|OpenAI|Anthropic|OTP|Fundamenta|Euroleasing|Hermes', re.I)
SZALLITO = re.compile(r'GTC|GT.?Company|^Fac_|KFConcept|K&F|ZhuoLian|Zhu|Zjuan|Vijim|Ulanzi|'
                      r'Dörr|Rollei|Jos\.Schneider|Transcontinenta|Kandao|Cullmann|Lenspen|'
                      r'Agfa|Kodak|Synco|Herma|Sunpak|Hunicorn|LCDeal|Assemblabs', re.I)

norm = lambda x: re.sub(r'[^A-Z0-9]', '', str(x).upper())

def kulcsok(cikkszamok):
    k = []
    for c in cikkszamok:
        k.append((norm(c), c))
        m = re.match(r'^([A-Z]{1,3})-?(.+)$', str(c).strip().upper())
        if m and len(norm(m.group(2))) >= 5:
            k.append((norm(m.group(2)), c))
    return k

def main():
    s = openpyxl.load_workbook(XLSX, data_only=True)[FUL]
    cikk = [str(r[0]).strip() for r in s.iter_rows(min_row=2, values_only=True) if r[0]]
    k = kulcsok(cikk)
    fajlok = sorted(p for y in EVEK for p in glob.glob(f'{ARCH}/{y}/*.pdf'))
    print(f'cikkszam={len(cikk)} minta={len(k)} fajl={len(fajlok)}', flush=True)
    tal, hiba, t0 = {}, [], time.time()
    for i, p in enumerate(fajlok):
        try:
            t = norm('\n'.join((pg.extract_text() or '') for pg in pypdf.PdfReader(p).pages))
        except Exception as e:
            hiba.append((os.path.basename(p), str(e)[:60])); continue
        if len(t) < 50:
            hiba.append((os.path.basename(p), 'nincs szovegreteg (scan?)')); continue
        h = sorted({c for kk, c in k if kk in t})
        if h: tal[os.path.relpath(p, ARCH)] = h
        if i and i % 200 == 0: print(f'  {i}/{len(fajlok)} {time.time()-t0:.0f}s', flush=True)
    oldal = lambda p: os.path.basename(p)
    sz = sorted({c for p, h in tal.items() if SZALLITO.search(oldal(p)) for c in h})
    ve = sorted({c for p, h in tal.items() if not SZALLITO.search(oldal(p)) and VEVO.search(oldal(p)) for c in h})
    eg = sorted({c for p, h in tal.items() if not SZALLITO.search(oldal(p)) and not VEVO.search(oldal(p)) for c in h})
    print(f'\nolvashatatlan/scan: {len(hiba)}')
    print(f'fajl talalattal: {len(tal)}')
    print(f'SZALLITOI szamlan: {len(sz)}/{len(cikk)} ({100*len(sz)/len(cikk):.0f}%)')
    print(f'csak VEVOI szamlan: {len(set(ve)-set(sz))}  |  egyeb/besorolatlan: {len(set(eg)-set(sz))}')
    json.dump({'szallitoi': sz, 'vevoi': ve, 'egyeb': eg, 'fajlonkent': tal,
               'olvashatatlan': hiba}, open('store/mm-beszerar/archiv_cikkszam_lefedes.json', 'w'),
              ensure_ascii=False, indent=1)
    import collections
    gy = json.load(open('store/mm-beszerar/cikk_nev_gyarto.json'))['gyarto']
    osszes = collections.Counter(gy.get(c, '?') for c in cikk)
    van = collections.Counter(gy.get(c, '?') for c in sz)
    print('\ngyarto           szallitoi szamlan / osszes')
    for g, n in osszes.most_common():
        print(f'  {g:16s} {van.get(g,0):4d} / {n:4d}')

main()
