#!/usr/bin/env python3
"""UserPromptSubmit hook: recognise and neutralise a re-delivered inter-agent
message before the agent acts on it a second time (ea2eb050, 2026-08-26).

Why this exists: the sub-agent tmux-inject delivery path cannot always prove a
message actually reached the target pane (a pane already busy with an
unrelated turn looks identical to one that just started processing OUR
message). The sender-side fix (confirmsDeliveryDespitePriorBusy in
pane-state.ts) closes most of that gap by checking the pane -- including
scrollback -- for positive proof before trusting an ambiguous verdict. This
hook is the independent, mechanical backstop for the residual case: if the
sender ever DOES resend a message that had, in fact, already landed, the
receiving agent must not act on it twice.

Every wrapped inter-agent message already carries its own database row id in
the injected text (wrapAgentMessageForDelivery, agent-message-wrap.ts) as
"msg_id:<N>". This hook extracts that id, and durably records -- per agent,
never per session, so it survives a restart -- whether THIS agent has already
seen it. A first sighting is silent (no behaviour change). A repeat sighting
injects a clear, mechanical stand-down instruction, so the agent does not
depend on noticing the duplication itself.

Never blocks the prompt (always exit 0): a duplicate is turned into a no-op
instruction, not a hard failure, and any internal error here must not silence
delivery of a message that might be genuinely new.
"""
import sys
import os
import re
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ledger_lib  # noqa: E402

# Matches the exact suffix wrapAgentMessageForDelivery appends: ", msg_id:123".
# Word-boundaried on both sides so it never matches inside an unrelated token.
MSG_ID_RX = re.compile(r"\bmsg_id:(\d+)\b")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_delivery_ids (
  agent_id TEXT NOT NULL,
  msg_id INTEGER NOT NULL,
  seen_at INTEGER NOT NULL,
  PRIMARY KEY (agent_id, msg_id)
)
"""

# Chronic-growth cap, same shape as the channels-respawn.log trim (SOAKRESPAWN819):
# once an agent's seen-set passes this many rows, trim to the newest half. A
# duplicate delivery this far removed from the original would already be a
# separate incident worth its own investigation, not silent dedup.
PRUNE_ABOVE = 2000
PRUNE_KEEP = 1000


def connect():
    con = sqlite3.connect(ledger_lib.db_path(), timeout=10)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute(SCHEMA)
    return con


def record_and_check_seen(con, agent_id, msg_id, now):
    """Returns True if this (agent_id, msg_id) was ALREADY recorded (a
    duplicate delivery); False if this is the first sighting (now recorded)."""
    cur = con.execute(
        "INSERT OR IGNORE INTO seen_delivery_ids (agent_id, msg_id, seen_at) VALUES (?, ?, ?)",
        (agent_id, msg_id, now),
    )
    return cur.rowcount == 0


def prune_if_needed(con, agent_id):
    (count,) = con.execute(
        "SELECT COUNT(*) FROM seen_delivery_ids WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if count <= PRUNE_ABOVE:
        return
    con.execute(
        """DELETE FROM seen_delivery_ids WHERE agent_id = ? AND msg_id NOT IN (
             SELECT msg_id FROM seen_delivery_ids WHERE agent_id = ?
             ORDER BY seen_at DESC LIMIT ?
           )""",
        (agent_id, agent_id, PRUNE_KEEP),
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    prompt = payload.get("prompt") or ""
    ids = [int(m.group(1)) for m in MSG_ID_RX.finditer(prompt)]
    if not ids:
        sys.exit(0)  # nothing to dedup, most turns (no inter-agent delivery)

    try:
        agent_id = ledger_lib.agent_id_from_cwd(payload.get("cwd") or "")
        con = connect()
        try:
            now = int(__import__("time").time())
            duplicates = []
            for msg_id in ids:
                if record_and_check_seen(con, agent_id, msg_id, now):
                    duplicates.append(msg_id)
            if duplicates:
                prune_if_needed(con, agent_id)
            con.commit()
        finally:
            con.close()
    except Exception:
        # Fail-open: never let a dedup-tracking error block or silence a
        # message that might be genuinely new.
        sys.exit(0)

    if not duplicates:
        sys.exit(0)  # first sighting(s): silent, no behaviour change

    ids_txt = ", ".join(f"msg_id:{i}" for i in duplicates)
    # UserPromptSubmit stdout (exit 0) is injected into the model context.
    print(
        f"MEGISMETLODOTT KEZBESITES ESZLELVE ({ids_txt}): ezt/ezeket az uzenetet "
        "mar korabban megkaptad es feldolgoztad -- a rendszer ovatossagbol "
        "ujrakuldte, mert nem tudta megerositeni az elso kezbesitest. NE "
        "dolgozd fel ujra, NE valaszolj ra ujra, NE vegezz vele ujra munkat. "
        "Ha a jelenlegi promptban KIZAROLAG ez az ismetlodo uzenet szerepel, "
        "fejezd be a kort valasz/muvelet nelkul."
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
