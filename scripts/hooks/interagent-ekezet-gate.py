#!/usr/bin/env python3
"""PreToolUse kapu: az INTER-AGENT uzenet (POST /api/messages) ne mehessen ki ekezet nelkuli
magyarral.

MIERT LETEZIK. A CLAUDE.md tilalma szo szerint kimondja: "soha ne irj ekezet nelkuli magyart,
sem Telegram-uzenetben, sem inter-agent/curl payloadban". 2026-09-18-an ezt HAROMSZOR szegtem
meg ugyanaznap (msg 4732, majd 4753 Maxnak). Mindharom esetben a payloadot python3 + json.dumps
allitotta ossze -- vagyis a vedelem, amit hasznaltam, egy MAS hibaosztalyra (shell-interpolacio)
szol, es semmi nem nezte az ekezeteket.

A sor a kuldes utan 8-15 masodperccel mar delivered volt, tehat az utolagos UPDATE a REKORDOT
javitja, a KEZBESITEST nem. Ezen az uton tehat csak ELOZETES ellenorzes er valamit.

Az afefa761 kartyara 08:0x-kor felirtam, hogy a [[feedback_tilalom_harom_helyre_kell]] harmadik
helye (guard a kozos uton) itt URES. Ez a fajl az.

MIT VIZSGAL. A Bash-hivas parancssorabol kiszedi a curl payload forrasat:
  --data-binary @<fajl>   vagy   idezett heredoc (<<'JSON' ... JSON)
es ha a cel a /api/messages, a JSON `content` mezojet ellenorzi.

A DETEKCIO nem azt keresi, hogy VAN-e ekezet, hanem hogy KELLENE-e lennie: magyar szavakban
gyakori, ekezet nelkulre csupaszitott mintakat szamol (pl. "keszult", "kuldes", "tovabbitas",
"dontes"), es azt veti ossze a tenylegesen jelen levo ekezetes karakterek szamaval. Igy az
ANGOL szoveg (technikai payload, kodreszlet) nem bukik el rajta.

MUKODES:
  1. Hook (PreToolUse, JSON a stdin-en, Bash): exit 2 = blokkolva.
  2. `--override "<indoklas>"`: ha a szoveg SZANDEKOSAN ekezet nelkuli (pl. egy idezett
     eredeti payload, vagy tisztan angol tartalom, amit a heurisztika felreert). 90 mp,
     egyszer hasznalhato.

FAIL-OPEN minden belso hibara: egy hook-hiba nem nemithatja el az agens-kozi kommunikaciot.
"""
import json
import os
import re
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "store")
_OVERRIDE_PATH = os.path.join(_STORE_DIR, ".interagent-ekezet-override.json")
_LOG_PATH = os.path.join(_STORE_DIR, "outgoing-copy-gate.log")
_OVERRIDE_TTL = 90

# A DETEKCIO A KOZOS MODULBAN VAN, NEM ITT (osszevonva 2026-09-18 12:0x).
# MIERT: ugyanezt az ellenorzest egyetlen delelott ot kulon helyen irtam meg kezzel, es a
# `reference_hu_guard_ket_divergens_peldany` pontosan azt rogziti, mi lesz ebbol: a ket peldany
# elvalik, az egyik az em dash-t fogja meg, a masik az aranyt, es egyik sem azt, amit a masik.
# Egy implementacio, ket hivo: ez a kapu (kozvetlen curl) es a kuldo szkriptek (`ellenoriz()`).
sys.path.insert(0, _SCRIPTS_DIR)
try:
    import pdb_szoveg
except ImportError as _e:  # pragma: no cover
    # FAIL-OPEN, es ez itt TUDATOS. Ha a modul nem toltheto be, a telepites romlott el, nem a
    # payload. Egy import-hiba miatt NEM nemithatom el a teljes agens-kozi kommunikaciot.
    # A kuldo oldal ettol nem marad fedetlen: a szkriptek ugyanezt a modult importaljak, tehat
    # ott az ImportError magat a kuldest allitja meg, mielott barmi kimenne.
    sys.stderr.write(f"EKEZET-KAPU: a kozos modul nem toltheto be ({_e}), a kapu ATENGED.\n")
    sys.exit(0)


