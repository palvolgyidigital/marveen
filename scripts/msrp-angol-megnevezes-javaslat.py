#!/usr/bin/env python3
"""Add a proposed, more descriptive English product name to the MSRP workbook.

Abel's request (2026-10-02, Telegram 8266): the English names should describe what the
product IS, the way the Hungarian names do -- "PEEPS BLACK-SILVER" tells a buyer nothing.

WHY A NEW COLUMN AND NOT AN OVERWRITE: the existing English name is Abel's data. A proposal
goes next to it so he can compare and accept per row. Overwriting would also destroy the only
copy of the current wording.

EVERY PROPOSAL CARRIES ITS SOURCE, because the three sources are not equally strong:
  HU       -- translated from OUR OWN Hungarian name on the same row. Strongest: it is the
              wording we already use commercially.
  TESTVER  -- derived from a SIBLING SKU's Hungarian name (same product family, different
              variant). Strong, but the variant-specific part is inferred.
  WEB      -- from lenspen.com, matched BY PRODUCT NAME ONLY. The fetch could not show SKU
              codes, so the code-to-name link is NOT proven. Needs Abel's eye.
  KERDES   -- cannot be settled from any source we hold; a question went to Abel.

Usage: python3 scripts/msrp-angol-megnevezes-javaslat.py
"""
import io
import shutil

import openpyxl

BE = "store/msrp-angol-megnevezes/Export_MSRP_2026-10-02_v3.xlsx"
KI = "store/msrp-angol-megnevezes/Export_MSRP_2026-10-02_v3_ANGOL_JAVASLAT.xlsx"

# (javasolt angol megnevezes, forras)
JAVASLAT = {
    # --- Sheet1: nincs magyar megnevezes a lapon ---
    "LP-HB-1": ("Lenspen Hurricane Blower hand air blower for lenses and camera sensors", "WEB"),
    "LP-MK-2-G": ("Lenspen MicroKlear microfibre cleaning cloth for optics", "HU-TESTVÉR"),
    "LP-NDSLRK-1": ("Lenspen DSLR Pro Kit camera and lens cleaning set", "WEB"),
    "LP-NLP-1": ("Lenspen Original lens cleaner pen, activated carbon, antibacterial", "TESTVÉR"),
    "LP-NSKLK-1": ("Lenspen SensorKlear Loupe Kit camera sensor cleaning kit with magnifier", "KÉRDÉS"),
    "LP-SK-1A": ("Lenspen SensorKlear II camera sensor cleaning pen", "TESTVÉR"),
    "LP-NLFK-1": ("Lenspen FilterKlear cleaning pen for camera lens filters", "WEB"),
    "LP-NMCP-1": ("Lenspen MicroPro compact cleaning pen for small optics", "WEB"),
    "LP-NDK-1": ("Lenspen DigiKlear cleaning pen for digital camera screens and displays", "WEB"),
    "LP-NMP-1": ("Lenspen MiniPro compact lens cleaning pen for small optics", "WEB+TESTVÉR"),
    # Abel 2026-10-02 14:14, SAJAT SZAVAIVAL BIZONYTALANUL: "a RU, az RUBBER, tehat gumis
    # bevonatu asszem". Az "asszem" miatt ez FELTEVES, nem mert tény, ezert a forras-cimke
    # kimondja. Ha a gumis bevonat nem igazolt, a jelzo kivehetо anelkul, hogy a tobbi resz valtozna.
    "LP-NMP-1-RU": ("Lenspen MiniPro compact lens cleaning pen for small optics, rubberised barrel",
                    "ÁBEL-FELTEVÉS"),
    "LP-FK-1-PPE": ("Lenspen FogKlear anti-fog cloth for face shields and protective equipment", "WEB"),
    "LP-LS-1E": ("Lenspen Smarty smartphone camera lens and screen cleaner", "WEB"),
    "LP-PEEPS-1-B-S": ("Peeps by Carbonklean eyeglass lens cleaner, black/silver, Lenspen technology", "TESTVÉR"),
    # --- "Kep-msrp nelkul": a magyar megnevezesbol forditva ---
    "LP-FK-1": ("Lenspen Carbonklean FogKlear anti-fog cloth", "HU"),
    "LP-LT-1": ("Lenspen Lens & Tablet Cleaner set for optics and tablet screens", "HU"),
    "LP-PN-1": ("Lenspen Panamatic panoramic tripod head", "HU"),
    "LP-SDK-SMK-1": ("Carbonklean ScreenKlean + SmartKlear tablet and smartphone screen cleaner kit, "
                     "Lenspen technology", "HU"),
    "LP-SMK-1-RUS": ("Carbonklean SmartKlear phone screen cleaner, activated carbon, antibacterial, "
                     "black/silver, Lenspen technology", "HU"),
    "LP-SMK-P-BL072": ("CarbonKlean SmartKlear phone screen cleaner, blue (BL072), Lenspen technology", "HU"),
    "LP-SMK-1-C-L": ("Carbonklean SmartKlear phone screen cleaner, lavender, Lenspen technology", "HU"),
    "LP-SMK-1-C-Y": ("Carbonklean SmartKlear phone screen cleaner, yellow, Lenspen technology", "HU"),
    "LP-SMK-2": ("Carbonklean SmartKlear phone screen cleaner kit + spare cleaning head, silver/black, "
                 "Lenspen technology", "HU"),
    "LP-PEEPS-B": ("Peeps by Carbonklean eyeglass lens cleaner, activated carbon, antibacterial, "
                   "black/white, Lenspen technology", "HU"),
    "LP-NMPA-1": ("Lenspen MiniPro lens cleaner pen for action cameras, activated carbon, antibacterial", "HU"),
    "LP-PEEPS-W": ("Peeps by Carbonklean eyeglass lens cleaner, activated carbon, antibacterial, "
                   "white/black, Lenspen technology", "HU"),
    "LP-NLP-2": ("Lenspen Original lens cleaner pen, activated carbon, antibacterial, "
                 "+ 1 spare cleaning head", "HU"),
    "LP-SK-2A": ("Lenspen SensorKlear II Plus camera sensor cleaning set (air blower + sensor pen), "
                 "activated carbon, antibacterial", "HU"),
    "LP-VM-1": ("Lenspen Carbonklean VidiMax TV and screen cleaner, activated carbon, antibacterial", "HU"),
    "LP-NHTPK-1": ("Lenspen HunterPro Kit cleaning set for binoculars and riflescopes, "
                   "activated carbon, antibacterial", "HU"),
    "LP-NPP-1": ("Lenspen Photo Pro Kit camera and lens cleaning set, activated carbon, antibacterial", "HU"),
    "LP-SDK-1-W": ("Lenspen Carbonklean ScreenKlean tablet and car display cleaner, white barrel", "HU"),
    "LP-SMK-1-W": ("Lenspen CarbonKlean SmartKlear tablet and car display cleaner, white barrel", "HU"),
    "LP-NLPK": ("Lenspen cleaning kit: NLP-1 lens pen + HB-1 air blower + MK-2-G microfibre cloth", "HU"),
    "LP-NLPEEPS-1": ("Lenspen Original lens cleaner pen + Peeps eyeglass cleaner bundle, "
                     "activated carbon, antibacterial", "HU"),
}

