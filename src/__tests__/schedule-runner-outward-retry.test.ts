import { describe, expect, it } from 'vitest'
import { isOutwardRetryTooStale, DEFAULT_CATCHUP_MAX_AGE_MIN } from '../web/schedule-runner.js'

// OUTWARD915. Measured on 2026-09-15: the host was down 04:44-08:07, so the
// 05:30 Auchan stock upload never ran. It did not vanish -- it landed in
// pending_task_retries and fired from there at 08:16, 166 minutes late, with
// no staleness check anywhere on that path. decideCatchUp is consulted by the
// cron scan and by nothing else, so one task obeyed two opposite policies
// depending on which entry point reached it.
//
// It only avoided a double upload because a human had been told to hold, while
// a colleague was deciding whether to upload by hand. For an outward-facing,
// non-idempotent task a late run does not arrive late -- it overwrites.

const MIN = 60_000
const outward = { type: 'task' as const, outwardFacing: true, catchUpMaxAgeMinutes: undefined }
const ordinary = { type: 'task' as const, outwardFacing: false, catchUpMaxAgeMinutes: undefined }
const NOW = 1_700_000_000_000

describe('isOutwardRetryTooStale', () => {
  it('leaves every unflagged task alone -- "never abandon" is unchanged', () => {
    // The whole point of opting in: a reporting task queued behind a busy
    // session must still fire whenever the session frees up, however late.
    const ancient = { first_attempt: NOW - 30 * 24 * 60 * MIN, occurrence_ms: NOW - 30 * 24 * 60 * MIN }
    expect(isOutwardRetryTooStale(ordinary, ancient, NOW)).toBe(false)
  })

  it('fires a flagged task that is still inside its budget', () => {
    const fresh = { first_attempt: NOW - 5 * MIN, occurrence_ms: NOW - 5 * MIN }
    expect(isOutwardRetryTooStale(outward, fresh, NOW)).toBe(false)
  })

  it('drops a flagged task past the per-type budget', () => {
    const budget = DEFAULT_CATCHUP_MAX_AGE_MIN.task
    expect(isOutwardRetryTooStale(outward, { first_attempt: NOW, occurrence_ms: NOW - (budget + 1) * MIN }, NOW)).toBe(true)
    // Exactly at the budget is still allowed -- strictly greater drops.
    expect(isOutwardRetryTooStale(outward, { first_attempt: NOW, occurrence_ms: NOW - budget * MIN }, NOW)).toBe(false)
  })

  it('measures from the DUE time, not from the first attempt (the real 09-15 shape)', () => {
    // The scheduler was down, so the row was created at boot: first_attempt is
    // minutes old while the occurrence is hours old. Reading first_attempt here
    // is exactly the bug -- it would call a 166-minute-old upload 9 minutes old.
    const row = { first_attempt: NOW - 9 * MIN, occurrence_ms: NOW - 166 * MIN }
    expect(isOutwardRetryTooStale({ ...outward, catchUpMaxAgeMinutes: 60 }, row, NOW)).toBe(true)
  })

  it('falls back to first_attempt when no occurrence was recorded', () => {
    // Pre-migration rows, and the call sites with no occurrence to speak of
    // (lost injection, give-up requeue). There the two genuinely coincide.
    expect(isOutwardRetryTooStale(outward, { first_attempt: NOW - 400 * MIN }, NOW)).toBe(true)
    expect(isOutwardRetryTooStale(outward, { first_attempt: NOW - MIN, occurrence_ms: null }, NOW)).toBe(false)
  })

  it('honours a per-task budget override', () => {
    const row = { first_attempt: NOW, occurrence_ms: NOW - 45 * MIN }
    expect(isOutwardRetryTooStale({ ...outward, catchUpMaxAgeMinutes: 30 }, row, NOW)).toBe(true)
    expect(isOutwardRetryTooStale({ ...outward, catchUpMaxAgeMinutes: 90 }, row, NOW)).toBe(false)
    // Negative means "no budget" for catchUpMaxAgeMs (Infinity) -- a flagged
    // task can opt back out of the guard without losing the flag's other uses.
    expect(isOutwardRetryTooStale({ ...outward, catchUpMaxAgeMinutes: -1 }, row, NOW)).toBe(false)
  })

  it('never reports a clock jump as staleness', () => {
    // A due time in the future (host clock moved backwards) must not read as
    // a huge negative age wrapping into "fire it".
    expect(isOutwardRetryTooStale(outward, { first_attempt: NOW, occurrence_ms: NOW + 60 * MIN }, NOW)).toBe(false)
  })
})
