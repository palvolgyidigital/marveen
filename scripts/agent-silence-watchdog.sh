#!/bin/bash
# Out-of-process silence watchdog for every fleet agent (card 53f4486a, Marci's
# decision 2026-10-05: systemd timer, not a dashboard-embedded check, not an
# agent-scheduled task).
#
# WHY A SEPARATE, OUT-OF-PROCESS TIMER -- same reasoning as
# scripts/main-inbox-observer.sh, which this script mirrors closely:
#   - An agent-scheduled task cannot detect the fleet going silent, because it
#     IS one of the things that goes silent (measured: the 2026-09-26/28
#     incident had 486 scheduler "fired" ticks and zero processing -- a task
#     firing is not proof anything ran).
#   - A dashboard-embedded check dies with the dashboard process if IT wedges
#     without crashing (systemd then never restarts it, and the check wedges
#     with it). A timer starts a fresh process every tick.
#
# WHAT IT MEASURES, AND WHY IT IS WIDER THAN THE CARD'S ORIGINAL WORDING.
# The card (53f4486a) said "the age of the last memory or daily-log entry per
# agent". Measured before building this (2026-10-05): that metric alone is
# NOISY in normal operation -- on a completely ordinary Monday, agent 'bob'
# showed 149.8h and 'salesagens' 291.8h since their last memories/daily_logs
# row, while both had tool_call_log activity in the SAME MINUTE the check ran.
# Memory/daily-log writes are a DECISION the agent makes, not an automatic
# trace of activity; tool_call_log and conversation_log are written by the
# runtime itself on every tool call / channel message, independent of that
# decision. Using memory/daily-log alone would have false-alarmed on an
# actively-working agent on the very first day.
#
# Verified the wider metric does not weaken the thing the card cares about:
# tool_call_log (like memories and daily_logs) shows ZERO rows, for every
# agent, across the exact 2026-09-26T01:31:43+02:00 .. 2026-09-28T07:30:06+02:00
# incident window -- so the original incident would have been caught the same
# way by either metric. The four sources are combined (MAX of each agent's
# latest row across all four) rather than substituted, so this is a widening,
# not a replacement of the card's own metric.
#
# TWO LIMITS OF THE WIDENED METRIC, MEASURED BY PEDRO 2026-10-05 AFTER THIS
# SHIPPED -- both real, neither weakens detection (OR-combined: a source that
# cannot vouch for an agent just contributes nothing, it never subtracts):
#   1. tool_call_log IS PRUNED AT 24h (pruneToolCallLog, src/db.ts, default
#      olderThanSecs=86400) -- it carries NO information about an agent past
#      24h ago, confirming neither activity nor silence. A threshold ABOVE 24h
#      (the original 36h weekend default) could therefore overstate an agent's
#      true silence: a tool call 20h ago ages out of the table, and if the
#      other three sources are also stale, the computed "last activity" reads
#      older than it really was. THIS IS WHY THE WEEKEND DEFAULT BELOW IS 24h,
#      NOT HIGHER -- it is pinned to this table's retention ceiling, not a
#      round number. Raising AGENT_SILENCE_WEEKEND_HOURS past 24 reopens this
#      gap; it is still safe to do so, it just means tool_call_log cannot back
#      up the extra hours.
#   2. conversation_log IS EFFECTIVELY PEDRO-ONLY. Measured row counts per
#      agent (2026-10-05): pedro=5274, sam=31 (newest row from 2026-07-22,
#      i.e. stale), marti=1, every other sub-agent ~0. For the seven
#      sub-agents the real signal set is memories + daily_logs + tool_call_log
#      (three sources, not four) -- document this as fact, not as "four
#      independent confirmations for everyone", which it is not.
#
# WHAT IT DOES NOT DO: this detects silence, it does not explain WHY a pane
# stopped processing prompts while its process stayed alive -- that question
# (the actual open part of card 53f4486a and its sibling 9e9d3aad) is
# unanswered and this script makes no claim about it.
#
# It alerts over the DIRECT Bot API (scripts/lib/send-telegram.sh), never over
# /api/* or an agent's own reply tool -- both die with the thing this watchdog
# exists to outlive.
#
# Usage:
#   scripts/agent-silence-watchdog.sh              # one tick (systemd/launchd)
#   scripts/agent-silence-watchdog.sh --check DB    # evaluate DB, print, exit; no writes, no alert
#
# Exit codes of --check: 0 = all agents within threshold, 1 = at least one
# silent beyond threshold, 2 = could not evaluate (db missing/unreadable).
#
# Env:
#   AGENT_SILENCE_WEEKDAY_HOURS   - weekday threshold in hours (default 8)
#   AGENT_SILENCE_WEEKEND_HOURS   - Sat/Sun threshold in hours (default 24, pinned to
#                                  tool_call_log's 24h prune ceiling -- see above)
#   AGENT_SILENCE_DB              - database (default <install>/store/claudeclaw.db)
#   AGENT_SILENCE_ALERT_DRYRUN    - if 1, print "ALERT_DRYRUN: <msg>" instead of sending
#
# NOTE ON THE DEFAULT THRESHOLDS: these are a starting point, not a measured
# optimum -- there is no prior data on this fleet's true weekday/weekend
# quiet-but-fine baseline under the WIDENED (four-source) metric, because the
# metric did not exist before this script. Watch the first one to two weeks
# for false positives/negatives (store/agent-silence-watchdog.log) and adjust
# via the env vars above; nothing here requires a code change to retune.

