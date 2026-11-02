// Card 9b6e4e6e, Part 2 (2026-10-29 OOM incident). Read-only, warn-only check
// of the EXISTING used-pct WARN/HARD band that scripts/fleet-memory-gate.sh
// already computes for the reconcile loop's non-core agents (memGateAllowsStart
// in channel-monitor.ts) -- NOT the new absolute-MemAvailable-MB gate in
// schedule-runner.ts, which is a separate mode (--min-avail) on the same script.
//
// Pedro's msg 7153 approval, verbatim: context-guard / reauth / model-fallback
// restarts do NOT block on memory pressure, only log in the HARD band. The
// reasoning: these three (plus the fleet-plan-switch rotation in
// claude-plan-fleet-wiring.ts) are RECOVERY actions for an agent that is
// already broken, stuck, or about to be deliberately replaced -- refusing to
// restart it would leave the fleet with a KNOWN-dead or KNOWN-stuck agent
// instead of a merely memory-risked one, which is a worse trade than the risk
// itself. This function only logs, so the operator can see the correlation if
// a restart is immediately followed by another OOM, without ever blocking the
// restart.
//
// --dry-run: the --status mode's band computation has side effects (writing
// the safe-mode flag, sending the deduped Telegram alert) that are already
// owned by the reconcile loop's own --check calls; this probe must not
// duplicate or race those, so it asks for the read-only view.
//
// spawnSync, not execFileSync: --status returns the SAME verdict exit code as
// --verdict (10 in the warn/hard/cap bands, measured), so execFileSync would
// THROW on exactly the HARD case this function exists to detect, instead of
// handing back the stdout. spawnSync never throws on a non-zero exit.
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { PROJECT_ROOT } from '../config.js'
import { logger } from '../logger.js'

const MEM_GATE_SCRIPT = join(PROJECT_ROOT, 'scripts', 'fleet-memory-gate.sh')

/**
 * `site`: a short label for which restart path called this (shows up in the
 * log line so the three/four call sites are distinguishable).
 * `context`: extra fields to attach (typically at least the agent name).
 * Fail-open by construction: any error (missing script, non-Linux host,
 * timeout) is logged at debug and never throws, never blocks the caller.
 */
export function logIfHardMemoryBand(site: string, context: Record<string, unknown>): void {
  const result = spawnSync('/bin/bash', [MEM_GATE_SCRIPT, '--status', '--dry-run'], { timeout: 5000, encoding: 'utf-8' })
  if (result.error) {
    logger.debug({ err: result.error, site, ...context }, 'memory-band-warn: status check failed, skipping (never blocks a restart)')
    return
  }
  const out = result.stdout ?? ''
  if (/\bband=hard\b/.test(out)) {
    logger.warn(
      { site, ...context, status: out.trim() },
      'memory-band-warn: restarting an agent while the fleet memory gate reports the HARD band (not blocked, per card 9b6e4e6e / Pedro msg 7153)',
    )
  }
}
