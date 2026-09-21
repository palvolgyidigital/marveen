#!/usr/bin/env python3
"""Build the quarterly EPR return from a Next goods-receipt export + the packaging master.

WHY THIS EXISTS: the quarter used to be assembled by hand in Excel, and that method has a
SILENT FAILURE. Measured on 2025 Q2 (2026-09-18): the submitted total was 8651 units while the
export's data rows sum to 8798. The 147-unit gap sits on 11 SKUs, and every one of those 11 is
ABSENT from CSOMAGOLAS.xlsx. They were not excluded by any rule -- they fell out because no
master row existed, and the sheet quietly multiplied them by zero. For 2026 Q1 the same gap is
86 SKUs, so the same mistake would land eight times harder.

This script therefore refuses to hide that: every SKU with no master row is reported, with its
quantity, as a separate block. A quarter is only ready to submit when that block is empty or
every line in it has been consciously accepted.

TWO TRAPS IN THE EXPORT, both measured, both guarded below:
  1. The LAST row of the Next export is an "Osszesen" (total) row and pandas reads it as data.
     Summing naively gives EXACTLY double (8798 data + 8798 total = 17596).
  2. NUMBERS ARE HUNGARIAN-FORMATTED, and pandas' DEFAULT settings silently corrupt them.
     The raw HTML holds "10,00" for ten units and "2.000,00" for two thousand. `read_html`
     defaults to thousands="," so it strips the DECIMAL comma: "10,00" becomes the integer
     1000, while "2.000,00" fails to parse at all and stays a string.
     CORRECTED 2026-09-18 after Max's second export. An earlier version of this file claimed
     "MENNY is scaled by 100" and divided by 100. That rule happened to give the right answer
     on the NAS exports, where no value carries a thousands separator, so every mangled value
     was exactly 100x too large. It is WRONG in general: on an export that does use thousands
     separators (Max's, saved from a live session) the large values drop out entirely -- the
     Q1 total came to 11851 instead of 16051, and the endoscope camera's 2000 units vanished.
     The fix is to parse explicitly: read_html(..., thousands=".", decimal=","), and NOT
     divide. All four files measured on 2026-09-18 then agree with their own summary row.

The export file is named .xls but is actually HTML -- read_html, not read_excel.

Usage:
  python3 scripts/epr-negyedev-osszesito.py "<bevetelezes.xls>" [--ki <kimeneti.xlsx>]
"""
import argparse
import re
import sys

import pandas as pd

MESTER = "/mnt/kozos/PÉNZÜGY/EPR/CSOMAGOLÁS.xlsx"
KATEGORIA_OSZLOP = "EPR Kategória"


def sku(v):
    """The leading number of 'CSZ' is the article number; the rest is the name."""
    m = re.match(r"\s*(\d+)", str(v))
    return m.group(1) if m else None


def idoszak(ut):
    """The report embeds its own filter parameters, including Datumtol/Datumig.

    This matters: the export has NO date column, so without this the period is only asserted by
    the file NAME. Measured on all three files held on 2026-09-18 -- the NAS Q1 file, and both
    of Max's exports -- every one carries its own date range in the header row.
    """
    nyers = open(ut, "rb").read()
    for e in ("utf8", "iso-8859-2", "cp1250"):
        try:
            s = nyers.decode(e)
        except UnicodeDecodeError:
            continue
        d = re.findall(r"(20\d\d\.\d\d\.\d\d)", s)
        if d:
            return sorted(set(d))[0], sorted(set(d))[-1]
    return None, None


def _oszlopnev(c):
    """A tobbszintu fejlecbol az UTOLSO szint a valodi oszlopnev."""
    return str(c[-1] if isinstance(c, tuple) else c).strip()


