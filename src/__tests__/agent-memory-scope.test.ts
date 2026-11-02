// Card 9b6e4e6e (2026-10-29 OOM incident): per-agent memory cap on the systemd scope tmux
// itself creates for each pane, instead of a new systemd-run wrap -- see agent-memory-scope.ts
// for the measured reasoning. These tests use the dependency-injection seams the module
// exposes (listPanePid/resolveScope/setProperty, and a readCgroup override) rather than
// mocking node:child_process/node:fs, so they exercise the real decision logic without
// shelling out.
import { describe, it, expect, vi } from 'vitest'
import { readFileSync, existsSync, readdirSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'
import {
  resolveMemoryScopeLimits,
  resolveTmuxSpawnScopeUnit,
  applyAgentMemoryScope,
  type MemoryScopeDeps,
} from '../web/agent-memory-scope.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..', '..')
const src = (rel: string) => readFileSync(join(ROOT, 'src', 'web', rel), 'utf-8')

let tmuxBin: string | null
try { tmuxBin = execFileSync('/bin/sh', ['-c', 'command -v tmux'], { encoding: 'utf-8' }).trim() || null } catch { tmuxBin = null }
let systemctlUserOk = false
try { execFileSync('systemctl', ['--user', 'is-system-running'], { timeout: 3000, stdio: 'ignore' }); systemctlUserOk = true }
catch (err) { systemctlUserOk = (err as { status?: number }).status != null } // "degraded" also exits non-zero but IS usable

describe('resolveMemoryScopeLimits', () => {
  it('defaults to 4G/3G/1G with no env overrides', () => {
    expect(resolveMemoryScopeLimits({})).toEqual({ max: '4G', high: '3G', swapMax: '1G' })
  })

  it('reads AGENT_MEMORY_MAX / AGENT_MEMORY_HIGH / AGENT_MEMORY_SWAP_MAX overrides', () => {
    expect(resolveMemoryScopeLimits({
      AGENT_MEMORY_MAX: '2G', AGENT_MEMORY_HIGH: '1500M', AGENT_MEMORY_SWAP_MAX: '512M',
    })).toEqual({ max: '2G', high: '1500M', swapMax: '512M' })
  })

  it('"0" on AGENT_MEMORY_MAX is kept verbatim (the opt-out sentinel), not treated as empty', () => {
    expect(resolveMemoryScopeLimits({ AGENT_MEMORY_MAX: '0' }).max).toBe('0')
  })

  it('blank/whitespace-only overrides fall back to the default, not an empty systemd value', () => {
    expect(resolveMemoryScopeLimits({ AGENT_MEMORY_MAX: '   ' }).max).toBe('4G')
  })
})

describe('resolveTmuxSpawnScopeUnit', () => {
  it('extracts the unit name from a real-shaped /proc/<pid>/cgroup line', () => {
    const cgroup = '0::/user.slice/user-1000.slice/user@1000.service/app.slice/tmux-spawn-a07017d9-19c4-465e-b04a-32e04d97b537.scope\n'
    expect(resolveTmuxSpawnScopeUnit(123, () => cgroup)).toBe('tmux-spawn-a07017d9-19c4-465e-b04a-32e04d97b537.scope')
  })

  it('returns null when the pid is not inside a tmux-spawn scope (non-systemd host, old tmux)', () => {
    const cgroup = '0::/user.slice/user-1000.slice/user@1000.service/app.slice/some-other.scope\n'
    expect(resolveTmuxSpawnScopeUnit(123, () => cgroup)).toBeNull()
  })

  it('fails open (returns null, does not throw) when /proc/<pid>/cgroup is unreadable', () => {
    expect(resolveTmuxSpawnScopeUnit(123, () => { throw new Error('ENOENT') })).toBeNull()
  })
})

