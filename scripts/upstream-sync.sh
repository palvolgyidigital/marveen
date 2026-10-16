#!/bin/bash
# Napi upstream-szinkron: behuzza az eredeti projekt (upstream) valtozasait,
# rauljteti a sajat PDB-commitjainkat, es feltolti a forkra (origin).
#
# Miert kell: ezen a gepen nincs iras-jog az eredeti repohoz, ezert a sajat
# javitasaink a fork develop again elnek. Az update.sh az origin-t (fork) huzza,
# tehat az upstream valtozasai CSAK ezen a lepesen keresztul jutnak el hozzank.
#
# ARCHITEKTURA (2026-10-16, kartya 52ac3a11, lezarja amit a 82068a49 igert de
# nem valositott meg -- mert ez utobbi grep -c worktree scripts/upstream-sync.sh
# = 0-t adott, holott a kartya done statuszban allt):
#
# A rebase ALLANDO, HOME alatti worktree-ben fut, SOHA nem az elo checkoutban.
# Ennek oka heteken at mert tenyeken all (Pedro naplozott merese, 10-08 ota
# minden ejszaka): az elo checkouton allando munkakor kozben (David-jogadas,
# CRM-munka, elo kapu-javitasok, utemezett feladatbol hivott szkriptek) mindig
# van modositott vagy nyomkovetetlen allomany, es ennek jelentos resze TENYLEG
# elo viselkedes (pl. garancia-levelek-gezanak.py-t negyedoranta fut egy
# utemezett feladat) -- egy stash ott nem semleges parkolas, hanem futo
# viselkedes nema visszavonasa. A worktree ezt a kerdest szerkezetileg
# szunteti meg: a szinkron soha nem olvassa es nem irja az elo checkout
# munkakonyvtarat/indexet a rebase+build+push alatt, csak a megosztott .git
# objektum-adatbazist (fetch/push), amihez a piszkos elo fa irrelevans.
#
# A worktree A REPON KIVUL, HOME alatt all (nem /tmp -- a WSL-ujrainditas
# torli -- es nem a repo ala, mert ott a sajat git status-unkban jelenne meg,
# es onmagunk lennenk az uj blokkolo, ahogy a .bak-fajloknal mar megtortent,
# kartya 5001879, 2026-09-22). A worktree ALLANDO, nem egyszer-hasznalatos:
# igy a node_modules nem torlodik minden korben, csak akkor kell npm ci, ha a
# package-lock.json valtozott a rebase soran.
#
# A WORKTREE-N A PROD-TREE-GUARD NEM ERVENYES (install-prod-tree-guard-hook.sh
# sajat dokumentacioja szerint: "Two git hooks, both scoped to the MAIN
# worktree only (linked worktrees have a different toplevel and pass
# untouched)"). A regi szkript MARVEEN_PROD_CHECKOUT_OK=1 korulirasa ezert
# itt feleslegesse valt -- csak a regi, elo-checkoutos valtozatnal kellett,
# mert ott TOPLEVEL == PROD_ROOT volt a rebase belso detached-HEAD lepesenel.
# Meresi bizonyitek a scratch-sandboxban: lasd a kartya lezaro kommentjet.
#
# A PUSH UTAN AZ ELO CHECKOUT UTOLERESE KULON LEPES, es ez uj a regi
# szkripthez kepest: a rebase UJRAIRJA a sajat commitjaink hash-jet, tehat az
# elo checkout local develop aga a push UTAN MAR NEM os-oldala (ancestor) az
# uj origin/develop-nek -- egy sima `git pull --ff-only` (amit az update.sh
# hasznal) ELUTASITANA ezt nem-fast-forward allapotkent. A tartalom viszont
# NEM veszik el: a sajat commitjaink tartalmilag MAR benne vannak az uj
# origin/develop-ban (ugyanaz a rebase vitte at oket), csak regi hash-szel --
# tehat az elo checkout local develop aganak hard-reset-elese az uj
# origin/develop-re BIZTONSAGOS, semmilyen tartalom nem veszik el. A piszkos/
# nyomkovetetlen allapotot ez nem erintheti: stash elotte (mindent, nem csak
# a HEARTBEAT.md-t, lasd update.sh sajat altalanos auto-stash mintaja), pop
# utana. Ha a pop utkozik, a stash NEM veszik el (nincs drop), csak jelzes
# megy es kezi feloldas kell -- ugyanaz a "ha utkozik, megall, nem dob el
# semmit" elv, mint a rebase+push lepesnel.
#
# Biztonsag: ha a rebase a worktree-ben utkozik, MEGALL es NEM tol fel semmit
# -- az origin/develop valtozatlan marad, az ejszakai update tovabbra is a
# jelenlegi (mukodo) allapotot huzza, es az ELO CHECKOUTHOZ A SZKRIPT EKKOR
# MEG HOZZA SEM NYULT (a live-checkout utoleres csak sikeres push utan fut).
# Az utkozest embernek kell feloldania, a worktree-ben (ami erintetlen
# allapotban marad, a rebase meg folyamatban all).
#
# GIT RERERE (2026-09-02, kartya 82068a49): a repo-szintu .git/config-ban
# `rerere.enabled = true` van bekapcsolva. Ez NEM automatizalja a rebase-t:
# minden utkozesnel megall, csak egy mar egyszer kezzel feloldott mintat tolt
# ki ujra automatikusan. A worktree ugyanazt a megosztott .git-et hasznalja,
# tehat a rr-cache-t is oroklji.
set -u

