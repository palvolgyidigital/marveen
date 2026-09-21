#!/usr/bin/env python3
"""PreToolUse kapu: a kimeno Telegram-uzenet ne legyen hosszabb, mint amit a CIMZETT ker.

MIERT LETEZIK. 2026-09-18-an David ezt irta (chat_id 8918812779, msg 6623, szo szerint):
"megint odakat, irsz, hogyan lehetne beallitani azt, hogy ne kelljen 1orat olvasni amiket
osszeirsz. minden nap kerem tobbszor". Aznap reggel hat uzenetet kuldtem neki, tobb
szakaszcimmel, nagybetus fejlecekkel es modszertani reszekkel.

A KRITIKUS RESZ: a keres NEM volt uj. A `feedback_david_rovid_uzenet` memoria mar
rogzitette ("mit mertem / mi a feladat / hogy oldom meg, a modszertan a kartyara megy"),
es a kanban-audit skill is kimondja, hogy fejenkent egy-ket mondat, nem bekezdes. Vagyis
a tudas megvolt, es megsem tartotta meg semmi IRAS KOZBEN. David sajat szavai szerint
"minden nap kerem tobbszor" -- tehat a feljegyzes mint mechanizmus bizonyitottan nem mukodik.
Ez a kapu a harmadik hely, ahol a tilalomnak allnia kell (memoria / skill / guard a kozos
uton), l. [[feedback_tilalom_harom_helyre_kell]].

MUKODES:
  1. Hook (PreToolUse, JSON a stdin-en): a telegram reply hivast vizsgalja. Ha a cimzett
     chat_id-re van hossz-limit, es a szoveg tullepi, exit 2 (a modell latja a stderr-t
     es rovidithet).
  2. `--override "<indoklas>" <chat_id>`: ha a hossz INDOKOLT (pl. a cimzett maga kert
     reszletes anyagot, vagy egy listat tetelesen kell atadni). 90 masodpercig ervenyes,
     EGYSZER hasznalhato.

A LIMITEK a store/uzenet-hossz-limitek.json fajlban vannak, cimzettenkent. Ha egy kollega
mast ker, ott kell atirni, nem a kodban.

FAIL-OPEN minden belso hibara: a Telegram-ag az egyetlen kifele meno csatorna, egy
hook-hiba miatti nemitas rosszabb, mint egy tul hosszu uzenet.
"""
import json
import os
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "store")
_LIMIT_PATH = os.path.join(_STORE_DIR, "uzenet-hossz-limitek.json")
_OVERRIDE_PATH = os.path.join(_STORE_DIR, ".uzenet-hossz-gate-override.json")
_LOG_PATH = os.path.join(_STORE_DIR, "outgoing-copy-gate.log")
_OVERRIDE_TTL = 90


def _naploz(sor: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf8") as fh:
            fh.write(time.strftime("%Y-%m-%dT%H:%M:%S") + " uzenet-hossz-gate " + sor + "\n")
    except Exception:  # noqa: BLE001
        pass


def write_override(indok: str, chat_id: str) -> None:
    payload = {"ts": int(time.time()), "chat_id": str(chat_id), "indok": indok}
    with open(_OVERRIDE_PATH, "w", encoding="utf8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    _naploz("OVERRIDE keszult chat_id=" + str(chat_id) + " indok=" + indok)
    print("Override rogzitve (90 mp, egyszer hasznalhato), chat_id=" + str(chat_id))


def _override_elhasznal(chat_id: str) -> bool:
    try:
        with open(_OVERRIDE_PATH, encoding="utf8") as fh:
            d = json.load(fh)
    except Exception:  # noqa: BLE001
        return False
    if str(d.get("chat_id")) != str(chat_id):
        return False
    if int(time.time()) - int(d.get("ts", 0)) > _OVERRIDE_TTL:
        return False
    try:
        os.remove(_OVERRIDE_PATH)  # egyszer hasznalhato
    except Exception:  # noqa: BLE001
        pass
    _naploz("OVERRIDE felhasznalva chat_id=" + str(chat_id))
    return True


def _limit(chat_id: str):
    try:
        with open(_LIMIT_PATH, encoding="utf8") as fh:
            d = json.load(fh)
    except Exception:  # noqa: BLE001
        return None
    return d.get(str(chat_id))


def _meret(text: str):
    """Sorok szama (az ures sorok NEM szamitanak, azok tagolas) es karakterszam."""
    sorok = [s for s in text.split("\n") if s.strip()]
    return len(sorok), len(text)


def hossz_kapu(tool_input: dict) -> None:
    chat_id = tool_input.get("chat_id")
    text = str(tool_input.get("text") or tool_input.get("caption") or "")
    if not chat_id or not text:
        sys.exit(0)
    lim = _limit(chat_id)
    if not lim:
        sys.exit(0)

    sor, kar = _meret(text)
    max_sor = int(lim.get("max_sor", 10**6))
    max_kar = int(lim.get("max_kar", 10**9))
    if sor <= max_sor and kar <= max_kar:
        sys.exit(0)

    if _override_elhasznal(chat_id):
        sys.exit(0)

    nev = lim.get("nev") or str(chat_id)
    indok = lim.get("indok") or ""
    tul = []
    if sor > max_sor:
        tul.append(f"{sor} nem-ures sor (a limit {max_sor})")
    if kar > max_kar:
        tul.append(f"{kar} karakter (a limit {max_kar})")
    _naploz(f"BLOKK chat_id={chat_id} sor={sor}/{max_sor} kar={kar}/{max_kar}")
    sys.stderr.write(
        "HOSSZ-KAPU: TILTVA. Ez az uzenet " + nev + "-nak/nek megy, es " + ", ".join(tul) + ".\n\n"
        + (indok + "\n\n" if indok else "")
        + "AMIT TENNI KELL: ird ujra rovidebben. Ne a tartalmat vagd le talalomra, hanem\n"
        "hagyd el a modszertant, az indoklast es a mereseket -- azok a KARTYARA mennek,\n"
        "nem az uzenetbe. Maradjon a kerdes vagy a dontes, amit tole varsz.\n\n"
        "Ha a hosszusag INDOKOLT (o kert reszletes anyagot, vagy egy listat tetelesen kell\n"
        "atadni), jelezd explicit szandekkal, MIELOTT ujra probalkozol:\n"
        f"  python3 {os.path.relpath(os.path.abspath(__file__))} --override \"<rovid indoklas>\" {chat_id}\n"
        "Ez 90 masodpercig ervenyes es egyszer hasznalhato.\n"
    )
    sys.exit(2)


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--override":
        if len(sys.argv) != 4:
            print(__doc__)
            return 2
        write_override(sys.argv[2], sys.argv[3])
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if "telegram" in tool.lower() and tool.lower().endswith("__reply"):
        hossz_kapu(tool_input)
    return 0


if __name__ == "__main__":
    sys.exit(main())
