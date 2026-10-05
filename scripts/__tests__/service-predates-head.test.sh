#!/usr/bin/env bash
# service_predates_head() a update.sh-ban (kartya 92ff79fc): a fuggvenyt KULON
# kinyerve teszteli (sed-del a definicio-blokkot), mert a teljes update.sh lefuttatasa
# npm/systemctl-muveleteket inditana. A PATH-ra egy VEZERELHETO hamis systemctl kerul,
# ami a SERVICE_PREDATES_HEAD_TS env-valtozobol olvassa az ActiveEnterTimestamp-ot --
# igy a teszt a VALODI git-repo HEAD commit-idejehez meri, nem egy kitalalt erteket
# masol a fuggvenybe.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
FAILS=0
DB=0

check() {  # check <nev> <feltetel-kimenet: 0=ok>
  DB=$((DB+1))
  if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1"; FAILS=$((FAILS+1)); fi
}

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/service-predates-head.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT

# Kinyeri a service_predates_head() definiciot update.sh-bol, es egy forrasozhato
# fajlba irja -- igy a teszt MINDIG a VALODI, eles fuggvenyt futtatja, nem egy
# kezzel masolt peldanyt.
FN_FILE="$SANDBOX/fn.sh"
sed -n '/^service_predates_head() {/,/^}/p' "$ROOT/update.sh" > "$FN_FILE"
if [ ! -s "$FN_FILE" ]; then
  echo "FAIL  service_predates_head fuggveny nem talalhato update.sh-ban (a kinyeres elromlott?)"
  exit 1
fi

REPO="$SANDBOX/repo"
mkdir -p "$REPO/.env.d"
git -C "$REPO" init -q . 2>/dev/null || { mkdir -p "$REPO"; git -C "$REPO" init -q .; }
echo "MAIN_AGENT_ID=teszt" > "$REPO/.env"
git -C "$REPO" add -A
git -C "$REPO" -c user.email=t@example.invalid -c user.name=teszt commit -qm init >/dev/null

FAKE_BIN="$SANDBOX/bin"
mkdir -p "$FAKE_BIN"

# Hamis systemctl: a "cat <unit>" letezest szimulalja (siker), a
# "show -p ActiveEnterTimestamp --value <unit>" a SERVICE_PREDATES_HEAD_TS
# kornyezeti valtozot adja vissza nyers szovegkent (mar systemd-formatumban).
cat > "$FAKE_BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
case "$*" in
  *"cat teszt-dashboard.service"*) exit 0 ;;
  *"show -p ActiveEnterTimestamp --value teszt-dashboard.service"*)
    printf '%s\n' "${SERVICE_PREDATES_HEAD_TS:-}"
    exit 0
    ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$FAKE_BIN/systemctl"

run_fn() {  # run_fn <INSTALL_DIR> -> exit code a service_predates_head()-bol
  (
    cd "$1" || exit 1
    export PATH="$FAKE_BIN:$PATH"
    export INSTALL_DIR="$1"
    # shellcheck source=/dev/null
    source "$FN_FILE"
    service_predates_head
  )
}

HEAD_EPOCH="$(git -C "$REPO" log -1 --format=%ct HEAD)"

# 1) A szolgaltatas a HEAD UTAN indult -> NEM elavult (exit != 0, mert a fuggveny
#    a "stale" esetben ad 0-t -- l. a "[ "$active_epoch" -lt "$head_epoch" ]" sort).
SERVICE_PREDATES_HEAD_TS="$(date -d "@$((HEAD_EPOCH + 3600))" '+%a %Y-%m-%d %H:%M:%S %Z')" \
  run_fn "$REPO"
RC=$?
check "szolgaltatas HEAD utan indult -> nem elavult" "$([ $RC -ne 0 ] && echo 0 || echo 1)"

# 2) A szolgaltatas a HEAD ELOTT indult (pont ez a mert eset, 92ff79fc) -> ELAVULT
#    (exit 0).
SERVICE_PREDATES_HEAD_TS="$(date -d "@$((HEAD_EPOCH - 3600))" '+%a %Y-%m-%d %H:%M:%S %Z')" \
  run_fn "$REPO"
RC=$?
check "szolgaltatas HEAD elott indult -> elavult" "$RC"

# 3) Nincs ActiveEnterTimestamp (pl. a szolgaltatas sosem futott) -> FAIL-OPEN,
#    a fuggveny NEM allitja elavultnak (exit != 0), mert nem tud merni.
SERVICE_PREDATES_HEAD_TS="" run_fn "$REPO"
RC=$?
check "nincs ActiveEnterTimestamp -> fail-open, nem elavult" "$([ $RC -ne 0 ] && echo 0 || echo 1)"

# 4) Az egyseg nem letezik (mas unit nevre fut a hamis systemctl "cat"-je) ->
#    FAIL-OPEN. Ehhez mas MAIN_AGENT_ID kell, hogy az unit-nev ne egyezzen.
REPO2="$SANDBOX/repo2"
mkdir -p "$REPO2"
git -C "$REPO2" init -q .
echo "MAIN_AGENT_ID=mas-nev" > "$REPO2/.env"
git -C "$REPO2" add -A
git -C "$REPO2" -c user.email=t@example.invalid -c user.name=teszt commit -qm init >/dev/null
run_fn "$REPO2"
RC=$?
check "ismeretlen egyseg -> fail-open, nem elavult" "$([ $RC -ne 0 ] && echo 0 || echo 1)"

echo "service-predates-head: $((DB-FAILS)) passed, $FAILS failed"
[ "$FAILS" -eq 0 ]
