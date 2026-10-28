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

TIMEZONE: naplo.log stamps are UTC with a Z suffix. The report prints LOCAL Budapest
time, because the reader's morning is local. Use the named zone, never a fixed
offset: a hard-coded UTC+2 was correct only in summer, and on 2026-10-26 (the first
weekday after DST ended) it printed every clock time one hour ahead -- the header
said 08:21 at 07:21 CET. The substantive counts are offset-independent, but the
timestamps a human reads are not.

Usage:
  python3 scripts/edi-reggeli-ellenorzes.py          # prints the report text
  python3 scripts/edi-reggeli-ellenorzes.py --json   # machine-readable verdict
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from install_zone import local_tz  # noqa: E402
import collections
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

NAPLO = "/home/pdb/marveen/store/ecod-agent/naplo.log"
HIBA = "/home/pdb/marveen/store/ecod-agent/cron-error.log"
SAM_STATE = "/home/pdb/marveen/agents/sam/data/edi-mail-check/state.json"
ORAK = 24

# A telepites zonaja, nem beegetett literal (ISSUE1895): scripts/lib/install_zone.py
TZ = local_tz()
INDIT = "ECOD Agent inditasa"
FIGY = re.compile(r"^(\S+) - FIGYELEM: a statuszvaltas NEM ment at ezekre: ([0-9 ,]+)")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


def most() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def ma_kezdet() -> dt.datetime:
    """A mai nap 00:00 LOKALIS idoben. Sam napi 06:00-s koret ehhez mérjük."""
    return most().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
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
    sam_allapot_ideje = None
    varakozo_reszletek: list[str] = []
    try:
        with open(SAM_STATE, encoding="utf-8") as fh:
            st = json.load(fh)
        fuggo = len(st.get("pending_orders") or {})
        ert = st.get("notified_orders") or {}
        varakozo = len(ert)
        # DAVID KERESE, 2026-10-12 08:42 (Telegram 9140), szo szerint: "Melyik, mikor
        # hianyzik? Fontos, hogy ezt jobban emeld ki a levelben". Addig a riport CSAK a
        # darabszamot adta, es o maga irta, hogy ezert nem vette eszre. Egy szam nem
        # cselekvesre hivo informacio: a rendelesszam, az aruhaz es a datumok azok.
        for rend, adat in sorted(ert.items()):
            if not isinstance(adat, dict):
                varakozo_reszletek.append(f"{rend}")
                continue
            reszek = [str(rend)]
            if adat.get("store"):
                reszek.append(str(adat["store"]))
            if adat.get("delivery_date"):
                reszek.append("szállítási dátum " + str(adat["delivery_date"]))
            tetelszam = len(adat.get("articles") or [])
            if tetelszam:
                reszek.append(f"{tetelszam} tétel")
            jelzes = str(adat.get("notified_at") or "")[:10]
            if jelzes:
                reszek.append("jelezve " + jelzes)
            varakozo_reszletek.append(", ".join(reszek))
        kor = dt.datetime.fromtimestamp(os.path.getmtime(SAM_STATE), dt.timezone.utc)
        sam_allapot_ideje = kor.astimezone(TZ)
        # SAM MERESE, 2026-10-14 09:2x (inter-agent msg 6352): a 30 oras kuszob TUL BO.
        # Ma a gazdagep-kieses miatt Sam 06:00-s kore 'missed' lett, az allapotfajl a
        # TEGNAPI 06:00-s meresnel maradt, es a 08:22-es riport abbol kuldott szamokat
        # Davidnak. A fajl akkor 26,4 oras volt, tehat a 30 oras kuszob NEM tuzelt, es
        # semmi nem jelezte, hogy a Relex-szamok egy napos adatbol vannak. Valos kar
        # ezuttal nem lett (a ket mai rendeles rendben volt), de a mechanizmus valodi.
        # EZERT A FELTETEL MOSTANTOL NEM IDOTARTAM, HANEM AZ, HOGY A MAI FUTASBOL VAN-E:
        # Sam ellenorzoje naponta 06:00-kor fut (cron '0 6 * * *', hetvegen is), tehat
        # 07:00 utan a mai allapot MEGLETE a helyes elvaras, nem egy 30 oras ablak.
        mai_hatar = ma_kezdet().replace(hour=6)
        if most().astimezone(TZ) >= ma_kezdet().replace(hour=7) and sam_allapot_ideje < mai_hatar:
            baj.append("A Relex-osszevetes allapota NEM a mai futasbol van ("
                       + sam_allapot_ideje.strftime("%m-%d %H:%M")
                       + "), tehat a napi 06:00-s ellenorzes a riport elott nem futott le. "
                       + "A lenti Relex-szamok ennek a korabbi napnak az allapotat tukrozik.")
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
                f"Relex-oldali függő rendelés: {fuggo if fuggo is not None else 'nem mérhető'}"
                + (f" (a Relex-összevetés állapota: {sam_allapot_ideje.strftime('%m-%d %H:%M')})"
                   if sam_allapot_ideje else "") + ".",
                f"Korábban jelzett hiányzó EDI-átvitel: {varakozo if varakozo is not None else 'nem mérhető'}."]
    if varakozo_reszletek:
        sorokki += ["",
                    ("FIGYELEM, EZ A TÉTEL MÉG NYITOTT, nem a mai napról szól:"
                     if len(varakozo_reszletek) == 1 else
                     f"FIGYELEM, {len(varakozo_reszletek)} TÉTEL MÉG NYITOTT, egyik sem a mai napról szól:")]
        sorokki += ["  - " + s for s in varakozo_reszletek]
        sorokki.append("Ez azt jelenti, hogy a Relex-levél megjött, de EDI-átvitel nem párosult hozzá,")
        sorokki.append("és a jelzés a fenti napon egyszer már kiment.")
    if elakadt and not tartos:
        sorokki.append("Egy futásban függőben maradt, a következő óra újrapróbálta: "
                       + ", ".join(sorted(elakadt)) + ".")
    print("\n".join(sorokki))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
