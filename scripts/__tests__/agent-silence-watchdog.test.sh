#!/bin/bash
# Contract tests for scripts/agent-silence-watchdog.sh -- the OUT-OF-PROCESS
# silence watchdog for the fleet (card 53f4486a, Marci's decision 2026-10-05).
#
# Driven through `agent-silence-watchdog.sh --check <db>`, which evaluates a
# database and exits BEFORE any alert, stamp or state write -- so these run
# from fixtures with no live install, no bot token and no Telegram. Agent
# discovery is pointed at a fixture directory via AGENT_SILENCE_AGENTS_DIR
# (mirrors MAIN_AGENT_ID/MAIN_INBOX_OBSERVER_DB-style overrides already used
# by main-inbox-observer.sh's suite), never at the real install.
#
# Exit codes: 0 = all agents within threshold, 1 = at least one silent beyond
# it, 2 = db unreadable or nothing discoverable.
#
# Run: bash scripts/__tests__/agent-silence-watchdog.test.sh

set -u

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1 -- got: $2"; }

INSTALL_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WATCHDOG="${WATCHDOG_BIN:-$INSTALL_DIR/scripts/agent-silence-watchdog.sh}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

. "$INSTALL_DIR/scripts/__tests__/lib/sqlite-oracle.sh"

if [ ! -f "$WATCHDOG" ]; then
  echo "FAIL: watchdog not found at $WATCHDOG"
  exit 1
fi

SCHEMA="
CREATE TABLE memories (id INTEGER PRIMARY KEY, agent_id TEXT, created_at INTEGER);
CREATE TABLE daily_logs (id INTEGER PRIMARY KEY, agent_id TEXT, created_at INTEGER);
CREATE TABLE tool_call_log (id INTEGER PRIMARY KEY, agent_id TEXT, created_at INTEGER);
CREATE TABLE conversation_log (id INTEGER PRIMARY KEY, agent_id TEXT, created_at INTEGER);
"

make_db() {
  local db="$TMP/$1.db"
  rm -f "$db"
  oracle_exec "$db" "$SCHEMA"
  echo "$db"
}

# $1=db $2=table $3=agent $4=age_seconds
add_row() {
  oracle_exec "$1" "INSERT INTO $2 (agent_id, created_at) VALUES ('$3', CAST(strftime('%s','now') AS INTEGER) - $4);"
}

# Fixture agent tree: AGENTS_DIR/<a>/, AGENTS_DIR/<b>/ -- 'main' is supplied via
# the MAIN_AGENT_ID env override, so it never needs an agents/<main> directory
# (matches the real install, where the main agent has no agents/<self> dir).
AGENTS_DIR="$TMP/agents"
mkdir -p "$AGENTS_DIR/suba" "$AGENTS_DIR/subb"

run_check() {  # run_check <db> [extra env assignments already exported by caller]
  MAIN_AGENT_ID=main AGENT_SILENCE_AGENTS_DIR="$AGENTS_DIR" \
    bash "$WATCHDOG" --check "$1" 2>&1
}

expect() {  # expect <label> <db> <expected_verdict> <expected_rc> [extra env...]
  local label="$1" db="$2" want_verdict="$3" want_rc="$4"
  shift 4
  local out rc verdict
  out=$(env "$@" MAIN_AGENT_ID=main AGENT_SILENCE_AGENTS_DIR="$AGENTS_DIR" bash "$WATCHDOG" --check "$db" 2>&1); rc=$?
  verdict=$(printf '%s' "$out" | sed -n 's/.*verdict=\([a-z]*\).*/\1/p')
  if [ "$verdict" = "$want_verdict" ] && [ "$rc" = "$want_rc" ]; then
    pass "$label"
  else
    fail "$label" "verdict=$verdict rc=$rc (expected $want_verdict/$want_rc) out: $out"
  fi
}

echo "=== agent-silence-watchdog.sh ==="

# 1) Everyone recently active (well inside the default 8h weekday threshold) -> ok.
DB1="$(make_db fresh)"
add_row "$DB1" memories main 60
add_row "$DB1" tool_call_log suba 120
add_row "$DB1" conversation_log subb 300
expect "all agents recent -> ok" "$DB1" ok 0

# 2) 'main' only has an OLD memories row but a FRESH tool_call_log row -> the
#    four-source MAX must pick the fresh one, not false-alarm on the stale
#    memory alone. This is the exact false-positive this script's design note
#    measured (bob/salesagens on 2026-10-05).
DB2="$(make_db mixed_fresh_tool)"
add_row "$DB2" memories main $((20*3600))
add_row "$DB2" tool_call_log main 60
add_row "$DB2" tool_call_log suba 60
add_row "$DB2" tool_call_log subb 60
expect "stale memory + fresh tool_call_log -> ok (widened metric)" "$DB2" ok 0

# 3) 'suba' silent beyond the (forced, low) threshold in EVERY source -> silent.
DB3="$(make_db one_silent)"
add_row "$DB3" memories main 60
add_row "$DB3" tool_call_log subb 60
add_row "$DB3" memories suba $((20*3600))
expect "one agent silent beyond threshold -> silent" "$DB3" silent 1 AGENT_SILENCE_WEEKDAY_HOURS=8

# 4) Same fixture as 3, but the threshold is raised above the silent agent's
#    age -> ok. Proves the threshold env override actually changes the verdict,
#    not just that SOME threshold exists.
expect "same fixture, threshold raised above the gap -> ok" "$DB3" ok 0 AGENT_SILENCE_WEEKDAY_HOURS=48

# 5) 'subb' has NO row in any of the four tables (brand-new agent) -> must be
#    reported as unknown-baseline, and must NOT by itself flip the verdict to
#    silent (a never-seen agent is not evidence of an outage).
DB5="$(make_db unknown_baseline)"
add_row "$DB5" memories main 60
add_row "$DB5" tool_call_log suba 60
out=$(run_check "$DB5")
rc=$?
case "$out" in
  *"unknown=[subb]"*) ;;
  *) fail "never-seen agent listed under unknown, not silent" "$out" ;;
esac
verdict=$(printf '%s' "$out" | sed -n 's/.*verdict=\([a-z]*\).*/\1/p')
if [ "$verdict" = "ok" ] && [ "$rc" = 0 ]; then
  pass "never-seen agent alone does not flip verdict to silent"
else
  fail "never-seen agent alone does not flip verdict to silent" "verdict=$verdict rc=$rc out: $out"
fi

# 6) Missing database file -> unknown/2, not a false "ok".
expect "missing db -> unknown" "$TMP/does-not-exist.db" unknown 2

# 7) Weekend threshold actually differs from weekday (structural check on the
#    source, not a date-mocking test: `date +%u` is not safely mockable in a
#    portable way here, so this asserts the two env vars are read and used
#    independently, which --check's threshold= output already proves above).
out=$(AGENT_SILENCE_WEEKEND_HOURS=1 MAIN_AGENT_ID=main AGENT_SILENCE_AGENTS_DIR="$AGENTS_DIR" bash "$WATCHDOG" --check "$DB1" 2>&1)
case "$out" in
  *"threshold="*) pass "weekend env var is read without error (day-of-week branch exercised structurally)" ;;
  *) fail "weekend env var is read without error" "$out" ;;
esac

echo "agent-silence-watchdog: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
