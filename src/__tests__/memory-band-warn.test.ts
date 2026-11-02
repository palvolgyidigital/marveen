// Card 9b6e4e6e, Part 2 -- logIfHardMemoryBand (src/web/memory-band-warn.ts).
// Real fleet-memory-gate.sh --status --dry-run, stubbed meminfo (same seam as
// the sibling schedule-runner-low-memory-gate.test.ts and
// scripts/__tests__/memgate-min-avail.test.sh), proving: it warns in the HARD
// band, stays silent otherwise, and never throws even when the script itself
// is unusable.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const mockWarn = vi.fn()
const mockDebug = vi.fn()
vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: (...a: unknown[]) => mockWarn(...a), debug: (...a: unknown[]) => mockDebug(...a), error: vi.fn() },
}))

describe('logIfHardMemoryBand', () => {
  let sandbox: string

  beforeEach(() => {
    sandbox = mkdtempSync(join(tmpdir(), 'memband-'))
    vi.stubEnv('MARVEEN_STORE', sandbox)
    vi.stubEnv('MARVEEN_MEM_GATE_OBSERVE', '0')
    vi.stubEnv('MARVEEN_MEM_GATE_DISABLE', '0')
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    rmSync(sandbox, { recursive: true, force: true })
  })

  function writeMeminfo(availMb: number): void {
    const p = join(sandbox, 'meminfo')
    writeFileSync(p, `MemTotal:       16000000 kB\nMemAvailable:   ${availMb * 1024} kB\n`)
    vi.stubEnv('MEMGATE_PROC_MEMINFO', p)
  }

  it('warns when the fleet memory gate reports the HARD band', async () => {
    writeMeminfo(400) // ~97% used on a 16G total -> hard band (default HARD_PCT=90)
    const { logIfHardMemoryBand } = await import('../web/memory-band-warn.js')
    logIfHardMemoryBand('test-site', { agent: 'someagent' })
    expect(mockWarn).toHaveBeenCalledTimes(1)
    const [fields, msg] = mockWarn.mock.calls[0] as [Record<string, unknown>, string]
    expect(msg).toContain('HARD band')
    expect(fields.site).toBe('test-site')
    expect(fields.agent).toBe('someagent')
    expect(String(fields.status)).toContain('band=hard')
  })

  it('stays silent when the band is ok', async () => {
    writeMeminfo(10000) // plenty free -> band=ok
    const { logIfHardMemoryBand } = await import('../web/memory-band-warn.js')
    logIfHardMemoryBand('test-site', { agent: 'someagent' })
    expect(mockWarn).not.toHaveBeenCalled()
  })

  it('stays silent in the WARN band (only HARD triggers the log, per Pedro msg 7153)', async () => {
    writeMeminfo(2000) // ~87.5% used on 16G -> warn band (default WARN_PCT=80, HARD_PCT=90)
    const { logIfHardMemoryBand } = await import('../web/memory-band-warn.js')
    logIfHardMemoryBand('test-site', { agent: 'someagent' })
    expect(mockWarn).not.toHaveBeenCalled()
  })

  it('never throws when the script itself is unusable (fail-open)', async () => {
    vi.stubEnv('MEMGATE_PROC_MEMINFO', join(sandbox, 'does-not-exist'))
    const { logIfHardMemoryBand } = await import('../web/memory-band-warn.js')
    expect(() => logIfHardMemoryBand('test-site', { agent: 'someagent' })).not.toThrow()
    expect(mockWarn).not.toHaveBeenCalled()
  })
})
