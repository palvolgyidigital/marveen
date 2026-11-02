import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { logger } from '../logger.js'
import { tmuxStderr } from './tmux-stderr.js'
import { resolveFromPath } from '../platform.js'
import { exactTmuxTarget } from '../tmux-target.js'

const TMUX = resolveFromPath('tmux')

/**
 * Per-agent memory cap (card 9b6e4e6e, 2026-10-29 OOM incident).
 *
 * Does NOT wrap the launch command in a new systemd-run scope. tmux itself already
 * places every pane it spawns into its own transient systemd scope when the host runs
 * systemd with cgroup delegation (`tmux-spawn-<uuid>.scope` under app.slice) -- measured
 * live on this host: both of today's kernel OOM kills (13:52 and 13:52-area, a pd.read_excel
 * child ballooning to 13-14G) landed on exactly this kind of scope, and
 * `systemctl --user set-property <that-unit> MemoryMax=... MemoryHigh=...` takes effect on it
 * immediately (confirmed on a disposable test session). Reusing the scope tmux already
 * creates means: no command-string quoting/escaping of the launch command, and a child
 * process (e.g. a python3 under the agent's claude) inherits the SAME scope automatically,
 * so it is capped without any extra plumbing.
 *
 * Fail-open by construction, same posture as scripts/fleet-memory-gate.sh: any missing
 * binary, unreadable /proc entry, non-systemd host, or systemctl error just skips the cap
 * (logged) and never blocks or kills the agent start itself.
 */

export interface MemoryScopeLimits {
  /** systemd MemoryMax value, e.g. "4G". "0" disables the cap entirely. */
  max: string
  /** systemd MemoryHigh value, e.g. "3G". */
  high: string
  /** systemd MemorySwapMax value, e.g. "1G". */
  swapMax: string
}

const DEFAULT_LIMITS: MemoryScopeLimits = { max: '4G', high: '3G', swapMax: '1G' }

export function resolveMemoryScopeLimits(env: NodeJS.ProcessEnv = process.env): MemoryScopeLimits {
  return {
    max: env.AGENT_MEMORY_MAX?.trim() || DEFAULT_LIMITS.max,
    high: env.AGENT_MEMORY_HIGH?.trim() || DEFAULT_LIMITS.high,
    swapMax: env.AGENT_MEMORY_SWAP_MAX?.trim() || DEFAULT_LIMITS.swapMax,
  }
}

const TMUX_SPAWN_SCOPE_RE = /\/(tmux-spawn-[0-9a-fA-F-]+\.scope)$/

/**
 * Reads /proc/<pid>/cgroup and extracts the tmux-spawn-*.scope unit name, if the pid is
 * running inside one. Returns null (not an error) when the host has no systemd auto-scoping
 * for tmux panes (older tmux, non-systemd host, cgroup delegation off) -- that is the normal,
 * expected "nothing to cap" case, not a failure.
 */
export function resolveTmuxSpawnScopeUnit(pid: number, readCgroup: (pid: number) => string = defaultReadCgroup): string | null {
  let content: string
  try {
    content = readCgroup(pid)
  } catch (err) {
    logger.debug({ err, pid }, 'agent-memory-scope: /proc/<pid>/cgroup unreadable, skipping cap')
    return null
  }
  for (const line of content.split('\n')) {
    const m = TMUX_SPAWN_SCOPE_RE.exec(line.trim())
    if (m) return m[1]
  }
  return null
}

function defaultReadCgroup(pid: number): string {
  return readFileSync(`/proc/${pid}/cgroup`, 'utf-8')
}

/** Dependency seam for tests -- avoids shelling out in unit tests. */
export interface MemoryScopeDeps {
  listPanePid: (session: string) => number | null
  resolveScope: (pid: number) => string | null
  setProperty: (unit: string, limits: MemoryScopeLimits) => void
}

function defaultListPanePid(session: string): number | null {
  try {
    const out = execFileSync(TMUX, ['list-panes', '-t', exactTmuxTarget(session), '-F', '#{pane_pid}'], {
      timeout: 5000,
      encoding: 'utf-8',
      // TMUXWINDOWATTR920: piped, so a tmux error is logged below with the site
      // instead of leaking undated onto dashboard.error.log.
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const pid = parseInt(out.trim().split('\n')[0] ?? '', 10)
    return Number.isFinite(pid) ? pid : null
  } catch (err) {
    logger.debug({ err: tmuxStderr(err), session }, 'agent-memory-scope: tmux list-panes failed, skipping cap')
    return null
  }
}

function defaultSetProperty(unit: string, limits: MemoryScopeLimits): void {
  // --runtime (Pedro, msg 7159): without it, `set-property` on a user unit writes a
  // PERSISTENT drop-in under ~/.config/systemd/user.control/, which would survive the
  // scope itself -- and every agent (re)start gets a freshly uuid-named
  // tmux-spawn-*.scope, so those drop-ins would never be reused or cleaned up, only
  // accumulate. --runtime keeps the override in the transient, memory-only unit state
  // and writes nothing to disk.
  execFileSync('systemctl', [
    '--user', 'set-property', '--runtime', unit,
    `MemoryMax=${limits.max}`, `MemoryHigh=${limits.high}`, `MemorySwapMax=${limits.swapMax}`,
  ], { timeout: 5000 })
}

const DEFAULT_DEPS: MemoryScopeDeps = {
  listPanePid: defaultListPanePid,
  resolveScope: (pid) => resolveTmuxSpawnScopeUnit(pid),
  setProperty: defaultSetProperty,
}

/**
 * Applies the per-agent memory cap to a just-started tmux session's auto-created scope.
 * Call this right after the `tmux new-session` that launches an agent pane returns.
 *
 * `crossUser`: pass true for a per-agent `runAsUser` launch (a DIFFERENT Linux user's tmux
 * pane). This function deliberately does NOT attempt a cross-user `systemctl --user`
 * call -- that would need sudo/dbus access into another user's session, which is a
 * privilege-crossing step outside what this helper does on its own. It logs once and
 * returns false; the cap for runAsUser agents is a separate, not-yet-covered case.
 *
 * Returns true if the cap was applied, false if it was skipped for any reason (always
 * fail-open: a skip never throws and never blocks the caller).
 */
export function applyAgentMemoryScope(
  session: string,
  opts: { crossUser?: boolean; env?: NodeJS.ProcessEnv; deps?: MemoryScopeDeps } = {},
): boolean {
  const limits = resolveMemoryScopeLimits(opts.env)
  if (limits.max === '0') return false // explicit opt-out
  if (opts.crossUser) {
    logger.debug({ session }, 'agent-memory-scope: runAsUser agent, cross-user systemd scope not attempted, skipping cap')
    return false
  }
  const deps = opts.deps ?? DEFAULT_DEPS
  const pid = deps.listPanePid(session)
  if (pid == null) return false
  const unit = deps.resolveScope(pid)
  if (unit == null) {
    logger.debug({ session, pid }, 'agent-memory-scope: no tmux-spawn-*.scope found (non-systemd host or old tmux), skipping cap')
    return false
  }
  try {
    deps.setProperty(unit, limits)
    logger.info({ session, unit, limits }, 'agent-memory-scope: memory cap applied to agent tmux scope')
    return true
  } catch (err) {
    logger.warn({ err: tmuxStderr(err), session, unit }, 'agent-memory-scope: systemctl set-property failed, agent runs uncapped')
    return false
  }
}
