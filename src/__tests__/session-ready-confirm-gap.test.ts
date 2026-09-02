// SESSREADY902 (2026-09-02): isSessionReadyForPrompt() already skips the
// second confirm capture whenever the first looks busy (Pedro's question,
// answered by reading the code: this optimization already existed). What did
// NOT exist was a confirm gap wide enough to survive the footer's own
// rotating hint segment omitting "esc to interrupt" during genuinely
// continuous work -- measured live on Anna's session (2026-09-02): 2 of 15
// samples, 3s apart, missed it while the pane content was changing every
// single sample (provably busy the whole time). The old 250ms gap was sized
// only for a ~1-frame submit-moment race, not this multi-second-scale one.
//
// capturePane goes through node:child_process execFileSync -- same mocking
// convention as parked-input-escalation.test.ts: intercept 'capture-pane'
// args, return queued fixtures in call order.

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const SRC = readFileSync(join(__dirname, '..', 'web', 'agent-process.ts'), 'utf-8')

const h = vi.hoisted(() => {
  const SEP = '─'.repeat(80)
  const IDLE_FOOTER = '  ⏵⏵ bypass permissions on (shift+tab to cycle)'
  // The rotating hint segment includes "esc to interrupt" during genuine
  // work -- but per the 2026-09-02 measurement, not on every single sample.
  const BUSY_FOOTER = '  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt · ctrl+t to hide tasks'
  const IDLE_PANE = ['', SEP, '❯ ', SEP, IDLE_FOOTER].join('\n')
  const BUSY_PANE = ['', SEP, '❯ ', SEP, BUSY_FOOTER].join('\n')
  return { IDLE_PANE, BUSY_PANE, queue: [] as string[], captureCalls: 0 }
})

vi.mock('node:child_process', async (orig) => ({
  ...(await orig() as object),
  execFileSync: vi.fn((_file: string, args?: string[]) => {
    if (Array.isArray(args) && args.includes('capture-pane')) {
      h.captureCalls++
      return h.queue.shift() ?? h.IDLE_PANE
    }
    return ''
  }),
}))

import { isSessionReadyForPrompt } from '../web/agent-process.js'

beforeEach(() => {
  h.queue.length = 0
  h.captureCalls = 0
})

describe('PANE_READY_CONFIRM_DELAY_MS: wide enough to survive the footer flicker', () => {
  it('is at least 2000ms (SESSREADY902, 2026-09-02 measurement)', () => {
    const m = SRC.match(/const PANE_READY_CONFIRM_DELAY_MS = (\d+)/)
    expect(m, 'PANE_READY_CONFIRM_DELAY_MS not found in source').not.toBeNull()
    expect(Number(m![1])).toBeGreaterThanOrEqual(2000)
  })
})

describe('isSessionReadyForPrompt: busy-first-capture skips the confirm capture', () => {
  it('returns false and never takes a second capture when the first is busy', async () => {
    h.queue.push(h.BUSY_PANE)
    const ready = await isSessionReadyForPrompt('agent-test')
    expect(ready).toBe(false)
    expect(h.captureCalls).toBe(1)
  })
})

describe('isSessionReadyForPrompt: confirm capture after the real gap', () => {
  it('returns true when both captures, real gap apart, read idle', async () => {
    h.queue.push(h.IDLE_PANE, h.IDLE_PANE)
    const ready = await isSessionReadyForPrompt('agent-test')
    expect(ready).toBe(true)
    expect(h.captureCalls).toBe(2)
  }, 10_000) // real PANE_READY_CONFIRM_DELAY_MS wait, per this file's own convention

  it('returns false when the confirm capture catches a still-busy pane (the flicker case)', async () => {
    h.queue.push(h.IDLE_PANE, h.BUSY_PANE)
    const ready = await isSessionReadyForPrompt('agent-test')
    expect(ready).toBe(false)
    expect(h.captureCalls).toBe(2)
  }, 10_000)
})