REPO="${UPSTREAM_SYNC_REPO:-/home/pdb/marveen}"
WORKTREE="${UPSTREAM_SYNC_WORKTREE:-$HOME/upstream-sync-worktree}"
WORK_BRANCH="upstream-sync-work"

cd "$REPO" || exit 1
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i /home/pdb/.ssh/id_ed25519_marveen -o IdentitiesOnly=yes}"

fail() { echo "UPSTREAM-SYNC HIBA: $1"; exit 1; }

# 1. A worktree letrehozasa, ha meg nem letezik (elso futas). Allando, tehat
#    ezutan mar csak ujrahasznaljuk.
if [ ! -e "$WORKTREE/.git" ]; then
  # Ha a worktree KONYVTARAT kezzel torolte valaki, a git metadata (.git/worktrees/)
  # megmarad, es a `worktree add` "already used by worktree at ..." hibara fut. A prune
  # pontosan ezeket a hianyzo bejegyzeseket szedi ki, a letezoket nem erinti.
  git worktree prune --quiet 2>/dev/null
  git fetch origin develop --quiet || fail "nem sikerult letolteni az origin-t az elso worktree-letrehozashoz"
  git worktree add -B "$WORK_BRANCH" "$WORKTREE" origin/develop --quiet \
    || fail "nem sikerult letrehozni a worktree-t ($WORKTREE)"
  echo "UPSTREAM-SYNC: uj worktree letrehozva ($WORKTREE)."
fi

cd "$WORKTREE" || fail "a worktree konyvtar nem elerheto ($WORKTREE)"

# 2. A munka-ag resetelese friss origin/develop-re. A worktree eldobhato
#    allapotu a SAJAT agan (nem a live checkouton): egy korabbi, felbeszakadt
#    fuggo allapotot (pl. elozo futasbol maradt rebase) ez nem old fel
#    automatikusan -- ha fuggo rebase van, a checkout -B elutasit, es ez
#    szandekos (lasd lejjebb a kezi feloldas megjegyzest).
if [ -e "$WORKTREE/.git" ] && { [ -d "$(git rev-parse --git-dir)/rebase-merge" ] || [ -d "$(git rev-parse --git-dir)/rebase-apply" ]; }; then
  fail "a worktree-ben FUGGO REBASE all (elozo futasbol). Kezi feloldas kell a worktree-ben ($WORKTREE): git -C $WORKTREE rebase --abort, vagy oldd fel az utkozest."
