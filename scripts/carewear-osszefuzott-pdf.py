# -*- coding: utf-8 -*-
"""Build one browsable CareWear PDF from the 22 corrected treatment guides.

Marci's request, 2026-10-22 13:23 (Telegram 10527): one complete, browsable PDF, the human
figure first, then the modules listed by category, each category with a bold title, and a
new category starting on a new page.

HIS CORRECTION, 13:32 (Telegram 10531), with two photos, verbatim: "Ha egy dokumentumban
ures helyek vannak, azokat toroljetek, legyen folymaatos. A cimet pedig ugy ertettem, hogy
a cim alatt egybol kezdodjenek az abrak, csak ha vege egy kategorianak, az uj kategoria uj
oldalon kezdodjon."

So the unit is the CARD (module), not the exported page. Cards are cut out of the source
pages and re-flowed: the category title sits at the top of the first page, the cards start
right under it, and they fill the page continuously. Only a NEW category forces a new page.

Why the category list looks the way it does: he also said the app sometimes only exported
in pieces, and that the e-mail subjects show it. Measured: 22 exports collapse into 19
distinct body regions (hand1+hand2, shoulder1+shoulder2, lowback1+lowback2 are one region
each), which matches the 18 markers plus the Strength & Conditioning point on the figure.

Input: the CORRECTED files (kuldes-javitott/), never the released kuldes/ set.
"""
import os, io
import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

B = "/home/pdb/marveen/store/inbox/carewear-forditas-20261021"
FORRAS = os.path.join(B, "kuldes-javitott")
ABRA = os.path.join(B, "abra-20261022", "K_perny_fot_._2026-10-22_12.00.51.png")
KIMENET = os.path.join(B, "CareWear-teljes-magyar.pdf")

# A kepernyokep jobb paneljenek vagasa: a ket emberi alak, a menu es a cimsor nelkul.
# Merve 2026-10-22: a fuggoleges elvalaszto a 902. oszlop, a tartalom y 278-2047, x 1020-2731.
ABRA_VAGAS = (1005, 265, 2732, 2048)

DPI = 200
FEJLEC_ALJA_PT = 52.0   # a futo "Patient Guide:" fejlec also hatara pontban (merve: 22,5-44 pt)

# Lap- es tipografiai meretek pontban
MARGO_X, MARGO_FENT, MARGO_LENT = 36, 40, 32
CIM_MAGAS = 58          # a kategoria-cim blokk teljes magassaga
KARTYA_KOZ = 12

