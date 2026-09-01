#!/bin/bash
# Napi upstream-szinkron: behuzza az eredeti projekt (upstream) valtozasait,
# rauljteti a sajat PDB-commitjainkat, es feltolti a forkra (origin).
#
# Miert kell: ezen a gepen nincs iras-jog az eredeti repohoz, ezert a sajat
# javitasaink a fork develop again elnek. Az update.sh az origin-t (fork) huzza,
# tehat az upstream valtozasai CSAK ezen a lepesen keresztul jutnak el hozzank.
#
# Biztonsag: ha a rebase utkozik, MEGALL es NEM tol fel semmit -- a develop
# valtozatlan marad, az ejszakai update tovabbra is a jelenlegi (mukodo)
# allapotot huzza. Az utkozest embernek kell feloldania.
set -u
cd /home/pdb/marveen || exit 1
export GIT_SSH_COMMAND="ssh -i /home/pdb/.ssh/id_ed25519_marveen -o IdentitiesOnly=yes"

fail() { echo "UPSTREAM-SYNC HIBA: $1"; exit 1; }

[ -z "$(git status --porcelain --untracked-files=no | grep -vE ' HEARTBEAT\.md$')" ] \
  || fail "a working tree modositott allapotban van, nem nyulok hozza. Nezd meg: git status"

BEFORE=$(git rev-parse HEAD)
git fetch upstream develop --quiet || fail "nem sikerult letolteni az upstreamet (halozat?)"

NEW=$(git rev-list --count HEAD..upstream/develop)
if [ "$NEW" -eq 0 ]; then
  echo "UPSTREAM-SYNC: nincs uj upstream commit, nincs teendo."
  exit 0
fi

# HEARTBEAT.md-t a fo agens irja at minden heartbeat tick-nel (self-modifying,
# lasd update-preflight.ts). A fenti dirty-ellenorzes ezert kihagyja -- DE a
# git rebase (szemben a sima git pull --ff-only-lyal, amit az update.sh hasznal
# ugyanerre a fajlra) NEM turi a piszkos indexet, es ha a fajl eppen STAGED
# modositott allapotban van a script inditasakor, ez pontosan a "cannot
# rebase: Your index contains uncommitted changes" hibat adja (mert
# 2026-09-01, scratch-fan reprodukalva, byte-ra egyezo uzenettel). A rebase
# elott felretesszuk, utana visszatesszuk -- ha a visszatetel utkozik,
# eldobjuk: adatvesztes nem szamit, a fajlt ugyis felulirja a legkozelebbi
# heartbeat tick.
HEARTBEAT_STASHED=0
if [ -n "$(git status --porcelain --untracked-files=no -- HEARTBEAT.md)" ]; then
  git stash push -- HEARTBEAT.md >/dev/null 2>&1 && HEARTBEAT_STASHED=1
fi
restore_heartbeat() {
  [ "$HEARTBEAT_STASHED" -eq 1 ] || return 0
  if ! git stash pop >/dev/null 2>&1; then
    git stash drop >/dev/null 2>&1
    echo "UPSTREAM-SYNC: FIGYELEM -- a HEARTBEAT.md ideiglenes stash-e utkozott visszaallitaskor, eldobva (a fajlt ugyis felulirja a kovetkezo heartbeat tick)."
  fi
}

echo "UPSTREAM-SYNC: $NEW uj upstream commit, rebase indul."
if ! git rebase upstream/develop >/tmp/upstream-sync-rebase.log 2>&1; then
  git rebase --abort 2>/dev/null
  restore_heartbeat
  fail "REBASE UTKOZES $NEW commitnal. A develop valtozatlan ($BEFORE). Kezi feloldas kell. Reszletek: /tmp/upstream-sync-rebase.log"
fi
restore_heartbeat

if ! npm run build >/tmp/upstream-sync-build.log 2>&1; then
  git reset --hard "$BEFORE" >/dev/null 2>&1
  fail "a rebase utani BUILD elbukott, visszaalltam a korabbi allapotra ($BEFORE). Reszletek: /tmp/upstream-sync-build.log"
fi

# A rebase ATIRJA a sajat commitjaink hash-eit, ezert a fork develop aga mindig divergal a helyitol.
# Sima push ezert SOHA nem tud sikerulni, amint az upstream elore megy (2026-08-25-en elesben ez tortent).
# --force-with-lease: csak akkor ir felul, ha az origin pontosan ott all, ahol a legutobbi fetch-nel lattuk.
# Ha kozben barki mas pusholt, ELUTASIT ahelyett hogy elgazolna. Sima --force-ot NE hasznalj itt.
git push --force-with-lease origin develop --quiet || fail "a push a forkra nem sikerult (--force-with-lease elutasitva: valaki mas pusholt az origin/develop-ra a legutobbi fetch ota?). A helyi develop mar rebase-elt allapotban van ($(git rev-parse --short HEAD)). NE eross force-old, eloszor nezd meg mi van az originon."

echo "UPSTREAM-SYNC OK: $NEW upstream commit behuzva, sajat javitasok a tetejen, forkra feltoltve. $(git rev-parse --short "$BEFORE") -> $(git rev-parse --short HEAD)"
git log --oneline "$BEFORE".."$(git rev-parse HEAD)" | head -20