set -u

INSTALL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STORE_DIR="$INSTALL_DIR/store"
DB_DEFAULT="$STORE_DIR/claudeclaw.db"
LIVENESS_STAMP="$STORE_DIR/.agent-silence-watchdog"
ALERT_STAMP="$STORE_DIR/.agent-silence-watchdog-alerted"
LOG_TAG="agent-silence-watchdog"
ALERT_COOLDOWN=10800  # at most one silence alert per 3 hours (not per agent: see main())

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [$LOG_TAG] $*" || true; }

weekday_hours="${AGENT_SILENCE_WEEKDAY_HOURS:-8}"
weekend_hours="${AGENT_SILENCE_WEEKEND_HOURS:-24}"
case "$weekday_hours" in (''|*[!0-9]*) weekday_hours=8;; esac
case "$weekend_hours" in (''|*[!0-9]*) weekend_hours=24;; esac

# ISO day-of-week: 1=Mon .. 7=Sun. Sat/Sun get the wider threshold.
dow="$(date +%u)"
if [ "$dow" = 6 ] || [ "$dow" = 7 ]; then
  THRESHOLD_HOURS="$weekend_hours"
  THRESHOLD_LABEL="hetvegi"
else
  THRESHOLD_HOURS="$weekday_hours"
  THRESHOLD_LABEL="hetkoznapi"
fi
THRESHOLD_SECONDS=$(( THRESHOLD_HOURS * 3600 ))

# Which agent ids to watch: every agents/<name> directory PLUS the main agent
# (MAIN_AGENT_ID from .env, default 'marveen') -- filesystem discovery, not a
# hardcoded list, so an added/removed agent needs no edit here. Matches
# resolve_main_agent_id()'s id-shape validation ([A-Za-z0-9._-] only) since
# these ids land inside a SQL string below.
valid_id() {
  case "$1" in
    ''|*[!A-Za-z0-9._-]*) return 1 ;;
    *) return 0 ;;
  esac
}

