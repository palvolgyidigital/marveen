#!/bin/bash
# Contract tests for the agent-silence watchdog's INSTALLATION (cards
# 24c7aaa5/4a2d243f -- the watchdog itself, scripts/agent-silence-watchdog.sh
# and its scripts/systemd/*.service/.timer templates, is card 53f4486a and
# was merged on its own; nothing installed it on either a fresh host
# (install-linux.sh) or an existing one (update.sh), so it shipped and never
# ran). Modeled closely on main-inbox-observer-install.test.sh, minus the
# macOS/launchd path: this watchdog has no launchd counterpart, and the two
# cards name update.sh and install-linux.sh specifically.
#
# Run: bash scripts/__tests__/agent-silence-watchdog-install.test.sh
#
# Hermetic: update.sh's function is extracted and run against a throwaway
# units dir with `systemctl` and `uname` stubs on PATH, so nothing on this
# machine is enabled, loaded or written outside the temp dir.

set -u

PASS=0; FAIL=0
pass() { PASS=$((PASS + 1)); echo "  PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "  FAIL: $1"; }
assert_eq() { if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected '$2', got '$3')"; fi; }
assert_contains() { case "$2" in *"$3"*) pass "$1" ;; *) fail "$1 (missing '$3')" ;; esac; }
assert_not_contains() { case "$2" in *"$3"*) fail "$1 (unexpected '$3')" ;; *) pass "$1" ;; esac; }

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ---------------------------------------------------------------------------
# 1. install-linux.sh -- the systemd pair on a fresh host. Grep-level: the
#    installer is not runnable here, but "written but never enabled" is
#    exactly the bug under test, so the enable list is asserted separately.
# ---------------------------------------------------------------------------
echo "install-linux.sh"
LINUX="$(cat "$REPO/install-linux.sh")"
assert_contains "writes the watchdog .service unit" "$LINUX" 'cat >"$SYSTEMD_DIR/${SILENCE_WATCHDOG_UNIT}.service"'
assert_contains "writes the watchdog .timer unit" "$LINUX" 'cat >"$SYSTEMD_DIR/${SILENCE_WATCHDOG_UNIT}.timer"'
assert_contains "ExecStart points at the watchdog" "$LINUX" 'ExecStart=$INSTALL_DIR/scripts/agent-silence-watchdog.sh'

ENABLE_LINE="$(grep -n 'systemctl --user enable "\${DASH_UNIT}"' "$REPO/install-linux.sh" | head -1)"
assert_contains "the watchdog timer is in the enable list" "$ENABLE_LINE" '${SILENCE_WATCHDOG_UNIT}.timer'

FIX_LINES="$(grep 'DIM}    ' "$REPO/install-linux.sh")"
assert_contains "the manual-fix hint names the watchdog timer too" "$FIX_LINES" '${SILENCE_WATCHDOG_UNIT}.timer'

START_LINE="$(grep -n 'for tmr in "\${KEEPALIVE_UNIT}' "$REPO/install-linux.sh" | head -1)"
assert_contains "the post-install timer-start loop covers the watchdog too (TIMERSTART1011)" \
  "$START_LINE" '${SILENCE_WATCHDOG_UNIT}.timer'

SW_SVC_BLOCK="$(awk '/cat >"\$SYSTEMD_DIR\/\$\{SILENCE_WATCHDOG_UNIT\}\.service"/,/^EOF$/' "$REPO/install-linux.sh")"
assert_not_contains "no AGENT_SILENCE_ALERT_TELEGRAM override in the written service (Marci's 2026-10-18 request stays in effect)" \
  "$SW_SVC_BLOCK" "AGENT_SILENCE_ALERT_TELEGRAM"

SW_TIMER_BLOCK="$(awk '/cat >"\$SYSTEMD_DIR\/\$\{SILENCE_WATCHDOG_UNIT\}\.timer"/,/^EOF$/' "$REPO/install-linux.sh")"
assert_not_contains "watchdog timer has no Requires=" "$SW_TIMER_BLOCK" "Requires="
assert_not_contains "watchdog timer has no Wants=" "$SW_TIMER_BLOCK" "Wants="
assert_contains "30-minute cadence" "$SW_TIMER_BLOCK" "OnUnitActiveSec=30min"
echo ""

# ---------------------------------------------------------------------------
# 2. update.sh -- the machines that already exist.
# ---------------------------------------------------------------------------
echo "update.sh install_agent_silence_watchdog_unit"

HELPERS="$(awk '/^_user_systemd_up\(\) \{/,/^\}$/' "$REPO/update.sh")
$(awk '/^ensure_timer_running\(\) \{/,/^\}$/' "$REPO/update.sh")"
FNBODY="$(awk '/^install_agent_silence_watchdog_unit\(\) \{/,/^\}$/' "$REPO/update.sh")"
FN="$HELPERS
$FNBODY"
if [ -z "$FNBODY" ] || ! printf '%s' "$HELPERS" | grep -q '^ensure_timer_running() {'; then
  fail "install_agent_silence_watchdog_unit() not found in update.sh"
  echo; echo "PASS=$PASS FAIL=$FAIL"; exit 1
fi
assert_contains "update.sh calls it during unit maintenance" \
  "$(awk '/^run_unit_maintenance\(\) \{/,/^\}$/' "$REPO/update.sh")" "install_agent_silence_watchdog_unit"

FAKE_INSTALL="$TMP/install"
mkdir -p "$FAKE_INSTALL/scripts" "$FAKE_INSTALL/store" "$TMP/bin" "$TMP/home"
printf '#!/bin/bash\nexit 0\n' > "$FAKE_INSTALL/scripts/agent-silence-watchdog.sh"
chmod +x "$FAKE_INSTALL/scripts/agent-silence-watchdog.sh"
printf 'BOT_NAME=TESTBOT\n' > "$FAKE_INSTALL/.env"

