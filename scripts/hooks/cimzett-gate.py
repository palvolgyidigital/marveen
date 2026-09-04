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
_UTOLSO_PATH = os.path.join(_STORE_DIR, ".cimzett-gate-utolso.json")
_OVERRIDE_TTL = 90  # masodperc
_UTOLSO_TTL = 24 * 3600  # a session -> utolso cimzett bejegyzes elettartama


def _load_ellenoriz():
    spec = importlib.util.spec_from_file_location("megszolitas_cimzett_ellenor", _ELLENOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.ellenoriz


def _load_cimzett_neve():
    spec = importlib.util.spec_from_file_location("megszolitas_cimzett_ellenor", _ELLENOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.cimzett_neve


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


# --- masodik szint: cimzett-valtaskor egyszer megallunk ----------------------
# Az elso szint ellentmondast keres (megszolitas kontra chat_id). Ha a szoveg
# senkit nem szolit meg, ellentmondas SINCS -- ezert engedte at helyesen a kaput
# a 2026-09-04-i teves cimzes. Itt nem okosabb szovegelemzes a valasz, hanem a
# hianyzo jel potlasa: cimzett-VALTASKOR, hosszu szovegnel, ha mas kollega neve
# szerepel benne, egyszer megallunk es kiirjuk, KINEK a csatornaja ez.
# A valtozatlan ujrakuldes atmegy: ez lassito, nem tiltas.

def _utolso_olvas_es_ir(kulcs: str, chat_id: str):
    """Visszaadja, mi volt ennek a sessionnek az ELOZO cimzettje, es bejegyzi az
    ujat. Barmilyen hibanal None (fail-open: nincs lassitas)."""
    now = time.time()
    data = {}
    try:
        with open(_UTOLSO_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    elozo = None
    reg = data.get(kulcs)
    if isinstance(reg, dict) and (now - float(reg.get("ts", 0))) <= _UTOLSO_TTL:
        elozo = reg.get("chat_id")
    data[kulcs] = {"chat_id": str(chat_id), "ts": now}
    # takaritas, hogy a fajl ne nojon vegtelenul
    for k in [k for k, v in data.items()
              if not isinstance(v, dict) or (now - float(v.get("ts", 0))) > _UTOLSO_TTL]:
        data.pop(k, None)
    try:
        os.makedirs(_STORE_DIR, exist_ok=True)
        tmp = _UTOLSO_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, _UTOLSO_PATH)
    except OSError:
        pass
    return elozo


def lassito_kapu(payload: dict, chat_id, text: str) -> None:
    """Exit-el (2) ha lassitani kell, kulonben visszater. Fail-open mindenre."""
    try:
        spec = importlib.util.spec_from_file_location("megszolitas_cimzett_ellenor", _ELLENOR_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        r = mod.lassito(chat_id, text)
        kulcs = str(payload.get("session_id") or payload.get("cwd") or "?")
        elozo = _utolso_olvas_es_ir(kulcs, chat_id)
        if not r:
            return
        if elozo is None or str(elozo) == str(chat_id):
            return  # nincs cimzett-valtas: ez a szal mar fut, nem itt szokott elromlani
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 -- deliberate: fail-open path
        _log(f"cimzett-gate/lassito: BELSO HIBA, FAIL-OPEN atengedes: {exc!r}")
        return

    cim, emlitett = r
    nevek = ", ".join(n for _, n in emlitett)
    _log(
        f"cimzett-gate: LASSITO -- chat_id={chat_id} ({cim}), elozo cimzett={elozo}, "
        f"emlitett nevek: {nevek}"
    )
    sys.stderr.write(
        "CIMZETT-KAPU (lassito, NEM tiltas): ez a(z) " + str(chat_id) + " chat_id, "
        "vagyis " + cim + " csatornaja.\n"
        "A szoveg nem szolit meg senkit, tehat nincs mibol ellenorizni a cimzettet, "
        "viszont " + nevek + " neve szerepel benne, es az elozo uzeneted MAS "
        "csatornara ment (" + str(elozo) + ").\n\n"
        "Egy kerdes, aztan mehet: tenyleg " + cim + "-nak/nek szol ez a szoveg?\n"
        "Ha IGEN: kuldd el ujra valtozatlanul, at fog menni.\n"
        "Ha NEM: javitsd a chat_id-t.\n"
    )
    sys.exit(2)


# --- a tenyleges ellenorzes ---------------------------------------------------

def telegram_gate(tool_input: dict, payload: dict) -> None:
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
        lassito_kapu(payload, chat_id, text)  # exit-elhet
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
    try:
        cimzett_nev = _load_cimzett_neve()(chat_id)
    except Exception:  # noqa: BLE001 -- a nev csak kenyelmi adat, nem allithatja meg a kaput
        cimzett_nev = None
    cimzett_leiras = (str(chat_id) + " = " + cimzett_nev) if cimzett_nev else str(chat_id)
    sys.stderr.write(
        "CIMZETT-KAPU: TILTVA. A szoveg '" + nev + "'-t szolitja meg, de ez az uzenet a "
        + cimzett_leiras + " chat_id-re menne, ami NEM az o csatornaja "
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
        telegram_gate(tool_input, payload)  # exit-elhet, nem ter vissza
    return 0


if __name__ == "__main__":
    sys.exit(main())
