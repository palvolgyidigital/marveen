#!/usr/bin/env python3
"""Forward an M365 message, attachments intact.

The graph-mail.ts CLI has no `forward` verb, only `send`. Re-sending a copied
body would DROP the attachments silently: the recipient gets a mail that looks
complete, so the loss is invisible on both ends. Graph's own /forward endpoint
carries attachments and formatting, so that is what this wraps.

  list     -- print id/received/from/subject/hasAttachments for the newest N
  forward  -- forward ONE message id to ONE address

The id is required for `forward` on purpose: "the latest message" is a moving
target, and two mails can arrive between listing and acting on one.

Usage:
  graph-mail-forward.py --creds <file> list [--top N]
  graph-mail-forward.py --creds <file> forward --id <id> --to <addr> [--comment TEXT]
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

GRAPH = 'https://graph.microsoft.com/v1.0'


def read_creds(path):
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                out[k.strip()] = v.strip()
    for key in ('TENANT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'MAILBOX'):
        if key not in out:
            sys.exit(f'missing {key} in {path}')
    return out


def token(c):
    body = urllib.parse.urlencode({
        'client_id': c['CLIENT_ID'],
        'client_secret': c['CLIENT_SECRET'],
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials',
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{c['TENANT_ID']}/oauth2/v2.0/token",
        data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return json.loads(urllib.request.urlopen(req).read())['access_token']


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--creds', required=True)
    sub = p.add_subparsers(dest='cmd', required=True)
    lst = sub.add_parser('list')
    lst.add_argument('--top', type=int, default=5)
    fwd = sub.add_parser('forward')
    fwd.add_argument('--id', required=True)
    fwd.add_argument('--to', required=True)
    fwd.add_argument('--comment', default='')
    a = p.parse_args()

    c = read_creds(a.creds)
    h = {'Authorization': f'Bearer {token(c)}', 'Content-Type': 'application/json'}
    mb = urllib.parse.quote(c['MAILBOX'])

    if a.cmd == 'list':
        # urlencode the whole query: a raw space in $orderby makes python's
        # urllib raise InvalidURL before the request is ever sent, which reads
        # like a server or permission error but is purely client-side.
        q = urllib.parse.urlencode({
            '$top': a.top,
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,subject,from,receivedDateTime,hasAttachments',
        })
        url = f'{GRAPH}/users/{mb}/mailFolders/inbox/messages?{q}'
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h)).read())
        for m in data['value']:
            print(f"{m['receivedDateTime']}  att={str(m['hasAttachments']):<5} "
                  f"{m['from']['emailAddress']['address']}  {m['subject']}")
            print(f"  id: {m['id']}")
        return

    payload = {'toRecipients': [{'emailAddress': {'address': a.to}}]}
    if a.comment:
        payload['comment'] = a.comment
    req = urllib.request.Request(f'{GRAPH}/users/{mb}/messages/{a.id}/forward',
                                 data=json.dumps(payload).encode(), headers=h, method='POST')
    r = urllib.request.urlopen(req)
    # 202 means accepted for delivery, NOT delivered. Read the target mailbox
    # back before reporting this as done.
    print(f'forward accepted: HTTP {r.status} -> {a.to}')


if __name__ == '__main__':
    main()