cat > "$TMP/bin/systemctl" <<EOF
#!/bin/bash
echo "\$*" >> "$TMP/systemctl.calls"
exit 0
EOF
chmod +x "$TMP/bin/systemctl"
printf '#!/bin/sh\nexit 1\n' > "$TMP/bin/pidof"; chmod +x "$TMP/bin/pidof"

make_uname() {
  cat > "$TMP/bin/uname" <<EOF
#!/bin/bash
[ "\${1:-}" = "-s" ] && echo "$1" && exit 0
echo "$1"
EOF
  chmod +x "$TMP/bin/uname"
}

run_fn() {
  PATH="$TMP/bin:$PATH" INSTALL_DIR="$FAKE_INSTALL" HOME="$TMP/home" \
    bash -c "set -u; INSTALL_DIR='$FAKE_INSTALL'; $FN
install_agent_silence_watchdog_unit '$1'" 2>&1
}

UNITS="$TMP/units"
mkdir -p "$UNITS"
make_uname Linux

# 2a. No channels unit -> nothing to extend.
run_fn "$UNITS" >/dev/null
assert_eq "no channels unit -> no watchdog units written" "0" "$(ls "$UNITS" | wc -l | tr -d ' ')"

# 2b. A real host: the id comes from the unit on disk.
printf '[Service]\n' > "$UNITS/hex-channels.service"
OUT="$(run_fn "$UNITS")"
assert_eq "watchdog .service written next to the channels unit" "yes" \
  "$([ -f "$UNITS/hex-agent-silence-watchdog.service" ] && echo yes || echo no)"
assert_eq "watchdog .timer written" "yes" \
  "$([ -f "$UNITS/hex-agent-silence-watchdog.timer" ] && echo yes || echo no)"
assert_contains "the timer was enabled AND started" "$(cat "$TMP/systemctl.calls")" \
  "--user enable --now hex-agent-silence-watchdog.timer"
assert_contains "ExecStart points at the watchdog" "$(cat "$UNITS/hex-agent-silence-watchdog.service")" \
  "ExecStart=$FAKE_INSTALL/scripts/agent-silence-watchdog.sh"
# The shipped units under scripts/systemd/ are placeholder templates. The unit
# that lands on a host must carry the REAL paths, or it fails at first fire.
assert_not_contains "no placeholder path survives into the written unit" \
  "$(cat "$UNITS/hex-agent-silence-watchdog.service")" "/path/to/marveen"
assert_not_contains "no placeholder user survives into the written unit" \
  "$(cat "$UNITS/hex-agent-silence-watchdog.service")" "/home/USER"
assert_contains "Description carries BOT_NAME from .env" \
  "$(cat "$UNITS/hex-agent-silence-watchdog.service")" "TESTBOT"
assert_not_contains "no AGENT_SILENCE_ALERT_TELEGRAM override written (Marci's 2026-10-18 request stays in effect)" \
  "$(cat "$UNITS/hex-agent-silence-watchdog.service")" "AGENT_SILENCE_ALERT_TELEGRAM"
assert_contains "30-minute cadence" "$(cat "$UNITS/hex-agent-silence-watchdog.timer")" "OnUnitActiveSec=30min"
assert_not_contains "no Requires= on the triggered service" \
  "$(cat "$UNITS/hex-agent-silence-watchdog.timer")" "Requires="
assert_contains "reports what it did" "$OUT" "hex-agent-silence-watchdog.timer"

# 2c. Idempotent: update.sh runs on every check.
: > "$TMP/systemctl.calls"
OUT="$(run_fn "$UNITS")"
assert_eq "second run calls no systemctl" "0" "$(wc -c < "$TMP/systemctl.calls" | tr -d ' ')"
assert_eq "second run prints nothing" "" "$OUT"

# 2d. A second agent on the same host gets its own timer.
printf '[Service]\n' > "$UNITS/marveen-channels.service"
run_fn "$UNITS" >/dev/null
assert_eq "second agent gets its own watchdog timer" "yes" \
  "$([ -f "$UNITS/marveen-agent-silence-watchdog.timer" ] && echo yes || echo no)"

# 2e. macOS: this watchdog has no launchd counterpart -- the function must stay
#     inert there rather than writing a systemd unit nothing on that host reads.
make_uname Darwin
: > "$TMP/systemctl.calls"
UNITS_MAC="$TMP/units-mac"; mkdir -p "$UNITS_MAC"
printf '[Service]\n' > "$UNITS_MAC/hex-channels.service"
run_fn "$UNITS_MAC" >/dev/null
assert_eq "on Darwin no systemd unit is written (only the seeded channels.service remains)" "1" "$(ls "$UNITS_MAC" | wc -l | tr -d ' ')"
assert_eq "on Darwin systemctl is never called" "0" "$(wc -c < "$TMP/systemctl.calls" | tr -d ' ')"

# 2f. An install predating the watchdog -> write nothing rather than enabling a
#     unit whose ExecStart does not exist.
make_uname Linux
rm -f "$FAKE_INSTALL/scripts/agent-silence-watchdog.sh"
UNITS2="$TMP/units2"; mkdir -p "$UNITS2"
printf '[Service]\n' > "$UNITS2/hex-channels.service"
run_fn "$UNITS2" >/dev/null
assert_eq "missing watchdog script -> no units written" "1" "$(ls "$UNITS2" | wc -l | tr -d ' ')"
echo ""

echo "==================================="
echo "PASS: $PASS  FAIL: $FAIL"
[ "$FAIL" = 0 ] || exit 1
