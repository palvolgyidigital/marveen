#!/usr/bin/env python3
"""Fill the quarterly EPR 'adatbekero' workbook from the calculated EPR tables.

WHY THIS EXISTS (2026-09-30): Abel asked on the card for "tablazat a korabbi negyedevek
mintajara". The pattern is the workbook
  /mnt/kozos/PENZUGY/EPR/2025. II/Palvolgyi Digital EPR adatbekero 2025.II.xlsx
which holds ONE row per quarter on the 'Alapadatok' sheet. Our calculated tables
(EPR_2026_<Q>_szamolt_0918.xlsx, sheet 'Osszesito') hold the same figures under different
column names. This script does the mapping MECHANICALLY so nobody retypes 40 numbers.

WHAT IT DOES NOT DO, ON PURPOSE: it does not guess. Four target fields cannot be derived
from our tables, and the script leaves them EMPTY and writes the reason into the note row
underneath, instead of inventing a plausible number:
  1. 'Elem/Akku hordozhato altalanos' vs 'Elem/Akku hordozhato' -- the form has TWO columns,
     our tables have ONE category. The 2025.II row split 14,4 / 93,554 with a hand note
     ("ebbol onallo termek: 57,141"), so the split is a human judgement, not a formula.
  2. 'Fa raklap' -- no source column exists in our calculation at all. 2025.II had 60,9.
  3. 'Csomagolóanyag vasarlas' -- 2025.II says "lsd: Remenyi szamlak". Comes from the 7
     in-scope Remenyi invoices, not from the receipt data.
  4. 'Kezi nyujthato folia' -- our nearest column is 'zsugorfolia', which is a DIFFERENT
     material (shrink vs hand stretch film). It is 0,0 in both 2026 quarters, so the number
     is harmless either way, but the naming mismatch is flagged rather than hidden.

MEASURED MAPPING RULE, and it is easy to get backwards: the per-category form columns take
the NET weight, while the separate 'Brutto suly (kg)' field takes the GROSS total. Verified
on 2025.II: the category values plus 'Kotelezettsegen kivuli' sum to the net total, not to
the 4688,61 gross figure in the header field.

Usage:
  python3 scripts/epr-adatbekero-kitoltes.py            # writes both quarters
  python3 scripts/epr-adatbekero-kitoltes.py --kiir     # dry run, prints, writes nothing
"""
import shutil
import sys

import openpyxl
import pandas as pd

MINTA = "/mnt/kozos/PÉNZÜGY/EPR/2025. II/Pálvölgyi Digital EPR adatbekérő 2025.II.xlsx"
ADAT_SOR = 5   # openpyxl 1-based row of the quarter's data line
MEGJ_SOR = 6   # the note row directly underneath, used by the 2025.II original too

NEGYEDEVEK = {
    "I": ("/mnt/kozos/PÉNZÜGY/EPR/2026 I/EPR_2026_I_szamolt_0918.xlsx",
          "/mnt/kozos/PÉNZÜGY/EPR/2026 I/EPR_adatbekero_2026_I_KITOLTESRE_0930.xlsx",
          "2026. I"),
    "II": ("/mnt/kozos/PÉNZÜGY/EPR/2026 II/EPR_2026_II_szamolt_0918.xlsx",
           "/mnt/kozos/PÉNZÜGY/EPR/2026 II/EPR_adatbekero_2026_II_KITOLTESRE_0930.xlsx",
           "2026. II"),
}

# form column index (0-based, as read with header=None) -> EPR category in our 'Osszesito'
KATEGORIA_OSZLOP = {
    6: "Képernyők, monitorok",
    7: "LED lámpa",
    10: "Nagygépek",
    13: "Kisgépek",
    24: "Irodai papír",
}
# every other product column on the form: we have no such category, so it is a measured zero
NULLA_OSZLOPOK = [5, 8, 9, 11, 12, 14, 15, 18, 19, 20, 21, 22, 23, 25, 26, 27, 28, 29, 30]

# form column -> our 'Osszesito' packaging column, name for name
CSOMAGOLAS_OSZLOP = {
    32: "Termék csomagolásának papír doboz tartalma",
    33: "Termék csomagolásának műanyag zacskó  tartalma",
    34: "Termék csomagolásának műanyag címke tartalma",
    35: "Termék csomagolásának műanyag ragasztószalag tartalma",
    36: "Termék csomagolásának páralekötő tartalma",
    37: "Termék csomagolásának lezáró tartalma",
    49: "Termék gyűjtő csomagolásának karton tartalma",
    50: "Termék gyűjtő csomagolásának papícímke tartalma",
    51: "Termék gyűjtő műanyag csomagolásának ragasztószalag tartalma",
    52: "Termék gyűjtő műanyag csomagolásának műanyag zacskó tartalma",
    53: "Termék gyűjtő műanyag csomagolásának műanyag címke tartalma",
    54: "Termék gyűjtő műanyag csomagolásának pántszalag tartalma",
    55: "Termék gyűjtő műanyag csomagolásának zsugorfólia tartalma",
}

