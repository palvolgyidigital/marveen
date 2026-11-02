#!/usr/bin/env bash
# Card 9b6e4e6e, Part 2 -- fleet-memory-gate.sh --min-avail (absolute
# MemAvailable-MB mode for the schedule-runner pre-injection gate).
#
# Independent of the WARN/HARD used-pct bands: a single runaway child (today's
# root cause was a pd.read_excel python3 child, not an agent-count problem)
# can OOM the box even with few agents running and used_pct still looking
# fine, so this mode checks the ABSOLUTE free MB and never touches the
# safe-mode flag or the alert-cooldown state (it is meant to be polled far
# more often than the reconcile loop's --check/--verdict).
#
# MEMGATE_SCRIPT overrides the script under test; defaults to the repo copy.
#
# Run:  bash scripts/__tests__/memgate-min-avail.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GATE="${MEMGATE_SCRIPT:-$ROOT/scripts/fleet-memory-gate.sh}"
[ -x "$GATE" ] || { echo "FATAL: the script under test is missing or not executable: $GATE" >&2; exit 2; }

FAILS=0; DONE=0
check() { DONE=$((DONE+1)); if [ "$2" = "0" ]; then echo "PASS  $1"; else echo "FAIL  $1${3:+  -- $3}"; FAILS=$((FAILS+1)); fi; }

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/memgateminavail.XXXXXX")"
trap 'rm -rf "$SANDBOX"' EXIT
mkdir -p "$SANDBOX/store"

write_meminfo() { printf 'MemTotal:       16000000 kB\nMemAvailable:   %9d kB\n' "$1" > "$SANDBOX/meminfo"; }

run_gate() {
  rm -f "$SANDBOX/store/.fleet-safe-mode" "$SANDBOX/store/.fleet-memgate-alert"
  OUT="$(env MEMGATE_PROC_MEMINFO="$SANDBOX/meminfo" \
      MARVEEN_STORE="$SANDBOX/store" \
      MARVEEN_SCHED_MIN_AVAILABLE_MB="${TEST_THRESHOLD:-}" \
      MARVEEN_MEM_GATE_OBSERVE="${TEST_OBSERVE:-0}" \
      bash "$GATE" --min-avail 2>&1)"
  RC=$?
}

# 1. Below the default threshold (1536 MB) -> block (exit 10).
write_meminfo 976000   # 976000 kB / 1024 = 953 MB (integer division, same as the script's own)
TEST_THRESHOLD="" run_gate
check "below default threshold blocks (exit 10)" "$([ "$RC" = "10" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"
check "block message names avail and threshold" \
      "$(echo "$OUT" | grep -q 'block low-memory: avail=953MB threshold=1536MB' && echo 0 || echo 1)" "got: $OUT"

# 2. Above the default threshold -> allow (exit 0).
write_meminfo 5000000  # ~4882 MB
TEST_THRESHOLD="" run_gate
check "above default threshold allows (exit 0)" "$([ "$RC" = "0" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"
check "allow message names avail and threshold" \
      "$(echo "$OUT" | grep -q 'allow: avail=4882MB threshold=1536MB' && echo 0 || echo 1)" "got: $OUT"

# 3. MARVEEN_SCHED_MIN_AVAILABLE_MB overrides the default both ways.
write_meminfo 976000
TEST_THRESHOLD="500" run_gate
check "env override: 976MB avail clears a 500MB threshold (exit 0)" "$([ "$RC" = "0" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"
write_meminfo 5000000
TEST_THRESHOLD="8000" run_gate
check "env override: 4882MB avail fails an 8000MB threshold (exit 10)" "$([ "$RC" = "10" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"

# 4. Observe-only mode never blocks, even deep below threshold.
write_meminfo 10000
TEST_THRESHOLD="" TEST_OBSERVE="1" run_gate
check "observe-only mode allows even far below threshold" "$([ "$RC" = "0" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"
check "observe-only mode says so in its output" \
      "$(echo "$OUT" | grep -q 'observe-only' && echo 0 || echo 1)" "got: $OUT"

# 5. Side-effect free: unlike --check/--verdict, --min-avail must never write
#    the safe-mode flag or the alert-cooldown stamp, in either direction.
write_meminfo 10000   # deep into what would be a "hard" used-pct band too
TEST_THRESHOLD="" run_gate
check "--min-avail never writes the safe-mode flag (blocking case)" \
      "$([ ! -f "$SANDBOX/store/.fleet-safe-mode" ] && echo 0 || echo 1)" "flag was written"
check "--min-avail never writes the alert-cooldown stamp (blocking case)" \
      "$([ ! -f "$SANDBOX/store/.fleet-memgate-alert" ] && echo 0 || echo 1)" "stamp was written"

# 6. meminfo-unreadable fail-open still applies (shared code path, read before
#    the --min-avail dispatch): a missing/corrupt stub allows, same as --check.
OUT="$(env MEMGATE_PROC_MEMINFO="$SANDBOX/does-not-exist" MARVEEN_STORE="$SANDBOX/store" bash "$GATE" --min-avail 2>&1)"
RC=$?
check "unreadable meminfo fails open (exit 0)" "$([ "$RC" = "0" ] && echo 0 || echo 1)" "rc=$RC out=$OUT"

echo
echo "$((DONE-FAILS))/$DONE passed  (script under test: $GATE)"
[ "$FAILS" = "0" ] || exit 1
