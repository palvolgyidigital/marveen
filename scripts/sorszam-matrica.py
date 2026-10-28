#!/usr/bin/env python3
"""Sorszamozott matricaiv A4-re, szoveggel (nem QR).

MARCI KERESE, 2026-10-14 11:09 (Telegram 9454), szo szerint: "Nekunk a 38x21,2mm
verzio van, ami 65 db matricat jelent. Ehhez kene nekem az, hogy generalj le egy olyan
dokumentumot, ahol UL-1tol UL-65ig generald le ezeket a sorszamokat a matricakra".

A KEPROL AZONOSITVA: Fortuna Office ontapado etikett, 100 iv A/4, a dobozon levo
kiosztas-tablaban a "65 / 38 x 21,2 mm" cella, 5 x 13-as raccsal.

MIERT NEM A qr-matrica.py --geometria l7651 UT: ott a cellak HEZAG NELKUL kovetik
egymast (x = bal + k * cella_sz), a 65-os ivnel viszont az oszlopok kozott 2,5 mm
hezag van. Hezag nelkul az otodik oszlop 10 mm-rel balra csuszna. Ez a szkript ezert
kulon oszlop-osztast hasznal (osztas = cella_sz + hezag).

A GEOMETRIA, Avery L7651-kompatibilis:
  cimke 38,1 x 21,2 mm | 5 oszlop x 13 sor | oszlop-hezag 2,5 mm | sor-hezag 0
  oldalmargo (210 - (5*38,1 + 4*2,5)) / 2 = 4,75 mm
  felso margo (297 - 13*21,2) / 2 = 10,7 mm
Az oldalmargo 4,75 mm, a hazi EPSON holtsavja kb. 3 mm, tehat EPPEN belefer.
Ezert a --keret kapcsoloval eloszor SIMA PAPIRRA kell nyomtatni es az ivhez tartani.

HASZNALAT:
  python3 scripts/sorszam-matrica.py --elotag UL- --tol 1 --ig 65 -o /tmp/matrica.pdf
  python3 scripts/sorszam-matrica.py --elotag UL- --tol 1 --ig 65 --keret -o /tmp/proba.pdf
"""
from __future__ import annotations

import argparse

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

CELLA_SZ, CELLA_MA = 38.1, 21.2
OSZLOP, SOR = 5, 13
HEZAG_X, HEZAG_Y = 2.5, 0.0
LAP_SZ, LAP_MA = 210.0, 297.0
BAL = (LAP_SZ - (OSZLOP * CELLA_SZ + (OSZLOP - 1) * HEZAG_X)) / 2
FELSO = (LAP_MA - (SOR * CELLA_MA + (SOR - 1) * HEZAG_Y)) / 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Sorszamozott matricaiv (38x21,2 mm, 65 db/lap)")
    ap.add_argument("--elotag", default="UL-", help="a sorszam elotagja (alap: UL-)")
    ap.add_argument("--tol", type=int, default=1)
    ap.add_argument("--ig", type=int, default=65)
    ap.add_argument("--jegy", type=int, default=0, help="nullara tolt szamjegyek (0 = nincs toltes)")
    ap.add_argument("--meret", type=float, default=11.0, help="betumeret pontban")
    ap.add_argument("--keret", action="store_true", help="szaggatott vagoel, CSAK sima papirra")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    cimkek = [f"{a.elotag}{str(n).zfill(a.jegy) if a.jegy else n}" for n in range(a.tol, a.ig + 1)]
    c = canvas.Canvas(a.out, pagesize=A4)
    lapon = OSZLOP * SOR
    for i, sz in enumerate(cimkek):
        if i and i % lapon == 0:
            c.showPage()
        k = (i % lapon) % OSZLOP
        r = (i % lapon) // OSZLOP
        x = (BAL + k * (CELLA_SZ + HEZAG_X)) * mm
        y = (LAP_MA - FELSO - (r + 1) * CELLA_MA - r * HEZAG_Y) * mm
        if a.keret:
            c.setDash(1, 2)
            c.setLineWidth(0.3)
            c.setStrokeGray(0.6)
            c.rect(x, y, CELLA_SZ * mm, CELLA_MA * mm)
            c.setDash()
        c.setFillGray(0)
        c.setFont("Helvetica-Bold", a.meret)
        sz_w = c.stringWidth(sz, "Helvetica-Bold", a.meret)
        c.drawString(x + (CELLA_SZ * mm - sz_w) / 2, y + (CELLA_MA * mm - a.meret) / 2 + 1, sz)
    c.save()
    print(f"kesz: {a.out} | {len(cimkek)} cimke | {(len(cimkek) + lapon - 1) // lapon} lap")
    print(f"geometria: {CELLA_SZ}x{CELLA_MA} mm, {OSZLOP}x{SOR}, oldalmargo {BAL:.2f} mm, felso {FELSO:.2f} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
