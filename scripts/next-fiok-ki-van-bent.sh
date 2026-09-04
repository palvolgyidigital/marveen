#!/bin/bash
# Ki hasznalja EPP MOST a kozos Next-fiokot?
#
# MIERT LETEZIK: 2026-08-31-en bizonyitottuk (memoria 826), hogy ket agens
# parhuzamos sessionje a kozos Next-fiokon elrontja a masodikat -- a navigacio
# elhasal, es a talalatok hamis "NOT FOUND"-kent jonnek vissza.
#
# KET BUKTATO, mindkettobe beleestem elsore:
# 1. A puszta "hany chromium fut" szamlalas HASZNALHATATLAN: a bejelento SAJAT,
#    epp indult sessionje is beleszamit, tehat magara mondja, hogy varjon.
#    Elesben ez tortent: Anna bejelentkezett, en megszamoltam 6 folyamatot, es
#    megvarakoztattam ot -- sajat magara.
# 2. A /proc/<pid>/stat 4. mezoje NEM megbizhatoan a PPID, mert a 2. mezo
#    (a parancs neve) zarojelben van es tartalmazhat szokozt. Hasznald a ps-t.
#
# HASZNALAT:
#   bash scripts/next-fiok-ki-van-bent.sh            # ki van bent
#   bash scripts/next-fiok-ki-van-bent.sh --self anna # a sajat sessionodet kihagyja
#
# AZ AGENSEK EZT MAGUK FUTTASSAK BELEPES ELOTT, --self <sajat nev>-vel.
# Ne a fo agens visszaigazolasara varjanak: az inter-agent uzenet aszinkron es
# lassu, tehat mire a valasz odaer, a script mar lefutott. Egy bejelentes, amit
# azonnali cselekves kovet, NEM kezfogas. A helyi, szinkron ellenorzes az.
# (2026-08-31, Anna jelezte: a "varj meg" uzenetem azutan ert oda, hogy o mar
# lefuttatta a sajat scriptjeit.)

SELF=""
if [ "$1" = "--self" ] && [ -n "$2" ]; then SELF="$2"; fi

for pid in $(pgrep -f "chrome-linux64|chrome-headless-shell|xvfb-run" 2>/dev/null); do
  p=$pid
  for _ in 1 2 3 4 5 6 7 8; do
    { [ -z "$p" ] || [ "$p" = "1" ] || [ "$p" = "0" ]; } && break
    cmd=$(tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null)
    a=$(printf '%s' "$cmd" | grep -oE "agents-[a-z]+|agents/[a-z]+" | head -1 | grep -oE "[a-z]+$")
    if [ -n "$a" ]; then
      [ "$a" = "$SELF" ] || echo "$a"
      break
    fi
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
done | sort -u > /tmp/.next-users.$$

# FIGYELEM: a `pgrep -c` nulla talalatnal KIIRJA a 0-t ES nem-nulla kilepesi koddal ter
# vissza, tehat a `|| echo 0` egy MASODIK nullat fuz hozza -> "0\n0" -> `[: integer expected`.
# Ezert soronkent szamolunk, nem a -c kapcsoloval.
n=$(pgrep -f "chrome-linux64|chrome-headless-shell|xvfb-run" 2>/dev/null | wc -l | tr -d " ")
[ -z "$n" ] && n=0
echo "=== Ki van bent a kozos Next-fiokon ==="
if [ -s /tmp/.next-users.$$ ]; then
  while read -r a; do echo "  AGENS: $a"; done < /tmp/.next-users.$$
  echo "  (osszesen $n bongeszo-folyamat)"
  echo
  echo "MAS VAN BENT -> NE LEPJ BE. Varj, amig a lista ures."
elif [ "$n" -gt 0 ]; then
  echo "  $n folyamat fut, de egyik sem agens-mappabol -- valoszinuleg pedro sajat futtatasa"
else
  echo "  senki, a fiok SZABAD -> mehetsz"
fi
rm -f /tmp/.next-users.$$
