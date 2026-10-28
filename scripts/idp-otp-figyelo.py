#!/usr/bin/env python3
"""OTP-figyelo: kiirja az IDP access code-ot a jelzofajlba, agens-kor NELKUL.

MIERT LETEZIK, ES EZT MERTEM, NEM FELTETTEM.
A kezi relay HAROMSZOR futott le (2026-09-01, 10-06, 10-13), es a szuk keresztmetszet
nem a letolto agens oldala, hanem a KIOLVASAS. 2026-10-13-i mert szamok:
  09:25:46Z  a kod kibocsatasa (az IDP level fejlece szerint)
  09:25:56Z  megerkezik az innova@-ra (a tovabbitas 10 masodperc)
  09:28:16Z  EN kiirom a jelzofajlba           <- itt ment el 2 perc 30
  09:28:20Z  Max scriptje beolvassa (4 masodperc)
  09:30:46Z  a kod lejar (a torzs szo szerint: "expire within 5 minutes")
Vagyis az otperces budzsebol felet egyetlen agens-kor vitte el. Ez nem fegyelemmel
javithato: a 2026-10-06-i memoria-bejegyzes ezt mar kimondta, es azota megegyszer
elofordult. Ez a szkript az a megoldas.

HASZNALAT, es a LENYEG a SORREND: a figyelot a bejelentkezes ELOTT inditsd el,
hatterben, MIELOTT uzensz a letolto agensnek:

  nohup python3 scripts/idp-otp-figyelo.py \\
      --creds store/.m365-innova-credentials \\
      --out store/mediamarkt-agent/.otp-code \\
      --minutes 20 > /tmp/otp-figyelo.log 2>&1 &

Igy amikor az OTP megerkezik, a kod masodperceken belul a jelzofajlban van, es a
letolto agens nem var agens-korre.

A HAROM SZABALY, AMIT A SZKRIPT BETART (a kezi eljarasbol atvéve):
1. CSAK a `--since` (alap: indulasi ido) UTAN erkezett kodot fogadja el. A "legfrissebb
   level" szabaly megbizhatatlan: 2026-09-01-en ot kod volt forgalomban perceken belul,
   es kettonek AZONOS volt a masodperce.
2. HA EGYNEL TOBB jelolt van, NEM VALASZT: nem ir fajlt, hanem hibat naplóz. Egy
   talalgatott kod elhasznal egy probalkozast, es negy-ot hibas kiserlet a postafiok
   gazdajanak TELJES portal-hozzaferesét zarolhatja.
3. A kibocsatasi idot es a lejaratot KIIRJA a naplóba, mert a budzse a KIBOCSATASTOL
   szamol, nem az erkezestol.

A szkript NEM torli a jelzofajlt: azt a beolvaso oldal teszi (Max scriptje magatol
torli, 2026-10-13-an ellenorizve). Ha megmarad, a hivo torolje.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KOD_MINTA = re.compile(r"[Aa]ccess code\s*:?\s*(\d{6})")
# Az IDP level targya; a tovabbitas "FW:" elotagot tesz ra, ezert nem anchorolunk.
TARGY_MINTA = re.compile(r"IDP access code", re.I)


def naplo(szoveg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%SZ')}] {szoveg}", flush=True)


def creds_betoltese(utvonal: str) -> dict:
    d = {}
    with open(utvonal, encoding="utf-8") as fh:
        for sor in fh:
            sor = sor.strip()
            if not sor or sor.startswith("#") or "=" not in sor:
                continue
            k, v = sor.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("TENANT_ID", "CLIENT_ID", "CLIENT_SECRET", "MAILBOX"):
        if not d.get(k):
            sys.exit(f"HIBA: hianyzik a(z) {k} a creds fajlbol ({utvonal})")
    return d


def token(c: dict) -> str:
    url = f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token"
    adat = urllib.parse.urlencode({
        "client_id": c["CLIENT_ID"], "client_secret": c["CLIENT_SECRET"],
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(url, data=adat, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["access_token"]


def csupasz(html_szoveg: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_szoveg)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def jeloltek(tok: str, mailbox: str, since: datetime) -> list[dict]:
    """Az Inbox ES a Junk atvizsgalasa. A Junk nem opcionalis: a tovabbitott
    gepi level oda is eshet, es onnan soha nem jon fel magatol."""
    out = []
    for mappa in ("Inbox", "JunkEmail"):
        qs = urllib.parse.urlencode({
            "$select": "subject,receivedDateTime,body,from",
            "$top": "15",
            "$orderby": "receivedDateTime desc",
        })
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/mailFolders/{mappa}/messages?{qs}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                adat = json.load(r)
        except Exception as exc:  # noqa: BLE001
            naplo(f"FIGYELEM: a(z) {mappa} lekerdezese elhasalt ({exc!r}), folytatom")
            continue
        for m in adat.get("value", []):
            erkezett = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))
            if erkezett <= since:
                continue
            torzs = csupasz(m.get("body", {}).get("content", ""))
            talalat = KOD_MINTA.search(torzs)
            if not (talalat or TARGY_MINTA.search(m.get("subject") or "")):
                continue
            if not talalat:
                naplo(f"FIGYELEM: IDP-targyu level kod nelkul: {m.get('subject')!r}")
                continue
            out.append({
                "kod": talalat.group(1),
                "erkezett": m["receivedDateTime"],
                "mappa": mappa,
                "targy": m.get("subject"),
                "felado": (m.get("from") or {}).get("emailAddress", {}).get("address"),
                "torzs": torzs,
            })
    return out


def kibocsatas(torzs: str) -> str | None:
    """A tovabbitott level fejlecebol az EREDETI kuldesi ido, mert a budzse attol
    szamol. Pl.: 'Elkuldve: 2026. oktober 13., kedd 11:25:46 (UTC+01:00)'."""
    m = re.search(r"(\d{4})\.\s*\S+\s*(\d{1,2})\.,?\s*\S*\s*(\d{1,2}):(\d{2}):(\d{2})", torzs)
    return f"{m.group(3)}:{m.group(4)}:{m.group(5)} (a level fejlece szerint, lokalis ido)" if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description="IDP OTP-figyelo: kodot ir a jelzofajlba")
    ap.add_argument("--creds", default="store/.m365-innova-credentials")
    ap.add_argument("--out", required=True, help="a jelzofajl, amibe CSAK a kod kerul")
    ap.add_argument("--minutes", type=float, default=20.0, help="meddig figyeljen (alap: 20)")
    ap.add_argument("--interval", type=float, default=8.0, help="pollozas masodpercben (alap: 8)")
    ap.add_argument("--since", help="ISO UTC idopont; enel ujabb levelet fogad el (alap: most)")
    a = ap.parse_args()

    since = (datetime.fromisoformat(a.since.replace("Z", "+00:00")) if a.since
             else datetime.now(timezone.utc))
    hatarido = datetime.now(timezone.utc) + timedelta(minutes=a.minutes)
    c = creds_betoltese(a.creds)
    tok = token(c)
    naplo(f"figyelo indul | postafiok={c['MAILBOX']} | since={since:%H:%M:%SZ} | "
          f"hatarido={hatarido:%H:%M:%SZ} | jelzofajl={a.out}")

    tokenido = time.time()
    while datetime.now(timezone.utc) < hatarido:
        if time.time() - tokenido > 2400:          # a token egy ora, 40 perc utan ujitunk
            tok = token(c)
            tokenido = time.time()
            naplo("token ujitva")
        lista = jeloltek(tok, c["MAILBOX"], since)
        if len(lista) == 1:
            j = lista[0]
            os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
            tmp = a.out + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(j["kod"])
            os.replace(tmp, a.out)
            kib = kibocsatas(j["torzs"]) or "a fejlecbol nem olvashato ki"
            naplo(f"KOD KIIRVA -> {a.out}")
            naplo(f"  erkezett: {j['erkezett']} | mappa: {j['mappa']} | felado: {j['felado']}")
            naplo(f"  kibocsatas: {kib}")
            naplo("  LEJARAT: a torzs szerint 5 perc a KIBOCSATASTOL, nem az erkezestol")
            return 0
        if len(lista) > 1:
            naplo(f"HIBA: {len(lista)} kod van forgalomban, NEM VALASZTOK es nem irok fajlt.")
            for j in lista:
                naplo(f"  jelolt: {j['erkezett']} {j['mappa']} kod=...{j['kod'][-2:]}")
            naplo("  TEENDO: egyetlen tiszta bejelentkezessel kezdjetek ujra.")
            return 3
        time.sleep(a.interval)

    naplo(f"LEJART a figyelesi ablak ({a.minutes} perc), kod nem erkezett. Fajlt nem irtam.")
    return 4


if __name__ == "__main__":
    sys.exit(main())
