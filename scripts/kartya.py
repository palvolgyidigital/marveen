#!/usr/bin/env python3
"""Egy kanban-kartya TELJES allapota: cim, leiras ES a legutobbi kommentek, egyben.

MIERT LETEZIK, ES MIERT KOTELEZO EZT HASZNALNI a nyers SQL helyett:
2026-09-02-an ot alkalommal allitottam vagy kerdeztem olyat, aminek a valasza mar le volt
irva nalunk. Bob lemerte az oteset, es kiderult, hogy NEGY nem "hianyzo tudas" volt, hanem
"mar lezart dolgot ujra elovettem". Ezek kozul HARMAT ugyanaz okozott: a kartya LEIRASAT
olvastam el, a KOMMENTEKET nem, es a helyesbites a kommentekben allt.
  - 40ef3d92: a leiras szerint "Marcira var", holott o 08-19-en mar dontott. A dontes kommentben.
  - c6b6f224: a leiras a legerosebb ervet tartalmazta, amit 08-31-en mar helyesbitettem. Kommentben.
  - a895c9d0: a leiras maga mondta ki a valaszt, csak a cimbol es a statuszbol dolgoztam.

Ez NEM archivum-szintu hasonlosag-kereses kerdese (arra nincs olcso megoldas). Ez annyi,
hogy egy dokumentumnak ket retege van, es en az egyiket olvastam. Ezert a helyes valasz nem
egy okos szuro, hanem az, hogy a ket reteget SOSEM lehet kulon lekerni.

A MASODIK CSAPDA, AMI EBBE A SZKRIPTBE IS BELEFER (2026-09-02 delutan, Marci szolt ram):
ezt a szkriptet HASZNALTAM, es MEGIS ujra feltettem egy kerdest, amit o reggel mar eldontott.
Az ok: az in_progress kartyak atnezesekor a kimenetet `--kommentek 1 | head -14`-gyel csonkoltam,
tehat CSAK a leiras elejet lattam -- es a leiras meg a dontes ELOTTI allapotot irta le.
A ket reteg egyben-lekerdezese NEM VED MEG, ha a sajat kimenetemet levagom. Ugyanaz a hibaosztaly,
mint a csonkolt keresesbol szuletett hamis "nincs talalat".
SZABALY: ha egy kartyabol DONTEST vagy ALLAPOTOT idezel (nem csak a cimet ellenorzod),
a kimenetet NE csonkold. head/tail csak akkor, ha pusztan azt nezed, letezik-e a kartya.

Hasznalat:
    python3 scripts/kartya.py 40ef3d92
    python3 scripts/kartya.py 40ef3d92 --kommentek 10
"""
import re, sqlite3, sys

DB = '/home/pdb/marveen/store/claudeclaw.db'

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    azon = sys.argv[1]
    n = 5
    if '--kommentek' in sys.argv:
        i = sys.argv.index('--kommentek') + 1
        if i >= len(sys.argv) or not sys.argv[i].lstrip('+').isdigit() or int(sys.argv[i]) < 1:
            print("hasznalat: --kommentek <pozitiv egesz szam>")
            return 2
        n = int(sys.argv[i])
    c = sqlite3.connect(DB).cursor()
    c.execute("""SELECT id,title,status,priority,assignee,project,due_date,
                 COALESCE(description,''),datetime(updated_at,'unixepoch','localtime')
                 FROM kanban_cards WHERE id LIKE ?""", (azon + '%',))
    sorok = c.fetchall()
    if not sorok:
        print(f"nincs ilyen kartya: {azon}")
        return 1
    if len(sorok) > 1:
        print(f"tobb kartya illeszkedik ({len(sorok)}), pontositsd:")
        for r in sorok:
            print(f"  {r[0][:8]} {r[1][:60]}")
        return 1
    cid, cim, st, pri, ass, proj, due, leiras, upd = sorok[0]
    print(f"=== {cid[:8]} | {st} | {pri} | {ass or 'NINCS GAZDA'}"
          + (f" | projekt: {proj}" if proj else "")
          + (f" | hatarido: {due}" if due else ""))
    print(f"=== {cim}")
    print(f"=== utolso mozgas: {upd}\n")
    print("--- LEIRAS (allapot-reteg) ---")
    print(leiras.strip() or "(ures)")

    c.execute("""SELECT author,content,datetime(created_at,'unixepoch','localtime')
                 FROM kanban_comments WHERE card_id=? ORDER BY created_at DESC LIMIT ?""", (cid, n))
    kom = c.fetchall()
    print(f"\n--- UTOLSO {len(kom)} KOMMENT (naplo-reteg), a legfrissebb elol ---")
    if not kom:
        print("(nincs komment)")
    # A CSEND-jelolo keresese SOSEM fugghet a megjelenitesi limittol: ha a jelolo utan
    # n-nel tobb komment gyulik ossze, a figyelmeztetes csendben eltunt volna a kimenetbol.
    # Ezert kulon, KORLATLAN lekerdezes fut MINDEN kommentre es a leirasra. (Bob, 2026-09-02)
    csend = None
    c.execute("SELECT content FROM kanban_comments WHERE card_id=?", (cid,))
    for (tartalom,) in list(c.fetchall()) + [(leiras,)]:
        for m in re.finditer(r'CSEND-(\d{4}-\d{2}-\d{2})', tartalom or ''):
            if csend is None or m.group(1) > csend:
                csend = m.group(1)
    for szerzo, tartalom, mikor in kom:
        print(f"\n[{mikor}] {szerzo}:")
        print(tartalom.strip()[:1200])
    if csend:
        print(f"\n*** CSEND-{csend}: erre a kartyara NE keruljon audit-komment eddig a datumig. ***")
    print("\n*** Ha a leiras es egy komment ellentmond, a KOMMENT nyer: az ujabb. ***")
    return 0

if __name__ == '__main__':
    sys.exit(main())
