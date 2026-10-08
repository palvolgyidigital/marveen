#!/usr/bin/env python3
"""Kiolvassa a NAV import-okmanyokbol (NIK_EV__*.pdf) a szallitmany-szintu adatokat.

MIERT: a vam es az AFA SZALLITMANYRA vonatkozik, nem tetelre, es a kozos meghajton
(/mnt/kozos/PENZUGY/VAM) szallitmanyonkenti mappakban allnak. Ez a szkript a mappakat
jarja be, es szallitmanyonkent egy sort ad: datum, szallito, szamla-osszeg, deviza,
arfolyam, tetelszam, vam (A00), AFA (B00).

MERVE 2026-10-07: a 12100AF0*.pdf a vamtartozas-kozles (kevesebb adat), a NIK_EV__*.pdf
az IMPORT OKMANY, abban van a teljes bontas, tetelsoronkent is.
"""
import glob, os, re, sys, json
import pypdf

GYOKER = "/mnt/kozos/PÉNZÜGY/VÁM"

def szoveg(p):
    try:
        r = pypdf.PdfReader(p)
        return "\n".join((pg.extract_text() or '') for pg in r.pages)
    except Exception as e:
        return ''

def elemez(t):
    s = [x.strip() for x in t.split('\n') if x.strip()]
    d = {}
    for i, sor in enumerate(s):
        if sor.startswith('Határozatszám:'):
            m = re.search(r'Határozatszám:\s*(\S+)', sor)
            if m: d['hatarozat'] = m.group(1)
        if 'Árunyilatkozat benyújtásának időpontja' in sor:
            m = re.search(r'(\d{4}\.\d{2}\.\d{2})', sor)
            if m: d['datum'] = m.group(1).replace('.', '-').strip('-')
        if sor.startswith('Exportõr') or sor.startswith('Exportőr'):
            if i + 1 < len(s): d['exportor'] = s[i+1].split('  ')[0][:45]
        if 'Számla teljes összege és pénznem' in sor and i + 1 < len(s):
            m = re.search(r'([\d\s]+,\d+)\s*([A-Z]{3})\s+([\d\s]+,\d+)', s[i+1])
            if m:
                d['szamla'] = m.group(1).replace(' ', '')
                d['deviza'] = m.group(2)
                d['arfolyam'] = m.group(3).replace(' ', '')
        if sor.startswith('Tételek száma'):
            m = re.search(r'Tételek száma\s+(\d+)', sor)
            if m: d['tetelszam'] = int(m.group(1))
        if re.match(r'^Vám\s+A00\s', sor):
            m = re.search(r'A00\s+([\d\s]+)$', sor)
            if m: d['vam_ft'] = int(m.group(1).replace(' ', ''))
        if re.match(r'^ÁFA\s+B00\s', sor):
            m = re.findall(r'([\d\s]+)', sor)
            szamok = [x.replace(' ', '') for x in re.findall(r'\d[\d\s]*', sor)]
            if szamok: d['afa_ft'] = int(szamok[-1].replace(' ', ''))
    return d

def main():
    sorok = []
    for mappa in sorted(glob.glob(GYOKER + '/*/')):
        nev = os.path.basename(mappa.rstrip('/'))
        if not re.match(r'^20\d{6}', nev):      # csak a datum-nevu szallitmany-mappak
            continue
        nik = sorted(glob.glob(mappa + 'NIK_EV__*.pdf'))
        if nik:
            for p in nik:
                d = elemez(szoveg(p))
                d['mappa'] = nev; d['fajl'] = os.path.basename(p); d['tipus'] = 'legi (import okmany)'
                sorok.append(d)
            continue
        # MERVE 2026-10-07: a TENGERI szallitmanyoknal nincs NIK_EV, hanem egy
        # hatarozat_*.pdf all a mappaban, mas szerkezettel. Ott a vam a
        # "Behozatali vamok osszesen" sorban van, szamla-osszeg nincs benne.
        for p in sorted(glob.glob(mappa + 'hatarozat*.pdf')) + sorted(glob.glob(mappa + 'hatarozat.pdf')):
            t2 = szoveg(p)
            d = {'mappa': nev, 'fajl': os.path.basename(p), 'tipus': 'tengeri (hatarozat)'}
            m = re.search(r'Behozatali vámok összesen:\s*([\d\s]+)', t2)
            if m: d['vam_ft'] = int(m.group(1).split()[0].replace(' ', ''))
            m = re.search(r'(\d{2}HU\d{5}A\w+)', t2)
            if m: d['hatarozat'] = m.group(1)
            sorok.append(d)
    fejlec = ['mappa','tipus','datum','exportor','szamla','deviza','arfolyam','tetelszam','vam_ft','afa_ft','hatarozat','fajl']
    print('\t'.join(fejlec))
    for d in sorok:
        print('\t'.join(str(d.get(k, '')) for k in fejlec))
    print(f'\nSZALLITMANY-OKMANY: {len(sorok)} | vam-osszeggel: {sum(1 for d in sorok if d.get("vam_ft") is not None)}'
          f' | szamla-osszeggel: {sum(1 for d in sorok if d.get("szamla"))}')
    json.dump(sorok, open('store/mm-beszerar/vam_szallitmanyok.json','w'), ensure_ascii=False, indent=1)

main()
