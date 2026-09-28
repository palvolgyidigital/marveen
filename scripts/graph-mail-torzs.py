#!/usr/bin/env python3
"""Read the FULL body of ONE message from a mailbox, by id.

Why this exists: `scripts/graph-mail.ts` has no `read` verb (verbs: verify | list |
headers | send). `list` returns only `bodyPreview` (~255 chars), and the inbox-watcher
skill forbids printing that preview, because it belongs to messages that may be out of
scope. So the only sanctioned way to read ONE message in scope is a targeted Graph call
that selects the body of that id and nothing else.

`$select` IS the protection: what is not selected cannot be printed by accident.

Usage:
  python3 scripts/graph-mail-torzs.py <creds-file> <message-id>
  python3 scripts/graph-mail-torzs.py <creds-file> <message-id> --leiratkozas

With --leiratkozas it also reports whether the body carries unsubscribe intent, which is
the one case the marketing-inbox-figyelo task is allowed to read a reply body for
(Marci's scope extension, 2026-09-28).

Measured 2026-09-28: this replaced a `body_run.ts` sample that the skill said was "left in
the scratchpad". Session scratchpads do not survive, so that pointer could never work for
a later round. Operational recipes belong in scripts/, not in a temp directory.
"""
import json
import re
import sys
import urllib.parse
import urllib.request

KULCSOK = ["leiratkozás", "leiratkozas", "leiratkozom", "leiratkoznék",
           "ne küldjetek", "ne kuldjetek", "ne küldjenek"]


def token(creds: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": creds["CLIENT_ID"], "client_secret": creds["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{creds['TENANT_ID']}/oauth2/v2.0/token"
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data)))["access_token"]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    creds = {}
    for line in open(sys.argv[1]):
        if "=" in line:
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    mid = sys.argv[2]
    url = (f"https://graph.microsoft.com/v1.0/users/{creds['MAILBOX']}/messages/"
           f"{urllib.parse.quote(mid, safe='')}"
           "?$select=subject,receivedDateTime,body")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token(creds)})
    m = json.load(urllib.request.urlopen(req))

    # A HTML-torzsbol a tageket ki kell szedni, kulonben olvashatatlan.
    torzs = re.sub(r"<[^>]+>", " ", m["body"]["content"])
    torzs = re.sub(r"\s+", " ", torzs).strip()

    print("TARGY:", m["subject"])
    print("ERKEZETT:", m["receivedDateTime"])
    print("TORZS:", torzs)
    if "--leiratkozas" in sys.argv:
        tal = [k for k in KULCSOK if k in torzs.lower()]
        print("LEIRATKOZASI SZANDEK:", "IGEN" if tal else "NEM", tal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
