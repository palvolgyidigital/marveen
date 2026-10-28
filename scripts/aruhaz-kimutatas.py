# -*- coding: utf-8 -*-
"""MediaMarkt aruhaz-kimutatas: IDP-riport + sajat keszlet -> kesz, tordelt szoveg.

David 2026-10-14-i hat szabalya szerint. A formatumot o hagyta jova (msg 9658:
"ez igy jo lesz"), a tordelest o kerte (msg 9652), es a tartalmat o szukitette
(msg 9649): a tetelek kellenek, nem az elemzes.

Hasznalat:
  python3 scripts/aruhaz-kimutatas.py H301
  python3 scripts/aruhaz-kimutatas.py --kereses allee     # nev -> SAP-kod a CRM-bol
  python3 scripts/aruhaz-kimutatas.py H301 --letoltes     # elobb friss IDP-riport

A kimenet NEGY blokk, '===== UZENET n =====' valasztokkal: szekciónkent kulon
Telegram-uzenet, mert egyben osszefolyik.
"""
import os, re, sys, html, zipfile, sqlite3, subprocess, datetime as dt

GYOKER = '/home/pdb/marveen'
IDP_DIR = os.path.join(GYOKER, 'store/mediamarkt-agent/inputs')
LETOLTO = os.path.join(GYOKER, 'store/mediamarkt-agent/download_store_report_barmely.cjs')
DB = os.path.join(GYOKER, 'store/claudeclaw.db')


def next_export():
    """A legfrissebb Export_automata_*.xlsx. NEM talalgat: ha nincs, kiab\u00e1l."""
    import glob
    fs = sorted(glob.glob(os.path.join(GYOKER, 'store/mm-keszletriport-agent/Export_automata_*.xlsx')))
    if not fs:
        sys.exit('NINCS Next-export a store/mm-keszletriport-agent/ alatt. Enelkul a sajat keszlet nem merheto.')
    return fs[-1]


def xlsx(p):
    z = zipfile.ZipFile(p)
    ss = re.findall(r'<si>(.*?)</si>', z.read('xl/sharedStrings.xml').decode('utf-8', 'ignore'), re.S)
    strs = [html.unescape(''.join(re.findall(r'<t[^>]*>(.*?)</t>', s, re.S))) for s in ss]
    rows = re.findall(r'<row[^>]*>(.*?)</row>', z.read('xl/worksheets/sheet1.xml').decode('utf-8', 'ignore'), re.S)

    def cells(r):
        out = {}
        for ref, attr, body in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(.*?)</c>', r, re.S):
            v = re.search(r'<v>(.*?)</v>', body, re.S)
            if not v:
                out[ref] = ''
                continue
            val = v.group(1)
            out[ref] = strs[int(val)] if 't="s"' in attr and val.isdigit() and int(val) < len(strs) else val
        return out
    fej = cells(rows[0])
    inv = {v: k for k, v in fej.items()}
    return [{n: cells(r).get(k, '') for n, k in inv.items()} for r in rows[1:]]


def tárgyeset(n):
    """A magyar tárgyrag a szám KIMONDOTT alakjától fugg, nem a szamjegytol.
    '1-et', de '2-t'; '6-ot', de '7-et'. Ha ezt nem kezeljuk, a kimutatas
    'Ebbol 1-at tudunk szallitani' alakban megy ki a kollegaknak."""
    n = int(n)
    if n == 0:
        return '0-t'
    szaz = n % 100
    if szaz in (2, 20, 30, 40, 50, 60, 70, 80, 90, 100) or n % 100 == 0:
        return '%d-t' % n if szaz == 2 else ('%d-at' % n if szaz in (20, 30, 60, 80, 100) or n % 100 == 0 else '%d-et' % n)
    v = n % 10
    if szaz in (10, 11, 12, 13, 14, 15, 16, 17, 18, 19):
        return '%d-%s' % (n, {0: 'et', 1: 'et', 2: 't', 3: 'at', 4: 'et', 5: 'öt', 6: 'ot', 7: 'et', 8: 'at', 9: 'et'}[v]) if szaz != 10 else '%d-et' % n
    return '%d-%s' % (n, {0: 'at', 1: 'et', 2: 't', 3: 'at', 4: 'et', 5: 'öt', 6: 'ot', 7: 'et', 8: 'at', 9: 'et'}[v])


