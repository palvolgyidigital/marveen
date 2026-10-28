# -*- coding: utf-8 -*-
"""Csucsu termek-ismerteto PDF, 18 termek. Minden adat MERT forrasbol:
   - ar: store/csucsu-termekismertetok/25_cikk_ar_es_url_2026-10-19.xlsx (Max, Next Column Chooser, 2026-10-19)
   - keszlet/kifuto: store/mm-keszletriport-agent/Export_automata_2026-10-16.xlsx
   - leiras: a termekoldalak sajat rovid es hosszu leirasa, determinisztikusan kinyerve
   - kep: a termekoldal og:image mezoje, webp-bol JPEG-be konvertalva
"""
import json, os, re, sys
import openpyxl
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image as RLImage, KeepTogether, HRFlowable)

SP = '/tmp/claude-1000/-home-pdb-marveen/b2d25bae-59d1-4435-bacb-5634ae9caf89/scratchpad'
KEP = 'store/csucsu-anyagok/kepek-2026-10-19/pdf'
OUT = 'store/csucsu-termekismertetok/PDB_termekismertetok_2026-10-19.pdf'

# CSUCSU KERESE, 2026-10-19 11:03 (Telegram 10056): "netto nagykerarat kerlek vedd ki".
# A dokumentum partnernek megy, tehat a nagyker ar nem tartozik bele. Kapcsolova tettem,
# nem torolve: ha egyszer belso valtozat kell, egy szo visszateszi.
NAGYKER_AR = '--nagyker' in sys.argv

# CSUCSU KERESE, 2026-10-19 11:11 (Telegram 10063): "nem kell sehova hogy kifuto".
# A kifuto jelzes a KIMENO, partneri valtozatbol kimarad. A TENY nem tunik el: a
# 306a6b8a kartya es a napi naplo tetelesen tartalmazza, melyik negy Vijim es melyik
# ket tovabbi cikk kifuto, es mennyi a keszletuk. Ket olvasoju nyilvantartas, ket reteg.
# A --kifuto kapcsolo visszateszi, ha egyszer belso valtozat kell.
KIFUTO_JELZES = '--kifuto' in sys.argv

# CSUCSU KERESE, 2026-10-19 11:14 (Telegram 10067): "Ne irjunk sehova keszlet mennyiseget".
# A keszlet-sor EGESZBEN kimarad, nem csak a szam. Ennek kulon indoka van, es ezt a
# dontest kimondtam neki is: egy puszta "Raktaron" felirat szam nelkul EPP a mar kivett
# kifuto-jelzes miatt lenne felrevezeto (negy Vijimnel 4-6 db all), tehat a szam nelkuli
# keszlet-allitas rosszabb, mint a hallgatas. A link a webaruhazra megy, ott lathato az
# elo elerhetoseg. A --keszlet kapcsolo visszateszi, ha belso valtozat kell.
KESZLET_SOR = '--keszlet' in sys.argv
if '--out' in sys.argv:
    OUT = sys.argv[sys.argv.index('--out') + 1]

