#!/usr/bin/env python3
"""PreToolUse gate: mielott egy kimeno Telegram-valasz TUDAS-TAGADAST allit
("nincs informacio", "nem tudom", "nem latom" stb.), ellenorzi, hogy a valasz
mar le van-e irva a sajat feljegyzeseinkben (memoria/skill/utemezett feladat/
kanban-kartya). Ha igen: BLOKKOL, es megmutatja a talalatot.

MIERT EZ A SZUK HATOKOR, NEM "MINDEN KIMENO UZENET": 2026-09-02-en Pedro ot
sajat esetet adott at meresre. A validalas (Bob) kimutatta, hogy egy tagabb
szabaly ("tudas-tagadas VAGY kerdojel") a napi forgalom kb. NEGYEDEN tuzelt
volna -- hasznalhatatlan zaj.

KET KULON SZAM VAN ITT, NE KEVEREDJEN A KETTO (Pedro javitasa, 2026-09-03,
msg 2673 -- a docstring korabban a tervezesi szamot allitotta a kesz kapu
jellemzojekent, majdnem otszoros tulbecslessel): a NYERS tudas-tagadas
MINTA-detektor onmagaban, MEG A FELJEGYZES-KERESES NELKUL, a forgalom 6.7
szazalekan tuzel (115/1714, Pedro sajat kimeno naploja -- ez a TERVEZESI
adat, msg 2605, ami eldontotte hogy a negacio-ag eleg szuk-e ahhoz, hogy
egyaltalan erdemes legyen ra epiteni). A MEGEPITETT, TENYLEGES kapu -- ahol
a tagadasnak ES a talalt feljegyzesnek EGYUTT kell teljesulnie -- ennel
sokkal szukebb: 1.4 szazalekon blokkol (24/1714, msg 2607). A 6.7 mint
tervezesi adat tovabbra is erdekes (ez mutatja, mekkora a nyers minta
zaj-potencialja a kereses nelkul), de az ELESITENDO KAPU jellemzoje az 1.4,
nem a 6.7.

Ez PONTOSAN azt az esetet fogja, amiert az egesz elindult (a "nincs GitHub
tokenunk" allitas, holott a szefben ott volt).
A "mar eldontott dolgot masodszor is elohozom" mintazat (a masik negy eset)
SZANDEKOSAN NINCS ebben a kapuban: az tartalmi egyezes kerdese, nem kulcsszo-
egyezese, es egy regex ezt nem tudja megbizhatoan elkulöníteni egy uj, jogos
kerdestol. Arra Pedro a scripts/kartya.py eszkozt epitette (a ket kartya-
reteg -- leiras es kommentek -- egyben-olvasasa), nem ez a kapu.

A detekcio a scripts/tudunk-e-rola.py fuggvenyeit hasznalja valtozatlanul
(talalatok_fajlokban, talalatok_kartyakon), tehat a kereses logikaja es a
forras-lista egyetlen helyen el.

SIKERESSEG-MERCE (irja bele Pedro, 2026-09-02): HA EGY HETEN BELUL A
TALALATOK TOBB MINT FELE OVERRIDE-OT KAP, A KAPU ROSSZ, NEM A FELHASZNALO.
Minden blokkolas es minden override bekerul a store/outgoing-copy-gate.log-ba
idobelyeggel, ez adja a nevezot/szamlalot a heti mereshez.

MEGJEGYZES A HATOKORROL: mind a 6.7 (nyers tagadas-detektor), mind az 1.4
szazalekos (a megepitett kapu tenyleges blokkolasi aranya) KIZAROLAG Pedro
sajat kimeno forgalman van megmerve. A hook fleet-wide van bekotve (minden
agens Telegram-valaszara), az egress-gate mintajat kovetve -- de MAS agens
sajat aranya nem volt megmerve. Ha valakinel ez zajosnak bizonyul, azt a
sikeresseg-merce (fent) es a store/outgoing-copy-gate.log mutatja meg.

MUKODESI MODOK, ugyanaz a szerkezet, mint a cimzett-gate.py-nal:
  1. Hook (PreToolUse, JSON a stdin-en): a
     mcp__plugin_telegram_telegram__reply hivast vizsgalja.
  2. `--override "<indoklas>"` CLI: explicit szandek-jelzes egy legitim eset
     elott (pl. a talalat valojaban nem relevans, mert idokozben megvaltozott
     az allapot). 90 masodpercig ervenyes, EGYSZER hasznalhato.

FAIL-OPEN minden BELSO hibara (hianyzo/serult import, varatlan kivetel):
a Telegram az EGYETLEN felugyeleti csatorna, egy hook-hiba miatti nemitas
rosszabb, mint egy el nem kapott, mar megvalaszolt kerdes ujra feltevese.
Egy TALALT problema viszont blokkol -- az a kapu ertelme.
"""
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TER_PATH = os.path.join(_SCRIPTS_DIR, "tudunk-e-rola.py")
_STORE_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "store")
_OVERRIDE_PATH = os.path.join(_STORE_DIR, ".tudastagadas-gate-override.json")
_LOG_PATH = os.path.join(_STORE_DIR, "outgoing-copy-gate.log")
_OVERRIDE_TTL = 90  # masodperc

