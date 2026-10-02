#!/usr/bin/env python3
"""Search a mailbox for a term, and report METADATA only (no bodies).

WHY THIS EXISTS (2026-09-30): `scripts/graph-mail.ts` has verbs verify | list |
headers | send. There is NO search. `list` returns only the newest N messages, so it
CANNOT answer a historical question like "is there any correspondence with this
company". Answering such a question from `list` would be a false negative dressed as
an answer -- the `[[feedback_nem_talaltam_vs_nem_lattam_bele]]` failure class.

WHAT IT PRINTS, AND WHY THAT IS THE LIMIT: subject, from, to, date, id. NO body and
NO bodyPreview. `$select` is the protection: what is not selected cannot be printed by
accident. If a hit needs reading, that is a SEPARATE, deliberate step with
`graph-mail-torzs.py` on that one id.

SCOPE IS NOT THIS SCRIPT'S DECISION. It searches the mailbox whose credentials you
hand it. Which mailboxes you are allowed to search is a rule that lives elsewhere:
 - innova@ is a shared company mailbox, no privacy limit;
 - marketing@ is Marci's personal company mailbox, and the limit is lifted ONLY by a
   request from his own authenticated channel (8668856531), not by a relayed one;
 - a colleague's mailbox is not searchable just because we hold a key to it.

THE FOLDER MATTERS. By default Graph's /messages searches the WHOLE mailbox
(including Sent Items), which is usually what a "did we ever correspond" question
wants. Use --folder to narrow it.

A GRAPH-SPECIFIC TRAP, and the reason the output names it: with `$search` the server
REFUSES `$orderby`, and the result is relevance-ordered, not date-ordered. So the
first hit is not the newest one. This script sorts what it got by date itself and
says so, to stop a later round reading "first row" as "latest".

Usage:
  python3 scripts/graph-mail-kereses.py <creds-file> "<kifejezes>"
  python3 scripts/graph-mail-kereses.py <creds-file> "<kifejezes>" --folder inbox
  python3 scripts/graph-mail-kereses.py <creds-file> "<kifejezes>" --top 50
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def token(creds: dict) -> str:
    data = urllib.parse.urlencode({
        "client_id": creds["CLIENT_ID"], "client_secret": creds["CLIENT_SECRET"],
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode()
    url = f"https://login.microsoftonline.com/{creds['TENANT_ID']}/oauth2/v2.0/token"
    return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data)))["access_token"]


def cim_kereses(creds: dict, cim: str, top: str) -> int:
    """EGZAKT cimre keres $filter-rel, NEM $search-csel. Ez a pontos ut.

    MIERT KELL: a $search a /messages vegponton NEM frazis-kereso, tokenekre bont, es a
    mezore szukitett KQL-t (participants:, from:) 400-zal utasitja el. Merve 2026-09-30:
    a "Verb Partner" 25/25 talalatot adott GLS-szamlakra es havi kimutatasokra, mert a
    "partner" szo bennuk volt. Egy ilyen szam atadva azt allitana, hogy kiterjedt
    levelezesunk van valakivel, akivel egy sor sincs.
    A $filter ezzel szemben MEZORE es EGYENLOSEGRE szur, tehat nincs tokenizalas.
    """
    mb = creds["MAILBOX"]
    tok = token(creds)
    c = cim.replace("'", "''")
    # MERVE 2026-09-30: a Graph a /messages vegponton a toRecipients es ccRecipients
    # mezore NEM engedi az any() szurot, 400 ErrorInvalidUrlQueryFilter a valasz.
    # Tehat EGZAKTUL csak a FELADO szurheto. A cimzett-oldalra a $search marad, ami
    # egy EMAIL-CIMRE hiteles (megkulonbozteto token), de egy KOZNAPI SZORA nem.
    # Ne vedd ki a ket agat: a kiirt 400 maga az informacio, hogy nem tudtuk megnezni.
    agak = [
        ("bejovo (from)", f"from/emailAddress/address eq '{c}'"),
        ("kimeno (to) -- a Graph ezt nem engedi", f"toRecipients/any(r: r/emailAddress/address eq '{c}')"),
    ]
    ossz = 0
    for cimke, szuro in agak:
        url = (f"https://graph.microsoft.com/v1.0/users/{mb}/messages?"
               + "$filter=" + urllib.parse.quote(szuro, safe="()/:'@,")
               + "&$select=subject,from,toRecipients,receivedDateTime,id"
               + f"&$top={top}")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            print(f"  {cimke}: A SZURES BUKOTT, HTTP {e.code} -- "
                  f"{e.read()[:200].decode('utf-8','replace')}")
            print("  EZ HARMADIK ALLAPOT, nem nemleges valasz. A cimzett-oldalt a $search-csel")
            print("  nezd meg, EMAIL-CIMRE az hiteles. Folytatom a tobbi aggal.")
            continue
        sorok = d.get("value", [])
        ossz += len(sorok)
        print(f"  {cimke}: {len(sorok)} talalat")
        for r in sorok:
            f = ((r.get("from") or {}).get("emailAddress") or {}).get("address", "?")
            print(f"     {r.get('receivedDateTime')}  {f}  targy: {(r.get('subject') or '')[:70]}")
    print(f"  OSSZESEN: {ossz}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    creds = {}
    for line in open(sys.argv[1]):
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip()

    kif = sys.argv[2]
    top = "25"
    mappa = None
    for i, a in enumerate(sys.argv):
        if a == "--top" and i + 1 < len(sys.argv):
            top = sys.argv[i + 1]
        if a == "--folder" and i + 1 < len(sys.argv):
            mappa = sys.argv[i + 1]

    if "--cim" in sys.argv:
        print(f"POSTAFIOK: {creds['MAILBOX']} | EGZAKT CIM-SZURES (filter, nem search): {kif}")
        return cim_kereses(creds, kif, top)

    mb = creds["MAILBOX"]
    alap = f"https://graph.microsoft.com/v1.0/users/{mb}"
    ut = f"{alap}/mailFolders/{mappa}/messages" if mappa else f"{alap}/messages"
    # --raw: a kifejezes KQL-kent megy at (from:, to:, subject:, body:, participants:).
    # Enelkul idezojelbe tesszuk, DE a Graph az idezojeles alakot SEM kezeli valodi
    # frazisként: tokenekre bontja. Merve 2026-09-30: a "Verb Partner" a GLS-szamlakra
    # es a havi forgalmi kimutatasokra illeszkedett, mert a "partner" szo bennuk van.
    # EZERT: tobbszavas nevhez HASZNALJ --raw-t mezo-megkotessel, kulonben a talalat zaj.
    nyers = "--raw" in sys.argv
    kifejezes = kif if nyers else f'"{kif}"'
    url = (f"{ut}?$search=" + urllib.parse.quote(kifejezes)
           + "&$select=subject,from,toRecipients,receivedDateTime,id"
           + f"&$top={top}")

    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token(creds),
        # $search needs this header on /messages, otherwise Graph returns 400.
        "ConsistencyLevel": "eventual",
    })
    try:
        d = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        # A failed search is a THIRD state. It is NOT "no such mail".
        print(f"A KERESES BUKOTT: HTTP {e.code} -- {e.read()[:300].decode('utf-8','replace')}")
        print("EZ NEM AZT JELENTI, HOGY NINCS TALALAT. Ne jelents nemleges valaszt belole.")
        return 2

    sorok = d.get("value", [])
    for r in sorok:
        r["_d"] = r.get("receivedDateTime") or ""
    sorok.sort(key=lambda r: r["_d"], reverse=True)

    print(f"POSTAFIOK: {mb} | MAPPA: {mappa or '(teljes postafiok, Elkuldott is)'}")
    print(f"KIFEJEZES: {kif!r} | TALALAT: {len(sorok)} (felso korlat {top})")
    if len(sorok) == int(top):
        print("FIGYELEM: a talalatszam ELERTE a felso korlatot, tehat lehet tobb. Emeld a --top erteket.")
    print("A sorrend DATUM szerinti, magam rendeztem: a $search relevancia szerint ad vissza,")
    print("es mellette a Graph NEM engedi az $orderby-t.")
    for r in sorok:
        f = ((r.get("from") or {}).get("emailAddress") or {}).get("address", "?")
        to = ", ".join(((x.get("emailAddress") or {}).get("address", "?"))
                       for x in (r.get("toRecipients") or []))[:70]
        print(f"  {r['_d']}  {f}  ->  {to}")
        print(f"      targy: {(r.get('subject') or '')[:90]}")
        print(f"      id:    {r.get('id')}")
    if not sorok:
        print("  (nincs talalat ebben a postafiokban erre a kifejezesre)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
