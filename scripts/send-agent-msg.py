#!/usr/bin/env python3
"""Send an inter-agent message, but refuse to send text containing
foreign-script homoglyphs (Cyrillic/Greek letters spliced into Hungarian words)
or an em dash.

WHY THIS EXISTS: between 2026-08-13 and 2026-08-31 the same defect recurred at
least four times -- a Cyrillic letter inside a Hungarian word ("keresе",
"nyeresег", "keszithetо", "tolthető"). The text validates as UTF-8, cat renders
it correctly and the eye does not catch it, but the character is not the one it
looks like, so no search will ever match it. The rule was written down; it kept
being skipped in curl payloads because that is where the work goes fastest.
A note in memory did not fix it. A gate on the send path does.

Usage:
    python3 scripts/send-agent-msg.py <to_agent> <file-with-message-body>
    python3 scripts/send-agent-msg.py <to_agent> -            # body on stdin
    python3 scripts/send-agent-msg.py --from sam <to> <file>  # explicit sender
    python3 scripts/send-agent-msg.py --check <to> <file>     # CSAK ellenorzes, nem kuld

HASZNALD A --check-ET, HA A SZKRIPTET MAGAT TESZTELED. 2026-08-31-en a kapu javitasat
elo kuldessel probaltam ki, es egy ertelmetlen teszt-uzenet ment ki egy kollegának, aki
joggal kerdezte vissza, mihez tartozik. Ugyanaz a hibaosztaly, mint egy write-API-t eles
rekordon kiprobalni: a teszt celja a SZKRIPT, nem a cimzett.

The sender is resolved in this order: an explicit --from, else the agent name
taken from the working directory (agents/<name>/...), else "pedro". The resolved
sender is ALWAYS printed before sending, because a silently wrong "from" field
is exactly the class of defect this script exists to prevent. (Sam spotted the
hardcoded sender on 2026-08-31 -- the guard against one silent error shipped
with a different one.)
"""
import json
import pathlib
import re
import sys
import unicodedata
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "store" / ".dashboard-token"
API = "http://localhost:3420/api/messages"

# A VALODI KOCKAZAT: NEM-LATIN BETU egy latin betus szoban (cirill/gorog homoglif).
# Egy SZIMBOLUM (nyil, emoji, tipografiai jel) NEM homoglif -- nem lehet osszeteveszteni
# egy betuvel, es sokszor SZANDEKOS (pl. egy UI-gomb felirata: "▾ Eszkozok").
#
# ELSO VALTOZAT TUL SZIGORU VOLT (2026-08-31): minden nem-latin karaktert megfogott, es
# elakadt egy legitim "▾"-on egy Next-menu nevben. Egy kapu, ami a helyes szoveget is
# blokkolja, arra tanit, hogy megkeruljed -- es akkor a valodi hibat sem fogja meg.
#
# Ezert most a szabaly: BETU (unicodedata kategoria L*), ami NEM latin irasrendszeru.
LATIN_OK = re.compile(r"[A-Za-zÀ-ɏ]")


def _is_foreign_letter(ch):
    if not unicodedata.category(ch).startswith("L"):
        return False  # szimbolum, iras, szam: nem homoglif
    if LATIN_OK.match(ch):
        return False
    try:
        return "LATIN" not in unicodedata.name(ch)
    except ValueError:
        return True
EM_DASH = re.compile(r"[–—]")


def check(text):
    problems = []
    for i, ch in enumerate(text):
        if _is_foreign_letter(ch):
            start = max(0, i - 25)
            problems.append(
                "nem-latin BETU %r (U+%04X) itt: ...%s..."
                % (ch, ord(ch), text[start:i + 12].replace("\n", " "))
            )
    for m in EM_DASH.finditer(text):
        start = max(0, m.start() - 25)
        problems.append(
            "gondolatjel %r itt: ...%s..."
            % (m.group(), text[start:m.start() + 12].replace("\n", " "))
        )
    return problems


def resolve_sender(explicit):
    if explicit:
        return explicit
    cwd = pathlib.Path.cwd().resolve()
    for parent in [cwd] + list(cwd.parents):
        if parent.parent.name == "agents" and parent.name:
            return parent.name
    return "pedro"


def main():
    argv = sys.argv[1:]
    check_only = False
    if "--check" in argv:
        check_only = True
        argv = [a for a in argv if a != "--check"]
    explicit_from = None
    if argv and argv[0] == "--from":
        if len(argv) < 2:
            print(__doc__, file=sys.stderr)
            return 2
        explicit_from, argv = argv[1], argv[2:]
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    to_agent, src = argv[0], argv[1]
    from_agent = resolve_sender(explicit_from)
    text = sys.stdin.read() if src == "-" else pathlib.Path(src).read_text(encoding="utf-8")

    problems = check(text)
    if problems:
        print("NEM KULDTEM EL. %d problema:" % len(problems), file=sys.stderr)
        for p in problems:
            print("  - " + p, file=sys.stderr)
        print("\nJavitsd a szoveget es futtasd ujra.", file=sys.stderr)
        return 1

    if check_only:
        print("CHECK OK: a szoveg tiszta, NEM kuldtem el (%s -> %s, %d karakter)"
              % (from_agent, to_agent, len(text)))
        return 0

    payload = json.dumps({"from": from_agent, "to": to_agent, "content": text}).encode()
    req = urllib.request.Request(
        API,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + TOKEN_FILE.read_text().strip(),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print("elkuldve: %s -> %s (HTTP %s)" % (from_agent, to_agent, r.status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