def bevetelezes_beolvas(ut):
    """A HELYES TABLAT A FAJL SAJAT BELSO ELLENORZESE VALASZTJA KI, nem a merete.

    MIERT (merve 2026-09-18): a Nextbol frissen mentett export TIZENKET egymasba agyazott
    tablat tartalmaz, ebbol harom is CSZ/MENNY/BESZERT oszlopnevekkel jon, kulonbozo
    sorszammal (583, 578, 573). A "legnagyobb tabla" szabaly a ROSSZAT valasztja. A NAS-on
    levo, maskepp mentett fajlban csak egy ilyen van, ezert az elso valtozat rajta mukodott
    es a kulonbseg csak egy masik forrasu fajlon derult ki.

    A dontest ezert a tabla SAJAT konzisztenciaja hozza: a beagyazott "Osszesen" sor
    mennyisege egyezzen az adatsorok osszegevel. Amelyik tablan ez all, az a teljes es
    csonkitatlan tabla.
    """
    tablak = []
    for e in ("utf8", "iso-8859-2"):
        try:
            # thousands/decimal EXPLICITEN: a pandas alapertelmezese a magyar TIZEDESVESSZOT
            # ezres elvalasztonak veszi, es a "10,00"-bol 1000 egeszt csinal. L. a fajl fejet.
            tablak = pd.read_html(ut, encoding=e, thousands=".", decimal=",")
            break
        except Exception:  # noqa: BLE001
            continue
    if not tablak:
        sys.exit("MEGALLOK: a fajl nem olvashato HTML-tablakent.")

    jeloltek = []
    for d in tablak:
        nevek = [_oszlopnev(c) for c in d.columns]
        if nevek[:3] != ["CSZ", "MENNY", "BESZERT"]:
            continue
        d = d.copy()
        d.columns = nevek[:3] + [f"x{i}" for i in range(len(nevek) - 3)]
        d["sku"] = d["CSZ"].map(sku)
        osszegzo = d[d["sku"].isna()]
        adat = d[d["sku"].notna()].copy()
        adat["db"] = pd.to_numeric(adat["MENNY"], errors="coerce")

        # MINDEN mennyisegnek szamma kell alakulnia. Ha nem, a szamformatum mas, mint hittuk,
        # es a kiesett sorok MENNYISEGE is kiesne -- nemán.
        nem_szam = adat["db"].isna().sum()
        if nem_szam:
            jeloltek.append((d, adat, None, f"{nem_szam} mennyiseg nem alakult szamma"))
            continue

        # az osszegzo sorok kozul az, amelyiknek van ertelmezheto mennyisege
        var = None
        for _, r in osszegzo.iterrows():
            v = pd.to_numeric(pd.Series([r["MENNY"]]), errors="coerce").iloc[0]
            if pd.notna(v):
                var = float(v)
        if var is None:
            jeloltek.append((d, adat, None, "nincs ertelmezheto osszegzo sor"))
            continue
        egyezik = abs(var - adat["db"].sum()) < 0.5
        jeloltek.append((d, adat, var, "EGYEZIK" if egyezik else
                         f"osszegzo {var:.0f} kontra adat {adat['db'].sum():.0f}"))

    if not jeloltek:
        sys.exit("MEGALLOK: nincs CSZ/MENNY/BESZERT oszlopu tabla a fajlban.")
    jo = [j for j in jeloltek if j[3] == "EGYEZIK"]
    print(f"  {len(tablak)} tabla a fajlban, {len(jeloltek)} CSZ/MENNY/BESZERT oszlopu, "
          f"{len(jo)} onmagaval konzisztens")
    for _, adat, var, allapot in jeloltek:
        print(f"    {len(adat):4d} adatsor -> {allapot}")
    if not jo:
        sys.exit("MEGALLOK: egyetlen tablan sem egyezik az 'Osszesen' sor az adatsorok "
                 "osszegevel. A Next formatuma valtozhatott, ellenorizd kezzel.")
    # tobb konzisztens tabla eseten a legtobb adatsort tartalmazo a teljes
    _, adat, var, _ = max(jo, key=lambda j: len(j[1]))
    print(f"  kontroll: az 'Osszesen' sor egyezik az adatsorok osszegevel ({var:.0f} db)")

    # Max merese 2026-09-18: VANNAK ures beszerzesi erteku sorok, MENNYISEGGEL. Aki a BESZERT
    # oszlopot szamma alakitja es dropna-zik, ezeket a sorokat ES A MENNYISEGUKET is elveszti.
    # Ez a szkript a BESZERT oszlopot nem is hasznalja, de kiirja, hogy lathato legyen.
    ures_ertek = adat[pd.to_numeric(adat["BESZERT"], errors="coerce").isna()]
    if len(ures_ertek):
        print(f"  URES BESZERZESI ERTEKU SOR: {len(ures_ertek)} db, {ures_ertek['db'].sum():.0f} "
              f"egyseg -- BENNE VANNAK az osszesitoben (a BESZERT oszlopot nem hasznaljuk)")
    return adat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bevetelezes")
    ap.add_argument("--ki")
    ap.add_argument("--mester", default=MESTER)
    ap.add_argument("--nulla-negativ", action="store_true",
                    help="A mester FIZIKAILAG LEHETETLEN negativ csomagolosuly-ertekeit nullara "
                         "veszi. ALAPBOL KI VAN KAPCSOLVA, hogy a mar BEADOTT negyedevek "
                         "reprodukcioja (a pozitiv kontroll) bitre egyezo maradjon -- azok a "
                         "tablak a hibas erteket tartalmazzak. UJ beadasnal viszont kapcsold be.")
    a = ap.parse_args()

    print(f"BEVETELEZES: {a.bevetelezes}")
    tol, ig = idoszak(a.bevetelezes)
    print(f"  a fajlba agyazott szuro-idoszak: {tol} .. {ig}"
          if tol else "  FIGYELEM: a fajl nem tartalmaz datum-szurot, az idoszakot csak a "
                      "fajlnev allitja")
    b = bevetelezes_beolvas(a.bevetelezes)
    print(f"  {len(b)} adatsor, {b['sku'].nunique()} kulonbozo cikk, {b['db'].sum():.0f} darab")

    m = pd.read_excel(a.mester, sheet_name="Munka1")
    m["sku"] = m["CSZ"].map(sku)
    m = m[m["sku"].notna()].drop_duplicates("sku", keep="first")
    print(f"MESTER: {len(m)} cikk ({a.mester})")

    suly_oszlopok = [c for c in m.columns
                     if c not in ("CSZ", "Cikkszám", "sku", KATEGORIA_OSZLOP)]

    # FIZIKAILAG LEHETETLEN ERTEKEK. A mesterben 14 cikknel NEGATIV a papir doboz sulya
    # (merve 2026-09-18, mind 153xxx-es cikkszam, vagyis abbol az idoszakbol, amikor a
    # karbantartas eltort). Egy negativ csomagolosuly nem lehet helyes, es a KATEGORIA-SORBAN
    # is megjelenik: a "Nagygepek" papirdoboz-osszege -0,100 kg lenne. A NAGYSAGA elenyeszo
    # (a ket 2026-os negyedevben egyutt -0,340 kg, a papirdoboz-ertek 0,03 szazaleka), a
    # LATHATOSAGA viszont nem: egy hatosagi tablaban egy negativ csomagolosuly kerdest hiv.
    negativ = []
    for c in suly_oszlopok:
        v = pd.to_numeric(m[c], errors="coerce")
        n = int((v < 0).sum())
        if n:
            negativ.append((c, n, float(v[v < 0].sum())))
    if negativ:
        print("  FIGYELEM, NEGATIV SULYERTEK A MESTERBEN (fizikailag lehetetlen):")
        for c, n, ossz in negativ:
            print(f"    {str(c)[:58]}: {n} sor, osszesen {ossz:+.4f}")
        if a.nulla_negativ:
            for c, _, _ in negativ:
                v = pd.to_numeric(m[c], errors="coerce")
                m.loc[v < 0, c] = 0.0
            print("    --nulla-negativ: ezeket NULLARA vettem.")
        else:
            print("    (bennhagyva. UJ beadasnal add meg a --nulla-negativ kapcsolot.)")
    print(f"  {len(suly_oszlopok)} sulyoszlop")

    e = b.merge(m[["sku", KATEGORIA_OSZLOP] + suly_oszlopok], on="sku", how="left")
    hianyzik = e[e[KATEGORIA_OSZLOP].isna()]
    megvan = e[e[KATEGORIA_OSZLOP].notna()]

    print()
    print("FEDETTSEG:")
    print(f"  mesteradattal:  {megvan['sku'].nunique():4d} cikk, {megvan['db'].sum():9.0f} db")
    print(f"  MESTERADAT NELKUL: {hianyzik['sku'].nunique():4d} cikk, {hianyzik['db'].sum():9.0f} db"
          f"  <-- EZ ESNE KI NEMAN")

    for c in suly_oszlopok:
        megvan[c] = pd.to_numeric(megvan[c], errors="coerce").fillna(0) * megvan["db"]

    pivot = megvan.groupby(KATEGORIA_OSZLOP).agg(
        {"db": "sum", **{c: "sum" for c in suly_oszlopok}})
    pivot.loc["VEGOSSZEG"] = pivot.sum()

    print()
    print("OSSZESITO (a beadando tabla alakja):")
    print(pivot[["db", "Nettó súly", "Bruttó súly", "Termék akkumulátorának súlya"]]
          .round(3).to_string())

    if len(hianyzik):
        print()
        print("A MESTERBOL HIANYZO CIKKEK -- ezek NELKUL a beadas hianyos:")
        h = (hianyzik.groupby(["sku", "CSZ"])["db"].sum()
             .reset_index().sort_values("db", ascending=False))
        print(h.to_string(index=False, max_colwidth=78))

    if a.ki:
        with pd.ExcelWriter(a.ki) as w:
            pivot.to_excel(w, sheet_name="Osszesito")
            megvan.to_excel(w, sheet_name="Tetelek", index=False)
            if len(hianyzik):
                h.to_excel(w, sheet_name="HIANYZO MESTERADAT", index=False)
        print(f"\nkiirva: {a.ki}")


if __name__ == "__main__":
    main()
