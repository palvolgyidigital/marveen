#!/usr/bin/env python3
"""QR-matrica generalo a csomagolashoz: SKU-nkent EGY fix kod, A4-es matricaivre.

MARCI DONTESE, 2026-10-13 10:54 (Telegram 9329), szo szerint: "Szerintem sku-kent
legyen 1-1 kod es akkor mindig az adott termekhez csak ki kell nyomtatni a megfeleloT".
Ezert a kod a SKU-bol SZAMOLHATO, nem adatbazisbol jon: ugyanaz a SKU mindig ugyanazt
a kodot adja, barmikor, barmelyik gepen. Nincs kod-nyilvantartas, amit szinkronban
kellene tartani.

A VIDEO-OLDAL NEM EZ A SZKRIPT DOLGA. Marci ugyanabban az uzenetben: "A videot most
hagyjuk, majd azokat en elintezem." A QR egy sajat, ATIRANYITHATO URL-re mutat
(--base-url), tehat a cel kesobb valtozhat anelkul, hogy a mar felragasztott
matricak ervenyuket vesztenek. EZ A FIX-KOD DONTES EGYENES KOVETKEZMENYE: egy
kozvetlen videolink egy kinyomtatott matrican nem javithato.

HASZNALAT
---------
  # egy rendeles matricai (SKU,darab soronkent), ez a raktari alapeset:
  python3 scripts/qr-matrica.py --rendeles rendeles.csv -o /tmp/matricak.pdf

  # nevesitett SKU-k, egy-egy darab:
  python3 scripts/qr-matrica.py --sku AG-C130,UL-3328 -o /tmp/minta.pdf

  # teljes keszlet (2900+ SKU, kb. 140 lap) -- eloregyartott keszlethez:
  python3 scripts/qr-matrica.py --mind -o /tmp/teljes.pdf

A terméknevet a Next-exportbol veszi (--nev-forras), ha megtalalja a SKU-t. Ha nem,
a matricara CSAK a SKU kerul. NEM talal ki nevet.

MIERT NEM A 70x37-ES, 24-ES IV AZ ALAPERTELMEZES (merve 2026-10-13):
az a kiosztas peremmentes (3 x 70 = 210 mm, pont az A4 szelessege), a hazi
EPSONFB7AC5 (ET-5170) viszont korben kb. 3 mm holtsavot hagy, tehat a szelso
oszlopok csonkulnanak. Az alapertelmezes ezert az Avery L7160 geometria
(63,5 x 38,1 mm, 3 x 7 = 21 db/lap, 7,2 mm oldalmargo), ami bofer a nyomtathato
teruleten belul van. Mas ivhez a --geometria kapcsolo van.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

# --- iv-geometriak, mm-ben:
#     (cella_sz, cella_ma, bal_margo, felso_margo, oszlop, sor, hezag_x, hezag_y)
#
# A HEZAG 2026-10-14-EN KERULT BE, ES EZ HIBAJAVITAS VOLT, NEM BOVITES.
# Addig a kiosztas HEZAG NELKUL szamolt (x = bal + k * cella_sz), vagyis a cellak
# egymashoz ertek. A valodi iveken viszont az oszlopok kozott 2,5 mm hezag van, es
# ettol a kiosztas BALRA CSUSZIK, oszloponkent kumulalva. Merve 2026-10-14:
#     l7160 (EZ VOLT AZ ALAPERTELMEZES): a 3. oszlop 5,10 mm-rel balra
#     l7651:                              az 5. oszlop 10,10 mm-rel balra
#     70x37:                              0,00 mm, mert az iv tenyleg peremmentes
# AZ ARULKODO JEL, es barmelyik uj geometrianal ezt kell nezni: ha a BAL es a JOBB
# margo nem egyenlo, a hezag hianyzik. A regi l7160-nal bal=7,20 / jobb=12,30 volt,
# az l7651-nel bal=4,70 / jobb=14,80. Egy helyesen megadott iven a ketto egyenlo.
GEOMETRIAK = {
    # Avery L7160 / 3422: 21 db, van oldalmargo -> hazi A4-es nyomtatora is jo
    "l7160": (63.5, 38.1, 7.2, 15.1, 3, 7, 2.55, 0.0),
    # 70x37, 24 db: peremmentes, CSAK olyan nyomtatora, ami a szelere is nyomtat
    "70x37": (70.0, 37.0, 0.0, 0.5, 3, 8, 0.0, 0.0),
    # Fortuna / Avery L7651: 65 db, kicsi -- csak akkor, ha a QR 15 mm-en is beolvashato
    "l7651": (38.1, 21.2, 4.7, 10.7, 5, 13, 2.52, 0.0),
}

ALAP_URL = "https://www.pdb.hu/v/"
ALAP_NEV_FORRAS = "/home/pdb/marveen/store/as-agent/inputs/PDB_keszlet_2026-10-13.xlsx"

# KET URL-SEMA VAN, ES A MASODIK MA MERT FELFEDEZES (2026-10-13, elesben):
#   "v"   -> <base-url><SKU>, pl. https://www.pdb.hu/v/AG-C130
#            Ehhez SZERVER-OLDALI ATIRANYITAS kell, ami MEG NINCS beallitva.
#            A cel kesobb szabadon valtoztathato, ezert ez a vegallapot.
#   "spd" -> https://www.pdb.hu/spd/<SKU>/x, vagyis a MEGLEVO UNAS termekoldal.
#            MERVE: a slug csak dekoracio, a /spd/UL-3328/x es a /spd/UL-2502E/x is
#            200-at ad, es a helyes termek lapjat adja. A CSUPASZ /spd/<SKU> viszont
#            404, slug nelkul nem megy -- ezert all ott az "/x".
#            Ez ma, atiranyitas NELKUL mukodik, tehat ezzel el lehet indulni.
URL_SEMAK = {
    "v": lambda base, sku: base + sku,
    "spd": lambda base, sku: f"https://www.pdb.hu/spd/{sku}/x",
}


def nevek_betoltese(utvonal: str) -> tuple[dict[str, str], dict[str, str]]:
    """(nevek, feloldo) a Next-exportbol.

    KETTO AZONOSITO VAN, ES EZT MERTEM, NEM FELTETTEM (2026-10-13): a Next
    `Cikkszam` oszlopa BELSO, NUMERIKUS azonosito (10, 13, 23...), az UNAS-os SKU
    (pl. `AG-C130`) a `Gyartoi cikkszam` oszlopban all. A QR a SKU-ra epul, mert
    Marci azt mondta ki, es mert az allandobb: a belso szam a Nexthez tartozik.
    DE a raktar papirjan a BELSO szam is szerepelhet, ezert a `feloldo` a belso
    szamrol is a SKU-ra kepez, igy mindkettot be lehet irni.

    Hiba eseten URES dictek, nem kivetel: a nev dekoracio, a SKU es a QR az ertek.
    """
    if not utvonal or not os.path.exists(utvonal):
        return {}, {}
    try:
        import pandas as pd

        df = pd.read_excel(utvonal, engine="calamine")
    except Exception as exc:  # noqa: BLE001
        print(f"[figyelem] a nev-forras nem olvashato ({exc!r}), a matricakra csak SKU kerul", file=sys.stderr)
        return {}, {}

    def oszlop(*nevek):
        for c in df.columns:
            if str(c).strip().lower() in nevek:
                return c
        return None

    belso = oszlop("cikkszám", "cikkszam")
    sku_col = oszlop("gyártói cikkszám", "gyartoi cikkszam", "sku")
    megnevezes = oszlop("megnevezés", "megnevezes", "név", "nev")
    if sku_col is None or megnevezes is None:
        print("[figyelem] a nev-forrasban nincs Gyartoi cikkszam / Megnevezes oszlop", file=sys.stderr)
        return {}, {}

    nevek: dict[str, str] = {}
    feloldo: dict[str, str] = {}
    belso_sor = df[belso] if belso is not None else [None] * len(df)
    for sku, nev, bsz in zip(df[sku_col], df[megnevezes], belso_sor):
        s = str(sku).strip()
        if not s or s.lower() == "nan":
            continue
        n = str(nev).strip()
        if s not in nevek:
            nevek[s] = "" if n.lower() == "nan" else n
        if bsz is not None:
            b = str(bsz).strip()
            if b.endswith(".0"):
                b = b[:-2]
            if b and b.lower() != "nan" and b not in feloldo and b != s:
                feloldo[b] = s
    return nevek, feloldo


def tetelek_rendelesbol(utvonal: str) -> list[tuple[str, int]]:
    """SKU,darab paroknak olvassa. A darab hianyaban 1. A fejlecsort atlepi."""
    tetelek: list[tuple[str, int]] = []
    with open(utvonal, encoding="utf-8-sig", newline="") as fh:
        for sor in csv.reader(fh):
            if not sor or not sor[0].strip():
                continue
            sku = sor[0].strip()
            if sku.lower() in ("sku", "cikkszám", "cikkszam"):
                continue
            db = 1
            if len(sor) > 1 and sor[1].strip():
                try:
                    db = max(1, int(float(sor[1].strip().replace(",", "."))))
                except ValueError:
                    db = 1
            tetelek.append((sku, db))
    return tetelek


def sku_lista_fajlbol(utvonal: str) -> list[str]:
    out = []
    with open(utvonal, encoding="utf-8-sig") as fh:
        for s in fh:
            s = s.strip()
            if s and s.lower() not in ("sku", "cikkszám", "cikkszam"):
                out.append(s)
    return out


def rovidit(szoveg: str, font: str, meret: float, max_sz: float) -> str:
    if not szoveg:
        return ""
    if pdfmetrics.stringWidth(szoveg, font, meret) <= max_sz:
        return szoveg
    while szoveg and pdfmetrics.stringWidth(szoveg + "...", font, meret) > max_sz:
        szoveg = szoveg[:-1]
    return szoveg + "..." if szoveg else ""


def matrica(c: canvas.Canvas, x: float, y: float, sz: float, ma: float,
            sku: str, nev: str, url: str, keret: bool) -> None:
    """Egy matrica: QR balra, SKU es nev jobbra. (x, y) a cella BAL ALSO sarka."""
    belso = 2.0 * mm
    if keret:
        c.setLineWidth(0.25)
        c.setDash(1, 2)
        c.rect(x, y, sz, ma)
        c.setDash()

    qr_meret = min(ma - 2 * belso, sz * 0.42)
    w = qr.QrCodeWidget(url, barLevel="M")
    b = w.getBounds()
    bw, bh = b[2] - b[0], b[3] - b[1]
    d = Drawing(qr_meret, qr_meret, transform=[qr_meret / bw, 0, 0, qr_meret / bh, 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x + belso, y + (ma - qr_meret) / 2)

    tx = x + belso + qr_meret + 1.5 * mm
    max_sz = x + sz - belso - tx
    if max_sz <= 0:
        return
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(tx, y + ma - belso - 7, rovidit(sku, "Helvetica-Bold", 8, max_sz))
    if nev:
        c.setFont("Helvetica", 5.6)
        szavak, sorok, akt = nev.split(), [], ""
        for sz_ in szavak:
            proba = (akt + " " + sz_).strip()
            if pdfmetrics.stringWidth(proba, "Helvetica", 5.6) <= max_sz:
                akt = proba
            else:
                if akt:
                    sorok.append(akt)
                akt = sz_
            if len(sorok) >= 3:
                break
        if akt and len(sorok) < 3:
            sorok.append(akt)
        yy = y + ma - belso - 15
        for s in sorok[:3]:
            c.drawString(tx, yy, rovidit(s, "Helvetica", 5.6, max_sz))
            yy -= 6.6
    c.setFont("Helvetica", 4.8)
    c.setFillGray(0.45)
    c.drawString(tx, y + belso + 1, rovidit(url, "Helvetica", 4.8, max_sz))
    c.setFillGray(0)


def main() -> int:
    ap = argparse.ArgumentParser(description="QR-matrica PDF a csomagolashoz, SKU-nkent fix koddal")
    forras = ap.add_mutually_exclusive_group(required=True)
    forras.add_argument("--rendeles", help="CSV: SKU,darab soronkent (a raktari alapeset)")
    forras.add_argument("--sku", help="vesszovel valasztott SKU-k")
    forras.add_argument("--sku-file", help="fajl, soronkent egy SKU")
    forras.add_argument("--mind", action="store_true", help="a teljes elo keszlet a nev-forrasbol")
    ap.add_argument("-o", "--out", required=True, help="a kimeneti PDF utvonala")
    ap.add_argument("--db", type=int, default=1, help="ismetles SKU-nkent (--rendeles nelkul)")
    ap.add_argument("--base-url", default=ALAP_URL, help=f"a QR cel-elotagja a 'v' semanal (alap: {ALAP_URL})")
    ap.add_argument("--url-sema", default="v", choices=sorted(URL_SEMAK),
                    help="'v' = sajat atiranyitas (meg nincs beallitva), "
                         "'spd' = a meglevo UNAS termekoldal (/spd/<SKU>/x, ma mukodik)")
    ap.add_argument("--nev-forras", default=ALAP_NEV_FORRAS, help="Next-export a megnevezesekhez")
    ap.add_argument("--geometria", default="l7160", choices=sorted(GEOMETRIAK),
                    help="matricaiv-kiosztas (alap: l7160, mert van oldalmargoja)")
    ap.add_argument("--keret", action="store_true", help="szaggatott vagoel, csak sima papirra")
    args = ap.parse_args()

    nevek, feloldo = nevek_betoltese(args.nev_forras)

    if args.rendeles:
        tetelek = tetelek_rendelesbol(args.rendeles)
    else:
        if args.mind:
            skuk = sorted(nevek)
            if not skuk:
                print("HIBA: a --mind a nev-forrasbol veszi a SKU-kat, de az nem olvashato.", file=sys.stderr)
                return 2
        elif args.sku:
            skuk = [s.strip() for s in args.sku.split(",") if s.strip()]
        else:
            skuk = sku_lista_fajlbol(args.sku_file)
        tetelek = [(s, max(1, args.db)) for s in skuk]

    if not tetelek:
        print("HIBA: nulla tetel, nincs mit nyomtatni.", file=sys.stderr)
        return 2

    _g = GEOMETRIAK[args.geometria]
    cella_sz, cella_ma, bal, felso = (v * mm for v in _g[:4])
    oszlop, sor = _g[4], _g[5]
    hezag_x, hezag_y = _g[6] * mm, _g[7] * mm
    per_lap = oszlop * sor
    c = canvas.Canvas(args.out, pagesize=A4)
    lap_sz, lap_ma = A4

    i = 0
    ismeretlen = []
    feloldott = []
    for sku, db in tetelek:
        if sku not in nevek and sku in feloldo:
            # a raktar a Next BELSO cikkszamat adta meg; a QR-re a SKU kell
            feloldott.append((sku, feloldo[sku]))
            sku = feloldo[sku]
        nev = nevek.get(sku)
        if nev is None:
            ismeretlen.append(sku)
            nev = ""
        for _ in range(db):
            if i and i % per_lap == 0:
                c.showPage()
            poz = i % per_lap
            r, k = divmod(poz, oszlop)
            x = bal + k * (cella_sz + hezag_x)
            y = lap_ma - felso - (r + 1) * cella_ma - r * hezag_y
            matrica(c, x, y, cella_sz, cella_ma, sku, nev,
                    URL_SEMAK[args.url_sema](args.base_url, sku), args.keret)
            i += 1
    c.save()

    lapok = (i + per_lap - 1) // per_lap
    print(f"OK: {i} matrica, {lapok} lap, geometria={args.geometria} ({per_lap}/lap) -> {args.out}")
    minta = URL_SEMAK[args.url_sema](args.base_url, "<SKU>")
    print(f"QR-cel ({args.url_sema} sema): {minta}")
    if args.url_sema == "v":
        print("FIGYELEM: a 'v' sema szerver-oldali atiranyitast igenyel, ami MEG NINCS "
              "beallitva. Elo nyomtatashoz --url-sema spd kell, az ma mukodik.")
    if feloldott:
        print(f"BELSO CIKKSZAMROL SKU-RA FELOLDVA ({len(feloldott)}): "
              + ", ".join(f"{b}->{s}" for b, s in feloldott[:10])
              + (" ..." if len(feloldott) > 10 else ""))
    if ismeretlen:
        print(f"MEGNEVEZES NELKUL ({len(ismeretlen)} SKU, csak a kod kerult a matricara): "
              f"{', '.join(ismeretlen[:10])}{' ...' if len(ismeretlen) > 10 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
