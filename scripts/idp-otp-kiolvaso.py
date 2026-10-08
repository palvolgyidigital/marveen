#!/usr/bin/env python3
"""Read the IDP 2FA access code from the innova@ mailbox and write it to the signal file.

WHY THIS EXISTS (measured 2026-10-06, two failed logins in a row):
the IDP mail says it plainly: `This code will expire within 5 minutes.` Both failures
that morning came from the SAME cause, and the cause was the relay latency, not the
code and not the browser session:

  attempt 1: issued 06:22:53, entered 06:32:52  -> ten minutes late
  attempt 2: issued 06:35:55, entered 06:41:19  -> five minutes and 24 seconds late

The second one ran in the SAME open browser session, so "a new browser invalidates the
earlier code" did not apply. The only remaining factor was the clock, and the clock was
spent on a human-in-the-loop relay: an agent had to notice the request, read its own
notes, find the extraction recipe and run it. Four minutes is not enough room for that.

So the relay must not have an agent on the critical path. The downloading agent calls
this script directly; it polls and writes the code itself.

THE DEADLINE IS MEASURED FROM ISSUE, NOT FROM ARRIVAL. The mail is forwarded (from
Abel's address), so `receivedDateTime` is already later than the issue time. On
2026-10-06 the forward cost 8 seconds, but that is not guaranteed. This script therefore
reports BOTH times and the remaining budget, so the caller can decide to abort instead
of entering a code that is already dead.

SELECTION RULE, and it is deliberately strict (measured 2026-09-01, five codes in
circulation within minutes, two with the same second): never take "the latest". Only a
code that arrived AFTER the login attempt started counts, and if more than one matches,
this script REFUSES rather than guesses. A wrong code burns the attempt.

Usage:
  python3 scripts/idp-otp-kiolvaso.py --after 2026-10-06T06:36:00Z
  python3 scripts/idp-otp-kiolvaso.py --after now          # a hivas pillanatatol
  python3 scripts/idp-otp-kiolvaso.py --after now --timeout 90 --out <fajl>

Exit codes:
  0  code written to the signal file
  1  no matching code within the timeout
  2  more than one candidate, or more than one number in the body: REFUSED
  3  the code found is already expired (past the 5 minute window)
"""
import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request

CREDS = "/home/pdb/marveen/store/.m365-innova-credentials"
OUT = "/home/pdb/marveen/store/mediamarkt-agent/.otp-code"
TARGY = "access code"
ELETTARTAM = 300  # masodperc, a level sajat szovege szerint: "expire within 5 minutes"
# Az eredeti kuldesi ido a tovabbitott fejlecben all, magyar Outlook-formaban:
#   "Elkuldve: 2026. oktober 6., kedd 8:35:55 (UTC+01:00) ..."
KULDES_RX = re.compile(r"Elk[uü]ldve:.*?(\d{1,2}):(\d{2}):(\d{2})")


def creds() -> dict:
    d = {}
    for line in open(CREDS):
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def token(c: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token"
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data)))["access_token"]


def get(url: str, tok: str) -> dict:
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})))


def jeloltek(c: dict, tok: str, after: str) -> list:
    q = urllib.parse.urlencode({"$select": "id,subject,receivedDateTime", "$top": "10",
                                "$orderby": "receivedDateTime desc"})
    r = get(f"https://graph.microsoft.com/v1.0/users/{c['MAILBOX']}/mailFolders/inbox/messages?{q}", tok)
    return [m for m in r["value"]
            if TARGY in (m["subject"] or "").lower() and m["receivedDateTime"] > after]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--after", required=True,
                    help="csak az ezutan erkezett kod szamit; ISO UTC vagy 'now'")
    ap.add_argument("--timeout", type=int, default=120, help="masodperc, meddig varjon a levelre")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    after = (dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
             if a.after == "now" else a.after)
    print(f"T (csak ez utan erkezett kod szamit): {after}", flush=True)

    c = creds()
    tok = token(c)
    hatarido = time.time() + a.timeout
    while True:
        j = jeloltek(c, tok, after)
        if len(j) > 1:
            print(f"ELUTASITVA: {len(j)} jelolt van a T utan, NEM valasztok.", file=sys.stderr)
            for m in j:
                print("  ", m["receivedDateTime"], file=sys.stderr)
            return 2
        if j:
            break
        if time.time() >= hatarido:
            print(f"NINCS KOD a T utan {a.timeout} masodpercen belul.", file=sys.stderr)
            return 1
        time.sleep(2)

    u = (f"https://graph.microsoft.com/v1.0/users/{c['MAILBOX']}/messages/"
         f"{urllib.parse.quote(j[0]['id'], safe='')}?"
         + urllib.parse.urlencode({"$select": "receivedDateTime,body"}))
    m = get(u, tok)
    torzs = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m["body"]["content"]))

    kodok = sorted(set(re.findall(r"\b\d{6}\b", torzs)))
    if len(kodok) != 1:
        print(f"ELUTASITVA: {len(kodok)} hatjegyu szam a torzsben, NEM tippelek: {kodok}",
              file=sys.stderr)
        return 2

    # A HATRALEVO IDO a KULDESTOL szamol, nem az erkezestol.
    erk = dt.datetime.strptime(m["receivedDateTime"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc)
    km = KULDES_RX.search(torzs)
    if km:
        h, mi, s = (int(x) for x in km.groups())
        kuldes = erk.replace(hour=h, minute=mi, second=s)
        # a fejlec helyi idot ir; ha az erkezesnel kesobbre esne, egy oras eltolas a magyarazat
        while kuldes > erk:
            kuldes -= dt.timedelta(hours=1)
        alap, honnan = kuldes, "a fejlecben allo KULDESI ido"
    else:
        alap, honnan = erk, "az ERKEZES (a kuldesi ido nem volt kiolvashato, tehat OPTIMISTA)"

    hatra = ELETTARTAM - (dt.datetime.now(dt.timezone.utc) - alap).total_seconds()
    print(f"erkezett: {m['receivedDateTime']} | alap: {honnan} | hatralevo: {hatra:.0f} mp")
    if hatra <= 0:
        print("ELUTASITVA: ez a kod MAR LEJART, nem irom ki. Uj kisérlet kell.", file=sys.stderr)
        return 3

    open(a.out, "w").write(kodok[0] + "\n")
    print(f"KIIRVA: {a.out} ({hatra:.0f} mp van hatra, ird be MOST)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
