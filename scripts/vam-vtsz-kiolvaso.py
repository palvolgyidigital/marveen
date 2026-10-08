#!/usr/bin/env python3
"""Kiolvassa a kozos VAM mappa okmanyaibol a VTSZ (vamtarifaszam) + arumegnevezes parokat.

MIERT: a Next Cikkek/Anyagok kepernyo Vamtarifaszam mezojenek kitoltesehez HIVATALOSAN
beadott VTSZ-ek kellenek. A /mnt/kozos/PÉNZÜGY/VÁM alatti szallitmany-mappakban allo
import-okmanyok (NIK_EV__*.pdf legi, hatarozat_*.pdf tengeri) tetelsorosan tartalmazzak a
"Vámtarifaszám: <szam> Árumegnevezés: <nev>" part, tehat eppen azt, ami hivatalosan beadva
volt. Merve 2026-10-07.

A TETELSOR TOBBET AD, MINT A VTSZ (merve 2026-10-07 23:5x): minden tetel-blokk tartalmazza a
mennyiseget, a netto tomeget, a szarmazasi orszagot, a TETELSOR ERTEKET DEVIZABAN, es a
"Kalkulacio" blokkban hat szamot FIX SORRENDBEN: A00 adoalap, B00 adoalap, A00 KULCS, B00 KULCS,
A00 osszeg, B00 osszeg. Ellenorizve ket tetelen: 642 083 x 0,037 = 23 757, es 428 020 x 0,000 = 0.
Vagyis a HIVATALOS VAMTETEL-SZAZALEK tetelsoronkent kiolvashato, nem csak a VTSZ.

KORLAT, AMIT KI KELL MONDANI: a mappak legkorabbi szallitmanya 2026-03-10, tehat ez NEM a
teljes multbeli vamolas-tortenet, csak a 2026-os. A tengeri `hatarozat_*.pdf` csak fizetesi
kozles, tetelsorok NINCSENEK benne, tehat a VTSZ-ek a legi `NIK_EV__*.pdf` okmanyokbol jonnek.
"""
import glob, json, os, re
import pypdf

GYOKER = '/mnt/kozos/PÉNZÜGY/VÁM'
SOR = re.compile(r'Vámtarifaszám:\s*([\d\s]+?)\s*Árumegnevezés:\s*(.+)')
ERTEK = re.compile(r'Tételsor érték:\s*([\d\s]+(?:,\d+)?)\s*([A-Z]{3})')
MENNY = re.compile(r'Mennyiség:\s*([\d\s]+(?:,\d+)?)')
ORSZAG = re.compile(r'Szárm\. ország:\s*([A-Z]{2})')
SZAM = re.compile(r'^[\d\s]*\d(?:,\d+)?$')

def szam(s):
    s = s.strip().replace('\u00a0', '').replace(' ', '').replace(',', '.')
    try: return float(s)
    except ValueError: return None

def kalkulacio(sorok, tol):
    """A 'Kalkulacio: A00' utani hat szam FIX sorrendben:
    A00 adoalap, B00 adoalap, A00 kulcs, B00 kulcs, A00 osszeg, B00 osszeg."""
    szamok = []
    for x in sorok[tol:tol + 14]:
        v = szam(x)
        if v is not None: szamok.append(v)
        if len(szamok) == 6: break
    if len(szamok) < 6: return {}
    return {'a00_alap': szamok[0], 'b00_alap': szamok[1],
            'vam_kulcs': szamok[2], 'afa_kulcs': szamok[3],
            'vam_ft': szamok[4], 'afa_ft': szamok[5]}

def main():
    mappak = sorted(p for p in glob.glob(GYOKER + '/*/') if re.match(r'^20\d{6}', os.path.basename(p.rstrip('/'))))
    sorok, hiba = [], []
    for m in mappak:
        nev = os.path.basename(m.rstrip('/'))
        for p in sorted(glob.glob(m + '*.pdf')):
            try:
                t = '\n'.join((pg.extract_text() or '') for pg in pypdf.PdfReader(p).pages)
            except Exception as e:
                hiba.append((nev, os.path.basename(p), str(e)[:40])); continue
            lapok = t.split('\n')
            for i, x in enumerate(lapok):
                mm = SOR.search(x)
                if not mm: continue
                d = {'mappa': nev, 'fajl': os.path.basename(p),
                     'vtsz': re.sub(r'\s+', '', mm.group(1)),
                     'megnevezes': mm.group(2).strip()[:120]}
                # a tetel-blokk a kovetkezo VTSZ-sorig tart
                for j in range(i + 1, min(i + 30, len(lapok))):
                    if SOR.search(lapok[j]): break
                    e = ERTEK.search(lapok[j])
                    if e: d['tetelsor_ertek'], d['deviza'] = szam(e.group(1)), e.group(2)
                    q = MENNY.search(lapok[j])
                    if q and 'menny' not in d: d['menny'] = szam(q.group(1))
                    o = ORSZAG.search(lapok[j])
                    if o: d['szarmazas'] = o.group(1)
                    if lapok[j].strip().startswith('Kalkuláció'):
                        d.update(kalkulacio(lapok, j + 1))
                sorok.append(d)
    print(f'MAPPA: {len(mappak)} | VTSZ-SOR: {len(sorok)} | olvasasi hiba: {len(hiba)}')
    egyedi = {}
    for s in sorok:
        egyedi.setdefault(s['vtsz'], set()).add(s['megnevezes'])
    print(f'EGYEDI VTSZ: {len(egyedi)}\n')
    kulcsok = {}
    for s in sorok:
        if s.get('vam_kulcs') is not None:
            kulcsok.setdefault(s['vtsz'], set()).add(s['vam_kulcs'])
        
    print(f'VTSZ VAMKULCCSAL: {len(kulcsok)}\n')
    print(f'{"VTSZ":12s} {"vam%":>7s}  megnevezes')
    for v in sorted(egyedi):
        nevek = sorted(egyedi[v])
        k = sorted(kulcsok.get(v, []))
        ks = '/'.join(f'{x*100:.1f}' for x in k) if k else '?'
        print(f'  {v:12s} {ks:>7s}  {nevek[0][:66]}')
        for n in nevek[1:3]:
            print(f'  {"":12s} {"":>7s}  + {n[:64]}')
    tob = {v: sorted(k) for v, k in kulcsok.items() if len(k) > 1}
    print(f'\nVTSZ KETFELE VAMKULCCSAL: {len(tob)} {tob if tob else ""}')
    json.dump(sorok, open('store/mm-beszerar/vam_vtsz_sorok.json', 'w'), ensure_ascii=False, indent=1)

main()