def _naploz(sor: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf8") as fh:
            fh.write(time.strftime("%Y-%m-%dT%H:%M:%S") + " interagent-ekezet-gate " + sor + "\n")
    except Exception:  # noqa: BLE001
        pass


def write_override(indok: str) -> None:
    with open(_OVERRIDE_PATH, "w", encoding="utf8") as fh:
        json.dump({"ts": int(time.time()), "indok": indok}, fh, ensure_ascii=False)
    _naploz("OVERRIDE keszult: " + indok)
    print("Override rogzitve (90 mp, egyszer hasznalhato).")


def _override_elhasznal() -> bool:
    try:
        with open(_OVERRIDE_PATH, encoding="utf8") as fh:
            d = json.load(fh)
    except Exception:  # noqa: BLE001
        return False
    if int(time.time()) - int(d.get("ts", 0)) > _OVERRIDE_TTL:
        return False
    try:
        os.remove(_OVERRIDE_PATH)
    except Exception:  # noqa: BLE001
        pass
    _naploz("OVERRIDE felhasznalva")
    return True


def _payload_szovegek(cmd: str):
    """(szovegek, olvashatatlan_utvonalak).

    A masodik visszateresi ertek MIERT KELL (Max merte, 2026-09-18): ha a `--data-binary @`
    minta MEGVAN, de a fajl nem olvashato (shell-valtozo, pl. `@"$S"`, vagy elgepelt path),
    akkor a regi valtozat a `except: continue`-val NEMAN atengedte a hivast. A kapu tehat
    FAIL-OPEN volt, es a hallgatasa nem bizonyitotta, hogy a payload rendben van.
    Ez ugyanaz a hibaosztaly, ami ellen a kapu iródott, csak magaban a VEDELEMBEN.

    A megoldas Max javaslata es a sajat harom-statuszos elvem (Auchan-szkript): a
    "nem futott le az ellenorzes" KULON statusz, nem ugyanaz, mint a "rendben".
    """
    ki = []
    olvashatatlan = []

    # Az IDEZETT HEREDOC TORZSE ADAT, NEM PARANCS (merve 2026-09-18, a sajat teszt-epito
    # parancsom blokkolta magat). Egy `<<'PYEOF' ... PYEOF` torzsben allo `--data-binary @...`
    # sztring nem kuldes, hanem kiirt szoveg. Ezert a `--data-binary @` kereses ELOTT
    # kivagjuk a heredoc-torzseket; JSON-kent lentebb kulon elemzodnek, ahogy eddig.
    kutatando = re.sub(r"<<'(\w+)'\n.*?\n\1", "", cmd, flags=re.S)

    for m in re.finditer(r"--data-binary\s+@(\S+)", kutatando):
        p = m.group(1).strip("'\"").rstrip("',;)\"")
        try:
            with open(p, encoding="utf8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001
            olvashatatlan.append(p)
            continue
        ki += _mezok(d)
    for m in re.finditer(r"<<'(\w+)'\n(.*?)\n\1", cmd, re.S):
        try:
            d = json.loads(m.group(2))
        except Exception:  # noqa: BLE001
            continue
        ki += _mezok(d)
    return ki, olvashatatlan


# A kartya-POST nem `content`-et kuld, hanem `title` + `description`-t, a komment viszont
# `content`-et. Ha csak a `content`-et neznenk, egy uj kartya leirasa atmenne a kapun.
_SZOVEGMEZOK = ("content", "description", "title")


def _mezok(d):
    if not isinstance(d, dict):
        return []
    return [str(d[k]) for k in _SZOVEGMEZOK if d.get(k)]


# BOVITVE 2026-09-18 10:5x, Max merese utan (msg 4810). A kapu eddig CSAK az /api/messages-t
# nezte, ezert a TARTOS NYILVANTARTAS (memoria, napi naplo, kartya-komment) egesz nap atcsuszott
# rajta. Sajat merés ugyanaznap: a 693 emlekem 77%-a, az 1528 kartya-kommentem 73%-a es az 1011
# naplo-bejegyzesem 71%-a bukna el az ekezet-ellenorzesen. A kar nem stilisztikai: a kevert
# irasmodu korpuszban egy magyar szora irt kereses nemán kihagyja az egyik felet.
_VEDETT_VEGPONTOK = (
    "/api/messages",    # inter-agent uzenet
    "/api/memories",    # memoria (tartos)
    "/api/daily-log",   # napi naplo (tartos)
    "/api/kanban",      # kartya es kartya-komment (tartos)
)


def bash_kapu(tool_input: dict) -> None:
    cmd = str(tool_input.get("command") or "")
    if not any(v in cmd for v in _VEDETT_VEGPONTOK):
        sys.exit(0)
    szovegek, olvashatatlan = _payload_szovegek(cmd)

    # FAIL-CLOSED CSAK ERRE AZ EGY AGRA: a `--data-binary @` minta megvan, de EGYETLEN
    # payload sem volt olvashato. Ha volt olvashato payload is, azt lent normalisan
    # ellenorizzuk -- es a GET-ek, valamint az idezett heredoc-os alak erintetlenul
    # atmennek, mert ott nincs `--data-binary @` minta. (Max kikotese: kulonben a kapu
    # mindent megallit, es az ugyanolyan hasznalhatatlan, mint ha mindent atengedne.)
    if olvashatatlan and not szovegek:
        if _override_elhasznal():
            sys.exit(0)
        _naploz("BLOKK nem-olvashato payload: " + ", ".join(olvashatatlan[:3]))
        sys.stderr.write(
            "EKEZET-KAPU: NEM TUDTAM ELLENORIZNI, ezert MEGALLOK.\n\n"
            "A parancsban van `--data-binary @<utvonal>`, de a payload nem olvashato:\n  "
            + "\n  ".join(olvashatatlan[:3]) + "\n\n"
            "A leggyakoribb ok, hogy az utvonal SHELL-VALTOZO (pl. `@\"$S\"`), amit ez a hook "
            "nem tud feloldani, mert nem lat bele a shell allapotaba. Egy elgepelt path is "
            "ugyanezt adja.\n\n"
            "A MÁSODIK OK, ÉS EZ RITKÁBBAN JUT ESZBE (mérve 2026-09-21, ugyanazon a napon, "
            "mint az első): az útvonal LITERÁLIS és helyes, de a fájl MÉG NEM LÉTEZIK, mert "
            "UGYANAZ a Bash-parancs hozza létre, amelyik küldi is. A hook a parancs INDÍTÁSA "
            "előtt fut, tehát a payloadot kiíró python-rész még le sem futott. Ilyenkor nem az "
            "útvonallal van baj, és az override sem a helyes válasz: bontsd KÉT külön "
            "Bash-hívásra, előbb a payload kiírása, utána a curl.\n\n"
            "MIERT ALLOK MEG ES NEM ENGEDEM AT: 2026-09-18-ig ez a kapu ilyenkor NEMAN atengedte "
            "a hivast (Max merte ki). A hallgatasa igy nem bizonyitotta, hogy a payload rendben "
            "van -- pontosan az a hibaosztaly, ami ellen a kapu iródott. A 'nem futott le az "
            "ellenorzes' KULON statusz, nem ugyanaz, mint a 'rendben'.\n\n"
            "TEENDO, a legolcsobb eloszor:\n"
            "  1. Ird ki az utvonalat LITERALISAN a curl-hivasban, valtozo helyett. Nulla koltseg, "
            "es utana a kapu tenylegesen ellenorzi a szoveget.\n"
            "  2. Vagy tedd az ellenorzest a KULDO SZKRIPTBE (l. a fajl vegen a snippettet), es "
            "jelezd itt override-dal, hogy tudatos:\n"
            f"     python3 {os.path.relpath(os.path.abspath(__file__))} --override \"<rovid indoklas>\"\n"
        )
        sys.exit(2)

    for szoveg in szovegek:
        # A kuszob a kozos modulban van (ket fuggetlen kivalto: mennyisegi, es a rovid
        # szovegre szolo nulla-ekezet szabaly). Itt szandekosan nincs sajat masolata.
        rossz, talalat, ek = pdb_szoveg.bukik(szoveg)
        if rossz:
            if _override_elhasznal():
                sys.exit(0)
            minta = ", ".join(sorted(set(talalat))[:8])
            _naploz(f"BLOKK csupasz={len(talalat)} ekezetes={ek}")
            sys.stderr.write(
                "EKEZET-KAPU: TILTVA. Az inter-agent payload magyar szovegnek latszik, de "
                f"ekezet nelkul: {len(talalat)} csupaszitott magyar minta es csak {ek} ekezetes "
                "karakter.\n\n"
                f"Talalt mintak: {minta}\n\n"
                "A CLAUDE.md tilalma szo szerint: 'soha ne irj ekezet nelkuli magyart, sem "
                "Telegram-uzenetben, sem inter-agent/curl payloadban'.\n\n"
                "AMIERT EZ A KAPU LETEZIK: 2026-09-18-an haromszor szegtem meg ugyanaznap, es a "
                "sor a kuldes utan 8-15 masodperccel mar delivered volt -- vagyis az utolagos "
                "javitas a REKORDOT teszi helyre, a KEZBESITEST nem. Csak elozetes ellenorzes "
                "er valamit.\n\n"
                "TEENDO: ird at a payloadot helyes ekezetekkel, es kuldd ujra.\n"
                "Ha a szoveg SZANDEKOSAN ekezet nelkuli (idezett eredeti payload, vagy tisztan "
                "angol tartalom, amit a heurisztika felreert):\n"
                f"  python3 {os.path.relpath(os.path.abspath(__file__))} --override \"<rovid indoklas>\"\n"
                "Ez 90 masodpercig ervenyes es egyszer hasznalhato.\n"
            )
            sys.exit(2)
    sys.exit(0)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--override":
        if len(sys.argv) != 3:
            print(__doc__)
            return 2
        write_override(sys.argv[2])
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0

    if str(payload.get("tool_name") or "") == "Bash":
        bash_kapu(payload.get("tool_input") or {})
    return 0


if __name__ == "__main__":
    sys.exit(main())

# JAVITVA 2026-09-18 09:5x: FAIL-CLOSED a nem-olvashato payloadra (Max merte ki a rest).
#
# A regi valtozat, ha a `--data-binary @` minta megvolt de a fajl nem olvashato (shell-valtozo,
# elgepelt path), NEMAN atengedte a hivast. Max harom agon merte: literalis utvonal -> blokk,
# az O valtozos mintaja UGYANAZZAL a payloaddal -> atengedte. Vagyis a kapu hallgatasa nem
# bizonyitotta, hogy a payload rendben van.
# Mostantol ez az ag MEGALL ("nem tudtam ellenorizni"), es felajanlja a ket utat.
#
# ES EGY HAMIS POZITIV, AMI AZONNAL KIDERULT: az elso valtozat a sajat teszt-epito parancsomat
# blokkolta, mert a `--data-binary @...` sztringek egy IDEZETT HEREDOC TORZSEBEN alltak, amit
# epp kiirtam egy fajlba. Azota a heredoc-torzsek ki vannak vagva a kereses elol (adat, nem
# parancs). Nyolc agon ujramerve: 1 rossz->2, 2 ekezetes->0, 3 angol->0, 4 valtozos->2,
# 5 elgepelt->2, 6 GET->0, 7 nem-/api/messages->0, 8 heredoc->2. Backup:
# interagent-ekezet-gate.py.bak-2026-09-18-failclosed.
#
# MERT RES, 2026-09-18 09:4x: EZ A KAPU CSAK A KOZVETLEN curl-t LATJA.
#
# A hook a Bash tool_input.command szovegeben keresi a `/api/messages`-t es a
# `--data-binary @fajl` alakot. Ha a curl-t egy PYTHON SZKRIPTEN BELULROL hivom
# (subprocess.run([...'curl'...])), akkor a Bash-parancs csak ennyi: `python3 valami.py`.
# Abban nincs `/api/messages`, tehat a kapu ATENGEDI, es nem is tud rola.
#
# Igy szegtem meg a tilalmat HATODSZOR ugyanaznap, a kapu megkeszulese UTAN.
# Ami megfogta: a kuldo szkriptbe tett sajat assert (ekezetes karakterek szamolasa).
#
# A KETTO TEHAT KOMPLEMENTER, NEM REDUNDANS:
#   - ez a kapu   -> a kozvetlen `curl ... /api/messages` hivasokat fedi
#   - szkript-assert -> a szkriptbol indulo kuldeseket fedi
# Ha uj kuldo szkriptet irsz, a SZKRIPTBE tedd be az ellenorzest, mert ez a kapu nem latja:
#     EK = set('áéíóöőúüűÁÉÍÓÖŐÚÜŰ')
#     assert sum(1 for ch in msg if ch in EK) > 50, 'EKEZET-ELLENORZES BUKOTT'
#     assert not [c for c in msg if 'Ѐ' <= c <= 'ӿ'], 'CIRILL KARAKTER'
# Es erdemes a cirill karakterekre is ('Ѐ'..'ӿ'), mert magyar szo kozepere becsuszo cirill
# betu ket kulon esetben is elofordult ma.
