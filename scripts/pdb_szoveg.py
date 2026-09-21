#!/usr/bin/env python3
"""Shared Hungarian-text checks: one implementation, every caller.

WHY THIS FILE EXISTS. On 2026-09-18 the same accent check was hand-written five separate times
in one morning -- once inside the PreToolUse gate and four times inline in ad-hoc send scripts.
That is precisely the shape recorded in `reference_hu_guard_ket_divergens_peldany`: two copies
of a guard drift apart, one catches the em dash, the other catches the ratio, and neither
catches what the other does. Copies do not stay equal; a single module does.

The same morning produced the calibration lesson too. A FIXED absolute threshold ("at least 40
accented characters") rejected a perfectly correct short message, because a shorter text simply
carries fewer accents. A PURE RATIO is the opposite failure: it rejects English. Hence the
detection below is neither -- it counts BARE HUNGARIAN word patterns and compares them against
the accented characters actually present. English text matches no pattern and passes; Hungarian
written without accents matches many and fails.

Callers:
  - scripts/hooks/interagent-ekezet-gate.py  (PreToolUse, direct curl)
  - any script that POSTs to /api/messages, /api/memories, /api/daily-log, /api/kanban

The gate covers DIRECT curl only. A curl launched from inside a Python script is invisible to it
(the Bash command is just `python3 valami.py`), so scripts must call `ellenoriz()` themselves.
"""
import re

EKEZETES = set("áéíóöőúüűÁÉÍÓÖŐÚÜŰ")
EM_DASH = chr(8212)

# Cirill (U+0400-U+04FF) es gorog (U+0370-U+03FF). A homoglifak itt elnek: a cirill "е", "о",
# "а", "с" latin betunek latszik. 2026-09-18-an 17 ilyen sor volt a tartos nyilvantartasban,
# mindig a szo UTOLSO betujeben.
IDEGEN_TARTOMANY = (0x370, 0x4FF)

# Ekezet nelkulre csupaszitott, magyar szovegben gyakori toredekek. Mindegyik olyan, ami
# ANGOL szoveget nem talal el (nem angol szo es nem angol szo resze).
CSUPASZ = [
    r"\bkesz\w*", r"\bkuld\w*", r"\bkerd\w*", r"\bdont\w*", r"\bkerem\b", r"\bkeres\w*",
    r"\bertek\w*", r"\bertesit\w*", r"\bellenoriz\w*", r"\bmeres\w*", r"\bmert\b",
    r"\btovabb\w*", r"\bhataride\w*", r"\bjelolo\w*", r"\bkovetkezo\w*", r"\bszukseg\w*",
    r"\bvalasz\w*", r"\bhianyz\w*", r"\bkulon\w*", r"\bidopont\w*", r"\bugyn?el?\w*",
    r"\bmegkap\w*", r"\bteny\w*", r"\bfontos\b", r"\baltalab\w*", r"\bblokkol\w*",
    r"\bkiment\b", r"\berkez\w*", r"\bcimzett\w*", r"\bszamla\w*", r"\bhonap\w*",
    r"\btermek\w*", r"\bmukod\w*", r"\bjavit\w*", r"\bhasznal\w*", r"\bmodosit\w*",
    r"\btortent\w*", r"\blezar\w*", r"\brogzit\w*", r"\bmegoldas\w*", r"\bnegyedev\w*",
]


def ekezet_hiany(szoveg):
    """(csupasz_talalatok, ekezetes_karakterek_szama).

    Hiany akkor all fenn, ha sok csupasz magyar minta all kevés ekezet mellett. A dontest a
    hivo hozza; a kuszob a `bukik()`-ban van, egy helyen.
    """
    kicsi = szoveg.lower()
    talalat = []
    for mintazat in CSUPASZ:
        talalat += re.findall(mintazat, kicsi)
    ek = sum(1 for ch in szoveg if ch in EKEZETES)
    return talalat, ek


def bukik(szoveg):
    """A kapu es a szkriptek KOZOS kuszobe. KET fuggetlen kivalto, mert egy sem eleg magaban.

    1. MENNYISEGI: legalabb 5 csupasz minta, es az ekezetes karakterek szama kevesebb a
       talalatok felenel. Ez a hosszabb szovegre jo.

    2. NULLA-EKEZET: legalabb 2 csupasz minta mellett EGYETLEN ekezetes karakter sincs.
       MIERT KELL KULON (merve 2026-09-18): a "A kartya keszen all, a dontes megtortent, tobb
       termek ellenorzese lezarult, a kuldes hianyzik meg." mondat csak NEGY mintat talal el,
       tehat az elso szabalyon ATCSUSZIK -- pedig egyetlen ekezet sincs benne. A darabszam-
       kuszob eppen a ROVID szovegnel a leggyengebb, es az ekezet nelkuli szokas eppen ott a
       legeszrevetlenebb. Magyar proza gyakorlatilag mindig tartalmaz ekezetet; a nulla nem
       veletlen. Angol szoveg egyetlen mintat sem talal el, tehat rajta nem tuzel.
    """
    talalat, ek = ekezet_hiany(szoveg)
    mennyisegi = len(talalat) >= 5 and ek < len(talalat) / 2
    nulla_ekezet = len(talalat) >= 2 and ek == 0
    return (mennyisegi or nulla_ekezet), talalat, ek


