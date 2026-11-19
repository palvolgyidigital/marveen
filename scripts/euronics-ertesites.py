#!/usr/bin/env python3
"""Euronics webEDI rendelésfigyelő: döntés és üzenetszöveg a Max-féle futás JSON-jából.

David szabálya (Telegram 12017-12058, 2026-11-10): minden futáskor jelezni kell, ha
(1) új rendelés van, vagy (2) van vissza nem igazolt rendelés, életkortól függetlenül;
a több napos legyen kiemelve. Ha egyik sincs: csend.

Bemenet: store/euronics-webedi/utolso-futas.json (euronics_order_monitor.cjs írja).
Kimenet:
  exit 0  -> nincs mit jelezni (stdout: NINCS)
  exit 1  -> van mit jelezni; a szöveg stdout-on, és fájlba is:
             store/euronics-webedi/ertesites-torzs.txt, ertesites-targy.txt
  exit 2  -> a mérés nem használható (bukott futás vagy elavult JSON): HARMADIK állapot,
             nem azt jelenti, hogy nincs rendelés.
--commit: a jelzés UTÁN az ismert-rendelések listáját frissíti (új rendelés csak egyszer új).
"""
import datetime as dt
import json
import os
import sys

# Telepites-fuggetlen gyoker, nem beegetett eleresi ut (ugyanaz a minta, mint
# megszolitas-cimzett-ellenor.py-ban, l. d63e6fe3).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "store", "euronics-webedi")
SRC = f"{BASE}/utolso-futas.json"
KNOWN = f"{BASE}/ismert-rendelesek.json"
BODY = f"{BASE}/ertesites-torzs.txt"
SUBJ = f"{BASE}/ertesites-targy.txt"
# Rendelések, amelyeket a kérő (David) kifejezetten kivett a figyelésből. Formátum:
# {"<rendelésszám>": "<ki, mikor, melyik üzenet>"}. Csak a vissza-nem-igazolt jelzésből
# vesz ki, az új rendelés jelzését nem érinti.
IGNORE = f"{BASE}/figyelmen-kivul.json"
MAX_AGE_MIN = 45


def main() -> int:
    commit = "--commit" in sys.argv
    try:
        d = json.load(open(SRC, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"MERES BUKOTT: a JSON nem olvasható ({e})")
        return 2
    if not d.get("ok"):
        print(f"MERES BUKOTT: a futás ok=false ({d.get('hiba') or d.get('error') or 'nincs hibaszöveg'})")
        return 2
    t = dt.datetime.fromisoformat(d["futas_ideje"].replace("Z", "+00:00"))
    kor = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60
    if kor > MAX_AGE_MIN:
        print(f"MERES BUKOTT: a JSON {kor:.0f} perces, a mai futás nem írta felül")
        return 2

    rend = d.get("rendelesek") or []
    known = set(json.load(open(KNOWN, encoding="utf-8"))) if os.path.exists(KNOWN) else None
    ma = dt.date.today()
    uj = [r for r in rend if known is not None and r["rendelesszam"] not in known]
    ignore = json.load(open(IGNORE, encoding="utf-8")) if os.path.exists(IGNORE) else {}
    nyitott = [r for r in rend if r.get("visszaigazolas_allapot") != "elkuldve"
               and r["rendelesszam"] not in ignore]

    if commit:
        json.dump(sorted(r["rendelesszam"] for r in rend), open(KNOWN, "w", encoding="utf-8"), indent=1)

    if known is None:
        # első futás: az alapállomány felvétele, új rendelésnek semmit nem tekintünk
        uj = []
    if not uj and not nyitott:
        print("NINCS")
        return 0

    uj_szamok = {r["rendelesszam"] for r in uj}
    sorok = []
    for r in sorted(nyitott, key=lambda r: r["datum"]):
        napok = (ma - dt.date.fromisoformat(r["datum"])).days
        allapot = "piszkozat, nincs elküldve" if r.get("visszaigazolas_allapot") == "piszkozat" else "nincs visszaigazolás"
        kiemel = "FONTOS: " if napok >= 1 else ""
        jel = " (ÚJ RENDELÉS)" if r["rendelesszam"] in uj_szamok else ""
        sorok.append(f"{kiemel}{r['rendelesszam']}{jel}: fogadva {r['datum']} {r['ido']} ({napok} napja), visszaigazolás: {allapot}")
    for r in uj:
        if r.get("visszaigazolas_allapot") != "elkuldve":
            continue
        sorok.append(f"ÚJ RENDELÉS: {r['rendelesszam']}, fogadva {r['datum']} {r['ido']}, visszaigazolás: {r.get('visszaigazolas_allapot')}")

    targy_reszek = []
    if uj:
        targy_reszek.append(f"új rendelés: {', '.join(sorted(uj_szamok))}")
    if nyitott:
        targy_reszek.append(f"visszaigazolás nélkül: {', '.join(r['rendelesszam'] for r in nyitott)}")
    targy = "Euronics " + "; ".join(targy_reszek)
    torzs = ("Sziasztok!\n\nAz Euronics webEDI mai ellenőrzése:\n\n" + "\n".join(sorok)
             + "\n\nA felület: https://euronics.webedi.exite.net/\n")
    open(SUBJ, "w", encoding="utf-8").write(targy)
    open(BODY, "w", encoding="utf-8").write(torzs)
    print(targy)
    print("\n".join(sorok))
    return 1


if __name__ == "__main__":
    sys.exit(main())