fi

git fetch origin develop --quiet || fail "nem sikerult letolteni az origin-t a worktree-ben"
git checkout -B "$WORK_BRANCH" origin/develop --quiet || fail "nem sikerult resetelni a worktree munka-agat origin/develop-re"

BEFORE=$(git rev-parse HEAD)
git fetch upstream develop --quiet || fail "nem sikerult letolteni az upstreamet (halozat?)"

NEW=$(git rev-list --count HEAD..upstream/develop)
if [ "$NEW" -eq 0 ]; then
  echo "UPSTREAM-SYNC: nincs uj upstream commit, nincs teendo."
  exit 0
fi

echo "UPSTREAM-SYNC: $NEW uj upstream commit, rebase indul (worktree: $WORKTREE)."
if ! git rebase upstream/develop >/tmp/upstream-sync-rebase.log 2>&1; then
  git rebase --abort 2>/dev/null
  fail "REBASE UTKOZES $NEW commitnal. Az origin/develop valtozatlan ($BEFORE). Az ELO CHECKOUTHOZ a szkript meg hozza sem nyult. A worktree ($WORKTREE) erintetlen allapotban maradt kezi feloldasra. Reszletek: /tmp/upstream-sync-rebase.log"
fi

# node_modules: a worktree ALLANDO, nem torlodik -- csak akkor kell
# npm ci, ha a package-lock.json valtozott a rebase soran.
if ! git diff --quiet "$BEFORE" HEAD -- package-lock.json 2>/dev/null; then
  echo "UPSTREAM-SYNC: package-lock.json valtozott, npm ci fut."
  if ! npm ci >/tmp/upstream-sync-npm.log 2>&1; then
    git reset --hard "$BEFORE" >/dev/null 2>&1
    fail "npm ci elbukott a fuggoseg-valtozas utan, a worktree visszaallitva ($BEFORE). Az ELO CHECKOUTHOZ a szkript hozza sem nyult. Reszletek: /tmp/upstream-sync-npm.log"
  fi
fi

if ! npm run build >/tmp/upstream-sync-build.log 2>&1; then
  git reset --hard "$BEFORE" >/dev/null 2>&1
  fail "a rebase utani BUILD elbukott, a worktree visszaallitva ($BEFORE). Az ELO CHECKOUTHOZ a szkript hozza sem nyult. Reszletek: /tmp/upstream-sync-build.log"
fi

# A rebase ATIRJA a sajat commitjaink hash-eit, ezert a fork develop aga mindig divergal a helyitol.
# Sima push ezert SOHA nem tud sikerulni, amint az upstream elore megy.
# --force-with-lease: csak akkor ir felul, ha az origin pontosan ott all, ahol a legutobbi fetch-nel lattuk.
git push --force-with-lease origin "$WORK_BRANCH":develop --quiet \
  || fail "a push a forkra nem sikerult (--force-with-lease elutasitva: valaki mas pusholt az origin/develop-ra a legutobbi fetch ota?). A worktree mar rebase-elt allapotban van ($(git rev-parse --short HEAD)), erintetlen, ujraprobalhato. Az ELO CHECKOUTHOZ a szkript hozza sem nyult."

AFTER=$(git rev-parse HEAD)
echo "UPSTREAM-SYNC OK: $NEW upstream commit behuzva, sajat javitasok a tetejen, forkra feltoltve. $(git rev-parse --short "$BEFORE") -> $(git rev-parse --short "$AFTER")"
git log --oneline "$BEFORE".."$AFTER" | head -20