pdfmetrics.registerFont(TTFont('DJ', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DJB', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))

ZOLD = colors.HexColor('#C1B435')   # a pdb.hu sajat theme-color-ja, a lapbol merve
SZURKE = colors.HexColor('#555555')

st_h1 = ParagraphStyle('h1', fontName='DJB', fontSize=19, leading=23, textColor=colors.black, spaceAfter=2)
st_al = ParagraphStyle('al', fontName='DJ', fontSize=9.5, leading=13, textColor=SZURKE)
st_sec = ParagraphStyle('sec', fontName='DJB', fontSize=12.5, leading=16, textColor=colors.white)
st_nev = ParagraphStyle('nev', fontName='DJB', fontSize=10.5, leading=13.5)
st_meta = ParagraphStyle('meta', fontName='DJ', fontSize=8.2, leading=11.5, textColor=SZURKE)
st_ar = ParagraphStyle('ar', fontName='DJB', fontSize=9.6, leading=13)
st_txt = ParagraphStyle('txt', fontName='DJ', fontSize=8.4, leading=11.6)
st_lab = ParagraphStyle('lab', fontName='DJ', fontSize=8.2, leading=11, textColor=colors.HexColor('#B00020'))
st_lab_ok = ParagraphStyle('labok', fontName='DJ', fontSize=8.2, leading=11, textColor=colors.HexColor('#1A7F37'))
st_lab_lb = ParagraphStyle('lablb', fontName='DJ', fontSize=8.2, leading=11, textColor=SZURKE)

SZEKCIOK = [
    ('Selfie botok es asztali allvanyok', 'Selfie botok és asztali állványok',
     ['KF-09-127V1', 'UL-2502E', 'UL-M001B', 'UL-T122', 'UL-T111',
      # Vijim asztali allvanyrendszerek, Csucsu kerte ide, 2026-10-19 11:09 (Telegram 10060)
      'UL-2957', 'UL-2952', 'UL-2487', 'UL-2880', 'UL-2805', 'UL-2806', 'UL-2665']),
    ('Vezetek nelkuli mikrofonok', 'Vezeték nélküli mikrofonok',
     ['UL-3319', 'UL-3328', 'UL-A014A', 'UL-A014GBB1', 'UL-A046', 'UL-A018GBB2']),
    ('LED lampak es fenyrudak', 'LED lámpák és fényrudak',
     ['KF-34-052', 'UL-3099', 'UL-L234', 'UL-L058GBB1', 'KF-34-045']),
    ('Telefonkeret', 'Telefonkeret, rig',
     ['UL-C001']),
    ('Konferencia', 'Konferencia-megoldás',
     ['KA-Meeting-Pro']),
]


def ft(v):
    if v is None:
        return ''
    s = '%0.0f' % round(float(v))
    out = ''
    while len(s) > 3:
        out = ' ' + s[-3:] + out
        s = s[:-3]
    return (s + out).strip() + ' Ft'


# --- adatok betoltese
wb = openpyxl.load_workbook('store/csucsu-termekismertetok/25_cikk_ar_es_url_2026-10-19.xlsx', data_only=True)
arak = {}
for r in list(wb.active.iter_rows(values_only=True))[1:]:
    arak[r[1]] = {'next': r[0], 'nev': r[2], 'nagyker': r[3], 'kisker': r[4], 'brutto': r[5], 'url': r[6] or ''}

erp = json.load(open(SP + '/sku11.json', encoding='utf-8'))
uj = json.load(open(SP + '/sku-uj.json', encoding='utf-8'))
for k, v in uj['ulanzi'].items():
    erp[k] = v
for k in uj['kandao']:
    if k['gy'] == 'KA-Meeting-Pro':
        erp['KA-Meeting-Pro'] = {'nev': k['nev'], 'cikkszam': k['cikkszam'], 'kifuto': k['kifuto'],
                                 'paperhill': k['paperhill'], 'url': k['url'], 'csoport': 'Konferencia'}

leir = json.load(open(SP + '/leirasok.json', encoding='utf-8'))
kepek = json.load(open(SP + '/kepek.json', encoding='utf-8'))
kepek.update(json.load(open(SP + '/kepek-uj.json', encoding='utf-8')))

# a UL-2502E URL-je a 301-es atiranyitasbol, mert a Next mezoje ures
POT_URL = {'UL-2502E': 'https://www.pdb.hu/Ulanzi-MT-44-E-selfie-allvany-monopod-telefontarto'}


def kep_meret(p, max_w, max_h):
    with Image.open(p) as im:
        w, h = im.size
    ar = min(max_w / w, max_h / h)
    return w * ar, h * ar


def leiras_szoveg(sku):
    d = leir.get(sku, {})
    t = (d.get('rovid') or '').strip()
    h = (d.get('hosszu') or '').strip()
    # a rovid leiras utan a hosszubol annyi, hogy a termek egy blokkban maradjon
    if h:
        # az elso ket erdemi bekezdes
        sorok = [s for s in h.split('\n') if len(s) > 25][:3]
        extra = ' '.join(sorok)
        if extra and extra[:40] not in t:
            t = (t + ' ' + extra).strip()
    t = re.sub(r'\s+', ' ', t)
    return t[:900]


def termek_blokk(sku):
    a = arak.get(sku, {})
    e = erp.get(sku, {})
    nev = a.get('nev') or e.get('nev') or sku
    url = a.get('url') or POT_URL.get(sku) or (kepek.get(sku) or {}).get('url') or ''
    kifuto = str(e.get('kifuto') or '0') == '1'
    try:
        kesz = int(float(e.get('paperhill') or 0))
    except Exception:
        kesz = 0

    jp = os.path.join(KEP, sku + '.jpg')
    bal = []
    if os.path.exists(jp):
        w, h = kep_meret(jp, 34 * mm, 34 * mm)
        bal.append(RLImage(jp, width=w, height=h))
    else:
        bal.append(Paragraph('(nincs kép)', st_meta))

    jobb = [Paragraph(nev, st_nev), Spacer(1, 1.6 * mm)]
    jobb.append(Paragraph('Cikkszám: <b>%s</b>' % sku, st_meta))
    jobb.append(Spacer(1, 1.2 * mm))
    if NAGYKER_AR:
        jobb.append(Paragraph('Nettó nagyker ár: <b>%s</b>' % ft(a.get('nagyker')), st_ar))
    jobb.append(Paragraph('Bruttó eladási ár: <b>%s</b>' % ft(a.get('brutto')), st_ar))
    jobb.append(Spacer(1, 1.2 * mm))
    if KESZLET_SOR:
        if kifuto and KIFUTO_JELZES:
            jobb.append(Paragraph('KIFUTÓ termék, készlet: %d db' % kesz, st_lab))
        elif kesz > 0:
            jobb.append(Paragraph('Raktáron, készlet: %d db' % kesz, st_lab_ok))
        else:
            jobb.append(Paragraph('Készlet: 0 db', st_lab))
    if url:
        jobb.append(Paragraph('<link href="%s" color="#1A4FA0"><u>%s</u></link>' % (url, url), st_lab_lb))

    t = Table([[bal, jobb]], colWidths=[37 * mm, 136 * mm])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    elemek = [t, Spacer(1, 2 * mm), Paragraph(leiras_szoveg(sku), st_txt), Spacer(1, 3 * mm),
              HRFlowable(width='100%', thickness=0.4, color=colors.HexColor('#DDDDDD')), Spacer(1, 3.5 * mm)]
    return KeepTogether(elemek)


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=16 * mm,
                        title='PDB termekismertetok 2026-10-19', author='Palvolgyi-Digital')
tart = []
tart.append(Paragraph('Termékismertetők', st_h1))
tart.append(Paragraph('Pálvölgyi-Digital Kft. &nbsp;|&nbsp; 18 termék &nbsp;|&nbsp; 2026. október 19.', st_al))
tart.append(Spacer(1, 2 * mm))
# A belso ar-forrasra (Next ERP) hivatkozo bekezdes TOROLVE, Csucsu keresere,
# 2026-10-19 11:09 (Telegram 10060): "Az elejen a next rp szoveget torold".
# Partnernek meno anyagban a belso rendszer megnevezese nem tartozik bele.
# A forras-megjeloles a 306a6b8a kartyan es a napi naploban all, tehat nem veszik el.
tart.append(Paragraph(
    'Az árak bruttó, 27 százalék áfával. A linkre kattintva a webáruház oldala nyílik meg.', st_meta))
tart.append(Spacer(1, 5 * mm))

for szekcio_ascii, szekcio, lista in SZEKCIOK:
    fej = Table([[Paragraph(szekcio, st_sec)]], colWidths=[173 * mm])
    fej.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), ZOLD),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 1.8 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.8 * mm),
    ]))
    tart.append(KeepTogether([fej, Spacer(1, 4 * mm)]))
    for sku in lista:
        tart.append(termek_blokk(sku))

doc.build(tart)
print('kesz:', OUT, os.path.getsize(OUT), 'byte')