# A jelolok a VAGOTT abran (1727x1783 px), klaszterezessel merve 2026-10-22: pontosan
# 18 testi jelolo plusz a "Strength & Conditioning" jelmagyarazat hatszoge (656,1163).
# AMI MERT: a jelolok szama es helye. AMI NEM: hogy melyik jelolo melyik kategoria.
# MARCI DONTESE 2026-10-22 13:45 (Telegram 10547), szo szerint: "A fejfajas es a szem az
# a fej, legyen egy kategoria. Igy mar jonak kell lennie. 18 testresz es +strength".
# Ezert 18 testtaj plusz az "Ero es alloképesseg" (a Full body dokumentum, aminek a sajat
# fejleceben is "Strength & Conditioning" all); annak a jeloloje a jelmagyarazat hatszoge.
KATEGORIAK = [
    ("Fej",           "Headache & Eye Ache",   ["headache", "eyeache"], (404, 78), "bal"),
    ("Nyak",          "Head & Neck",           ["neck"],       (1219, 206),  "jobb"),
    ("Váll",          "Shoulder",              ["shoulder1", "shoulder2"], (1076, 329), "jobb"),
    ("Mellkas",       "Chest",                 ["chest"],      (406, 406),   "bal"),
    ("Alsó mellkas",  "Lower Thorax",          ["thorax"],     (1219, 418),  "jobb"),
    ("Könyök",        "Lateral Elbow",         ["elbow"],      (601, 520),   "bal"),
    ("Csukló",        "Carpal Tunnel / Pinch", ["wrist"],      (117, 715),   "bal"),
    ("Kéz",           "Hand",                  ["hand1", "hand2"], (901, 778), "jobb"),
    ("Has",           "Abdomen / Incontinence", ["abdomen"],   (404, 654),   "bal"),
    ("Derék",         "Low Back & Buttock",    ["lowback1", "lowback2"], (1218, 677), "jobb"),
    ("Lágyék",        "Groin",                 ["groin"],      (373, 848),   "bal"),
    ("Csípő",         "Hip",                   ["hip"],        (1340, 832),  "jobb"),
    ("Elülső comb",   "Anterior Thigh",        ["thigh"],      (495, 966),   "bal"),
    ("Hátsó comb",    "Posterior Thigh",       ["postthigh"],  (1160, 992),  "jobb"),
    ("Térd",          "Anterior Knee",         ["knee"],       (346, 1173),  "bal"),
    ("Lábikra",       "Calf",                  ["calf"],       (1271, 1336), "jobb"),
    # VEGSO ALLAS, Marci dontese 2026-10-22 14:49 (Telegram 10569), szo szerint:
    # "A 17. legyen Boka es a 18. Lab. Ezeknek megfeleloen a kategoria neveket is
    # valtoztasd meg a megfelelo oldlakon." A cim a valasztolapon ugyanebbol a
    # tablabol jon, tehat a nev-csere ott is atmegy, kulon lepes nelkul.
    # ELOZMENY, hogy egy kesobbi kor ne forgassa vissza: 14:23-kor meg azt kerte,
    # hogy a 17. legyen labfej; 14:44-kor jelezte, hogy ez igy rossz; 14:49-kor adta
    # meg a neveket; 14:57-kor pedig KEPPEL, egyertelmuen a JELOLOKET is: "A bal
    # oldali az legyen 17. szamu es a neve legyen Boka. A jobb oldali pedig legyen
    # 18. szamu es a neve legyen Lab." (Telegram 10573.)
    # EZERT all a Boka a BAL oldali (elolnezeti) jelolon es a Lab a JOBB oldalin
    # (hatulnezet). Ez az O dontese a kepre nezve; a dokumentum-parositas valtozatlan
    # (Boka = Achilles Tendinopathy, Lab = Dorsal Foot).
    ("Boka",          "Achilles Tendinopathy", ["ankle"],      (460, 1565),  "bal"),
    ("Láb",           "Dorsal Foot",           ["foot"],       (1179, 1625), "jobb"),
    ("Erő és állóképesség", "Strength & Conditioning", ["fullbody"], (656, 1163), "kozep"),
]

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def fajl(kulcs: str) -> str:
    return os.path.join(FORRAS, f"CareWear-{kulcs}-magyar.pdf")


def _lila(a: np.ndarray) -> np.ndarray:
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    return (abs(r - 204) < 35) & (abs(g - 39) < 45) & (abs(b - 176) < 35)


def _savok(a: np.ndarray):
    """A modul-kartyak also lila savja.

    SZUKITES, MERT A LILA MAS IS LEHET: a fejlec-szoveg es a vekony elvalaszto vonalak is
    lilak. Valodi sav csak az, ami legalabb 30 px magas ES legalabb 800 px szeles.
    """
    m = _lila(a)
    ys = np.where(m.sum(axis=1) > 100)[0]
    if len(ys) == 0:
        return []
    cs, s, pr = [], ys[0], ys[0]
    for y in ys[1:]:
        if y > pr + 1:
            cs.append((int(s), int(pr))); s = y
        pr = y
    cs.append((int(s), int(pr)))
    hatar = int(a.shape[0] * 30 / 1651), int(a.shape[1] * 800 / 1275)
    ki = []
    for (y0, y1) in cs:
        if y1 - y0 + 1 < hatar[0]:
            continue
        osz = np.where(m[y0:y1 + 1].sum(axis=0) > (y1 - y0 + 1) * 0.4)[0]
        if len(osz) < hatar[1]:
            continue
        ki.append((y0, y1, int(osz.min()), int(osz.max())))
    return ki


