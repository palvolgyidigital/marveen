#!/usr/bin/env python3
"""Find duplicate images INSIDE each product's webshop gallery.

WHY THE OBVIOUS METHOD IS NOT ENOUGH (measured 2026-09-04): comparing file
checksums finds only byte-identical copies. David spotted a pair by eye that
checksums called different -- two separate files, different sizes, showing the
same shot at a slightly different crop. My checksum sweep reported "one
duplicate in the whole line"; his eye said two. He was right.

So this compares IMAGE CONTENT with a difference hash, not bytes. Validated
against the exact pair he found: both the byte-identical pair and the
merely-visually-identical pair come out at distance 0.

THE OTHER TRAP, also measured: the shop does NOT 404 a missing image slot, it
serves a PLACEHOLDER. A naive sweep therefore reports almost every product as
full of duplicates -- the first run flagged 98 products out of 99. The
placeholder is detected here dynamically as the most frequent checksum, and a
sanity threshold refuses to run if it does not look like one.

Usage:
  python3 scripts/galeria-duplikatum.py <skulista.txt> [--max-dist 5] [--shop-id 72544]
"""
import argparse
import collections
import hashlib
import io
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

URL = "https://www.pdb.hu/img/{shop}/{s}/400x400,r,1/{s}.webp"
MAX_ALT = 8


def fetch(slot, shop):
    try:
        req = urllib.request.Request(URL.format(shop=shop, s=slot),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except Exception:
        return None


def dhash(blob, size=8):
    im = Image.open(io.BytesIO(blob)).convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(im.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (1 if px[row * (size + 1) + col] > px[row * (size + 1) + col + 1] else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def scan(sku, shop):
    out = {}
    for slot in [sku] + [f"{sku}_altpic_{i}" for i in range(1, MAX_ALT + 1)]:
        blob = fetch(slot, shop)
        if blob:
            out[slot] = (hashlib.md5(blob).hexdigest(), dhash(blob))
    return sku, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skulist")
    ap.add_argument("--max-dist", type=int, default=5)
    ap.add_argument("--shop-id", default="72544")
    a = ap.parse_args()
    skus = [l.strip() for l in open(a.skulist, encoding="utf-8") if l.strip()]

    res = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sku, out in ex.map(lambda s: scan(s, a.shop_id), skus):
            res[sku] = out

    counts = collections.Counter(v[0] for d in res.values() for v in d.values())
    placeholder, hits = counts.most_common(1)[0]
    total = sum(len(d) for d in res.values())
    if hits < max(10, total // 4):
        sys.exit(f"MEGALLTAM: a leggyakoribb checksum csak {hits}x fordul elo {total} kepbol, "
                 "ez nem nez ki helykitoltonek. Nezd meg kezzel, mielott tovabbmesz.")
    print(f"helykitolto felismerve: {placeholder[:12]} ({hits} helyen)")

    real = {k: {s: v for s, v in d.items() if v[0] != placeholder} for k, d in res.items()}
    print(f"valodi kepek: {sum(len(v) for v in real.values())} / {len(skus)} termek")

    found = 0
    for sku, d in sorted(real.items()):
        slots = sorted(d)
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                x, y = d[slots[i]], d[slots[j]]
                dist = hamming(x[1], y[1])
                if dist <= a.max_dist:
                    kind = "BAJTAZONOS" if x[0] == y[0] else "csak szemre azonos"
                    print(f"  {sku}: {slots[i]} = {slots[j]}  (tavolsag {dist}, {kind})")
                    found += 1
    print(f"\nismetlodo par osszesen: {found}")


if __name__ == "__main__":
    main()
