#!/usr/bin/env python3
"""Estimate weights for EPR articles whose nearest sibling match was too weak to trust.

WHY A SECOND ESTIMATOR. `epr-hasonlo-cikk-becsles.py` proposes a sibling per article, and its
own report splits the result at a similarity of 0.30. Above that the sibling is a real relative
and its weights can be copied. Below it the sibling is often a coincidence of one shared word,
so copying its WEIGHT would be worse than a coarse figure -- while its CATEGORY guess is still
usable, because a category is a much lower-resolution claim than a kilogram.

Abel's written rule for the no-data case (card 2d3748c2) is that an estimate from the similar
category beats a blank: "barmilyen adat is jobb mint a nincs adat". This script implements
exactly that, and nothing more: the MEDIAN of the master rows in the proposed category.

WHY THE MEDIAN AND NOT THE MEAN: the master's categories hold a few very heavy items (tripods,
large lamps) next to many light ones. On 2026 Q3's "Kisgepek" the mean sits well above the bulk
of the rows, so a mean-based estimate would inflate every light article assigned to it.

WHAT IT REFUSES TO DO: articles named in --kihagy are left out entirely. Those are the
high-volume items where a wrong estimate moves the quarter's total materially, and they belong
to a human decision, not to a median.

Every output row carries `becsles_modja` so the filled return can mark which figures are
measured and which are estimated. A number that cannot be told apart from a measurement is the
thing this whole pipeline exists to prevent.

Usage:
  python3 scripts/epr-kategoria-median-becsles.py <javaslat.csv> --ki <out.csv> \
      [--max-hasonlosag 0.30] [--kihagy SKU [SKU ...]]
"""
import argparse
import csv
import io
import statistics
import sys

import pandas as pd

MESTER = "/mnt/kozos/PÉNZÜGY/EPR/CSOMAGOLÁS.xlsx"
KATEGORIA = "EPR Kategória"
MEZOK = [
    ("netto", "Nettó súly"),
    ("brutto", "Bruttó súly"),
    ("akku", "Termék akkumulátorának súlya"),
    ("doboz", "Termék csomagolásának papír doboz tartalma"),
]


def szam(v):
    try:
        return float(str(v if v is not None else 0).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("javaslat")
    ap.add_argument("--ki", required=True)
    ap.add_argument("--mester", default=MESTER)
    ap.add_argument("--max-hasonlosag", type=float, default=0.30)
    ap.add_argument("--kihagy", nargs="*", default=[])
    a = ap.parse_args()

    m = pd.read_excel(a.mester)
    if KATEGORIA not in m.columns:
        sys.exit(f"a mesterben nincs '{KATEGORIA}' oszlop")

    median = {}
    for kat, resz in m.groupby(KATEGORIA):
        egy = {}
        for kulcs, oszlop in MEZOK:
            if oszlop not in resz.columns:
                egy[kulcs] = 0.0
                continue
            ertekek = [v for v in (szam(x) for x in resz[oszlop]) if v > 0]
            egy[kulcs] = round(statistics.median(ertekek), 4) if ertekek else 0.0
        median[str(kat).strip()] = egy
        print(f"  {str(kat).strip():26s} n={len(resz):4d}  "
              + "  ".join(f"{k}={egy[k]}" for k, _ in MEZOK))

    sorok = list(csv.DictReader(io.open(a.javaslat, encoding="utf-8-sig")))
    kihagy = {str(s).strip() for s in a.kihagy}
    ki, kihagyott, nincs_kat = [], [], []

    for r in sorok:
        if szam(r.get("hasonlosag")) >= a.max_hasonlosag:
            continue
        sku = str(r.get("sku", "")).strip()
        if sku in kihagy:
            kihagyott.append(r)
            continue
        kat = str(r.get("javasolt_EPR Kategória", "")).strip()
        if kat not in median:
            nincs_kat.append(r)
            continue
        m_ = median[kat]
        ki.append({
            "sku": sku, "nev": r.get("CSZ", ""),
            "netto": m_["netto"], "brutto": m_["brutto"],
            "akku": m_["akku"], "doboz": m_["doboz"],
            "kategoria": kat, "db": szam(r.get("db")),
            "becsles_modja": f"kategoria-median ({kat})",
        })

    with io.open(a.ki, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ki[0].keys()) if ki else
                           ["sku", "nev", "netto", "brutto", "akku", "doboz",
                            "kategoria", "db", "becsles_modja"])
        w.writeheader()
        w.writerows(ki)

    print(f"\nkategoria-median becsles: {len(ki)} cikk, {sum(r['db'] for r in ki):.0f} db")
    print(f"kiirva: {a.ki}")
    if kihagyott:
        print(f"\nSZANDEKOSAN KIHAGYVA (emberi dontest var): {len(kihagyott)} cikk, "
              f"{sum(szam(r.get('db')) for r in kihagyott):.0f} db")
        for r in kihagyott:
            print(f"   {szam(r.get('db')):6.0f} db  {str(r.get('CSZ'))[:66]}")
    if nincs_kat:
        print(f"\nNINCS HASZNALHATO KATEGORIA, igy becsles sincs: {len(nincs_kat)} cikk")
        for r in nincs_kat[:10]:
            print(f"   {szam(r.get('db')):6.0f} db  {str(r.get('CSZ'))[:66]}")


if __name__ == "__main__":
    main()
