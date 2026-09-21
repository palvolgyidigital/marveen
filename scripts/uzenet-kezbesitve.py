#!/usr/bin/env python3
"""Did that message actually REACH the agent? One call, before you claim you told them.

WHY THIS EXISTS. Twice on 2026-09-18 I stated that a colleague had been told something, when the
message was only QUEUED. The first time I wrote to the owner that I had stopped Max before he
wasted an hour -- eight messages were sitting pending at the time, and he was doing exactly the
work I meant to stop. The second time, two hours later, I told David that Max was writing the
PPWR column "right now": the instruction was pending, and he had not started.

The POST returning 200 with an id proves the row entered the queue. It does NOT prove delivery.
A busy agent's session cannot take an injection, so the gap is minutes for an idle agent and
HOURS for a working one -- exactly when you most want to reach them.

A rule was not enough; two entries in memory did not stop the third occurrence. This is the
mechanism: one call, and the answer is in the output.

WHOSE messages? Max reported on 2026-09-18 (msg 4918) that from_agent was hardcoded to
'pedro' on two lines, so the tool only ever answered for me. The tempting fix -- default to
'pedro' and add a flag -- would have been WORSE than the bug it replaced: Max running it plain
would get "no messages sent today", a clean, confident, reassuring FALSE NEGATIVE about someone
else's outbox. That is the exact failure this tool exists to prevent, reintroduced one level up.

So there is no silent default. The sender is resolved in this order, and the resolved name is
PRINTED in every output, so an answer can never be about someone you did not mean:
  1. --from NAME
  2. $PDB_AGENT
  3. the tmux session name (agent-max -> max, pedro-worker -> pedro), validated against the
     senders that actually exist in agent_messages
  4. no guess: exit 2 with the reason

Usage:
  python3 scripts/uzenet-kezbesitve.py max            # today's messages to max
  python3 scripts/uzenet-kezbesitve.py max 4908       # one specific message
  python3 scripts/uzenet-kezbesitve.py --mind         # every agent, pending only
  python3 scripts/uzenet-kezbesitve.py --from sam max # sam's messages to max
"""
import os
import re
import sqlite3
import subprocess
import sys
import datetime as dt

DB = "/home/pdb/marveen/store/claudeclaw.db"


def _tmux_agens(c):
    """Derive the agent from the tmux session name, but only accept it if that name is a sender
    that EXISTS in agent_messages. An unvalidated guess here would put a plausible wrong name in
    the header, which is worse than no answer.

    THE $TMUX GUARD IS NOT COSMETIC, it was measured on 2026-09-18. Outside any session,
    `tmux display-message -p '#S'` does NOT fail and does NOT return empty: it answers with the
    most recently used session on the server. Running this from a plain shell reported KULDO: sam
    with full confidence, for a caller who was not sam at all. The existence check passed, because
    sam IS a real sender. So the validation caught nothing -- only $TMUX distinguishes "I am in
    this session" from "some session exists somewhere"."""
    if not os.environ.get("TMUX"):
        return None
    try:
        s = subprocess.run(["tmux", "display-message", "-p", "#S"],
                           capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None
    if not s:
        return None
    n = re.sub(r"^agent-", "", s)
    n = re.sub(r"-(channels|worker|worker-fast)$", "", n)
    ismert = {r[0] for r in c.execute("SELECT DISTINCT from_agent FROM agent_messages")}
    return n if n in ismert else None


def kuldo(argv, c):
    """(nev, honnan). Nincs nema default -- l. a modul dokumentacioját."""
    if "--from" in argv:
        i = argv.index("--from")
        if i + 1 >= len(argv):
            print("a --from utan kell egy agensnev", file=sys.stderr)
            sys.exit(2)
        n = argv[i + 1]
        del argv[i:i + 2]
        return n, "--from"
    if os.environ.get("PDB_AGENT"):
        return os.environ["PDB_AGENT"], "$PDB_AGENT"
    n = _tmux_agens(c)
    if n:
        return n, "tmux session"
    print("NEM TUDOM, KI A KULDO, es nem tippelek: egy rossz nevvel a valasz valaki MAS\n"
          "postafiokjarol szolna, ugy, hogy a kimenet megnyugtatonak latszik.\n"
          "Add meg: --from NEV, vagy allitsd a PDB_AGENT kornyezeti valtozot.", file=sys.stderr)
    sys.exit(2)


def main():
    a = [x for x in sys.argv[1:]]
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    en, honnan = kuldo(a, c)
    # A nap kezdete HELYI idoben: a zaro 'utc' KELL, kulonben ket orat veszit. L. sqlite-ido-csapdak.
    nap = "strftime('%s','now','localtime','start of day','utc')"

    if a and a[0] == "--mind":
        q = c.execute(f"SELECT to_agent, status, COUNT(*) n, MIN(created_at) elso "
                      f"FROM agent_messages WHERE from_agent=? AND created_at >= {nap} "
                      f"GROUP BY to_agent, status ORDER BY to_agent", (en,))
        print(f"KULDO: {en}  ({honnan})")
        print(f"{'cimzett':10s} {'statusz':12s} {'db':>4s}  legregebbi")
        for r in q:
            kor = (dt.datetime.now() - dt.datetime.fromtimestamp(r["elso"]))
            jel = "  <-- VAR" if r["status"] != "delivered" else ""
            print(f'{r["to_agent"]:10s} {r["status"]:12s} {r["n"]:4d}  '
                  f'{int(kor.total_seconds()//60)} perce{jel}')
        return 0

    if not a:
        print(__doc__)
        return 2
    cel = a[0]
    if len(a) > 1:
        r = c.execute("SELECT id,from_agent,to_agent,status,created_at,substr(content,1,70) t "
                      "FROM agent_messages WHERE id=?", (a[1],)).fetchone()
        if not r:
            print(f"NINCS ilyen sor: {a[1]}")
            return 1
        if r["from_agent"] != en:
            print(f'FIGYELEM: ez a sor {r["from_agent"]} uzenete, nem {en}-e.')
        kor = int((dt.datetime.now() - dt.datetime.fromtimestamp(r["created_at"])).total_seconds() // 60)
        print(f'{r["id"]} -> {r["to_agent"]}  {r["status"]}  ({kor} perce)')
        print(f'   {r["t"]}')
        print()
        print("KEZBESITVE" if r["status"] == "delivered" else
              "MEG NEM ERKEZETT MEG. NE allitsd, hogy szoltal neki.")
        return 0

    q = c.execute(f"SELECT id,status,created_at,substr(content,1,58) t FROM agent_messages "
                  f"WHERE from_agent=? AND to_agent=? AND created_at >= {nap} "
                  f"ORDER BY id", (en, cel))
    sorok = q.fetchall()
    print(f"KULDO: {en}  ({honnan})  ->  {cel}")
    if not sorok:
        print(f"{en} ma nem kuldott uzenetet neki: {cel}")
        return 0
    var = 0
    for r in sorok:
        kor = int((dt.datetime.now() - dt.datetime.fromtimestamp(r["created_at"])).total_seconds() // 60)
        jel = "" if r["status"] == "delivered" else "  <-- VAR"
        var += r["status"] != "delivered"
        print(f'  {r["id"]} {dt.datetime.fromtimestamp(r["created_at"]).strftime("%H:%M")} '
              f'{r["status"]:10s} {kor:4d}p  {r["t"]}{jel}')
    print()
    print(f"{len(sorok)} uzenet, ebbol {var} MEG NEM ERKEZETT MEG."
          if var else f"mind a {len(sorok)} kezbesitve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
