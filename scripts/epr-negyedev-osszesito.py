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

A HARMADIK CSAPDA, ES EZ A KIMENETET OLVASOT ERI (merve 2026-10-05, sajat hiba): a "Tetelek"
ful egy JOIN eredménye, tehat a mester sulyoszlopai MELLETT a bevetelezes-export oszlopai is
rajta vannak (MENNY, BESZERT, x0, x1, sku). Ha egy kesobbi elemzes a sulyoszlopokat KIZARASSAL
valogatja ("minden, ami nem CSZ/db/kategoria/netto/brutto"), akkor a BESZERT beszerzesi ERTEK
is belekerul az osszegbe. Nalam ez 61,7 MILLIO kg "elterest" adott, es nem hibauzenet fogta meg,
hanem a fizikai ertelmetlenseg.
A szabaly: a sulyoszlopokat BEFOGLALASSAL valogasd (a 'Termék ...' prefixu oszlopok plusz a
netto/brutto), vagy ha mar kizarassal, akkor allits egy nagysagrendi assertet a vegen. Egy
"minden kiveve X" halmaz akkor romlik el, amikor a tabla uj oszlopot kap -- es a join pontosan
ezt teszi.

A NEGYEDIK CSAPDA, ES EZ A PARAMETEREKET ERI (merve 2026-10-05, sajat hiba): A SZKRIPT
ALAPERTELMEZETT MESTERE NEM AZ, AMIVEL A KOZOS MAPPA FAJLJAI KESZULTEK. A --mester default a
CSOMAGOLAS.xlsx, a /mnt/kozos/PENZUGY/EPR/2026 I es 2026 II mappaban levo szamolt tablak viszont
a CSOMAGOLAS_BOVITETT_2026-09-18_javaslat.xlsx-szel keszultek, ES a --kizar-ral. A kettő kozti
elteres nem kozmetikai: 2026 Q2-re 570 tetel / 11049 db a bovitettel, szemben 341 / 8350-nel az
alapertelmezettel, vagyis 229 cikk es 2699 darab a kulonbseg.

A REPRODUKALO RECEPT, BITRE IGAZOLVA mindket negyedeven (az Osszesito fulon 0,000000000 a
legnagyobb cella-elteres a 10-02-i kozos fajlokhoz kepest):

  --mester "/mnt/kozos/PENZUGY/EPR/CSOMAGOLAS_BOVITETT_2026-09-18_javaslat.xlsx" \
  --kizar 14584 154216

A ket kizart cikk: 14584 (Remootio 3.0 Dual) es 154216 (LinX vercukormero), Abel magyar-beszallitoi
szabalya szerint. Q1-ben 189 db, Q2-ben 286 db.

A SZABALY: ha a kimenet egy MAR LETEZO fajl mellé vagy helyere kerul, elobb REPRODUKALD azt a
fajlt, es csak a bitre egyezes utan tedd ra a sajat valtoztatasod. Az alapertelmezes a szkript
sajat tortenete, nem a celhelye.

Usage:
  python3 scripts/epr-negyedev-osszesito.py "<bevetelezes.xls>" [--ki <kimeneti.xlsx>]
