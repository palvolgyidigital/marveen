#!/usr/bin/env python3
"""Read Abel's "Abel HO" calendar and print the upcoming absences.

WHY THIS EXISTS (Marci, 2026-09-04): Zoli does not watch this calendar, so Cili
has to. Abel created it as a PLAIN calendar in his own mailbox after the first
attempt (an M365 group) turned out to be unreachable: no key we hold has any
Group.* permission, so a group calendar cannot be read at all. A plain calendar
in a mailbox we already have a key for needs no new permission.

THE TRAP THIS SCRIPT EXISTS TO REMOVE: Graph reports an all-day event's `end`
as EXCLUSIVE. A two-day home office on the 10th and 11th comes back as
2026-09-10 -> 2026-09-12. Reporting that end date verbatim tells Zoli that Abel
is away a day longer than he is. Every date this script prints is already
converted to the inclusive last day.

Usage:
  python3 scripts/abel-ho-naptar.py            # human-readable, next 60 days
  python3 scripts/abel-ho-naptar.py --json     # machine-readable
  python3 scripts/abel-ho-naptar.py --days 14  # different window
"""
import argparse
import datetime
import json
import sys
import urllib.parse
import urllib.request

CREDS = "/home/pdb/marveen/store/.m365-abel-kondics-credentials"
CALENDAR_NAME = "Ábel HO"
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
        "Prefer": f'outlook.timezone="{TZ}"'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch(days_ahead=60, days_back=1):
    c = _creds(CREDS)
    tok = _token(c)
    mb = c["MAILBOX"]
    cals = _get(f"https://graph.microsoft.com/v1.0/users/{mb}/calendars", tok)["value"]
    match = [x for x in cals if x.get("name") == CALENDAR_NAME]
    if not match:
        raise SystemExit(
            f"A(z) {CALENDAR_NAME!r} naptar NINCS a(z) {mb} fiokban. "
            f"Meglevo naptarak: {[x.get('name') for x in cals]}")
    cal = match[0]
    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (now + datetime.timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (f"https://graph.microsoft.com/v1.0/users/{mb}/calendars/{cal['id']}"
           f"/calendarView?startDateTime={start}&endDateTime={end}"
           f"&$orderby=start/dateTime&$top=100")
    return _get(url, tok)["value"]


def normalise(events):
    """Turn Graph events into inclusive first/last day records."""
    today = datetime.date.today()
    out = []
    for e in events:
        first = datetime.date.fromisoformat(e["start"]["dateTime"][:10])
        last = datetime.date.fromisoformat(e["end"]["dateTime"][:10])
        if e.get("isAllDay"):
            # Graph's all-day end is EXCLUSIVE -- the last real day is end - 1.
            last = last - datetime.timedelta(days=1)
        subject = (e.get("subject") or "").strip()
        low = subject.lower()
        if "szabad" in low:
            kind = "szabadsag"
        elif "ho" in low.replace("-", " ").split() or "home office" in low:
            kind = "home_office"
        else:
            kind = "egyeb"
        out.append({
            "subject": subject,
            "kind": kind,
            "first_day": first.isoformat(),
            "last_day": last.isoformat(),
            "all_day": bool(e.get("isAllDay")),
            "days": (last - first).days + 1,
            "starts_today": first == today,
            "starts_tomorrow": first == today + datetime.timedelta(days=1),
            "ongoing_today": first <= today <= last,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    recs = normalise(fetch(days_ahead=a.days))
    if a.json:
        json.dump(recs, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return
    if not recs:
        print(f"Nincs bejegyzes a(z) {CALENDAR_NAME!r} naptarban a kovetkezo {a.days} napban.")
        return
    print(f"{CALENDAR_NAME} -- {len(recs)} bejegyzes (a zaro nap MAR bennfoglalo):")
    for r in recs:
        span = r["first_day"] if r["days"] == 1 else f"{r['first_day']} .. {r['last_day']}"
        flags = []
        if r["ongoing_today"]:
            flags.append("MA IS TART")
        if r["starts_tomorrow"]:
            flags.append("HOLNAP KEZDODIK")
        print(f"  {span:<26} {r['days']:>2} nap  {r['kind']:<12} {r['subject']}"
              + (f"   [{', '.join(flags)}]" if flags else ""))


if __name__ == "__main__":
    main()