def szam(r, k):
    try:
        return float(r.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


def sap_keres(toredek):
    """Aruhaz-nev -> SAP-kod a CRM partner-note-jabol. Ekezet-fuggetlen."""
    import unicodedata

    def n_(s):
        return ''.join(c for c in unicodedata.normalize('NFD', s or '')
                       if unicodedata.category(c) != 'Mn').lower()
    c = sqlite3.connect(DB)
    ki = []
    for nev, note in c.execute("SELECT name, COALESCE(note,'') FROM partners WHERE note LIKE '%SAP%'"):
        m = re.search(r'SAP k[oó]d:\s*([A-Z]\d{3})', note)
        if m and n_(toredek) in n_(nev + ' ' + note):
            ki.append((m.group(1), nev))
    return ki


def riport(kod, letoltes):
    ma = dt.date.today().isoformat()
    p = os.path.join(IDP_DIR, 'IDP_StoreReport_%s_%s.xls' % (kod, ma))
    if letoltes or not os.path.exists(p):
        print('[letoltes] IDP-riport, %s ...' % kod, file=sys.stderr)
        r = subprocess.run(['node', LETOLTO, ma, kod], capture_output=True, text=True,
                           cwd=os.path.dirname(LETOLTO), timeout=600)
        if not os.path.exists(p):
            sys.exit('A letoltes nem keszult el. Kimenet:\n' + (r.stdout or '') + (r.stderr or ''))
    return p


def fut(kod, letoltes=False):
    idp = xlsx(riport(kod, letoltes))
    nxt = xlsx(next_export())
    if not idp:
        sys.exit('A riport URES. Ez NEM azt jelenti, hogy nincs hiany: a lekerdezes nem merheto.')
    N = {}
    for r in nxt:
        g = (r.get('Gyártói cikkszám') or '').strip().upper()
        if g:
            N.setdefault(g, r)
    nev = (idp[0].get('Áruház') or kod).strip()

    def keszlet(r):
        return szam(N.get((r.get('gyártói cikkszám') or '').strip().upper(), {}), 'Paperhill')

    def rovid(s, n=54):
        """Szoszinten vag, hogy ne csonkoljon szo kozepen."""
        s = (s or '').strip()
        if len(s) <= n:
            return s
        v = s[:n].rsplit(' ', 1)[0]
        return (v or s[:n]).rstrip(' ,.;-') + '...'

    def nextnev(r):
        """Nev + gyartoi cikkszam. A cikkszam NEM dekoracio: ket WM-10 mikrofon
        neve beture azonos, csak a SKU kulonbozteti meg oket (UL-3319 vs UL-3328)."""
        g = (r.get('gyártói cikkszám') or '').strip().upper()
        n = N.get(g)
        nev = (n.get('Megnevezés') if n else None) or (r.get('termék leírás') or '')
        return '%s (%s)' % (rovid(nev, 48), g) if g else rovid(nev, 54)

    # 2-3. szabaly: eladhato 0 ES nyitott rendeles 0 ES iden fogyott, es NEKUNK van
    rend = [r for r in idp if szam(r, 'Teljes eladható készlet') == 0
            and szam(r, 'nyitott rendelés') == 0 and szam(r, 'Eladás CY') > 0]
    van = sorted([r for r in rend if keszlet(r) > 0], key=lambda x: -szam(x, 'Eladás CY'))
    nincs = [r for r in rend if keszlet(r) <= 0]

    # 4. szabaly: kifutonal utod vagy valtozat
    TOK = re.compile(r'\b([A-Z]{2,6}-?\d{2,4}[A-Z]?)\b')
    def utod(r):
        gy = (r.get('Gyártó') or '').strip().upper()
        tk = set(TOK.findall((nextnev(r) or '').upper()))
        j = [c for c in nxt
             if (c.get('Gyártó') or '').upper().startswith(gy[:5])
             and szam(c, 'Paperhill') > 0
             and (c.get('Kifutó') or '0').strip() in ('0', '0.0', '')
             and tk & set(TOK.findall((c.get('Megnevezés') or '').upper()))]
        j.sort(key=lambda x: -szam(x, 'Paperhill'))
        return j[0] if j else None
    alt = [(r, utod(r)) for r in sorted(nincs, key=lambda x: -szam(x, 'Eladás CY'))]
    alt = [(r, u) for r, u in alt if u]

    # 5. szabaly: 4 honapnal regebbi keszlet
    regi = sorted([r for r in idp if szam(r, '4-7 ') > 0 or szam(r, '>7 ') > 0],
                  key=lambda x: (-szam(x, '>7 '), -(szam(x, '4-7 ') + szam(x, '>7 '))))
    def kor(r):
        return '>7' if szam(r, '>7 ') > 0 else '4-7'

    ossz_elad = sum(szam(r, 'Teljes eladható készlet') for r in idp)
    egy_honap = sum(szam(r, '1') for r in idp)
    regi_db = sum(szam(r, '4-7 ') + szam(r, '>7 ') for r in regi)

    B = []
    # --- 1. uzenet
    s = ['AMIT ÉRDEMES RENDELNIÜK, %s' % kod, '',
         '%s' % nev, '',
         'Idén fogyott, most nincs készletük, nyitott rendelés sincs rá, mi tudunk szállítani.', '']
    for r in van[:10]:
        s += ['\u2022 %s' % nextnev(r),
              '   idén %.0f db, nálunk %.0f db' % (szam(r, 'Eladás CY'), keszlet(r)), '']
    if not van:
        s += ['Nincs ilyen tétel ebben az áruházban.', '']
    B.append('\n'.join(s).rstrip())

    # --- 2. uzenet
    s = ['AMIT MÁS CIKKSZÁMON TUDUNK ADNI', '']
    if alt:
        for r, u in alt[:6]:
            s += ['\u2022 %s' % rovid(r.get('termék leírás'), 52),
                  '   helyette %s' % rovid(u.get('Megnevezés'), 52),
                  '   nálunk %.0f db, idén %.0f db fogyott' % (szam(u, 'Paperhill'), szam(r, 'Eladás CY')), '']
        s += ['A helyettesítő eltérhet színben vagy kivitelben, az ajánlatban jelezni kell.']
    else:
        s += ['Most nincs ilyen tétel.']
    B.append('\n'.join(s).rstrip())

    # --- 3. uzenet
    s = ['AMIT A HELYSZÍNEN MEG KELL NÉZNI', '',
         'Négy hónapnál régebben állnak a polcon. Megvan-e a termék, van-e rajta ár, nem sérült-e a csomagolás.', '']
    surgos = [r for r in regi if kor(r) == '>7' and szam(r, 'Eladás CY') == 0]
    if surgos:
        s += ['A legsürgősebbek, hét hónapja ott állnak és idén egy darab sem fogyott:', '']
        for r in surgos:
            s += ['\u2022 %s, %.0f db' % (rovid(r.get('termék leírás'), 52), szam(r, '4-7 ') + szam(r, '>7 '))]
        s += ['']
    tobbi = [r for r in regi if r not in surgos]
    if tobbi:
        s += ['A többi:', '']
        for r in tobbi:
            s += ['\u2022 %s, %.0f db, %s hónapos' % (rovid(r.get('termék leírás'), 48),
                  szam(r, '4-7 ') + szam(r, '>7 '), kor(r))]
    if not regi:
        s += ['Nincs négy hónapnál régebbi készlet.']
    B.append('\n'.join(s).rstrip())

    # --- 4. uzenet
    s = ['ÖSSZEFOGLALVA', '',
         'A készlet %s: a %.0f db eladhatóból %.0f db egy hónapnál fiatalabb, és %.0f db áll négy hónapnál régebben a polcon.'
         % ('friss' if ossz_elad and egy_honap / max(ossz_elad, 1) > 0.4 else 'vegyes korú', ossz_elad, egy_honap, regi_db), '',
         '%d olyan cikkünk van, ami idén fogyott, most mégsem elérhető náluk, és nyitott rendelés sincs rá. Ebből %s azonnal tudunk szállítani.'
         % (len(rend), tárgyeset(len(van))), '']
    if van:
        s += ['A legnagyobb egyedi tétel: %s, idén %.0f db.' % (nextnev(van[0]), szam(van[0], 'Eladás CY'))]
    B.append('\n'.join(s).rstrip())
    return nev, B


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    if '--kereses' in sys.argv:
        for k, n in sap_keres(a[0] if a else ''):
            print('%s  %s' % (k, n))
        sys.exit(0)
    if not a:
        sys.exit('Hasznalat: python3 scripts/aruhaz-kimutatas.py <SAP-kod>  [--letoltes]\n'
                 '           python3 scripts/aruhaz-kimutatas.py --kereses <nev-toredek>')
    nev, blokkok = fut(a[0].upper(), '--letoltes' in sys.argv)
    for i, b in enumerate(blokkok, 1):
        print('\n===== UZENET %d =====' % i)
        print(b)