def kezi_jegyzetek(o) -> dict:
    """The four fields we refuse to guess, each with the number the filler actually needs.

    The note carries the TOTAL to be split, because leaving the cell empty without it makes
    the battery weight vanish from the form with nothing pointing at where it went.
    """
    elem = ertek(o, "Elem/Akku hordozható")
    akku = vegosszeg(o, "Termék akkumulátorának súlya")
    alkali = vegosszeg(o, "Termék alkáli elem tartozékának súlya")
    return {
        16: (f"KEZI DONTES. A form ket oszlopra bontja, a szamitas egy kategoriat ad. "
             f"SZETOSZTANDO: Elem/Akku hordozhato netto = {elem:.3f} kg. "
             f"2025.II-ben a bontas 14,4 / 93,554 volt."),
        17: (f"KEZI DONTES, a bontas masik fele. Tampont a szamitasbol: termekbe epitett "
             f"akkumulator {akku:.3f} kg, alkali elem tartozek {alkali:.3f} kg. "
             f"2025.II-ben kezi jegyzet allt itt: 'ebbol onallo termek: 57,141'."),
        56: "NINCS FORRAS a szamitasban (Fa raklap). 2025.II-ben 60,9 volt.",
        57: "A 7 hatokorben levo Remenyi szamlabol kell osszeadni (lsd: Remenyi szamlak).",
    }


def osszesito(path: str) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name="Osszesito")


def ertek(o: pd.DataFrame, kategoria: str, oszlop: str = "Nettó súly") -> float:
    sor = o[o["EPR Kategória"].astype(str).str.strip() == kategoria]
    return 0.0 if sor.empty else float(sor.iloc[0][oszlop])


def vegosszeg(o: pd.DataFrame, oszlop: str) -> float:
    sor = o[o["EPR Kategória"].astype(str).str.contains("VEGOSSZEG", na=False)]
    return float(sor.iloc[0][oszlop])


def kitolt(forras: str, cel: str, cimke: str, szarazon: bool) -> None:
    o = osszesito(forras)
    if not szarazon:
        shutil.copyfile(MINTA, cel)
    wb = openpyxl.load_workbook(cel if not szarazon else MINTA)
    ws = wb["Alapadatok"]

    beirt = {}
    beirt[2] = cimke
    beirt[3] = vegosszeg(o, "db")
    beirt[4] = vegosszeg(o, "Bruttó súly")
    for i, kat in KATEGORIA_OSZLOP.items():
        beirt[i] = ertek(o, kat)
    for i in NULLA_OSZLOPOK:
        beirt[i] = 0
    beirt[31] = ertek(o, "Kötelezettségen kívüli")
    for i, oszl in CSOMAGOLAS_OSZLOP.items():
        beirt[i] = vegosszeg(o, oszl)

    for i, v in beirt.items():
        ws.cell(row=ADAT_SOR, column=i + 1).value = v
    kezi = kezi_jegyzetek(o)
    for i, indok in kezi.items():
        ws.cell(row=ADAT_SOR, column=i + 1).value = None
        ws.cell(row=MEGJ_SOR, column=i + 1).value = indok
    # the naming mismatch is worth saying out loud even though the number is 0,0
    ws.cell(row=MEGJ_SOR, column=56).value = (
        "A szamitasban 'zsugorfolia' all, a formon 'Kezi nyujthato folia' -- mas anyag. "
        "Mindket 2026-os negyedevben 0,0, tehat a szam nem mulik rajta.")

    print(f"--- {cimke}")
    print(f"    db={beirt[3]}  brutto={beirt[4]:.4f}  kotelezettsegen kivuli={beirt[31]:.3f}")
    print(f"    kitoltott mezok: {len(beirt)}  | kezi dontesre hagyva: {len(kezi)}")
    if szarazon:
        print("    SZARAZ FUTAS, nem irtam fajlt.")
        return
    wb.save(cel)
    print(f"    kiirva: {cel}")


def main() -> int:
    szarazon = "--kiir" in sys.argv
    for _, (forras, cel, cimke) in NEGYEDEVEK.items():
        kitolt(forras, cel, cimke, szarazon)
    print("\nA data validation kiterjesztes az openpyxl-mentesnel elveszik: a legordulok "
          "eltunhetnek, a SZAMOK nem valtoznak. Vegleges beadas elott erdemes Excelben ranezni.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
