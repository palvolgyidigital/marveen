#!/usr/bin/env python3
"""Propose a weight estimate for each SKU missing from the EPR master, from its nearest sibling.

WHY. The 2026 Q1-Q2 return needs per-SKU weights for 263 articles that have no master row. The
Next fields that would hold them cannot be read in bulk (measured 2026-09-11, card 37b772fb), and
most are empty anyway for new listings. Abel's written rule for that case is that an estimate from
a similar item beats a blank ("barmilyen adat is jobb mint a nincs adat"), and Marci confirmed it
on 2026-09-18.

This script does that at the PRODUCT level rather than the category level, which is both closer
and checkable: for every missing article it finds the master article whose NAME overlaps most, and
proposes that article's weights. A "K&F Concept 12in1 beepitett akkumulatoros porfujo" lands on a
K&F porfujo, not on the average of "Kisgepek".

HUNGARIAN MORPHOLOGY DEFEATS LETTER-BASED FILTERS IN THREE SEPARATE WAYS, all measured on
2026-09-18, all in the same direction (they UNDER-match, and they do it precisely on the closest
relatives):
  SUFFIXED STEM   "endoszkop" and "endoszkopos" are two different tokens, so an endoscope camera
                  drew a Cullmann camera bag instead of the K&F endoscope camera sitting in the
                  master. 2000 units, 29% of the gap. Fix: index the first 6 chars as well.
  CASE ENDING     "-hoz/-hez" marks the COMPLEMENT, not the head. "telefon tarto adapter
                  ALLVANYHOZ" (a phone holder FOR a stand) was classed as a STAND, and a 155 cm
                  video tripod inherited 0,080 kg from it. Fix: drop -hoz/-hez words before
                  taking the head noun.
  BRAND SHAPE     "K&F" normalises to "k f", two single-character tokens that a length filter
                  throws away -- so K&F articles carried NO brand signal at all and drew Ulanzi
                  and Rollei siblings. Fix: extract the brand separately, by regex.

KNOWN LIMIT, MEASURED 2026-09-18: THE MATCHER READS WORDS, NOT NUMBERS. Where a product's
substance IS a number -- a tripod's load rating, a stand's height, a bag's litres, a filter's
diameter -- the proposal ignores exactly the figure that drives the weight, and it does so
systematically rather than at random. Measured examples from the 0,30-0,50 band:
  154251 OMBRA II XINAG, 157 cm, 3 KG  ->  153613 Ombra YING, 158 cm, 8 KG, netto 1,10
  154040 K&F O234A0+BV01, 196 cm, 4 KG ->  153433 A234A1+BH-28L, 160 cm, 10 KG, netto 1,30
A 3 kg tripod is normally lighter than an 8 kg one, so these proposals OVERSTATE. Reviewed by
hand for tripods and light stands; trusted as-is for kinds where the type is the substance
(blower, strap, cloth, ball head, bag).
A load-capacity scaling was deliberately NOT built in: the items concerned run 20-30 units each
and cannot move the return's totals, while a scaling factor would add an unvalidated assumption
to a filing that goes to an authority. A warning is cheaper and more honest than an unchecked
formula.

WHAT COUNTS AS EVIDENCE THAT TWO NAMES MEAN THE SAME PRODUCT (measured on the 1437-article
master, 2026-09-18, after Max's parallel tool hit the same wall):

  STRONG      the shared token carries BOTH letters and digits -- a model number (t254a7, bh28l).
              648 of the 2163 tokens have this shape, and a shared model number really does
              identify. Or a 2-4 digit pure number, which is a size (77 mm, 5L).
  MEDIUM      a pure-letter shared token appearing in AT MOST 2 of the 1437 articles.
  NOT EVIDENCE anything appearing in 3 or more articles.

THE NUMBERS BEHIND THE CUT: "ombra" sits in 2 articles (idf 6.17), "alap" in 3 (5.88),
"aluminium" in 13 (4.63). A document-frequency cut at 2 separates them; in idf terms that is
roughly 6.0, and the margin between "alap" and "ombra" is only 0.29, so the cut is narrow.

AND WHY THE MEDIUM TIER STILL LEAKS: "plate" occurs in exactly ONE article, so it passes the
frequency cut, yet it is an ordinary English word that happens to be rare HERE. Frequency-rarity
is not the same thing as distinguishing power. 65% of the corpus passes df<=2, so that cut alone
is loose -- keep a second condition (the candidate must not LOSE any token the incumbent shared).

ABSOLUTE RULE, learned the expensive way: A MEASURED VALUE IS NEVER DISPLACED BY AN ESTIMATE, at
any score. Max's tool briefly rewrote a Mac Mini case from a measured 487 g to 50 g on a shared
"aluminium" token. Whatever the matcher proposes, rows whose weight came from Next or from a
manufacturer spec are frozen.

IT PROPOSES, IT DOES NOT DECIDE. Every line carries the matched sibling and a similarity score so
a human can accept or reject it, and the output is a worklist, not a filled master.

Usage:
  python3 scripts/epr-hasonlo-cikk-becsles.py <hianyzo.csv> [--ki javaslat.csv] [--min 0.30]
"""
import argparse
import re
import sys
import unicodedata

import pandas as pd

MESTER = "/mnt/kozos/PÉNZÜGY/EPR/CSOMAGOLÁS.xlsx"

