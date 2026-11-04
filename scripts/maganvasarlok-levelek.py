#!/usr/bin/env python3
"""Personal (cross-sell) letters we SENT to the private customers on the dashboard's
Maganvasarlok tab. Marci's request, 2026-11-03 (Telegram 11621, 11624): show whether a
customer got a personalised email from us, when, and whether they ordered after it
("hogy mikor rendelte meg a level utan, tok mindegy").

READS ONLY OUR OWN SENT ITEMS, and only three fields of them: recipients, subject and
send time. `$select` is the protection: the body of a letter is never requested, so it
cannot leak into a log or the dashboard. The marketing@ mailbox is Marci's personal one;
this script looks at nothing in it except what we ourselves sent.

Output: store/maganvasarlok/levelek.json, keyed by lower-case recipient address, with the
letters sorted newest first. The dashboard merges it at read time.

Usage: python3 scripts/maganvasarlok-levelek.py [--days 400]
Exit 2 if any mailbox query fails: a failed query is NOT "no letters", and in that case
the previous output file is left untouched.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = "/home/pdb/marveen"
MAILBOXES = {
    "marketing": f"{ROOT}/store/.m365-marketing-credentials",
    "innova": f"{ROOT}/store/.m365-innova-credentials",
}
SRC = f"{ROOT}/store/maganvasarlok/feliratkozok.json"
OUT = f"{ROOT}/store/maganvasarlok/levelek.json"


def creds(path):
    c = {}
    for line in open(path):
        if "=" in line:
            k, v = line.split("=", 1)
            c[k.strip()] = v.strip()
    return c


def token(c):
    data = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "grant_type": "client_credentials", "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token"
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=60))["access_token"]


def sent_items(c, since_iso):
    tok = token(c)
    q = urllib.parse.urlencode({
        "$select": "subject,sentDateTime,toRecipients,ccRecipients",
        "$filter": f"sentDateTime ge {since_iso}",
        "$orderby": "sentDateTime desc",
        "$top": "200",
    })
    url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(c['MAILBOX'])}/mailFolders/sentitems/messages?{q}"
    while url:
        r = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}), timeout=120))
        yield from r.get("value", [])
        url = r.get("@odata.nextLink")


# Only our cross-sell letters are kept. Measured 2026-11-03 on 679 sent items: the
# cross-sell subjects all carry "... melle ajanljuk" or "... kedvezmeny ..."; the rest
# of the matches were Marci's own private sends (empty subjects, photo transfers) and
# "[MINTA ...]" samples that went to a colleague, not to the customer. Anything not
# matching is DROPPED here, so a private subject never reaches the dashboard file.
import re
# 2026-11-03: Marci shortened the subject form to "Ajanljuk az ... melle" (Telegram 11687),
# so both word orders must match, or the next letter would silently drop off the tab.
CROSS_SELL = re.compile(r"mell[eé] aj[aá]nljuk|aj[aá]nljuk .{0,60}mell[eé]|kedvezm[eé]ny", re.I)
NOT_TO_CUSTOMER = re.compile(r"^\s*\[MINTA", re.I)


def main():
    days = 400
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw = json.load(open(SRC, encoding="utf-8"))
    lista = raw if isinstance(raw, list) else raw.get("vasarlok", [])
    wanted = {str(v.get("email") or "").strip().lower() for v in lista} - {""}

    out = {}
    counts = {}
    for name, path in MAILBOXES.items():
        n = 0
        try:
            for m in sent_items(creds(path), since):
                n += 1
                subj = m.get("subject") or ""
                if not CROSS_SELL.search(subj) or NOT_TO_CUSTOMER.search(subj):
                    continue
                rcpt =[x["emailAddress"]["address"].strip().lower()
                        for x in (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])]
                for a in rcpt:
                    if a in wanted:
                        out.setdefault(a, []).append({
                            "datum": m.get("sentDateTime"), "targy": m.get("subject") or "",
                            "postafiok": name,
                        })
        except Exception as e:  # noqa: BLE001 -- any failure is the third state
            print(f"HIBA ({name}): {type(e).__name__}: {e}", file=sys.stderr)
            return 2
        counts[name] = n
    for a in out:
        out[a].sort(key=lambda x: x["datum"] or "", reverse=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"keszult": datetime.now(timezone.utc).isoformat(), "ablak_nap": days,
                   "levelek": out}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)
    print(f"atnezett elkuldott levelek: {counts} | vasarlo levellel: {len(out)} / {len(wanted)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