def kartyak(utvonal: str):
    """Egy dokumentum modul-kartyai kepkent, oldalrol oldalra, sorrendben.

    Egy kartya a lila savjaval zarul, es ott kezdodik, ahol az elozo savja vegzodott.
    A kartya folotti ures sorokat levagjuk -- ez a "legyen folyamatos" keres lenyege.
    """
    d = pdfium.PdfDocument(utvonal)
    fejlec_px = int(FEJLEC_ALJA_PT * DPI / 72)
    ki = []
    for pg in d:
        a = np.array(pg.render(scale=DPI / 72).to_pil().convert("RGB"))
        elozo = fejlec_px
        for (y0, y1, x0, x1) in _savok(a):
            szelet = a[elozo:y1 + 1]
            elozo = y1 + 1
            nf = (szelet < 243).any(axis=2)
            sorok = np.where(nf.any(axis=1))[0]
            if len(sorok) == 0:
                continue
            oszlopok = np.where(nf.any(axis=0))[0]
            vagott = szelet[sorok.min():sorok.max() + 1, oszlopok.min():oszlopok.max() + 1]
            ki.append(Image.fromarray(vagott))
    return ki


def _cimlap(c, w, h, kezdoOldal):
    """Cimlap: a ket emberi alak, es minden jelolohoz vonal + sorszamozott kategoria-nev.

    Marci kerese, 2026-10-22 13:35 (Telegram 10535): "vonalak mutatnak az abran levo
    pontokra es mindegyik kiirja hogy az melyik kategoria. Sorszamozva."
    """
    c.setFont("DejaVuSans-Bold", 20)
    c.drawCentredString(w / 2, h - 46, "CareWear fénytapasz")
    c.setFont("DejaVuSans", 11)
    c.drawCentredString(w / 2, h - 64, "Kezelési útmutató – teljes, magyar nyelvű kiadás")

    vagott = Image.open(ABRA).convert("RGB").crop(ABRA_VAGAS)
    iw, ih = vagott.size
    kep_sz = 408.0
    ar = kep_sz / iw
    kep_mag = ih * ar
    kep_x = (w - kep_sz) / 2
    # fuggolegesen kozepre, a cim es a labjegyzet koze
    kep_y = 70.0 + ((h - 80.0) - 70.0 - kep_mag) / 2
    c.drawImage(ImageReader(vagott), kep_x, kep_y, kep_sz, kep_mag)

    def pont(jel):
        px, py = jel
        return kep_x + px * ar, kep_y + kep_mag - py * ar

    bal = [(n, hu, jel) for n, (hu, _e, _k, jel, old) in enumerate(KATEGORIAK, 1) if old == "bal"]
    jobb = [(n, hu, jel) for n, (hu, _e, _k, jel, old) in enumerate(KATEGORIAK, 1) if old == "jobb"]
    kozep = [(n, hu) for n, (hu, _e, _k, _j, old) in enumerate(KATEGORIAK, 1) if old == "kozep"]

    # A strength tetel cimkeje KOZEPRE megy, az angol jelmagyarazo szoveg ALA, vonallal.
    # Marci kerese, 2026-10-22 13:50 (Telegram 10551): "Az ero allokepesseg felirat kozepre
    # kerueljon, az angol szoveg ala, vonallal. Es igy nem fog belelogni a tobbibe."
    # A jelmagyarazat szovegenek merete a vagott abran: y 1136-1227, x 680-927.
    for n, hu in kozep:
        kx = kep_x + ((680 + 927) / 2) * ar
        felso = kep_y + kep_mag - 1227 * ar          # a szoveg alja
        c.setLineWidth(0.6)
        c.setStrokeColorRGB(0.45, 0.45, 0.45)
        c.line(kx, felso - 3, kx, felso - 13)
        c.setFont("DejaVuSans", 7)
        c.drawCentredString(kx, felso - 22, f"{n}. {hu}")
        c.setFont("DejaVuSans", 6)
        c.setFillColorRGB(0.45, 0.45, 0.45)
        c.drawCentredString(kx, felso - 30.5, f"{kezdoOldal.get(n, 0)}. oldal")
        c.setFillColorRGB(0, 0, 0)
        c.setStrokeColorRGB(0, 0, 0)

    c.setLineWidth(0.4)
    c.setStrokeColorRGB(0.45, 0.45, 0.45)
    for lista, oldal in ((bal, "bal"), (jobb, "jobb")):
        lista.sort(key=lambda t: t[2][1])
        felso = kep_y + kep_mag
        also = kep_y
        lepes = (felso - also) / max(len(lista), 1)
        for i, (n, hu, jel) in enumerate(lista):
            cy = felso - lepes * (i + 0.5)
            jx, jy = pont(jel)
            # Az oldalszam a nev ALATT all, kisebb es halvanyabb: Marci kerese,
            # 2026-10-22 14:23 (Telegram 10561), "legyen oldalszam, hogy honnan
            # kezdodik a kategoria". A vonal a NEV sorahoz kotodik, nem a
            # szamhoz, kulonben a mutato elcsuszna a jelolotol.
            szam = f"{kezdoOldal.get(n, 0)}. oldal"
            if oldal == "bal":
                cx = MARGO_X + 2
                c.setFont("DejaVuSans", 7)
                c.drawString(cx, cy - 2.5, f"{n}. {hu}")
                hossz = c.stringWidth(f"{n}. {hu}", "DejaVuSans", 7)
                c.setFont("DejaVuSans", 6)
                c.setFillColorRGB(0.45, 0.45, 0.45)
                c.drawString(cx, cy - 11, szam)
                c.setFillColorRGB(0, 0, 0)
                c.line(cx + hossz + 3, cy, jx - 3, jy)
            else:
                cx = w - MARGO_X - 2
                c.setFont("DejaVuSans", 7)
                c.drawRightString(cx, cy - 2.5, f"{n}. {hu}")
                hossz = c.stringWidth(f"{n}. {hu}", "DejaVuSans", 7)
                c.setFont("DejaVuSans", 6)
                c.setFillColorRGB(0.45, 0.45, 0.45)
                c.drawRightString(cx, cy - 11, szam)
                c.setFillColorRGB(0, 0, 0)
                c.line(cx - hossz - 3, cy, jx + 3, jy)
    c.setStrokeColorRGB(0, 0, 0)

    c.setFont("DejaVuSans", 8)
    c.drawCentredString(w / 2, 58, "Elölnézet és hátulnézet – a sorszám a kategória sorszáma a dokumentumban")
    c.showPage()


