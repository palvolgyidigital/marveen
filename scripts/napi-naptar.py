#!/usr/bin/env python3
"""Print one day's events from a mailbox calendar, for the morning briefing.

WHY THIS EXISTS (Marci, 2026-09-29 08:18, msg 7692): the briefing's calendar
section is built from ABEL's calendar only -- "Altalaban Abelnel minden ott van,
eleg csak az ovet nezni". That is the owner's decision, so the default mailbox
here is Abel's and a later round must not widen it on its own.

WHY A TRACKED SCRIPT AND NOT A SCRATCHPAD SNIPPET: the briefing runs every
morning, so the recipe has to survive the session. A scratchpad file does not
(measured 2026-09-28: a `body_run.ts` pointer in a skill had been dead from the
day it was written, because the session scratchpad is gone by the next round).

TWO TRAPS THIS SCRIPT REMOVES:

1. `Prefer: outlook.timezone` is what makes Graph return local wall-clock time.
   Without it the times come back UTC and a 09:00 meeting reads as 07:00.
2. An all-day event's `end` is EXCLUSIVE in Graph. A single all-day event today
   comes back as today -> tomorrow. This script marks all-day events instead of
   printing a misleading end time.

It only READS. There is no write path here by design.

Usage:
  python3 scripts/napi-naptar.py                 # today, Abel's mailbox, every calendar
  python3 scripts/napi-naptar.py --date 2026-10-01
  python3 scripts/napi-naptar.py --json
  python3 scripts/napi-naptar.py --creds store/.m365-david-credentials
"""
import argparse
import datetime
import json
import sys
import urllib.parse
import urllib.request

CREDS = "/home/pdb/marveen/store/.m365-abel-kondics-credentials"
TZ = "Europe/Budapest"


def _creds(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def _token(c):
    data = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token",
        data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def _get(url, tok):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {tok}",
        # Without this header the times come back in UTC. See trap 1 above.
        "Prefer": f'outlook.timezone="{TZ}"'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(day, creds_path=CREDS):
    """Every event overlapping `day` (a datetime.date), across all calendars."""
    c = _creds(creds_path)
    tok = _token(c)
    mb = c["MAILBOX"]
    start = f"{day.isoformat()}T00:00:00"
    end = f"{(day + datetime.timedelta(days=1)).isoformat()}T00:00:00"
    url = (f"https://graph.microsoft.com/v1.0/users/{mb}/calendarView"
           f"?startDateTime={start}&endDateTime={end}"
           f"&$orderby=start/dateTime&$top=100"
           f"&$select=subject,start,end,isAllDay,location,isCancelled,showAs")
    return mb, _get(url, tok)["value"]


def normalise(events, day):
    out = []
    for e in events:
        if e.get("isCancelled"):
            continue
        all_day = bool(e.get("isAllDay"))
        s = e["start"]["dateTime"]
        en = e["end"]["dateTime"]
        loc = ((e.get("location") or {}).get("displayName") or "").strip()
        out.append({
            "subject": (e.get("subject") or "").strip(),
            "all_day": all_day,
            # For a timed event the wall clock is the useful part; for an all-day
            # one any end time would be misleading (trap 2), so we drop it.
            "from": None if all_day else s[11:16],
            "to": None if all_day else en[11:16],
            "location": loc,
            "show_as": e.get("showAs"),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD, default: today")
    ap.add_argument("--creds", default=CREDS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    day = (datetime.date.fromisoformat(a.date) if a.date
           else datetime.date.today())
    try:
        mb, raw = fetch(day, a.creds)
    except Exception as e:  # a failed measurement is a THIRD state, not "no events"
        print(f"A NAPTAR-LEKERDEZES BUKOTT: {e}\n"
              "Ez NEM azt jelenti, hogy nincs esemeny. Ne jelents ures naptarat.",
              file=sys.stderr)
        return 2
    rows = normalise(raw, day)

    if a.json:
        print(json.dumps({"mailbox": mb, "date": day.isoformat(),
                          "events": rows}, ensure_ascii=False, indent=2))
        return 0

    print(f"{mb} -- {day.isoformat()} -- {len(rows)} esemeny")
    for r in rows:
        mikor = "egesz nap" if r["all_day"] else f"{r['from']}-{r['to']}"
        hol = f"   [{r['location']}]" if r["location"] else ""
        print(f"  {mikor:>11}  {r['subject']}{hol}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
