#!/usr/bin/env python3
"""Morning EDI completeness check for David: did any MediaMarkt order miss the load?

WHY (2026-09-30, David's request on Telegram): he asked for a WEEKDAY EMAIL, by 08:00,
confirming that no order is left out of the loading. Until now there were two separate
silent checks and no positive confirmation:
  - the hourly ECOD loader (system cron, store/ecod-agent/ecod_agent.cjs),
  - Sam's daily 06:00 Relex-vs-ECOD comparison (agents/sam/data/edi-mail-check/).
Neither says "all clear", and a check that only speaks up on failure cannot be told
apart from a check that has died. This script produces the positive report.

IT READS SAM'S state.json, IT DOES NOT RUN HIS CHECKER. Running it would mutate the
shared state, and his "notify once" logic would then fire for whichever of us got there
first, silently robbing the other. Read-only is the whole point.

THREE THINGS IT MEASURES, and they fail differently:
  1. RUN COVERAGE -- one loader start per hour. A missing hour is a window in which an
     order could have sat unfetched. Measured from the log's own start lines.
  2. RUN FAILURE -- cron-error.log. The loader writes stdout to /dev/null and stderr
     here, so a crashed run leaves NO trace in naplo.log at all: the hour simply goes
     missing. On 2026-09-29 09:00 a MODULE_NOT_FOUND killed one run exactly this way.
  3. STUCK STATUS -- a "FIGYELEM: a statuszvaltas NEM ment at" line names orders left
     pending in ECOD. These retry next hour, so one appearance is normal; the same
     order across several runs is not.

A NOTE ON THE THIRD STATE, because this is a report someone will trust: whenever a
source cannot be read, the script says so and the verdict becomes BIZONYTALAN. It never
reports "all clear" from a file it failed to open -- an unreadable log looks exactly
like a quiet one.

TIMEZONE: naplo.log stamps are UTC with a Z suffix. Budapest is UTC+2 in summer. The
report prints LOCAL time, because the reader's morning is local.

Usage:
  python3 scripts/edi-reggeli-ellenorzes.py          # prints the report text
  python3 scripts/edi-reggeli-ellenorzes.py --json   # machine-readable verdict
"""
import collections
import datetime as dt
import json
import os
import re
import sys

NAPLO = "/home/pdb/marveen/store/ecod-agent/naplo.log"
HIBA = "/home/pdb/marveen/store/ecod-agent/cron-error.log"
SAM_STATE = "/home/pdb/marveen/agents/sam/data/edi-mail-check/state.json"
ORAK = 24