# Overridable for tests (mirrors MAIN_AGENT_ID/MAIN_INBOX_OBSERVER_DB-style env
# overrides already used by main-inbox-observer.sh): AGENT_SILENCE_AGENTS_DIR
# points discovery at a fixture tree instead of the real install's agents/.
discover_agent_ids() {
  local main_id d name agents_dir
  main_id="${MAIN_AGENT_ID:-}"
  if [ -z "$main_id" ]; then
    main_id="$(grep -E '^MAIN_AGENT_ID=' "$INSTALL_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r "')"
  fi
  [ -n "$main_id" ] || main_id="marveen"
  valid_id "$main_id" && printf '%s\n' "$main_id"
  agents_dir="${AGENT_SILENCE_AGENTS_DIR:-$INSTALL_DIR/agents}"
  if [ -d "$agents_dir" ]; then
    for d in "$agents_dir"/*/; do
      [ -d "$d" ] || continue
      name="$(basename "$d")"
      valid_id "$name" || continue
      [ "$name" = "$main_id" ] && continue
      printf '%s\n' "$name"
    done
  fi
}

# Same read pattern as main-inbox-observer.sh: read-only open first (the only
# one that can open a WAL-mode db with no live writer and no -shm file, i.e.
# EXACTLY the "dashboard is down" case this watchdog must survive), falling
# back to a query_only normal open.
_READ_PY='
import sqlite3, sys, urllib.parse
mode, path, sql = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    if mode == "ro":
        con = sqlite3.connect("file:" + urllib.parse.quote(path) + "?mode=ro", uri=True, timeout=3)
    else:
        con = sqlite3.connect(path, timeout=3)
        con.execute("PRAGMA query_only=ON")
    try:
        rows = con.execute(sql).fetchall()
    finally:
        con.close()
except Exception:
    sys.exit(1)
for r in rows:
    print("|".join("" if v is None else str(v) for v in r))
'
read_row() {
  local db="$1" sql="$2" out
  if out="$(python3 -c "$_READ_PY" ro "$db" "$sql" 2>/dev/null)"; then
    printf '%s' "$out"; return 0
  fi
  out="$(python3 -c "$_READ_PY" query_only "$db" "$sql" 2>/dev/null)" || return 1
  printf '%s' "$out"; return 0
}

# Last-activity epoch (seconds -- verified against this db: memories.created_at
# and daily_logs.created_at are both unixepoch SECONDS, checked directly
# against `date +%s` output, not assumed; this is a DIFFERENT table from the
# task_runs.ts millisecond trap the card itself warns about) for one agent,
# as the MAX across all four source tables. Prints "" (empty) if the agent has
# NO row in any of the four tables yet (a brand-new agent) -- callers must
# treat that as "no baseline, skip" rather than "infinitely stale".
last_activity_epoch() {
  local db="$1" agent="$2" row
  row="$(read_row "$db" "
    SELECT MAX(x) FROM (
      SELECT MAX(created_at) AS x FROM memories WHERE agent_id='$agent'
      UNION ALL SELECT MAX(created_at) FROM daily_logs WHERE agent_id='$agent'
      UNION ALL SELECT MAX(created_at) FROM tool_call_log WHERE agent_id='$agent'
      UNION ALL SELECT MAX(created_at) FROM conversation_log WHERE agent_id='$agent'
    );")" || return 1
  case "$row" in (''|*[!0-9]*) return 1 ;; esac
  printf '%s' "$row"
}

# Evaluate every discovered agent. Sets SILENT_LIST (space-joined
# "agent:age_h" entries) and UNKNOWN_LIST (agents with no baseline row at
# all). Returns 0 = all within threshold, 1 = at least one silent beyond it,
# 2 = db unreadable / nothing discoverable.
SILENT_LIST=""
UNKNOWN_LIST=""
evaluate_fleet() {
  local db="$1" now agent epoch age any_agent=0
  SILENT_LIST=""; UNKNOWN_LIST=""
  [ -f "$db" ] || return 2
  now="$(date +%s)"
  while IFS= read -r agent; do
    [ -n "$agent" ] || continue
    any_agent=1
    epoch="$(last_activity_epoch "$db" "$agent")"
    if [ -z "$epoch" ]; then
      UNKNOWN_LIST="$UNKNOWN_LIST $agent"
      continue
    fi
    age=$(( now - epoch ))
    [ "$age" -ge 0 ] || age=0
    if [ "$age" -ge "$THRESHOLD_SECONDS" ]; then
      SILENT_LIST="$SILENT_LIST ${agent}:$(( age / 3600 ))h"
    fi
  done <<EOF_AGENTS
$(discover_agent_ids)
EOF_AGENTS
  [ "$any_agent" = 1 ] || return 2
  [ -n "$SILENT_LIST" ] && return 1
  return 0
}

verdict_word() {  # verdict_word <rc> -> "ok" | "silent" | "unknown"
  case "$1" in
    0) echo ok ;;
    1) echo silent ;;
    *) echo unknown ;;
  esac
}

if [ "${1:-}" = "--check" ]; then
  [ -n "${2:-}" ] || { echo "usage: agent-silence-watchdog.sh --check <db-path>" >&2; exit 2; }
  evaluate_fleet "$2"; CHECK_RC=$?
  echo "threshold=${THRESHOLD_LABEL}(${THRESHOLD_HOURS}h) silent=[${SILENT_LIST# }] unknown=[${UNKNOWN_LIST# }] verdict=$(verdict_word "$CHECK_RC")"
  exit "$CHECK_RC"
fi

# DIRECT-BOT-API alert, same contract as main-inbox-observer.sh's alert_owner.
alert_owner() {
  local msg="$1" token chat tg_dir tg_env
  if [ "${AGENT_SILENCE_ALERT_DRYRUN:-}" = "1" ]; then
    echo "ALERT_DRYRUN: $msg"; return 0
  fi
  tg_dir="${TELEGRAM_STATE_DIR:-}"
  if [ -z "$tg_dir" ]; then
    tg_dir="$INSTALL_DIR/.claude/channels/telegram"
    [ -f "$tg_dir/.env" ] || tg_dir="$HOME/.claude/channels/telegram"
  fi
  tg_env="$tg_dir/.env"
  token="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$tg_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r ')"
  chat="$(grep -E '^ALLOWED_CHAT_ID=' "$INSTALL_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r ')"
  [ -z "$chat" ] && chat="$(grep -E '^TELEGRAM_CHAT_ID=' "$tg_env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r ')"
  [ "$chat" = "0" ] && chat=""  # CHATID0: installer placeholder, not a chat.
  if [ -z "$token" ] || [ -z "$chat" ]; then
    log "ALERT (no bot token or owner chat id configured, could not Telegram): $msg"; return 1
  fi
  . "$(cd "$(dirname "$0")" && pwd)/lib/send-telegram.sh"
  local send_err
  if send_err="$(send_telegram_message "$token" "$chat" "$msg" 2>&1)"; then
    log "owner alerted via direct Bot API (delivery confirmed)"
    return 0
  fi
  log "ALERT sendMessage FAILED: ${send_err}"
  return 1
}

main() {
  local db rc now last msg
  mkdir -p "$STORE_DIR" 2>/dev/null || true
  db="${AGENT_SILENCE_DB:-$DB_DEFAULT}"
  evaluate_fleet "$db"; rc=$?
  now="$(date +%s)"
  echo "$now verdict=$(verdict_word "$rc") threshold=${THRESHOLD_LABEL}(${THRESHOLD_HOURS}h) silent=[${SILENT_LIST# }] unknown_baseline=[${UNKNOWN_LIST# }]" \
    > "$LIVENESS_STAMP" 2>/dev/null || true

  if [ "$rc" = 0 ]; then
    rm -f "$ALERT_STAMP" 2>/dev/null || true
    return 0
  fi
  if [ "$rc" = 2 ]; then
    log "cannot evaluate: db missing/unreadable or no agents discovered ($db)"
    return 0
  fi

  last=0; [ -f "$ALERT_STAMP" ] && last="$(cat "$ALERT_STAMP" 2>/dev/null || echo 0)"
  case "$last" in (''|*[!0-9]*) last=0;; esac
  if [ $(( now - last )) -lt "$ALERT_COOLDOWN" ]; then
    log "verdict=silent ([${SILENT_LIST# }]) but within alert cooldown ($(( now - last ))s) -- skip alert"
    return 0
  fi

  msg="🔴 Nema agens(ek) eszlelve (${THRESHOLD_LABEL} kuszob, ${THRESHOLD_HOURS}h): [${SILENT_LIST# }]. Egyik forrasban sincs ujabb nyom (memoria, napi naplo, eszkoz-hivas, csatorna-uzenet). Ha ez tobb agenst erint egyszerre, nezd meg a tmux session-oket es a dashboard folyamatot elkulonitve -- a 2026-09-26/28-i kiesesnel a scheduler futott, az agensek megis nemak voltak."
  log "$msg"
  if alert_owner "$msg"; then
    echo "$now" > "$ALERT_STAMP" 2>/dev/null || true
  else
    log "alert not delivered -- cooldown stamp NOT written, will retry next tick"
  fi
}

main "$@"
exit 0
