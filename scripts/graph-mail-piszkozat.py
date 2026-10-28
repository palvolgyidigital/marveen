#!/usr/bin/env python3
"""PISZKOZAT létrehozása egy M365 postafiókban, melléklettel. NEM küld semmit.

Miért létezik: a `scripts/graph-mail.ts` igéi `verify | list | headers | send`, tehát
piszkozatot nem tud. Marci 2026-10-15 12:52-kor (Telegram 9809) a marketing@ fiókba kért
egy piszkozatot egy PDF-fel és egy szó szerint megadott törzzsel, és erre a flottában nem
volt recept (sem skill, sem szkript).

A KÜLDÉS ÉS A PISZKOZAT KÉT KÜLÖN DOLOG, és ez a szkript szándékosan csak az utóbbit
tudja: a `POST /users/<mailbox>/messages` draft-ot hoz létre, amit a fiók gazdája lát a
Piszkozatok mappában, és ő dönti el, kinek és mikor megy ki. Küldés-képesség itt nincs,
tehát ezzel a szkripttel nem lehet véletlenül levelet kiengedni.

A TORZS SIMA SZOVEG (contentType: Text). Ha HTML-t kuldunk be, a kliens a tageket
jeleniti meg -- ez a 2026-10-01-i mert hiba az EDI-korben.

Hasznalat:
  python3 scripts/graph-mail-piszkozat.py <creds-fajl> --torzs <fajl> [--targy "..."]
                                          [--cimzett a@b.hu] [--masolat c@d.hu]
                                          [--melleklet <fajl> ...]
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request

GRAPH = 'https://graph.microsoft.com/v1.0'


def creds_betolt(utvonal: str) -> dict:
    d = {}
    with open(utvonal, encoding='utf-8') as f:
        for sor in f:
            sor = sor.strip()
            if not sor or sor.startswith('#') or '=' not in sor:
                continue
            k, v = sor.split('=', 1)
            d[k.strip()] = v.strip()
    return d


def token(c: dict) -> str:
    adat = urllib.parse.urlencode({
        'client_id': c['CLIENT_ID'], 'client_secret': c['CLIENT_SECRET'],
        'grant_type': 'client_credentials',
        'scope': 'https://graph.microsoft.com/.default',
    }).encode()
    url = f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token"
    with urllib.request.urlopen(urllib.request.Request(url, data=adat)) as r:
        return json.load(r)['access_token']


def hivas(tok: str, mod: str, ut: str, payload: dict) -> dict:
    req = urllib.request.Request(
        GRAPH + ut, method=mod, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': f'Bearer {tok}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req) as r:
        test = r.read()
        return json.loads(test) if test else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('creds')
    ap.add_argument('--torzs', required=True, help='a torzs sima szovegkent, fajlbol')
    ap.add_argument('--targy', default='', help='ha nincs megadva, URES marad')
    ap.add_argument('--cimzett', action='append', default=[])
    # MASOLAT (cc): Marci kerese, 2026-10-15 16:08 (Telegram 9861), az UNAS-nak szolo
    # SSL-level piszkozataban Abelt masolatba kerte. A Graph ugyanugy fogadja, mint a
    # toRecipients-et; a draft igy a kliensben is cc-vel nyilik meg.
    ap.add_argument('--masolat', action='append', default=[], help='cc cimzett(ek)')
    ap.add_argument('--melleklet', action='append', default=[])
    a = ap.parse_args()

    c = creds_betolt(a.creds)
    mailbox = c['MAILBOX']
    tok = token(c)
    torzs = open(a.torzs, encoding='utf-8').read()

    uj = {
        'subject': a.targy,
        'body': {'contentType': 'Text', 'content': torzs},
        'toRecipients': [{'emailAddress': {'address': x}} for x in a.cimzett],
    }
    if a.masolat:
        uj['ccRecipients'] = [{'emailAddress': {'address': x}} for x in a.masolat]
    d = hivas(tok, 'POST', f'/users/{mailbox}/messages', uj)
    mid = d['id']
    print(f'PISZKOZAT LETREHOZVA: {mailbox}')
    print(f'  id={mid}')
    print(f'  targy={a.targy!r}  cimzett={a.cimzett or "(nincs)"}  masolat={a.masolat or "(nincs)"}')
    print(f'  torzs {len(torzs)} karakter, contentType=Text')

    for ut in a.melleklet:
        nev = os.path.basename(ut)
        tartalom = open(ut, 'rb').read()
        tipus = mimetypes.guess_type(nev)[0] or 'application/octet-stream'
        hivas(tok, 'POST', f'/users/{mailbox}/messages/{mid}/attachments', {
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': nev, 'contentType': tipus,
            'contentBytes': base64.b64encode(tartalom).decode('ascii'),
        })
        print(f'  melleklet: {nev} ({len(tartalom)} bajt, {tipus})')
    print('KULDES NEM TORTENT. A piszkozat a fiok Piszkozatok mappajaban all.')
    print(f'VISSZAOLVASAS: {mid}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
