import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { resolveBoundChannel } from '../web/schedule-runner.js'

// Regression guard for 2026-09-02 (Pedro, msg 2611): POST /api/schedules
// silently dropped the telegramChatId field. The request body's type cast
// didn't list it and the writeScheduledTask() call built a fresh object
// literal that didn't copy it either, so a POST that pinned e.g. David's
// chat_id landed on disk with NO telegramChatId at all. resolveBoundChannel
// then fell back to the creating agent's own owner chat -- the task's result
// would silently go to the WRONG recipient (main agent) or be silently
// skipped (sub-agent with 2+ DM contacts, WRONGRECIP819's ambiguous branch),
// with the response still saying ok:true. PUT /api/schedules/<name> was
// never affected: it passes the parsed body straight through to
// writeScheduledTask() instead of rebuilding a literal.
describe('POST /api/schedules: telegramChatId is not silently dropped', () => {
  const src = readFileSync(join(__dirname, '..', 'web', 'routes', 'schedules.ts'), 'utf-8')

  function postHandlerBody(): string {
    const start = src.indexOf("path === '/api/schedules' && method === 'POST'")
    expect(start, 'POST /api/schedules handler not found').toBeGreaterThan(0)
    const end = src.indexOf("scheduleUpdateMatch", start)
    return src.slice(start, end)
  }

  it('the request body type cast includes telegramChatId', () => {
    const body = postHandlerBody()
    expect(body).toMatch(/telegramChatId\?:\s*string/)
  })

  it('the writeScheduledTask() call actually copies telegramChatId through', () => {
    const body = postHandlerBody()
    const writeCallStart = body.indexOf('writeScheduledTask(name, {')
    expect(writeCallStart, 'writeScheduledTask(name, {...}) literal not found').toBeGreaterThan(-1)
    const writeCallEnd = body.indexOf('})', writeCallStart)
    const literal = body.slice(writeCallStart, writeCallEnd)
    expect(literal).toContain('telegramChatId')
  })

  it('the response reports the ACTUALLY RESOLVED delivery target, not just ok:true', () => {
    // Pedro's second ask: a caller must be able to catch a misconfiguration
    // from the response itself, not only by re-reading task-config.json.
    const body = postHandlerBody()
    expect(body).toContain('resolveBoundChannel(agentName')
    expect(body).toMatch(/json\(res,\s*\{\s*ok:\s*true,\s*name,\s*delivery\s*\}\)/)
  })

  it('sanity: resolveBoundChannel actually uses the pinned chat_id (no filesystem needed)', () => {
    // Proves the SECOND half of the pipe (resolution) already worked before
    // this fix -- the bug was purely the FIRST half (the field never reaching
    // resolveBoundChannel because it never reached disk).
    expect(resolveBoundChannel('sam', { telegramChatId: '8918812779' }).chatId).toBe('8918812779')
  })
})
