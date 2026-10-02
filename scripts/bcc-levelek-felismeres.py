#!/usr/bin/env python3
"""List inbox messages and decide, per message, whether it arrived as BCC.

WHY THIS EXISTS (2026-10-01): the `david-bcc-levelek-emlekezteto` scheduled task runs
every three days and its recipe has two measured traps that are easy to re-botch by
hand. Both are about comparing a sound signal in the wrong SHAPE:

 1. The `X-MS-Exchange-Processed-By-BccFoldering` header proves NOTHING on its own --
    in this tenant it lands on ordinary To/CC mail too (measured 2026-09-13, two
    messages carried it and NEITHER was a BCC). The recipient list decides; the header
    is only confirmation.
 2. Plus-addressing (`innova+tag@pdb.hu`) makes a substring test call a direct To
    message a BCC (measured 2026-09-28). The local part must be normalised by cutting
    at `+` BEFORE comparison.

It prints metadata only: date, from, subject, To/CC, verdict. No body, no bodyPreview
-- `$select` is the protection, as in graph-mail-kereses.py.

THE WINDOW IS THE WHOLE LIST, NOT A TIME RANGE. Three rounds slid past two real BCC
letters in 2026-09 because this task has no state file and each round guessed how far
back to look. Every listed message is classified; deduplication against the existing
`BCC-levelek` cards is what stops re-filing, not a watermark.

Usage:
  python3 scripts/bcc-levelek-felismeres.py <creds-file> <sajat-cim> [--top N] [--headers]

`--headers` adds the per-message header fetch (one extra call per BCC candidate) to
confirm the BccFoldering header. Without it, the verdict rests on the recipient list
alone, which is the authoritative half anyway.
"""
import json
import sys
import urllib.parse
import urllib.request

GRAPH = "https://graph.microsoft.com/v1.0"


def token(creds: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": creds["CLIENT_ID"], "client_secret": creds["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{creds['TENANT_ID']}/oauth2/v2.0/token"
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data)))["access_token"]


def kulcs(cim: str) -> str:
    """Normalise one address: lowercase, and drop the `+tag` from the local part.

    Without this, `innova+leiratkozasteszt0925@pdb.hu` does not contain the substring
    `innova@pdb.hu`, so a direct To message is misread as a BCC (measured 2026-09-28).
    """
    loc, _, dom = (cim or "").strip().lower().partition("@")
    return loc.split("+")[0] + "@" + dom


def cimek(uzenet: dict, mezo: str) -> list:
    return [((r.get("emailAddress") or {}).get("address") or "") for r in (uzenet.get(mezo) or [])]


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    creds = {}
    for line in open(sys.argv[1]):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()
    sajat = kulcs(sys.argv[2])
    top = "20"
    for i, a in enumerate(sys.argv):
        if a == "--top" and i + 1 < len(sys.argv):
            top = sys.argv[i + 1]
    fejlec_is = "--headers" in sys.argv

    mb = creds["MAILBOX"]
    tok = token(creds)
    url = (f"{GRAPH}/users/{mb}/mailFolders/inbox/messages"
           "?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime"
           f"&$top={top}&$orderby=" + urllib.parse.quote("receivedDateTime desc"))
    d = json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}), timeout=60))
    sorok = d.get("value", [])

    print(f"POSTAFIOK: {mb} | sajat cim normalizalva: {sajat} | atnezett levelek: {len(sorok)}")
    print("A dontest a cimzett-lista mondja ki, a fejlec csak megerosites.\n")
    jeloltek = []
    for r in sorok:
        to = [kulcs(c) for c in cimek(r, "toRecipients")]
        cc = [kulcs(c) for c in cimek(r, "ccRecipients")]
        f = ((r.get("from") or {}).get("emailAddress") or {}).get("address", "?")
        bcc = sajat not in to and sajat not in cc
        jel = "BCC-JELOLT" if bcc else "sima (To/CC)"
        print(f"{r.get('receivedDateTime')}  [{jel}]  {f}")
        print(f"    targy: {(r.get('subject') or '(nincs targy)')[:95]}")
        print(f"    To: {', '.join(to) or '(ures)'}")
        print(f"    CC: {', '.join(cc) or '(ures)'}")
        if bcc:
            jeloltek.append(r)
            if fejlec_is:
                h = json.load(urllib.request.urlopen(urllib.request.Request(
                    f"{GRAPH}/users/{mb}/messages/{urllib.parse.quote(r['id'])}"
                    "?$select=internetMessageHeaders",
                    headers={"Authorization": "Bearer " + tok}), timeout=60))
                nevek = {(x.get("name") or "").lower() for x in (h.get("internetMessageHeaders") or [])}
                van = "x-ms-exchange-processed-by-bccfoldering" in nevek
                print(f"    BccFoldering fejlec: {'megvan' if van else 'NINCS'} (megerosites, nem bizonyitek)")
        print()
    print(f"OSSZESEN {len(jeloltek)} BCC-jelolt a {len(sorok)} atnezett levelbol.")
    print("A kartya-felvetel elott dedupliqalj a BCC-levelek projekt kartyaira: targy + datum egyutt azonosit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
