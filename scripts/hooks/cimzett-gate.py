#!/usr/bin/env python3
"""PreToolUse gate: a kimeno Telegram valasz CIMZETTJE (chat_id) es a szoveg
MEGSZOLITASA (a szoveg elejen alló nev) ne mondjon ellent egymasnak.

MIERT LETEZIK ES MIT FED LE: lasd scripts/megszolitas-cimzett-ellenor.py
docstringjet -- ez a hook csak a beeplesztes, a detekcios logika ott el,
innen importaljuk (`ellenoriz(chat_id, szoveg)`). EZ A GATE FLEET-WIDE:
minden agentre vonatkozik (fo-agens ES minden sub-agens), mert a hibaosztaly
(rossz csatornara kuldott, mas nevet szolito szoveg) barmelyik agens sajat
Telegram-csatornajan elofordulhat, nem csak a fo-agensen.

MUKODESI MODOK:
  1. Hook (PreToolUse, JSON a stdin-en): a
     mcp__plugin_telegram_telegram__reply hivast vizsgalja, chat_id + text
     mezok alapjan. exit 0 = mehet, exit 2 = blokkolva (stderr -> a modell
     latja, es javithat vagy override-olhat).
  2. `--override "<indoklas>" <chat_id>` CLI: explicit szandek-jelzes egy
     legitim eset elott (pl. tovabbitas: sajat szavaiddal mas nevet
     szolitod meg, mint akinek kuldod). 90 masodpercig ervenyes, EGYSZER
     hasznalhato, és a hasznalata naplozva van -- lasd lent "AZ OVERRIDE".

FAIL-OPEN minden BELSO hibara (hianyzo/serult import, varatlan kivetel):
ez a Telegram-ag az EGYETLEN felugyeleti csatorna, egy hook-hiba miatti
nemitas rosszabb, mint egy el nem kapott rossz-cimzes. Egy TALALT problema
viszont blokkol -- az a kapu ertelme.
"""
import importlib.util
import json
import os
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ELLENOR_PATH = os.path.join(_SCRIPTS_DIR, "megszolitas-cimzett-ellenor.py")
_STORE_DIR = os.path.join(os.path.dirname(_SCRIPTS_DIR), "store")
_OVERRIDE_PATH = os.path.join(_STORE_DIR, ".cimzett-gate-override.json")
_LOG_PATH = os.path.join(_STORE_DIR, "outgoing-copy-gate.log")
_OVERRIDE_TTL = 90  # masodperc


def _load_ellenoriz():
    spec = importlib.util.spec_from_file_location("megszolitas_cimzett_ellenor", _ELLENOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.ellenoriz


def _log(sor: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(sor.rstrip("\n") + "\n")
    except OSError:
        pass


# --- override: explicit szandek-jelzes, egyszer hasznalhato, idokorlatos ----

def write_override(reason: str, chat_id: str) -> None:
    os.makedirs(_STORE_DIR, exist_ok=True)
    data = {"reason": reason, "chat_id": str(chat_id), "written_at": time.time()}
    tmp = _OVERRIDE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _OVERRIDE_PATH)
    print(
        f"OVERRIDE feljegyezve chat_id={chat_id}-hez, {_OVERRIDE_TTL} masodpercig "
        "ervenyes, egyszer hasznalhato. Kuldd el most a valaszt."
    )


def consume_override(chat_id: str):
    """Ha van FRISS, ERRE a chat_id-re szolo override, fogyaszd el (torold) es
    add vissza az indoklast. Kulonben None -- es a fajlt EROSEN torold, ha
    lejart, hogy ne maradjon ott hamis biztonsagot adva."""
    if not os.path.exists(_OVERRIDE_PATH):
        return None
    try:
        with open(_OVERRIDE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    fresh = (time.time() - float(data.get("written_at", 0))) <= _OVERRIDE_TTL
    matches = str(data.get("chat_id")) == str(chat_id)
    try:
        os.remove(_OVERRIDE_PATH)
    except OSError:
        pass
    if fresh and matches:
        return data.get("reason") or "(indoklas nelkul)"
    return None


# --- a tenyleges ellenorzes ---------------------------------------------------

def telegram_gate(tool_input: dict) -> None:
    try:
        ellenoriz = _load_ellenoriz()
        chat_id = tool_input.get("chat_id")
        text = str(tool_input.get("text") or tool_input.get("caption") or "")
        if chat_id is None or not text.strip():
            sys.exit(0)  # nincs cimzett vagy nincs szoveg: nincs mit ellenorizni
        r = ellenoriz(chat_id, text)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate: fail-open path
        _log(f"cimzett-gate: BELSO HIBA, FAIL-OPEN atengedes: {exc!r}")
        sys.exit(0)

    if not r:
        sys.exit(0)

    nev, helyes_chat = r
    override_ok = consume_override(chat_id)
    if override_ok:
        _log(
            f"cimzett-gate: OVERRIDE hasznalva -- chat_id={chat_id}, "
            f"megszolitva='{nev}' (sajat csatornaja: {helyes_chat}), indoklas: {override_ok}"
        )
        sys.exit(0)

    _log(f"cimzett-gate: BLOKKOLVA -- chat_id={chat_id}, megszolitva='{nev}' (sajat csatornaja: {helyes_chat})")
    sys.stderr.write(
        "CIMZETT-KAPU: TILTVA. A szoveg '" + nev + "'-t szolitja meg, de ez az uzenet a "
        + str(chat_id) + " chat_id-re menne, ami NEM az o csatornaja "
        "(az o csatornaja: " + str(helyes_chat) + ").\n\n"
        "Ha ez hiba: javitsd a cimzettet vagy a megszolitast, es kuldd ujra.\n"
        "Ha SZANDEKOS (pl. tovabbitod/idezed mas valakinek szolo szoveget): jelezd "
        "explicit szandekkal, MIELOTT ujra probalkozol:\n"
        f"  python3 {os.path.relpath(os.path.abspath(__file__))} --override \"<rovid indoklas>\" {chat_id}\n"
        "Ez 90 masodpercig ervenyes es egyszer hasznalhato -- utana a kapu ujra ellenoriz.\n"
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
    except Exception:
        return 0  # ertelmezhetetlen payload nem akaszthatja meg a sessiont

    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if "telegram" in tool.lower() and tool.lower().endswith("__reply"):
        telegram_gate(tool_input)  # exit-el, nem ter vissza
    return 0


if __name__ == "__main__":
    sys.exit(main())
