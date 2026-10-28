# -*- coding: utf-8 -*-
"""A 18 termekoldalbol kinyeri a rovid es a hosszu leirast, determinisztikusan."""
import re, json, html, os, glob

SP = '/tmp/claude-1000/-home-pdb-marveen/b2d25bae-59d1-4435-bacb-5634ae9caf89/scratchpad'


def blokk(t, cls):
    """A megadott class-u div TARTALMA, a nyito div utani elso kiegyensulyozott zarasig."""
    m = re.search(r'<div[^>]*class="[^"]*' + re.escape(cls) + r'[^"]*"[^>]*>', t)
    if not m:
        return None
    i = m.end()
    szint = 1
    for mm in re.finditer(r'<(/?)div\b', t[i:]):
        szint += -1 if mm.group(1) else 1
        if szint == 0:
            return t[i:i + mm.start()]
    return None


def csupasz(h):
    if not h:
        return ''
    h = re.sub(r'(?is)<(script|style).*?</\1>', ' ', h)
    h = re.sub(r'(?i)<br\s*/?>', '\n', h)
    h = re.sub(r'(?i)</(p|li|div|h\d|tr)>', '\n', h)
    h = re.sub(r'(?i)<li[^>]*>', '  - ', h)
    h = re.sub(r'<[^>]+>', '', h)
    h = html.unescape(h)
    h = h.replace(' ', ' ')
    sorok = [re.sub(r'[ \t]+', ' ', s).strip() for s in h.split('\n')]
    sorok = [s for s in sorok if s]
    return '\n'.join(sorok)


ki = {}
for f in sorted(glob.glob(SP + '/page-*.html')):
    sku = os.path.basename(f)[5:-5]
    t = open(f, encoding='utf-8', errors='replace').read()
    rovid = csupasz(blokk(t, 'artdet__short-descripton-content'))
    hosszu = csupasz(blokk(t, 'long-description__content'))
    ki[sku] = {'rovid': rovid, 'hosszu': hosszu}
    print('%-15s rovid %5d kar | hosszu %6d kar' % (sku, len(rovid), len(hosszu)))

json.dump(ki, open(SP + '/leirasok.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\nkiirva:', len(ki), 'termek')
