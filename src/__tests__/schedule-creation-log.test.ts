import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { formatScheduleCreationLogLine } from '../web/routes/schedules.js'

// Regression guard for 2026-10-01 (kártya 9930fecf): egy frissen létrehozott,
// közeli időpontra szóló egyszeri feladat kétszer nem sült el, és a
// gyökér-ok vizsgálatakor KIDERÜLT, hogy semmilyen nyom nem marad a
// létrehozáskori configról -- a task_runs 24 óránként ürül, a feladat
// könyvtára fire után eltűnik. Ez a teszt azt a naplót fedi, ami a
// KÖVETKEZŐ elbukásnál már ad mit mérni.
describe('formatScheduleCreationLogLine (SCHEDCREATELOG930)', () => {
  it('writes one JSON line with the full config and the resolved delivery', () => {
    const line = formatScheduleCreationLogLine({
      at: Date.parse('2026-10-01T06:27:00.000Z'),
      name: 'next-231-igazolas-1203',
      schedule: '3 12 22 9 *',
      type: 'task',
      agent: 'bob',
      skipIfBusy: false,
      telegramChatId: undefined,
      createdBy: 'pedro',
      resolvedChatId: null,
      ambiguousCandidates: 4,
    })
    expect(line.endsWith('\n')).toBe(true)
    const row = JSON.parse(line)
    expect(row).toMatchObject({
      ts: '2026-10-01T06:27:00.000Z',
      name: 'next-231-igazolas-1203',
      schedule: '3 12 22 9 *',
      type: 'task',
      agent: 'bob',
      skipIfBusy: false,
      telegramChatId: null,
      createdBy: 'pedro',
      resolvedChatId: null,
      ambiguousCandidates: 4,
    })
  })

  it('a missing createdBy is recorded as "unknown", not silently omitted', () => {
    // A sub-agent can never reach this route (self-pace-gate.mjs blocks the
    // POST before it leaves the agent's own Bash tool) -- but if the field
    // is ever missing, the log must say so plainly, not guess "pedro".
    const row = JSON.parse(formatScheduleCreationLogLine({
      at: 0, name: 'x', schedule: '* * * * *', type: 'task', agent: 'pedro',
      skipIfBusy: false, telegramChatId: undefined, createdBy: undefined,
      resolvedChatId: null, ambiguousCandidates: undefined,
    }))
    expect(row.createdBy).toBe('unknown')
  })

  it('an unresolved telegramChatId and a resolved ambiguousCandidates both serialise as null, not undefined/omitted', () => {
    const row = JSON.parse(formatScheduleCreationLogLine({
      at: 0, name: 'x', schedule: '* * * * *', type: 'heartbeat', agent: 'sam',
      skipIfBusy: true, telegramChatId: undefined, createdBy: 'pedro',
      resolvedChatId: '8918812779', ambiguousCandidates: undefined,
    }))
    expect(row).toHaveProperty('telegramChatId', null)
    expect(row).toHaveProperty('ambiguousCandidates', null)
    expect(row.resolvedChatId).toBe('8918812779')
  })
})

describe('POST /api/schedules: the creation log is actually wired in (source contract)', () => {
  const src = readFileSync(join(__dirname, '..', 'web', 'routes', 'schedules.ts'), 'utf-8')

  function postHandlerBody(): string {
    const start = src.indexOf("path === '/api/schedules' && method === 'POST'")
    expect(start, 'POST /api/schedules handler not found').toBeGreaterThan(0)
    const end = src.indexOf('scheduleUpdateMatch', start)
    return src.slice(start, end)
  }

  it('logs AFTER resolveBoundChannel, so the delivery resolution is captured, and BEFORE the response', () => {
    const body = postHandlerBody()
    const deliveryIdx = body.indexOf('resolveBoundChannel(agentName')
    const logIdx = body.indexOf('appendScheduleCreationLog(')
    const jsonIdx = body.indexOf('json(res, { ok: true, name, delivery }')
    expect(deliveryIdx, 'resolveBoundChannel call not found').toBeGreaterThan(-1)
    expect(logIdx, 'appendScheduleCreationLog call not found').toBeGreaterThan(-1)
    expect(jsonIdx, 'the ok:true response not found').toBeGreaterThan(-1)
    expect(logIdx).toBeGreaterThan(deliveryIdx)
    expect(jsonIdx).toBeGreaterThan(logIdx)
  })

  it('the request body type cast includes createdBy', () => {
    const body = postHandlerBody()
    expect(body).toMatch(/createdBy\?:\s*string/)
  })
})