TZ = dt.timezone(dt.timedelta(hours=2))
INDIT = "ECOD Agent inditasa"
FIGY = re.compile(r"^(\S+) - FIGYELEM: a statuszvaltas NEM ment at ezekre: ([0-9 ,]+)")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def most() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def olvas(path: str):
    """(sorok, hibauzenet). A hibauzenet NEM ures = harmadik allapot, nem nulla talalat."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines(), None
    except Exception as exc:  # noqa: BLE001
        return [], f"{path} nem olvashato: {exc!r}"


def futas_lefedettseg(sorok, hatar):
    """Melyik orakban indult futas a vizsgalt ablakban, es melyikben nem."""
    latott = set()
    for s in sorok:
        if INDIT not in s:
            continue
        m = STAMP.match(s)
        if not m:
            continue
        t = dt.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if t >= hatar:
            latott.add(t.replace(minute=0, second=0, microsecond=0))
    # A hatar ritkan esik egesz orara. Az elso ELVART ora az elso olyan egesz ora, ami
    # mar a hataron BELUL van -- kulonben a hatar elotti percekben indult futas kiesik a
    # `latott` halmazbol, miközben az ora bekerul a `vart`-ba, es a kettoso egy nem letezo
    # kimaradast jelent. Ez a kulonbseg adott hamis riasztast az elso futasnal.
    elso = hatar.replace(minute=0, second=0, microsecond=0)
    if elso < hatar:
        elso += dt.timedelta(hours=1)
    # Az UTOLSO elvart ora a mostani, de csak ha mar eltelt par perc a fordulo ota: a
    # betolto :00-kor indul, es egy :00 es :03 kozott futo jelentes kulonben azt allitana,
    # hogy kimaradt egy ora, amelyik meg el sem kezdodott.
    utolso = most().replace(minute=0, second=0, microsecond=0)
    if most().minute < 5:
        utolso -= dt.timedelta(hours=1)
    vart = set()
    t = elso
    while t <= utolso:
        vart.add(t)
        t += dt.timedelta(hours=1)
    return latott, sorted(vart - latott)


def elakadt_statuszok(sorok, hatar):
    """rendelesszam -> hany kulon futasban jelezte a naplo fuggonek."""
    szamlalo = collections.Counter()
    utolso = {}
    for s in sorok:
        m = FIGY.match(s)
        if not m:
            continue
        t = dt.datetime.strptime(m.group(1)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if t < hatar:
            continue
        for szam in re.findall(r"\d{6,}", m.group(2)):
            szamlalo[szam] += 1
            utolso[szam] = t
    return szamlalo, utolso


def main() -> int:
    hatar = most() - dt.timedelta(hours=ORAK)
    bizonytalan = []
    baj = []

    sorok, hiba = olvas(NAPLO)
    if hiba:
        bizonytalan.append(hiba)
    latott, hianyzo = futas_lefedettseg(sorok, hatar)
    if hianyzo and not hiba:
        baj.append("Kimaradt betoltesi ora: "
                   + ", ".join(t.astimezone(TZ).strftime("%m-%d %H:00") for t in hianyzo))

    hibasorok, hiba2 = olvas(HIBA)
    friss_hiba = False
    if hiba2:
        bizonytalan.append(hiba2)
    elif os.path.exists(HIBA):
        kor = dt.datetime.fromtimestamp(os.path.getmtime(HIBA), dt.timezone.utc)
        friss_hiba = kor >= hatar and bool([s for s in hibasorok if s.strip()])
        if friss_hiba:
            baj.append("A betolto hibanaploja frissult: "
                       + kor.astimezone(TZ).strftime("%m-%d %H:%M")
                       + " -- utolso sor: " + (hibasorok[-1][:120] if hibasorok else ""))

    elakadt, utolso = elakadt_statuszok(sorok, hatar)
    tartos = {k: v for k, v in elakadt.items() if v > 1}
    if tartos:
        baj.append("Tobb futason at fuggoben maradt statuszvaltas: "
                   + ", ".join(f"{k} ({v} futas)" for k, v in sorted(tartos.items())))

    fuggo = varakozo = None
    try:
        with open(SAM_STATE, encoding="utf-8") as fh:
            st = json.load(fh)
        fuggo = len(st.get("pending_orders") or {})
        varakozo = len(st.get("notified_orders") or {})
        kor = dt.datetime.fromtimestamp(os.path.getmtime(SAM_STATE), dt.timezone.utc)
        if kor < most() - dt.timedelta(hours=30):
            baj.append("A Relex-osszevetes allapota 30 oranal regebbi ("
                       + kor.astimezone(TZ).strftime("%m-%d %H:%M")
                       + "), tehat a napi 06:00-s ellenorzes valoszinuleg nem futott.")
    except Exception as exc:  # noqa: BLE001
        bizonytalan.append(f"Sam allapotfajlja nem olvashato: {exc!r}")

    if bizonytalan:
        verdikt = "BIZONYTALAN"
    elif baj:
        verdikt = "ELTERES"
    else:
        verdikt = "RENDBEN"

    if "--json" in sys.argv:
        print(json.dumps({"verdikt": verdikt, "baj": baj, "bizonytalan": bizonytalan,
                          "futott_ora": len(latott), "hianyzo_ora": len(hianyzo),
                          "relex_fuggo": fuggo}, ensure_ascii=False, indent=2))
        return 0

    ma = most().astimezone(TZ)
    sorokki = [f"EDI betöltés-ellenőrzés, {ma.strftime('%Y-%m-%d %H:%M')}",
               f"Vizsgált időszak: az elmúlt {ORAK} óra.", ""]
    if verdikt == "RENDBEN":
        sorokki.append("Nem maradt ki rendelés a betöltésből.")
    elif verdikt == "ELTERES":
        sorokki.append("ELTÉRÉS, az alábbiak szerint:")
    else:
        sorokki.append("BIZONYTALAN: legalább egy forrást nem tudtam elolvasni, ezért")
        sorokki.append("ezt a kört NEM jelentem rendben lévőnek.")
    for b in baj:
        sorokki.append("  - " + b)
    for b in bizonytalan:
        sorokki.append("  - nem mérhető: " + b)
    sorokki += ["",
                f"Lefutott betöltés: {len(latott)} óra a várt {ORAK}-ból.",
                f"Relex-oldali függő rendelés: {fuggo if fuggo is not None else 'nem mérhető'}.",
                f"Korábban jelzett hiányzó EDI-átvitel: {varakozo if varakozo is not None else 'nem mérhető'}."]
    if elakadt and not tartos:
        sorokki.append("Egy futásban függőben maradt, a következő óra újrapróbálta: "
                       + ", ".join(sorted(elakadt)) + ".")
    print("\n".join(sorokki))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
