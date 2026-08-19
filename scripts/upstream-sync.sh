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

echo "UPSTREAM-SYNC: $NEW uj upstream commit, rebase indul."
if ! git rebase upstream/develop >/tmp/upstream-sync-rebase.log 2>&1; then
  git rebase --abort 2>/dev/null
  fail "REBASE UTKOZES $NEW commitnal. A develop valtozatlan ($BEFORE). Kezi feloldas kell. Reszletek: /tmp/upstream-sync-rebase.log"
fi

if ! npm run build >/tmp/upstream-sync-build.log 2>&1; then
  git reset --hard "$BEFORE" >/dev/null 2>&1
  fail "a rebase utani BUILD elbukott, visszaalltam a korabbi allapotra ($BEFORE). Reszletek: /tmp/upstream-sync-build.log"
fi

git push origin develop --quiet || fail "a push a forkra nem sikerult, a helyi develop mar rebase-elt allapotban van ($(git rev-parse --short HEAD))"

echo "UPSTREAM-SYNC OK: $NEW upstream commit behuzva, sajat javitasok a tetejen, forkra feltoltve. $(git rev-parse --short "$BEFORE") -> $(git rev-parse --short HEAD)"
git log --oneline "$BEFORE".."$(git rev-parse HEAD)" | head -20