# Accent folding for SEARCH, not for writing. Added 2026-09-21 after a measured near-miss.
#
# WHY THIS BELONGS HERE. Everything this module gates is written WITH Hungarian accents -- that is
# the whole point of ellenoriz(). The side effect is that our own corpus (skills, prompts, daily
# logs, memories) is accented, while the patterns we type into grep habitually are not. On
# 2026-09-21 Max searched a prompt of mine for 'backup', 'mar torolte', 'PLAUZIBILITAS' and got
# zero on all five, and nearly reported that five safeguards were missing. They were all present,
# spelled 'másolat', 'már törölte', 'plauzibilitás'. The style rule we enforce is exactly what
# made the search blind.
#
# So: fold BOTH the haystack and the needle before matching, and never build a claim on a raw
# accent-less grep over text this module has approved.
_EKEZET_PAROK = str.maketrans(
    "áéíóöőúüűÁÉÍÓÖŐÚÜŰ",
    "aeiooouuuAEIOOOUUU",
)


def ekezettelen(szoveg):
    """Ekezet nelkuli, kisbetus alak KERESESHEZ. Ne hasznald irashoz: a kimeno szoveg
    tovabbra is helyes ekezettel megy, azt az ellenoriz() kenyszeriti ki."""
    return szoveg.translate(_EKEZET_PAROK).lower()


def tartalmazza(szoveg, minta):
    """Ekezet-fuggetlen reszlet-kereses. `minta` lehet ekezetes vagy ekezet nelkuli,
    mindketto ugyanazt talalja. Ez a helyes eszkoz arra, hogy egy sajat korpuszunkon
    futtatott kereses NULLAJA tenyleg hianyt jelentsen, ne irasmod-kulonbseget."""
    return ekezettelen(minta) in ekezettelen(szoveg)


def idegen_kodpontok(szoveg):
    """[(index, karakter, 'U+XXXX')] a cirill/gorog homoglifakra."""
    a, b = IDEGEN_TARTOMANY
    return [(i, ch, f"U+{ord(ch):04X}") for i, ch in enumerate(szoveg) if a <= ord(ch) <= b]


def ellenoriz(szoveg, cimke="szoveg"):
    """Megall, ha a szoveg nem mehet ki. Harom kulon ok, mindharom kulon uzenettel.

    Ezt kell hivni MINDEN olyan szkriptben, ami /api/messages, /api/memories, /api/daily-log
    vagy /api/kanban fele POST-ol -- a PreToolUse kapu ezeket a hivasokat NEM latja.

    A SZERZODES, KIMONDVA, mert 2026-09-21-en egy hivo parkent olvasta es rosszul mert vele:
      ellenoriz(szoveg, cimke) -> True, VAGY AssertionError-t DOB. NEM ad (ok, hibak) part.
      bukik(szoveg)            -> (rossz, talalatok, ekezetszam) harmas, es az CSAK az ekezet-
                                  kuszob. A belepesi pont ez a fuggveny, mert ez nezi mind a
                                  harom okot (ekezet, idegen kodpont, gondolatjel).

    HA EZT A MODULT BURKOLOD (pl. egy agens sajat payload-ellenorevel): FAIL CLOSED. Ha az
    import barmiert nem sikerul, a burkolo UTASITSA EL a kuldest, ne engedje at. Egy csendben
    eltuno kapu rosszabb, mint egy gyengebb kapu: a gyengenel tudjuk, mit enged at, az eltunonel
    azt hisszuk, meg ved. (Megallapodas Max-szal, kartya afefa761.)
    """
    baj = []
    rossz, talalat, ek = bukik(szoveg)
    if rossz:
        minta = ", ".join(sorted(set(talalat))[:8])
        baj.append(f"EKEZET NELKULI MAGYAR: {len(talalat)} csupasz minta, csak {ek} ekezetes "
                   f"karakter. Mintak: {minta}")
    idegen = idegen_kodpontok(szoveg)
    if idegen:
        # A karaktert NEM irjuk ki, csak a kodpontot es a kornyezetet: egy homoglifarol szolo
        # hibauzenetbe beagyazni magat a homoglifat pont azt terjeszti, amirol szol.
        reszlet = "; ".join(f"{kp} a {i}. pozicioban ({szoveg[max(0,i-12):i]!r} utan)"
                            for i, _, kp in idegen[:4])
        baj.append(f"IDEGEN KODPONT (cirill/gorog homoglifa): {reszlet}")
    if EM_DASH in szoveg:
        baj.append(f"EM DASH: {szoveg.count(EM_DASH)} darab. A CLAUDE.md tiltja.")
    if baj:
        raise AssertionError(f"[{cimke}] A szoveg NEM mehet ki:\n  " + "\n  ".join(baj))
    return True
