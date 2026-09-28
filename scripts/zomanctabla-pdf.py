#!/usr/bin/env python3
"""A zomanctabla-tablazat vevoi valtozatabol telefonon is megnyilo PDF.

Marci kerese (2026-09-25 14:32): a lehetseges vasarlo iPhone-jan a kapott fajl nem
jelent meg rendesen, a kepek nem toltottek be. Egy XLSX beagyazott kepekkel iOS-en
tenyleg rosszul jon vissza; a PDF viszont a rendszer sajat nezegetojevel nyilik.

Amit a telefonos megnyithatosagert teszunk, es MINDEGYIK szandekos:
  - JPEG, nem PNG: kisebb, es minden nezegeto tudja
  - a kepek 1600 px hosszabb oldalra skalazva: a 67 kep igy nehany MB, nem 30
  - beagyazott DejaVu betu: a magyar o" es u" kulonben kiesik a szovegbol
  - egyetlen oszlop, nagy kep + alatta a nev: telefonon fuggolegesen gorgetheto

Hasznalat: zomanctabla-pdf.py [forras.xlsx] [cel.pdf]
"""
import io
import re
import sys
import zipfile

import pandas as pd
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

SRC = sys.argv[1] if len(sys.argv) > 1 else "/home/pdb/marveen/store/zomanctablak-2026-09-22-vevoi.xlsx"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/pdb/marveen/store/zomanctablak-2026-09-22-vevoi.pdf"
MAX_PX = 1600
JPEG_Q = 82
MARGIN = 14 * mm

pdfmetrics.registerFont(TTFont("DejaVu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))


def wrap(c, text, width, font, size):
    """Sortores a rendelkezesre allo szelessegre, a tenyleges betuszelesseggel."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if c.stringWidth(probe, font, size) <= width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def main():
    df = pd.read_excel(SRC, engine="calamine")
    nevek = [str(v).strip() for v in df["Megnevezés"].fillna("")]

    z = zipfile.ZipFile(SRC)
    rels = {i: t for t, i in re.findall(r'Target="([^"]+)"\s+Id="(rId\d+)"',
                                        z.read("xl/drawings/_rels/drawing1.xml.rels").decode())}
    anchors = re.findall(r"<row>(\d+)</row>.*?r:embed=\"(rId\d+)\"",
                         z.read("xl/drawings/drawing1.xml").decode(), re.S)
    # a rajz sorszama 0-alapu es az elso sor a fejlec, tehat a sor N a df N-1. eleme
    sor_kep = {int(r) - 1: rels[i].lstrip("/") for r, i in anchors}

    W, H = A4
    c = canvas.Canvas(OUT, pagesize=A4)
    c.setTitle("Zománctáblák")
    c.setAuthor("Pálvölgyi-Digital")

    # RACS, NEM EGESZ OLDAL. A forras-kepek 195x260 pixelesek (a Drive-rol ekkora
    # bejegyzes-kep kerult az Excelbe), tehat egy A4-es oldalra felnagyitva
    # pixelesek lennenek. Hat kep egy oldalon ~90 dpi-t ad, ami telefonon tiszta.
    COLS, ROWS = 2, 3
    GUT = 8 * mm
    cell_w = (W - 2 * MARGIN - (COLS - 1) * GUT) / COLS
    cell_h = (H - 2 * MARGIN - 18 * mm - (ROWS - 1) * GUT) / ROWS
    cap_h = 26

    def fejlec(oldal):
        c.setFont("DejaVu-Bold", 15)
        c.drawString(MARGIN, H - MARGIN - 4, "Zománctáblák")
        c.setFont("DejaVu", 9)
        c.drawRightString(W - MARGIN, H - MARGIN - 4, f"{len(nevek)} tétel")
        c.setLineWidth(0.5)
        c.line(MARGIN, H - MARGIN - 12, W - MARGIN, H - MARGIN - 12)
        c.setFont("DejaVu", 8)
        c.drawRightString(W - MARGIN, MARGIN / 2, str(oldal))

    hiany = []
    oldal = 1
    fejlec(oldal)
    for idx, nev in enumerate(nevek):
        pos = idx % (COLS * ROWS)
        if idx and pos == 0:
            c.showPage()
            oldal += 1
            fejlec(oldal)
        col, row = pos % COLS, pos // COLS
        x0 = MARGIN + col * (cell_w + GUT)
        y_top = H - MARGIN - 18 * mm - row * (cell_h + GUT)

        media = sor_kep.get(idx)
        if media:
            im = Image.open(io.BytesIO(z.read(media)))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=JPEG_Q, optimize=True)
            buf.seek(0)
            sc = min(cell_w / im.width, (cell_h - cap_h) / im.height)
            w, h = im.width * sc, im.height * sc
            c.drawImage(ImageReader(buf), x0 + (cell_w - w) / 2, y_top - h, w, h)
            y = y_top - (cell_h - cap_h) - 10
        else:
            hiany.append(idx + 1)
            y = y_top - 14

        c.setFont("DejaVu", 8.5)
        c.drawString(x0, y, f"{idx + 1}.")
        c.setFont("DejaVu-Bold", 8.5)
        for line in wrap(c, nev, cell_w - 14, "DejaVu-Bold", 8.5)[:2]:
            c.drawString(x0 + 14, y, line)
            y -= 10

    c.save()
    print(f"kesz: {OUT}")
    print(f"tetel: {len(nevek)} | kep nelkuli: {len(hiany)} {hiany if hiany else ''}")


if __name__ == "__main__":
    main()
