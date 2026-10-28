#!/usr/bin/env python3
"""List message IDs + subjects of a mailbox folder, WITHOUT fetching any body.

Why this exists: `scripts/graph-mail.ts list` prints date, sender and subject but NOT the
message id, while `headers --id` and `graph-mail-torzs.py <creds> <id>` both need one. The
inbox-watcher skill's documented workaround was a `head` on the raw list output, and that
printed the `bodyPreview` of messages that may be out of scope (measured 2026-09-25).

`$select` IS the protection: body is not selected, so it cannot be printed by accident.

Usage:
  python3 scripts/graph-mail-idk.py <creds-file> [--top N] [--folder inbox|sentitems]
"""
import json
import sys
import urllib.parse
import urllib.request


def creds_betolt(utvonal: str) -> dict:
    d = {}
    with open(utvonal, encoding="utf-8") as f:
        for sor in f:
            sor = sor.strip()
            if not sor or sor.startswith("#") or "=" not in sor:
                continue
            k, v = sor.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def token(c: dict) -> str:
    adat = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=adat)) as r:
        return json.load(r)["access_token"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    c = creds_betolt(sys.argv[1])
    top, folder = 10, "inbox"
    arg = sys.argv[2:]
    for i, a in enumerate(arg):
        if a == "--top" and i + 1 < len(arg):
            top = int(arg[i + 1])
        if a == "--folder" and i + 1 < len(arg):
            folder = arg[i + 1]
    q = urllib.parse.urlencode({
        "$select": "id,subject,receivedDateTime,isRead",
        "$top": str(top),
        "$orderby": "receivedDateTime desc",
    })
    url = (f"https://graph.microsoft.com/v1.0/users/{c['MAILBOX']}"
           f"/mailFolders/{folder}/messages?{q}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token(c)}"})
    with urllib.request.urlopen(req) as r:
        adat = json.load(r)
    for m in adat.get("value", []):
        jel = " " if m.get("isRead") else "*"
        print(f"{jel} {m['receivedDateTime']}  {m.get('subject') or '(nincs targy)'}")
        print(f"    id={m['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
