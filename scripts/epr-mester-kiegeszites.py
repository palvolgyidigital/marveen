#!/usr/bin/env python3
"""Extend the EPR master with newly researched articles, then the quarter can be recomputed.

The packaging master (CSOMAGOLAS.xlsx) is the file the quarterly script joins against. New
articles collected by hand or by sibling-matching arrive as a flat CSV with four numbers
(netto, brutto, akku, doboz) plus the EPR category. This script turns those into full master
rows, filling the remaining columns from the rules measured on 2026-09-18:

  gyujto karton      = 0,15 x brutto        (1317 of 1438 rows are exactly 0,150; the median is
                                             0,15 in all eight EPR categories)
  6 constant columns = the single value every one of the 1438 rows carries
  5 near-constant    = the dominant value (70-99% of rows), marked as a default in the report

IT DOES NOT TOUCH THE ORIGINAL. A new workbook is written; CSOMAGOLAS.xlsx stays as it is.
"""
import argparse
import sys

import pandas as pd

MESTER = "/mnt/kozos/PÉNZÜGY/EPR/CSOMAGOLÁS.xlsx"

ALLANDO = {
    "Termék gyűjtő csomagolásának papícímke tartalma": 0.0001,
    "Termék gyűjtő műanyag csomagolásának ragasztószalag tartalma": 0.0001,
    "Termék gyűjtő műanyag csomagolásának műanyag zacskó tartalma": 0.0,
    "Termék gyűjtő műanyag csomagolásának műanyag címke tartalma": 0.0,
    "Termék gyűjtő műanyag csomagolásának pántszalag tartalma": 0.0,
    "Termék gyűjtő műanyag csomagolásának zsugorfólia tartalma": 0.0,
}
URALKODO = {
    "Termék csomagolásának műanyag zacskó  tartalma": 0.001,
    "Termék csomagolásának műanyag címke tartalma": 0.0,
    "Termék csomagolásának műanyag ragasztószalag tartalma": 0.0,
    "Termék csomagolásának páralekötő tartalma": 0.0,
    "Termék csomagolásának lezáró tartalma": 0.0,
    "Termék alkáli elem tartozékának súlya": 0.0,
}
KARTON_ARANY = 0.15


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("uj", nargs="+", help="CSV(-k): sku, nev, netto, brutto, akku, doboz, kategoria")
    ap.add_argument("--ki", required=True)
    ap.add_argument("--mester", default=MESTER)
    a = ap.parse_args()

    m = pd.read_excel(a.mester, sheet_name="Munka1")
    print(f"MESTER: {len(m)} cikk, {len(m.columns)} oszlop")
    megvan = set(m["CSZ"].astype(str).str.extract(r"^\s*(\d+)")[0].dropna())

    ujak = []
    for f in a.uj:
        d = pd.read_csv(f)
        hiany = {"sku", "netto", "brutto", "kategoria"} - set(d.columns)
        if hiany:
            sys.exit(f"MEGALLOK: {f} -- hianyzo oszlop: {hiany}")
        d["_forras_fajl"] = f
        ujak.append(d)
        print(f"  {f}: {len(d)} sor")
    u = pd.concat(ujak, ignore_index=True)
    u["sku"] = u["sku"].astype(str)

    # Ures sulyu sor NEM kerulhet be: az pont a nema nullazas, ami ellen az egesz keszult.
    ures = u[pd.to_numeric(u["netto"], errors="coerce").fillna(0) <= 0]
    u = u[pd.to_numeric(u["netto"], errors="coerce").fillna(0) > 0].copy()
    if len(ures):
        print(f"  KIHAGYVA {len(ures)} sor ures vagy nulla nettoval (ezek tovabbra is hianyoznak):")
        for _, r in ures.iterrows():
            print(f"      {r['sku']}  {str(r.get('nev', ''))[:64]}")

    # ES UGYANIGY A KATEGORIA. SAJAT HIBA, merve 2026-09-18 12:2x: az elso valtozat CSAK a
    # sulyt ellenorizte. Ot sor sullyal EGYUTT, de KATEGORIA NELKUL bekerult a mesterbe, es a
    # negyedeves szkript ezeket HIANYZOKENT kezelte, mert a kategoria-oszlopot nezi. Vagyis a
    # sor ott volt, az adata is, megis nemán kiesett -- pontosan az a hibaosztaly, ami ellen
    # ez az egesz eszkoz keszult, csak eggyel beljebb. A sor sulya nem er semmit kategoria
    # nelkul, mert a beadando tabla KATEGORIANKENT osszegez.
    kat = u["kategoria"].astype(str).str.strip()
    nincs_kat = u[(u["kategoria"].isna()) | (kat == "") | (kat.str.lower() == "nan")]
    u = u[~u.index.isin(nincs_kat.index)].copy()
    if len(nincs_kat):
        print(f"  KIHAGYVA {len(nincs_kat)} sor SULLYAL, DE KATEGORIA NELKUL. Ezek a negyedeves "
              f"tablabol ugyanugy kiesnenek, csak eszrevetlenebbul:")
        for _, r in nincs_kat.iterrows():
            print(f"      {r['sku']}  netto={r['netto']}  {str(r.get('nev', ''))[:52]}")

    utkozes = set(u["sku"]) & megvan
    if utkozes:
        print(f"  FIGYELEM: {len(utkozes)} sku MAR SZEREPEL a mesterben, ezeket kihagyom: "
              f"{sorted(utkozes)[:8]}")
        u = u[~u["sku"].isin(utkozes)]

    sorok = []
    for _, r in u.iterrows():
        brutto = float(r["brutto"])
        sor = {c: 0.0 for c in m.columns}
        sor["CSZ"] = f"{r['sku']} {r.get('nev', '')}".strip()
        sor["Cikkszám"] = float(r["sku"])
        sor["EPR Kategória"] = r["kategoria"]
        sor["Nettó súly"] = float(r["netto"])
        sor["Bruttó súly"] = brutto
        sor["Termék akkumulátorának súlya"] = float(r.get("akku", 0) or 0)
        sor["Termék csomagolásának papír doboz tartalma"] = float(r.get("doboz", 0) or 0)
        sor["Termék gyűjtő csomagolásának karton tartalma"] = round(KARTON_ARANY * brutto, 6)
        for k, v in {**ALLANDO, **URALKODO}.items():
            if k in sor:
                sor[k] = v
        sorok.append(sor)

    uj_m = pd.concat([m, pd.DataFrame(sorok)], ignore_index=True)
    with pd.ExcelWriter(a.ki) as w:
        uj_m.to_excel(w, sheet_name="Munka1", index=False)
    print(f"\n{len(m)} + {len(sorok)} = {len(uj_m)} cikk -> {a.ki}")
    if len(ures):
        print(f"MEG MINDIG HIANYZIK {len(ures)} cikk sulyadata.")


if __name__ == "__main__":
    main()
