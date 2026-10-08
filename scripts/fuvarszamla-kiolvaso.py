#!/usr/bin/env python3
"""Kiolvassa a szallitmany-mappakban talalt FUVAROZOI szamlakbol a koltsegeket.

MIERT: a vam a NAV-okmanyban van (l. vam-hatarozat-kiolvaso.py), a FUVAR viszont a
fuvarozo szamlajan. A tengeri szallitmanyoknal ez a Hunicorn (HCLOG-...) szamla, es
ugyanabban a szallitmany-mappaban all.

MERVE 2026-10-07: a Hunicorn-szamla tetelsorai kulon sorokban allnak (megnevezes, majd
"1 db", majd a netto egysegar, a netto ar, az afa-kulcs es a brutto ar). A vegen
"NETTO OSSZEG:" es "FIZETENDO BRUTTO VEGOSSZEG:". A MEGJEGYZES blokk tartalmazza a
Shipper nevet, a karton/kg/cbm adatot es az arfolyamot.
"""
import glob, json, os, re
import pypdf

GYOKER = "/mnt/kozos/PÉNZÜGY/VÁM"
TETEL = ['Export okmány', 'Külföldi fuvardíj', 'Belföldi fuvardíj', 'Biztosítás',
         'Ki-betárolás', 'Adminisztrációs költség', 'Házhozszállítás', 'Import okmány',
         'Vámkezelés', 'Tárolás']

def ft(s):
    m = re.match(r'^([\d\s]+(?:,\d+)?)\s*Ft$', s.strip())
    if not m: return None
    return float(m.group(1).replace(' ', '').replace(',', '.'))

def elemez(t):
    s = [x.strip() for x in t.split('\n') if x.strip()]
    d = {'tetelek': {}}
    for i, sor in enumerate(s):
        if sor in TETEL:
            for j in range(i + 1, min(i + 5, len(s))):
                v = ft(s[j])
                if v is not None:
                    d['tetelek'][sor] = v
                    break
        if sor.startswith('NETTÓ ÖSSZEG'):
            for j in range(i + 1, min(i + 3, len(s))):
                v = ft(s[j])
                if v is not None: d['netto_ft'] = v; break
        if sor.startswith('Shipper:'):
            d['shipper'] = sor.split(':', 1)[1].strip()
        if re.match(r'^\d+ karton', sor):
            d['kolli'] = sor
        if sor.startswith('SZÁMLA KELTE'):
            for j in range(i + 1, min(i + 3, len(s))):
                m = re.match(r'^(\d{4})\.\s*(\d{2})\.\s*(\d{2})\.?$', s[j])
                if m: d['datum'] = '-'.join(m.groups()); break
    return d

def main():
    sorok, mappak = [], 0
    for mappa in sorted(glob.glob(GYOKER + '/*/')):
        nev = os.path.basename(mappa.rstrip('/'))
        if not re.match(r'^20\d{6}', nev): continue
        mappak += 1
        for p in sorted(glob.glob(mappa + '*.pdf')):
            alap = os.path.basename(p)
            if not re.search(r'HCLOG|fuvar|invoice', alap, re.I): continue
            try:
                r = pypdf.PdfReader(p)
                t = "\n".join((pg.extract_text() or '') for pg in r.pages)
            except Exception as e:
                print(f'  HIBA {alap}: {str(e)[:50]}'); continue
            d = elemez(t); d['mappa'] = nev; d['fajl'] = alap
            sorok.append(d)
    print(f'MAPPA: {mappak} | FUVARSZAMLA: {len(sorok)}')
    print()
    for d in sorok:
        print(f"{d['mappa']:22s} {d.get('datum','?'):12s} shipper={d.get('shipper','?'):22s} netto={d.get('netto_ft','?')} Ft")
        for k, v in d.get('tetelek', {}).items():
            print(f"      {k:28s} {v:>12,.0f} Ft".replace(',', ' '))
        if d.get('kolli'): print(f"      [{d['kolli']}]")
    json.dump(sorok, open('store/mm-beszerar/fuvar_szallitmanyok.json','w'), ensure_ascii=False, indent=1)

main()