describe('applyAgentMemoryScope', () => {
  function deps(overrides: Partial<MemoryScopeDeps> = {}): MemoryScopeDeps {
    return {
      listPanePid: vi.fn(() => 4242),
      resolveScope: vi.fn(() => 'tmux-spawn-test.scope'),
      setProperty: vi.fn(),
      ...overrides,
    }
  }

  it('calls setProperty with the resolved unit and the default limits on the happy path', () => {
    const d = deps()
    const ok = applyAgentMemoryScope('agent-foo', { deps: d, env: {} })
    expect(ok).toBe(true)
    expect(d.setProperty).toHaveBeenCalledWith('tmux-spawn-test.scope', { max: '4G', high: '3G', swapMax: '1G' })
  })

  it('AGENT_MEMORY_MAX=0 is a full opt-out: no pane lookup, no setProperty call', () => {
    const d = deps()
    const ok = applyAgentMemoryScope('agent-foo', { deps: d, env: { AGENT_MEMORY_MAX: '0' } })
    expect(ok).toBe(false)
    expect(d.listPanePid).not.toHaveBeenCalled()
    expect(d.setProperty).not.toHaveBeenCalled()
  })

  it('crossUser: true skips entirely without even looking up the pane (no privilege-crossing attempt)', () => {
    const d = deps()
    const ok = applyAgentMemoryScope('agent-foo', { deps: d, crossUser: true })
    expect(ok).toBe(false)
    expect(d.listPanePid).not.toHaveBeenCalled()
  })

  it('no pane pid found (tmux list-panes failed): fails open, no setProperty call', () => {
    const d = deps({ listPanePid: vi.fn(() => null) })
    const ok = applyAgentMemoryScope('agent-foo', { deps: d })
    expect(ok).toBe(false)
    expect(d.setProperty).not.toHaveBeenCalled()
  })

  it('no tmux-spawn scope found (non-systemd host): fails open, no setProperty call', () => {
    const d = deps({ resolveScope: vi.fn(() => null) })
    const ok = applyAgentMemoryScope('agent-foo', { deps: d })
    expect(ok).toBe(false)
    expect(d.setProperty).not.toHaveBeenCalled()
  })

  it('systemctl set-property throwing (e.g. systemctl missing) fails open, never throws out to the caller', () => {
    const d = deps({ setProperty: vi.fn(() => { throw new Error('systemctl: command not found') }) })
    expect(() => applyAgentMemoryScope('agent-foo', { deps: d })).not.toThrow()
    expect(applyAgentMemoryScope('agent-foo', { deps: d })).toBe(false)
  })
})

describe('wiring: every local tmux new-session launch for an agent pane applies the cap', () => {
  it('agent-process.ts: the primary start path calls applyAgentMemoryScope right after its new-session', () => {
    const file = src('agent-process.ts')
    expect(file).toContain("import { applyAgentMemoryScope } from './agent-memory-scope.js'")
    // Loose containment, not a line-anchored regex (AGENTMEMCAP1029 tag marks both call sites):
    // a future reformatting of this file should not need this test rewritten line-for-line.
    const occurrences = file.split('applyAgentMemoryScope(session').length - 1
    expect(occurrences).toBeGreaterThanOrEqual(2) // primary start + EPERM /tmp fallback
  })

  it('agent-worker.ts: the worker-session launch calls applyAgentMemoryScope right after its new-session', () => {
    const file = src('agent-worker.ts')
    expect(file).toContain("import { applyAgentMemoryScope } from './agent-memory-scope.js'")
    expect(file).toContain('applyAgentMemoryScope(ctx.session)')
  })

  it('agent-memory-scope.ts: the systemctl set-property call uses --runtime (Pedro, msg 7159)', () => {
    const file = src('agent-memory-scope.ts')
    expect(file).toContain("'--user', 'set-property', '--runtime', unit")
  })
})

// Real end-to-end proof, not a mock: a disposable tmux session's auto-created systemd scope
// actually gets capped, and --runtime means NOTHING is written under
// ~/.config/systemd/user.control/ (the persistent-drop-in leak Pedro flagged in msg 7159 --
// every agent start names a fresh uuid scope, so a persistent drop-in would never be reused,
// only accumulate forever).
describe.skipIf(!tmuxBin || !systemctlUserOk)('applyAgentMemoryScope: real systemd scope, no persistent leftover', () => {
  it('caps a disposable session\'s tmux-spawn scope via --runtime, and leaves no file under user.control', async () => {
    const session = `bob-memtest-unit-${process.pid}`
    const userControlDir = join(homedir(), '.config', 'systemd', 'user.control')
    const before = existsSync(userControlDir) ? new Set(readdirSync(userControlDir)) : new Set<string>()
    try {
      execFileSync(tmuxBin as string, ['new-session', '-d', '-s', session, 'sleep', '60'], { timeout: 5000 })
      // Give tmux's systemd integration a moment to finish creating the scope.
      await new Promise((r) => setTimeout(r, 300))
      const ok = applyAgentMemoryScope(session, { env: { AGENT_MEMORY_MAX: '256M', AGENT_MEMORY_HIGH: '200M', AGENT_MEMORY_SWAP_MAX: '0' } })
      expect(ok).toBe(true)
      const after = existsSync(userControlDir) ? new Set(readdirSync(userControlDir)) : new Set<string>()
      const newFiles = [...after].filter((f) => !before.has(f))
      expect(newFiles).toEqual([])
    } finally {
      try { execFileSync(tmuxBin as string, ['kill-session', '-t', `=${session}:`], { timeout: 5000 }) } catch { /* already gone */ }
    }
  })
})