def _cim(c, w, h, hu, en, n):
    c.setFont("DejaVuSans-Bold", 24)
    c.drawString(MARGO_X, h - MARGO_FENT - 18, hu)
    c.setFont("DejaVuSans", 11)
    c.drawString(MARGO_X, h - MARGO_FENT - 33, en)
    c.setFont("DejaVuSans", 9)
    c.drawRightString(w - MARGO_X, h - MARGO_FENT - 18, f"{n}. kategória")
    c.setLineWidth(1.2)
    c.line(MARGO_X, h - MARGO_FENT - 42, w - MARGO_X, h - MARGO_FENT - 42)


def main() -> int:
    """KET MENETBEN epul, es ez nem korulmenyesseg.

    A cimlapon ott kell allnia, melyik oldalon kezdodik egy kategoria (Marci kerese,
    2026-10-22 14:23). Ezt a szamot viszont csak akkor tudjuk, amikor a tartalom mar
    el van tordelve. Ezert eloszor a TARTALOM keszul el (es kozben feljegyezzuk a
    kezdo oldalakat), es csak utana a cimlap -- a vegso dokumentumban a cimlap az
    elso lap, tehat a kategoria kezdo oldala a tartalmon beluli indexe + 2.
    """
    pdfmetrics.registerFont(TTFont("DejaVuSans", FONT))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", FONT_B))
    w, h = 612.0, 792.0
    szeles = w - 2 * MARGO_X

    # --- 1. menet: a tartalom ------------------------------------------------
    tartalom = io.BytesIO()
    c = canvas.Canvas(tartalom, pagesize=(w, h))
    kezdoOldal: dict[int, int] = {}
    konyvjelzo: list[tuple[str, int]] = []
    oldal = 0            # a tartalmon beluli, 0-tol indulo lapszam
    osszes_kartya = 0

    for n, (hu, en, kulcsok, _jel, _old) in enumerate(KATEGORIAK, start=1):
        kepek = []
        for k in kulcsok:
            kepek.extend(kartyak(fajl(k)))
        osszes_kartya += len(kepek)
        kezdoOldal[n] = oldal + 2        # +1 cimlap, +1 mert a lapszam 1-tol indul
        konyvjelzo.append((f"{n}. {hu}", oldal + 1))
        _cim(c, w, h, hu, en, n)
        y = h - MARGO_FENT - CIM_MAGAS
        for kep in kepek:
            iw, ih = kep.size
            mag = szeles * ih / iw
            if y - mag < MARGO_LENT and y < h - MARGO_FENT - 6:
                c.showPage(); oldal += 1
                y = h - MARGO_FENT
            c.drawImage(ImageReader(kep), MARGO_X, y - mag, szeles, mag)
            y -= mag + KARTYA_KOZ
        c.showPage(); oldal += 1

    c.save()

    # --- 2. menet: a cimlap, mar a kesz oldalszamokkal ------------------------
    fedlap = io.BytesIO()
    cf = canvas.Canvas(fedlap, pagesize=(w, h))
    _cimlap(cf, w, h, kezdoOldal)
    cf.save()

    ki = PdfWriter()
    ki.add_page(PdfReader(io.BytesIO(fedlap.getvalue())).pages[0])
    for lap in PdfReader(io.BytesIO(tartalom.getvalue())).pages:
        ki.add_page(lap)
    ki.add_outline_item("Áttekintő ábra", 0)
    for cim, idx in konyvjelzo:
        ki.add_outline_item(cim, idx)
    with open(KIMENET, "wb") as f:
        ki.write(f)
    print(f"kesz: {KIMENET} ({os.path.getsize(KIMENET)} bajt, {len(ki.pages)} oldal, "
          f"{len(KATEGORIAK)} kategoria, {osszes_kartya} kartya)")
    print("kategoria kezdolapok: " + ", ".join(
        f"{n}.{KATEGORIAK[n-1][0]}={kezdoOldal[n]}" for n in sorted(kezdoOldal)))
    return 0


def tomorit(be: str, ki_utvonal: str, dpi: int = 150, minoseg: int = 82) -> str:
    """Telegram-barat valtozat: minden lap JPEG-kent, azonos lapmereten.

    MIERT KELL: a teljes felbontasu valtozat tobb szaz MB, a Telegram hatara 50 MB. A
    tartalom amugy is raszter (a kartyak szovege a kepekben van), tehat az ujraraszterezes
    nem vesz el vektoros reszletet.
    """
    d = pdfium.PdfDocument(be)
    r = PdfReader(be)
    w = float(r.pages[0].mediabox.width); h = float(r.pages[0].mediabox.height)
    c = canvas.Canvas(ki_utvonal, pagesize=(w, h))
    for pg in d:
        im = pg.render(scale=dpi / 72).to_pil().convert("RGB")
        b = io.BytesIO()
        im.save(b, "JPEG", quality=minoseg, optimize=True, subsampling=0)
        b.seek(0)
        c.drawImage(ImageReader(b), 0, 0, w, h)
        c.showPage()
    c.save()
    return ki_utvonal


if __name__ == "__main__":
    raise SystemExit(main())