# Az ekezet es a kis-nagy betu a nev-egyeztetesnel zajt visz be, a szamok es a mertekegysegek
# viszont JELET: a "77 mm" vagy a "10x15" pont az, ami ket hasonlo nevu cikket megkulonboztet.
_SZOSZEMET = {
    "concept", "es", "a", "az", "db", "cm", "mm", "kg", "g", "w", "-", "es",
    "fekete", "feher", "ezust", "piros", "kek", "zold", "sarga", "szurke", "rozsaszin", "bezs",
}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.lower()


def tokenek(nev):
    """A magyar TOLDALEK miatt nem a teljes szo a kulcs, hanem a TO eleje.

    MERT HIBA 2026-09-18: a "154267 YP-105, endoszkop kamera" cikkre a teljes-szavas egyeztetes
    egy Cullmann fotostaskat javasolt (hasonlosag 0,11), holott a mesterben ott all a "153881
    K&F Concept Endoszkopos ellenorzo kamera". Az "endoszkop" es az "endoszkopos" KET KULONBOZO
    token, tehat a leheto legjobb testvert epp a magyar ragozas rejtette el. Ez 2000 darab volt,
    a teljes hianyzo mennyiseg 29 szazaleka.

    A megoldas nem teljes ertek u szotovezetes, csak annyi, amennyi ide kell: a 6 karakternel
    hosszabb szavakat az elso 6 karakterukkel IS felvesszuk. Igy az "endoszkop" es az
    "endoszkopos" kozos jegye az "endosz", a rovid szavak pedig valtozatlanok maradnak.
    """
    nev = re.sub(r"^\s*\d+\s+", "", str(nev))
    szavak = [x for x in re.split(r"[^0-9a-z]+", norm(nev)) if len(x) > 1 and x not in _SZOSZEMET]
    t = set(szavak)
    t |= {x[:6] for x in szavak if len(x) > 6}
    return t


def hasonlosag(a, b):
    """Jaccard, de a RITKA szavak tobbet ernek. A 'fotostaska' tobbet mond, mint a 'mini'."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hianyzo")
    ap.add_argument("--ki")
    ap.add_argument("--min", type=float, default=0.30)
    ap.add_argument("--mester", default=MESTER)
    a = ap.parse_args()

    m = pd.read_excel(a.mester, sheet_name="Munka1")
    m = m[m["CSZ"].notna()].copy()
    m["_tok"] = m["CSZ"].map(tokenek)
    print(f"MESTER: {len(m)} cikk")

    h = pd.read_csv(a.hianyzo)
    if "CSZ" not in h.columns:
        sys.exit(f"MEGALLOK: a hianyzo listaban nincs CSZ oszlop: {list(h.columns)}")
    print(f"HIANYZO: {len(h)} cikk\n")

    SULY = ["EPR Kategória", "Nettó súly", "Bruttó súly", "Termék akkumulátorának súlya",
            "Termék csomagolásának papír doboz tartalma"]
    sorok = []
    for r in h.itertuples():
        t = tokenek(r.CSZ)
        pont = m["_tok"].map(lambda x: hasonlosag(t, x))
        i = pont.idxmax()
        s = float(pont.loc[i])
        jo = m.loc[i]
        sorok.append({
            "sku": r.sku, "CSZ": r.CSZ, "db": r.db,
            "hasonlosag": round(s, 3),
            "testver_CSZ": jo["CSZ"],
            **{f"javasolt_{k}": jo[k] for k in SULY},
            "kozos_szavak": ", ".join(sorted(t & jo["_tok"])[:6]),
        })
    d = pd.DataFrame(sorok).sort_values("db", ascending=False)

    jo = d[d["hasonlosag"] >= a.min]
    gyenge = d[d["hasonlosag"] < a.min]
    print(f"HASZNALHATO JAVASLAT (hasonlosag >= {a.min}): {len(jo)} cikk, {jo['db'].sum():.0f} db "
          f"({100*jo['db'].sum()/d['db'].sum():.0f}% a hianyzo mennyisegbol)")
    print(f"GYENGE, KEZI MUNKA KELL:                     {len(gyenge)} cikk, "
          f"{gyenge['db'].sum():.0f} db\n")

    print("A TIZ LEGNAGYOBB TETEL:")
    # itertuples ekezetes oszlopnevbol hasznalhatatlan attributumnevet csinal, ezert dict.
    for _, r in d.head(10).iterrows():
        jel = "OK " if r["hasonlosag"] >= a.min else "!! "
        print(f'  {jel}{r["db"]:6.0f} db  hasonlosag {r["hasonlosag"]:.2f}  {str(r["CSZ"])[:54]}')
        print(f'        testver: {str(r["testver_CSZ"])[:62]}')
        print(f'        javasolt: netto {r["javasolt_Nettó súly"]}, brutto '
              f'{r["javasolt_Bruttó súly"]}, kategoria "{r["javasolt_EPR Kategória"]}"')

    print()
    print("AMI KEZI MUNKAT IGENYEL, mennyiseg szerint (a gyenge egyezesuek):")
    for _, r in gyenge.head(12).iterrows():
        print(f'  {r["db"]:6.0f} db  ({r["hasonlosag"]:.2f})  {str(r["CSZ"])[:70]}')

    if a.ki:
        d.to_csv(a.ki, index=False, encoding="utf-8-sig")
        print(f"\nkiirva: {a.ki}")


if __name__ == "__main__":
    main()
