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
#
# GIT RERERE (2026-09-02, kartya 82068a49): a repo-szintu .git/config-ban
# `rerere.enabled = true` van bekapcsolva (elotte nem volt beallitva sehol).
# Ez NEM automatizalja a rebase-t: a git rebase minden utkozesnel megall,
# rerere nélkül is, rerere-vel is -- csak azt teszi, hogy ha egy MAR EGYSZER
# kezzel feloldott utkozes-mintazat ujra elojon, a tartalmat automatikusan
# kitolti (nem hivja meg a git add-et vagy a --continue-t maganak). A
# .git/rr-cache alatt egy bejegyzes van (a src/web/agent-process.ts
# c21acf4-es utkozesenek feloldasa, unios minta, ugyanaz mint a tobbi mai
# ehhez hasonlo ütkozes). Visszavonas egy paranccsal: git config --unset
# rerere.enabled (a cache-bejegyzes ekkor is megmarad, de nem hasznalodik).
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
# MARVEEN_PROD_CHECKOUT_OK=1: a prod-tree-guard post-checkout hookja (2026-08-22
# ota el) minden agvaltast figyel, es levalasztott HEAD-en (git rev-parse
# --abbrev-ref HEAD == "HEAD", nem esik a develop|main|master case-orzobe)
# AUTOMATIKUSAN visszacsekkoutol developra. A git rebase belsoleg detached
# HEAD-re valt (checkout upstream/develop), a hook ezt szandekolatlan
# agvaltasnak nezi es kozbeszol -- MIKOZBEN a rebase indexe meg az
# upstream/develop-et varja, ebbol jott a "cannot rebase: Your index
# contains uncommitted changes" hiba. Mert 2026-09-02, reflog: 91f276e
# rebase(start)->2c61aee checkout(develop)->2c61aee rebase(abort), mind
# ugyanabban a masodpercben, plusz a hook sajat riasztasa (agent_messages
# 2538) szo szerint megerositi. A MARVEEN_PROD_CHECKOUT_OK=1 a hook sajat,
# szandekolt kijarata erre az esetre -- csak erre az egy hivasra korlatozva,
# nem a teljes szkriptre. Marci jovahagyta 2026-09-02.
if ! MARVEEN_PROD_CHECKOUT_OK=1 git rebase upstream/develop >/tmp/upstream-sync-rebase.log 2>&1; then
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