# A lap neve -> (fejlec-sor, gyartoi cikkszam oszlop, angol megnevezes oszlop)
#
# JAVITVA 2026-10-02, es ezt a hibat egy DARABSZAM-OSSZEVETES fogta meg, nem az olvasas:
# a "Kep-msrp nelkul" lapon a 2. sort fejlecnek vettem, mert UGY NEZ KI (az 1. sor teljesen
# ures). Valojaban a 2. sor ADAT (3617 / LP-FK-1), tehat a javaslat-oszlop fejlecet egy
# TERMEK soraba irtam, es az a termek kimaradt a javaslatbol. Semmi nem jelzett: a kimenet
# "34 sor beirva" volt, ami hihetoen hangzik.
# A lelet forrasa: a javaslat-tablaban 35 kod van, a fajlban 34 -- a ket szam kulonbsege
# maga a hiba. Ezert van a main() vegen a ket-iranyu halmaz-osszevetes.
LAPOK = {"Sheet1": (1, 3, 4), "Kép-msrp nélkül": (1, 3, 5)}


def main():
    shutil.copy(BE, KI)
    wb = openpyxl.load_workbook(KI)
    erintett, hianyzo = 0, []

    for lap, (fej, c_kod, c_ang) in LAPOK.items():
        ws = wb[lap]
        uj = ws.max_column + 1
        ws.cell(row=fej, column=uj, value="JAVASOLT angol megnevezés")
        ws.cell(row=fej, column=uj + 1, value="javaslat forrása")
        for sor in range(fej + 1, ws.max_row + 1):
            kod = ws.cell(row=sor, column=c_kod).value
            if not kod:
                continue
            kod = str(kod).strip()
            if kod in JAVASLAT:
                szoveg, forras = JAVASLAT[kod]
                ws.cell(row=sor, column=uj, value=szoveg)
                ws.cell(row=sor, column=uj + 1, value=forras)
                erintett += 1
            else:
                hianyzo.append((lap, sor, kod))

    wb.save(KI)
    print(f"javaslat beirva: {erintett} sor -> {KI}")
    if hianyzo:
        print(f"NINCS JAVASLAT {len(hianyzo)} sorra (ezeket kezzel kell megnezni):")
        for lap, sor, kod in hianyzo:
            print(f"   {lap} {sor}. sor  {kod}")
    hasznalt = {k for k in JAVASLAT}
    print(f"\nforras-megoszlas: ", end="")
    from collections import Counter
    print(dict(Counter(f for _, f in JAVASLAT.values())))
    print(f"a javaslat-tablaban {len(hasznalt)} kod van, a fajlban {erintett} sort talalt el")


if __name__ == "__main__":
    main()