"""
import argparse
import re
import sys

import pandas as pd

MESTER = "/mnt/kozos/PÉNZÜGY/EPR/CSOMAGOLÁS.xlsx"
KATEGORIA_OSZLOP = "EPR Kategória"
# A ket kategoria-nev, amit az akku-atvezetes osszekot. A mesterben pontosan igy
# szerepelnek (merve 2026-10-05: 1083 "Kotelezettsegen kivuli" es 57 "Elem/Akku
# hordozhato" sor), ezert szo szerint hasonlitunk, nem mintaval.
KIVULI_KAT = "Kötelezettségen kívüli"
AKKU_KAT = "Elem/Akku hordozható"
AKKU_OSZLOP = "Termék akkumulátorának súlya"
NETTO_OSZLOP = "Nettó súly"
BRUTTO_OSZLOP = "Bruttó súly"


def resz_oszlopok(df):
    """A RESZSULY-oszlopok, BEFOGLALASSAL valogatva (l. a HARMADIK CSAPDA a docstringben).

    A mester minden reszsuly-oszlopa 'Termék ' prefixszel kezdodik: a beepitett akku, az
    alkali elem tartozek, az elsodleges csomagolas hat oszlopa es a gyujto csomagolas het
    oszlopa. A netto es a brutto NEM reszsuly, azok kulon allnak. Kizarassal ('minden, ami
    nem CSZ/db/kategoria/netto/brutto') ez a lista a join utan a BESZERT beszerzesi erteket
    is beszedné, ami 61,7 millio kg "elterest" adott 2026-10-05-en.
    """
    return [c for c in df.columns if c.startswith("Termék ")]


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
    ap.add_argument("--akku-atvezetes", action="store_true",
                    help="A KOTELEZETTSEGEN KIVULI kategoriaban allo cikkek AKKU-SULYAT atvezeti "
                         "az Elem/Akku hordozhato sorba. ABEL KERESE 2026-10-05, a konyvelo "
                         "eszrevetele alapjan (Hotter Andras, t15hivatal): az osszesito fulon a "
                         "kotelezettsegen kivuli sor es az elem/akku resz KIZARJA EGYMAST. A "
                         "kategoria a KESZULEK-aramra vonatkozik, a beepitett akku viszont kulon "
                         "aram, tehat az akku-suly akkor is a mienk, ha a termek maga nem esik "
                         "keszulek-kotelezettseg ala. CSAK az akku-oszlopot mozgatja, a csomagolas- "
                         "es sulyertekeket NEM. ALAPBOL KI VAN KAPCSOLVA, hogy a mar BEADOTT "
                         "negyedevek reprodukcioja bitre egyezo maradjon; UJ beadasnal kapcsold be.")
    ap.add_argument("--brutto-kiigazitas", action="store_true",
                    help="Ahol a RESZSULYOK OSSZEGE (netto + minden 'Termék ...' oszlop) "
                         "TOBB a brutto sulynal, ott a bruttot felhozza a reszek osszegere. "
                         "ABEL KERESE 2026-10-05: 'ne legyen elteres, ugy javitsd, hogy a "
                         "brutto tomegnel ne legyen tobb az osszes reszadat.' A konyvelo a "
                         "tetelek fulon szurke ellenorzo oszlopokkal pont ezt vizsgalta. "
                         "FIZIKAI INDOK: a resz nem lehet nehezebb az egesznel, tehat ezeken "
                         "a teteleken valami biztosan hibas. AMIT EZ A KAPCSOLO NEM TUD: azt "
                         "NEM dontheti el, hogy a brutto van-e alulmerve vagy egy reszoszlop "
                         "felulmerve. A bruttot mozgatja, mert a BEVALLASBA a reszsulyok "
                         "mennek (anyagaram szerint), a brutto csak kontroll-adat -- igy a "
                         "bevallott mennyisegek egyetlen grammal sem valtoznak. A fordított "
                         "irany (brutto > reszek) ERINTETLEN marad: az fizikailag lehetseges, "
                         "mert nem minden osszetevo van tetelezve. ALAPBOL KI VAN KAPCSOLVA, "
                         "hogy a mar BEADOTT negyedevek reprodukcioja bitre egyezo maradjon.")
    ap.add_argument("--kizar", nargs="*", default=[], metavar="SKU",
                    help="Cikkszamok, amelyek NEM tartoznak az EPR kotelezettseg ala, es ezert "
                         "ki kell esniuk a negyedevbol. ABEL SZABALYA, 2026-10-02: ami MAGYAR "
                         "beszallitotol jon, azt nem mi helyezzuk eloszor forgalomba, tehat nem "
                         "a mi bevallasunkba valo. A BEVETELEZES-EXPORT NEM HORDOZ BESZALLITOT "
                         "(csak CSZ, MENNY, BESZERT, es a BESZERT ertek, nem partner), ezert ez "
                         "a szures CSAK cikkszam alapjan vegezheto el, kezzel megadott listabol.")
    a = ap.parse_args()

    print(f"BEVETELEZES: {a.bevetelezes}")
    tol, ig = idoszak(a.bevetelezes)
    print(f"  a fajlba agyazott szuro-idoszak: {tol} .. {ig}"
          if tol else "  FIGYELEM: a fajl nem tartalmaz datum-szurot, az idoszakot csak a "
                      "fajlnev allitja")
    b = bevetelezes_beolvas(a.bevetelezes)
    print(f"  {len(b)} adatsor, {b['sku'].nunique()} kulonbozo cikk, {b['db'].sum():.0f} darab")

    if a.kizar:
        kizar = {str(x).strip() for x in a.kizar}
        marad = b[~b["sku"].astype(str).str.strip().isin(kizar)]
        kiesett = b[b["sku"].astype(str).str.strip().isin(kizar)]
        print(f"  KIZARVA (EPR-kotelezettsegen kivuli beszallito): {len(kiesett)} cikk, "
              f"{kiesett['db'].sum():.0f} db")
        for _, r in kiesett.iterrows():
            print(f"    {r['db']:6.0f} db  {str(r['CSZ'])[:64]}")
        nem_talalt = kizar - set(b["sku"].astype(str).str.strip())
        if nem_talalt:
            print(f"    FIGYELEM, a megadott cikkszamok kozul {len(nem_talalt)} NINCS BENNE "
                  f"ebben a negyedevben: {sorted(nem_talalt)}")
        b = marad
        print(f"  kizaras utan: {len(b)} adatsor, {b['db'].sum():.0f} darab")

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

    # A KONTROLL-OSZLOP MINDIG kiirodik, kapcsolotol fuggetlenul: a konyvelo pontosan ezt
    # szamolta ki kezzel a visszakuldott tablan, es ha a fulon ott all, nem kell ujra.
    reszek = resz_oszlopok(megvan)
    megvan["ELLENORZES netto+reszek-brutto"] = (
        megvan[NETTO_OSZLOP] + megvan[reszek].sum(axis=1) - megvan[BRUTTO_OSZLOP])

    if a.brutto_kiigazitas:
        osszeg = megvan[NETTO_OSZLOP] + megvan[reszek].sum(axis=1)
        tul = osszeg - megvan[BRUTTO_OSZLOP]
        erintett = tul > 0.0005
        if not erintett.any():
            print("  BRUTTO-KIIGAZITAS: egyetlen tetelen sem haladja meg a reszek osszege "
                  "a bruttot, nincs mit kiigazitani.")
        else:
            print(f"  BRUTTO-KIIGAZITAS: {int(erintett.sum())} tetelen a reszek osszege "
                  f"meghaladta a bruttot, osszesen {tul[erintett].sum():.3f} kg-mal. "
                  f"A brutto ezeken felhozva a reszek osszegere.")
            print(f"    a brutto vegosszege: {megvan[BRUTTO_OSZLOP].sum():.3f} -> "
                  f"{(megvan[BRUTTO_OSZLOP] + tul.clip(lower=0)).sum():.3f} kg")
            nagy = megvan.loc[erintett, ["CSZ", "db", BRUTTO_OSZLOP]].assign(tul=tul[erintett])
            print("    a ot legnagyobb kiigazitas:")
            for _, r in nagy.sort_values("tul", ascending=False).head(5).iterrows():
                print(f"      {str(r['CSZ'])[:54]:54} {r[BRUTTO_OSZLOP]:9.3f} -> "
                      f"{r[BRUTTO_OSZLOP] + r['tul']:9.3f}  (+{r['tul']:.3f})")
            megvan[BRUTTO_OSZLOP] = megvan[BRUTTO_OSZLOP] + tul.clip(lower=0)
            megvan["ELLENORZES netto+reszek-brutto"] = (
                megvan[NETTO_OSZLOP] + megvan[reszek].sum(axis=1) - megvan[BRUTTO_OSZLOP])
            marad = (megvan["ELLENORZES netto+reszek-brutto"] > 0.0005).sum()
            print(f"    VISSZAMERVE: a kiigazitas utan {int(marad)} tetelen haladja meg "
                  f"a reszek osszege a bruttot (0 a helyes).")

    pivot = megvan.groupby(KATEGORIA_OSZLOP).agg(
        {"db": "sum", **{c: "sum" for c in suly_oszlopok}})

    if a.akku_atvezetes:
        # A VEGOSSZEG ELOTT fut, tehat a vegosszeg valtozatlan marad: ez atsorolas,
        # nem uj suly. Ha valamelyik kategoria nem szerepel ebben a negyedevben, azt
        # KIMONDJUK, nem csendben kihagyjuk.
        if KIVULI_KAT not in pivot.index:
            print(f"  AKKU-ATVEZETES: a '{KIVULI_KAT}' kategoria nincs ebben a negyedevben, "
                  f"nincs mit atvezetni.")
        else:
            mozog = float(pivot.loc[KIVULI_KAT, AKKU_OSZLOP])
            if mozog == 0:
                print(f"  AKKU-ATVEZETES: a '{KIVULI_KAT}' sorban nulla akku-suly all, "
                      f"nincs mit atvezetni.")
            else:
                if AKKU_KAT not in pivot.index:
                    print(f"  AKKU-ATVEZETES: FIGYELEM, a cel kategoria ('{AKKU_KAT}') nincs "
                          f"ebben a negyedevben, ezert UJ sorként jon letre.")
                    pivot.loc[AKKU_KAT] = 0.0
                elotte = float(pivot.loc[AKKU_KAT, AKKU_OSZLOP])
                pivot.loc[AKKU_KAT, AKKU_OSZLOP] = elotte + mozog
                pivot.loc[KIVULI_KAT, AKKU_OSZLOP] = 0.0
                print(f"  AKKU-ATVEZETES: {mozog:.3f} kg akku-suly atvezetve "
                      f"'{KIVULI_KAT}' -> '{AKKU_KAT}' ({elotte:.3f} -> "
                      f"{elotte + mozog:.3f}). A vegosszeg NEM valtozik.")

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
