# -*- coding: utf-8 -*-
"""Csucsu termek-ismerteto PDF, 11 termek (Collagenius, Kameleon Kamera, CareWear).
Csucsu kerese, 2026-10-27 11:25 (Telegram 10808): "a korabbi termekismertetokhoz hasonloan".
A formatum a 2026-10-19-i PDF-et koveti, az ott KIMONDOTT keresekkel egyutt:
nincs netto nagyker ar, nincs kifuto jelzes, nincs keszlet-mennyiseg.

MINDEN ADAT MERT FORRASBOL:
  - nev, cikkszam, netto kisker ar, url, rovid es hosszu leiras:
    store/mikrosat-agent/inputs/PDB_keszlet_2026-10-27.xlsx (mai Next-export, Max, 10:27)
  - brutto ar: a netto kisker * 1.27. A szorzo NEM feltevés: 25 soron visszamerve a
    2026-10-19-i ar-fajl ellen, mind a 25-on pontosan egyezik.
  - kep: a termekoldal og:image mezoje, determinisztikusan kinyerve, webp -> JPEG.
    KIVETEL a 154485: annak nincs termekoldala az exportban, a kepe a webaruhaz
    kanonikus CG-769907 utvonalarol jott, es szemre ellenorizve (vanilia italpor).
"""
import json, os, re
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image as RLImage, KeepTogether, HRFlowable)

KEP = 'store/csucsu-anyagok/kepek-2026-10-27/pdf'
ADAT = 'store/csucsu-anyagok/kepek-2026-10-27/termekek.json'
OUT = 'store/csucsu-termekismertetok/PDB_termekismertetok_2026-10-27.pdf'

pdfmetrics.registerFont(TTFont('DJ', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
pdfmetrics.registerFont(TTFont('DJB', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'))

ZOLD = colors.HexColor('#C1B435')
SZURKE = colors.HexColor('#555555')

st_h1 = ParagraphStyle('h1', fontName='DJB', fontSize=19, leading=23, textColor=colors.black, spaceAfter=2)
st_al = ParagraphStyle('al', fontName='DJ', fontSize=9.5, leading=13, textColor=SZURKE)
st_sec = ParagraphStyle('sec', fontName='DJB', fontSize=12.5, leading=16, textColor=colors.white)
st_nev = ParagraphStyle('nev', fontName='DJB', fontSize=10.5, leading=13.5)
st_meta = ParagraphStyle('meta', fontName='DJ', fontSize=8.2, leading=11.5, textColor=SZURKE)
st_ar = ParagraphStyle('ar', fontName='DJB', fontSize=9.6, leading=13)
st_txt = ParagraphStyle('txt', fontName='DJ', fontSize=8.4, leading=11.6)
st_lab_lb = ParagraphStyle('lablb', fontName='DJ', fontSize=8.2, leading=11, textColor=SZURKE)

# CSUCSU KERESE, 2026-10-27 11:39 (Telegram 10813), szo szerint: "kezdodjon a kameleonnal,
# utana a care wear majd a Collagenius-bol csak a 901 grammos szerepeljen."
SZEKCIOK = [('Kaméleon Kamera', 'KAMÉLEON KAMERA'),
            ('CareWear fényterápia', 'CAREWEAR'),
            ('Collagenius', 'COLLAGENIUS')]

# Ugyanabbol a keresbol: a Collageniusbol CSAK a 901 grammos (154438 / CG-762939).
# A masik ketto nem torolt adat, csak ebbol a dokumentumbol marad ki.
CSAK = {'COLLAGENIUS': {'154438'}}


def ft(v):
    s = '%0.0f' % round(float(v))
    out = ''
    while len(s) > 3:
        out = ' ' + s[-3:] + out
        s = s[:-3]
    return (s + out).strip() + ' Ft'


def kep_meret(p, max_w, max_h):
    with Image.open(p) as im:
        w, h = im.size
    ar = min(max_w / w, max_h / h)
    return w * ar, h * ar


def leiras_szoveg(t):
    sz = (t['rovid'] or '').strip()
    h = (t['hosszu'] or '').strip()
    h = re.sub(r'<[^>]+>', ' ', h)
    if h:
        sorok = [s.strip() for s in re.split(r'[\n\r]+', h) if len(s.strip()) > 25][:3]
        extra = ' '.join(sorok)
        if extra and extra[:40] not in sz:
            sz = (sz + ' ' + extra).strip()
    sz = re.sub(r'<[^>]+>', ' ', sz)
    sz = re.sub(r'\s+', ' ', sz)
    return sz[:900]


def termek_blokk(t):
    jp = os.path.join(KEP, t['cikkszam'] + '.jpg')
    bal = []
    if os.path.exists(jp):
        w, h = kep_meret(jp, 34 * mm, 34 * mm)
        bal.append(RLImage(jp, width=w, height=h))
    else:
        bal.append(Paragraph('(nincs kép)', st_meta))

    jobb = [Paragraph(t['nev'], st_nev), Spacer(1, 1.6 * mm)]
    jobb.append(Paragraph('Cikkszám: <b>%s</b>' % t['gyartoi'], st_meta))
    jobb.append(Spacer(1, 1.2 * mm))
    jobb.append(Paragraph('Bruttó eladási ár: <b>%s</b>' % ft(t['brutto']), st_ar))
    jobb.append(Spacer(1, 1.2 * mm))
    if t['url']:
        jobb.append(Paragraph('<link href="%s" color="#1A4FA0"><u>%s</u></link>'
                              % (t['url'], t['url']), st_lab_lb))

    tb = Table([[bal, jobb]], colWidths=[37 * mm, 136 * mm])
    tb.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (0, 0), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([tb, Spacer(1, 2 * mm), Paragraph(leiras_szoveg(t), st_txt),
                         Spacer(1, 3 * mm),
                         HRFlowable(width='100%', thickness=0.4, color=colors.HexColor('#DDDDDD')),
                         Spacer(1, 3.5 * mm)])


termekek = json.load(open(ADAT, encoding='utf-8'))
doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                        topMargin=16 * mm, bottomMargin=16 * mm,
                        title='PDB termekismertetok 2026-10-27', author='Palvolgyi-Digital')
tart = [Paragraph('Termékismertetők', st_h1),
        Paragraph('Pálvölgyi-Digital Kft. &nbsp;|&nbsp; %d termék &nbsp;|&nbsp; 2026. október 27.'
                  % sum(len([t for t in termekek if t['gyarto'].upper() == gy
                                and (gy not in CSAK or t['cikkszam'] in CSAK[gy])])
                        for _, gy in SZEKCIOK), st_al),
        Spacer(1, 2 * mm),
        Paragraph('Az árak bruttó, 27 százalék áfával. A linkre kattintva a webáruház oldala nyílik meg.',
                  st_meta),
        Spacer(1, 5 * mm)]

for cim, gyarto in SZEKCIOK:
    lista = [t for t in termekek if t['gyarto'].upper() == gyarto]
    if gyarto in CSAK:
        lista = [t for t in lista if t['cikkszam'] in CSAK[gyarto]]
    if not lista:
        continue
    fej = Table([[Paragraph(cim, st_sec)]], colWidths=[173 * mm])
    fej.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), ZOLD),
        ('LEFTPADDING', (0, 0), (-1, -1), 3 * mm),
        ('TOPPADDING', (0, 0), (-1, -1), 1.8 * mm),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.8 * mm),
    ]))
    tart.append(KeepTogether([fej, Spacer(1, 4 * mm)]))
    for t in lista:
        tart.append(termek_blokk(t))

doc.build(tart)
print('kesz:', OUT, os.path.getsize(OUT), 'byte')
