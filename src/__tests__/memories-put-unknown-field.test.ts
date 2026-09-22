// eb063e6c / CSEND-2026-09-26: PUT and PATCH /api/memories/:id answered 200
// {ok:true} even when the body carried no field the endpoint recognises.
// Measured case (Max, msg 5068): {"ping":1} against memory 1568 left the row
// untouched but reported success. Two guarantees under test, mirroring
// kanban-put-unknown-field.test.ts (#1023):
//   1. an unknown field is rejected with 400, and the row is NOT touched --
//      even when it rides along with a real, known field;
//   2. the callers that exist today (dashboard UI content/tier/agent_id/
//      keywords, and a category-only tier move with no content) still work.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { Readable } from 'node:stream'
import { initDatabase, saveAgentMemory, getDb } from '../db.js'
import { tryHandleMemories } from '../web/routes/memories.js'
import type { RouteContext } from '../web/routes/types.js'

vi.mock('../config.js', async () => {
  const actual = await vi.importActual<typeof import('../config.js')>('../config.js')
  return { ...actual, MAIN_AGENT_ID: 'bob', ALLOWED_CHAT_ID: 'test-chat', OLLAMA_URL: '' }
})

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: vi.fn(), debug: vi.fn(), error: vi.fn() },
}))

function putCtx(id: number, payload: unknown, method: 'PUT' | 'PATCH' = 'PUT'): { ctx: RouteContext; out: { status: number; body: any } } {
  const out: { status: number; body: any } = { status: 200, body: null }
  const res: any = {
    writeHead(status: number) { out.status = status; return res },
    setHeader() { return res },
    end(chunk?: string) { if (chunk) out.body = JSON.parse(chunk) },
  }
  const req: any = Readable.from([Buffer.from(JSON.stringify(payload))])
  const url = new URL(`http://localhost:3420/api/memories/${id}`)
  return { ctx: { req, res, path: url.pathname, method, url } as RouteContext, out }
}

function readRow(id: number) {
  return getDb().prepare('SELECT content, category, keywords FROM memories WHERE id = ?').get(id) as
    { content: string; category: string; keywords: string | null } | undefined
}

describe('PUT/PATCH /api/memories/:id -- unknown fields are rejected, no silent no-op', () => {
  beforeEach(() => { initDatabase(':memory:') })

  it('rejects an unrecognised field with 400 and does NOT touch the row (the measured incident)', () => {
    const { id } = saveAgentMemory('bob', 'a long, carefully corrected memory body', 'hot', 'k1')
    const before = readRow(id)!
    const { ctx, out } = putCtx(id, { ping: 1 })
    return tryHandleMemories(ctx).then((handled) => {
      expect(handled).toBe(true)
      expect(out.status).toBe(400)
      expect(out.body.error).toContain('ping')
      const after = readRow(id)!
      expect(after).toEqual(before)
    })
  })

  it('rejects an unrecognised field even riding along with a real one, and does not write either', () => {
    const { id } = saveAgentMemory('bob', 'original content', 'warm', 'k1')
    const before = readRow(id)!
    const { ctx, out } = putCtx(id, { content: 'new content', description_append: 'more text' })
    return tryHandleMemories(ctx).then((handled) => {
      expect(handled).toBe(true)
      expect(out.status).toBe(400)
      expect(out.body.error).toContain('description_append')
      expect(readRow(id)!.content).toBe(before.content)
    })
  })

  it('accepts the dashboard UI payload shape (content, tier, agent_id, keywords) and writes it', async () => {
    const { id } = saveAgentMemory('bob', 'old content', 'warm', 'old-kw')
    const { ctx, out } = putCtx(id, { content: 'updated content', tier: 'cold', agent_id: 'bob', keywords: 'new-kw' })
    expect(await tryHandleMemories(ctx)).toBe(true)
    expect(out.status).toBe(200)
    const after = readRow(id)!
    expect(after.content).toBe('updated content')
    expect(after.category).toBe('cold')
    expect(after.keywords).toBe('new-kw')
  })

  it('accepts a category-only tier move with no content (Dream Engine hot->cold) and keeps content', async () => {
    const { id } = saveAgentMemory('bob', 'unchanged content', 'hot', 'k1')
    const { ctx, out } = putCtx(id, { category: 'cold' })
    expect(await tryHandleMemories(ctx)).toBe(true)
    expect(out.status).toBe(200)
    const after = readRow(id)!
    expect(after.content).toBe('unchanged content')
    expect(after.category).toBe('cold')
  })

  it('PATCH follows the same rule as PUT', async () => {
    const { id } = saveAgentMemory('bob', 'x', 'hot', 'k1')
    const { ctx, out } = putCtx(id, { ping: 1 }, 'PATCH')
    expect(await tryHandleMemories(ctx)).toBe(true)
    expect(out.status).toBe(400)
  })
})