# 3. AZ ELO CHECKOUT UTOLERESE. Lasd a fejlec-magyarazatot: a sajat
#    commitjaink hash-e megvaltozott, tehat ez nem fast-forward az elo
#    checkout szemszogebol -- hard-reset kell, nem pull. A tartalom nem
#    veszik el (ugyanaz a rebase mar atvitte), csak a regi hash-azonossag.
#    A piszkos/nyomkovetetlen allapotot stash orzi meg a reset korul.
cd "$REPO" || fail "nem sikerult visszaterni az elo checkoutba az utoleres lepeshez (a push mar sikerult, origin/develop frissult -- a kovetkezo update.sh kor ezt ugyis felveszi)"

git fetch origin develop --quiet || {
  echo "UPSTREAM-SYNC FIGYELEM: az elo checkout nem tudta leszedni az uj origin/develop-ot. A push sikeres volt, a kovetkezo update.sh kor felveszi."
  exit 0
}

# AZ UTOLERES ELOTT A BRANCHET MEG KELL MERNI, NEM FELTENNI (Pedro kikotese a
# commit elott). A lenti `git reset --hard origin/develop` a MOST CHECKOUTOLT agat
# mozgatja. A tartalom-nem-veszik-el erveles KIZAROLAG a develop-ra all: azokat a
# commitokat vitte at a rebase. Ha az elo checkout kozben egy feature-agon vagy
# detached HEAD-en all, a hard-reset annak a sajat commitjait DOBNA EL. Ilyenkor az
# utoleres kimarad: a push mar sikerult, es a kovetkezo update.sh kor (vagy egy ember)
# elvegzi, amikor a develop van kint.
LIVE_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ "$LIVE_BRANCH" != "develop" ]; then
  echo "UPSTREAM-SYNC FIGYELEM: az elo checkout nem a develop agon all (most: ${LIVE_BRANCH:-detached HEAD}), ezert az utoleres KIMARAD -- egy hard-reset itt idegen ag commitjait dobna el. A push sikeres volt, origin/develop friss."
  exit 0
fi

LIVE_DIRTY=0
if [ -n "$(git status --porcelain)" ]; then
  LIVE_DIRTY=1
  if ! git stash push --include-untracked -m "upstream-sync-auto-$(date +%Y%m%d-%H%M%S)" >/tmp/upstream-sync-live-stash.log 2>&1; then
    echo "UPSTREAM-SYNC FIGYELEM: az elo checkout piszkos allapotanak stash-elese nem sikerult, az elo-ag utoleret ezert kihagyva. A push sikeres volt, a kovetkezo update.sh kor megprobalja (vagy elutasitja nem-fast-forwardkent, ha a fa meg mindig piszkos -- akkor kezi beavatkozas kell)."
    exit 0
  fi
fi

if ! git reset --hard origin/develop >/tmp/upstream-sync-live-reset.log 2>&1; then
  echo "UPSTREAM-SYNC FIGYELEM: az elo checkout branch-mutatojanak frissitese nem sikerult. A push sikeres volt, a kovetkezo update.sh kor megprobalja."
  if [ "$LIVE_DIRTY" -eq 1 ]; then
    git stash pop >/tmp/upstream-sync-live-stash-pop.log 2>&1 || echo "UPSTREAM-SYNC FIGYELEM: a reset-hiba utani stash-visszaallitas is utkozott, a stash NEM lett eldobva (git stash list), kezi feloldas kell."
  fi
  exit 0
fi

if [ "$LIVE_DIRTY" -eq 1 ]; then
  if ! git stash pop >/tmp/upstream-sync-live-stash-pop.log 2>&1; then
    echo "UPSTREAM-SYNC FIGYELEM: az elo checkout korabbi piszkos allapota utkozott a visszaallitaskor. A stash NEM lett eldobva (git stash list), kezi feloldas kell. Reszletek: /tmp/upstream-sync-live-stash-pop.log"
  fi
fi

echo "UPSTREAM-SYNC: az elo checkout utolerte origin/develop-ot ($(git rev-parse --short HEAD)), piszkos allapot megorizve."

