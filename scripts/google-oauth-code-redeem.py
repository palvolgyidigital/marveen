#!/usr/bin/env python3
"""Redeem a Google OAuth authorization code and update BOTH shared credential files.

WHY THIS SCRIPT EXISTS: the fleet-wide `curl *https://*` deny (OUTWARD915) blocks the raw
exchange that used to be done by hand, and the `external-oauth-integration-pattern` skill
requires a targeted script with a HARDCODED endpoint and no URL argument -- so it cannot be
pointed anywhere else. Measured 2026-10-12 and again 2026-10-19: both credential files share
one OAuth client and carry the SAME refresh token, and one redeemed code fixes both.

Usage:
    python3 scripts/google-oauth-code-redeem.py '<code or full redirect URL>'

It never prints a secret: only key names, sha256 prefixes and byte counts.
"""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

GYOKER = '/home/pdb/marveen'
TOKEN_URI = 'https://oauth2.googleapis.com/token'          # BEEGETVE, nem argumentum
REDIRECT = 'http://localhost'
SHEETS = os.path.join(GYOKER, 'store/.google-sheets-credentials')
ADS = os.path.join(GYOKER, 'agents/marti/.google-ads-credentials')


def olvas(ut):
    d = {}
    with open(ut, encoding='utf-8') as f:
        for sor in f:
            sor = sor.strip()
            if sor and not sor.startswith('#') and '=' in sor:
                k, v = sor.split('=', 1)
                d[k.strip()] = v.strip()
    return d


def ir(ut, d):
    """Sorrend-tarto ujrairas: csak az erintett kulcs erteke valtozik."""
    with open(ut, encoding='utf-8') as f:
        sorok = f.read().splitlines()
    ki = []
    for sor in sorok:
        if '=' in sor and not sor.strip().startswith('#'):
            k = sor.split('=', 1)[0].strip()
            if k in d:
                ki.append('%s=%s' % (k, d[k]))
                continue
        ki.append(sor)
    tmp = ut + '.uj'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('\n'.join(ki) + '\n')
    os.chmod(tmp, 0o600)
    os.replace(tmp, ut)


def kod_kiszed(arg):
    """A gazda a TELJES atiranyitott URL-t is bemasolhatja; abbol kiemeljuk a code-ot."""
    if 'code=' in arg:
        qs = urllib.parse.urlparse(arg).query or arg.split('?', 1)[-1]
        v = urllib.parse.parse_qs(qs).get('code')
        if v:
            return v[0]
    return arg.strip()


def ujj(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    kod = kod_kiszed(sys.argv[1])
    print('kod hossza: %d karakter, sha256-prefix: %s' % (len(kod), ujj(kod)))

    sh = olvas(SHEETS)
    ad = olvas(ADS)
    cid, secret = sh['CLIENT_ID'], sh['CLIENT_SECRET']
    print('kliens-azonossag a ket fajl kozott: %s'
          % ('AZONOS' if ad.get('GOOGLE_ADS_OAUTH_CLIENT_ID') == cid else 'ELTER'))
    print('regi refresh token sha256-prefix: sheets=%s ads=%s'
          % (ujj(sh.get('REFRESH_TOKEN', '')), ujj(ad.get('GOOGLE_ADS_REFRESH_TOKEN', ''))))

    adat = urllib.parse.urlencode({
        'code': kod, 'client_id': cid, 'client_secret': secret,
        'redirect_uri': REDIRECT, 'grant_type': 'authorization_code'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URI, data=adat)) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        torzs = e.read().decode('utf-8', 'replace')
        print('HTTP %s a token-vegponttol: %s' % (e.code, torzs[:400]), file=sys.stderr)
        return 1

    if 'refresh_token' not in tok:
        print('NINCS refresh_token a valaszban. Kulcsok: %s' % sorted(tok.keys()), file=sys.stderr)
        print('Ez jellemzoen azt jelenti, hogy a consent-URL-bol hianyzott az '
              'access_type=offline vagy a prompt=consent.', file=sys.stderr)
        return 1

    rt = tok['refresh_token']
    print('UJ refresh token: %d bajt, sha256-prefix: %s' % (len(rt), ujj(rt)))
    print('a valasz scope-ja: %s' % tok.get('scope', '(nincs)'))
    print('hozzaferesi jegy ervenyessege: %s masodperc' % tok.get('expires_in', '?'))

    ir(SHEETS, {'REFRESH_TOKEN': rt})
    ir(ADS, {'GOOGLE_ADS_REFRESH_TOKEN': rt})
    print('MENTVE mind a kettobe. Visszaolvasva, titok-kiiras nelkul:')
    for ut, k in ((SHEETS, 'REFRESH_TOKEN'), (ADS, 'GOOGLE_ADS_REFRESH_TOKEN')):
        d = olvas(ut)
        print('  %-44s %s = %s' % (ut.replace(GYOKER + '/', ''), k, ujj(d.get(k, ''))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