# A validalt lista (Bob merese, 2026-09-02): szuk, tudas-TAGADAS mintak.
# Szandekosan NEM tartalmaz kerdojelet vagy altalanos "nincs" szot onmagaban --
# az elozo meres szerint a kerdojel egyedul a forgalom kb. negyeden tuzelt volna.
NEG_PHRASES = [
    "nincs bejelentkez",
    "nem latom",
    "nem latjuk",
    "nem tudom",
    "nem tudjuk",
    "nem talaltam",
    "nem talaltuk",
    "nem tudunk rola",
    "nincs info",
    "nincs rola info",
    "meg nem neztem",
]

STOP = set("""a az es hogy nem meg ha de mar mint egy ket ki mi aki ami
ott itt most tehat vagy csak igy attol arra erre ebbol abbol azt ezt
en te o mi ti ok magam maga sajat volt van lesz kell lehet ez az egyik
masik olyan ilyen nagyon nagyobb kisebb miatt utan elott kozott szerint
azert ezert amikor amig mert hanem viszont pedig tovabba illetve stb
igen nincsen sincs semmi minden mindegyik barmi valami akkor most ma
tegnap holnap reggel este delutan delelott""".split())


def _ekezettelen(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _load_ter():
    spec = importlib.util.spec_from_file_location("tudunk_e_rola", _TER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _log(sor: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(sor.rstrip("\n") + "\n")
    except OSError:
        pass


# Ezek a flotta SAJAT, mindennapos szokincse -- annyira gyakoriak a sajat
# feljegyzeseinkben, hogy EGYEDUL, tovabbi szo nelkul SOSEM lehetnek kereso-
# kulcsszo (Bob merese, 2026-09-02: 'telegram' onmagaban 401, 'agent' onmagaban
# 793 talalatot ad -- ez nem egyezes, ez zaj). Csak akkor tiltjuk oket, ha
# EGYEDUL allnanak; par mellett (pl. 'telegram'+'kapcsolat') tovabbra is
# hasznalhatoak, mert ott a masik szo mar szukit.
SOLO_BLACKLIST = {
    "telegram", "agent", "agens", "ugynok", "dashboard", "memoria", "kanban",
    "skill", "email", "kartya", "csatorna", "uzenet", "rendszer", "projekt",
    "feladat", "komment", "level", "adat", "riport", "teszt", "hiba", "kerdes",
}


def _keywords(text: str, n: int = 2, only_specific: bool = False):
    """A legspecifikusabb tartalmi szavak, nem az elso n. Ok (mert az elso
    valtozat, ami egyszeruen az elso n nem-stopszot vette, a github-eseten
    a 'megprobaltam'-ot valasztotta 'github' melle -- ez a szo tulsagosan
    altalanos, es veletlenszeru egyezest adott egy oda nem tartozo
    kartya-kommenttel): egy szo AKKOR szamit specifikusnak, ha az EREDETI
    (nem ekezettelenitett) szovegben van benne nagybetu, ami NEM a mondat
    elso karaktere -- ez a magyar helyesiras szerint tulajdonnevet vagy
    termeket jelol (GitHub, Marci, UNAS), nem koznevet vagy igealakot.
    A specifikus szavak elore kerulnek, utana hossz szerint csokkeno sorrend.
    `only_specific=True`: a NEM specifikus szavak ki sem kerulnek a listaba --
    ezt hasznalja az egy-szavas widen-lepes, mert a 'leghosszabb szo a
    mondatban, akarmi legyen is' (bizz, megmondani, harmadikat, stb.) meres
    szerint tiszta zaj, ha nincs mogotte tulajdonnev-jelleg."""
    sentence_starts = set()
    pos = 0
    for s in re.split(r"(?<=[.!?])\s+|\n+", text):
        sentence_starts.add(pos)
        pos += len(s) + 1

    seen = set()
    scored = []
    for m in re.finditer(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}", text):
        raw = m.group(0)
        norm = _ekezettelen(raw)
        if norm in STOP or norm in seen:
            continue
        seen.add(norm)
        interior_upper = any(c.isupper() for c in raw[1:])
        starts_sentence = m.start() in sentence_starts or m.start() == 0
        specific = interior_upper or (raw[0:1].isupper() and not starts_sentence)
        if only_specific and not specific:
            continue
        scored.append((not specific, -len(raw), norm))
    scored.sort()
    return [norm for _spec, _len, norm in scored[:n]]


def _keywords_widen(text: str):
    """Fokozatosan bovulo kulcsszo-halmazok kereseshez: elobb a ket
    legspecifikusabb szo egyutt (pontos, de tobb hamis-negativ), majd ha az
    ures, a legspecifikusabb EGYEDUL, DE csak ha az tenyleg specifikus
    (tulajdonnev-jellegu) ES nincs a SOLO_BLACKLIST-en. Az elso NEM-ures
    eredmenyt hasznaljuk -- a keresomotorok szokasos 'szukitsd, majd tagitsd,
    ha nincs talalat' strategiaja, nem ez az egy eset diktalja."""
    two = _keywords(text, n=2)
    if len(two) == 2:
        yield two
    one = _keywords(text, n=1, only_specific=True)
    if one and one[0] not in SOLO_BLACKLIST:
        yield one


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _negation_sentences(text: str):
    """A tagadast tartalmazo MONDATOK szovege, nem a teljes uzenet eleje.
    Ok (mert eloszor a teljes-uzenet-eleji valtozat elbukott a sajat
    tesztjen): a github-eset tagadasa a szoveg KOZEPEN allt, a mondat elso
    hat tartalmi szava viszont egy korabbi, oda nem tartozo bekezdesbol jott
    volna -- a kereses igy sose talalta volna meg a 'github'/'token' szavakat.
    A tagadast hordozo mondat(ok) szovege viszont pont a releváns temat adja."""
    sentences = _SENT_SPLIT.split(text)
    out = []
    for s in sentences:
        if any(p in _ekezettelen(s) for p in NEG_PHRASES):
            out.append(s)
    return out or [text]  # biztonsagi halo, ha a splitter nem valt szet semmit


# --- override: explicit szandek-jelzes, egyszer hasznalhato, idokorlatos ----

def write_override(reason: str) -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)
    data = {"reason": reason, "written_at": time.time()}
    tmp = _OVERRIDE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _OVERRIDE_PATH)
    print(f"OVERRIDE feljegyezve, {_OVERRIDE_TTL} masodpercig ervenyes, egyszer hasznalhato. Kuldd el most a valaszt.")


def consume_override():
    if not os.path.exists(_OVERRIDE_PATH):
        return None
    try:
        with open(_OVERRIDE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    fresh = (time.time() - float(data.get("written_at", 0))) <= _OVERRIDE_TTL
    try:
        os.remove(_OVERRIDE_PATH)
    except OSError:
        pass
    return (data.get("reason") or "(indoklas nelkul)") if fresh else None


# --- a tenyleges ellenorzes ---------------------------------------------------

def collect_text(tool_input: dict) -> str:
    fields = ("text", "caption", "message")
    got = [str(tool_input[f]) for f in fields if tool_input.get(f)]
    return "\n".join(got)


def telegram_gate(tool_input: dict) -> None:
    try:
        text = collect_text(tool_input)
        if not text.strip():
            sys.exit(0)
        norm = _ekezettelen(text)
        hit_phrases = [p for p in NEG_PHRASES if p in norm]
        if not hit_phrases:
            sys.exit(0)
        scope = " ".join(_negation_sentences(text))
        ter = _load_ter()
        kw, talalatok = [], []
        for kw in _keywords_widen(scope):
            talalatok = ter.talalatok_fajlokban(kw) + ter.talalatok_kartyakon(kw)
            if talalatok:
                break
        if not kw:
            sys.exit(0)  # egyetlen specifikus szo sem volt, a kereses csak zajt adna
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate: fail-open path
        _log(f"tudastagadas-gate: BELSO HIBA, FAIL-OPEN atengedes: {exc!r}")
        sys.exit(0)

    if not talalatok:
        sys.exit(0)

    override_ok = consume_override()
    if override_ok:
        _log(
            f"tudastagadas-gate: OVERRIDE hasznalva -- tagadas={hit_phrases}, "
            f"kulcsszavak={kw}, {len(talalatok)} talalat, indoklas: {override_ok}"
        )
        sys.exit(0)

    _log(f"tudastagadas-gate: BLOKKOLVA -- tagadas={hit_phrases}, kulcsszavak={kw}, {len(talalatok)} talalat")
    shown = "\n".join(f"  [{c}] {h}\n      {sz}" for c, h, _s, sz in talalatok[:5])
    more = f"\n  ... es meg {len(talalatok) - 5} talalat." if len(talalatok) > 5 else ""
    sys.stderr.write(
        "TUDAS-TAGADAS KAPU: TILTVA. A szoveg tudas-hianyt allit "
        f"({', '.join(hit_phrases)!r}), de a sajat feljegyzeseink kozott van talalat "
        f"a kulcsszavakra ({', '.join(kw)}):\n\n{shown}{more}\n\n"
        "Nezd meg a talalatot, mielott kuldod. Ha valoban erre a valaszra van szukseg "
        "(a talalat elavult vagy nem relevans): jelezd explicit szandekkal, MIELOTT "
        "ujra probalkozol:\n"
        f"  python3 {os.path.relpath(os.path.abspath(__file__))} --override \"<rovid indoklas>\"\n"
        "Ez 90 masodpercig ervenyes es egyszer hasznalhato.\n"
    )
    sys.exit(2)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--override":
        if len(sys.argv) != 3:
            print(__doc__)
            return 2
        write_override(sys.argv[2])
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if "telegram" in tool.lower() and tool.lower().endswith("__reply"):
        telegram_gate(tool_input)
    return 0


if __name__ == "__main__":
    sys.exit(main())
