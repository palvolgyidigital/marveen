// eb063e6c / CSEND-2026-09-26: PUT and PATCH /api/memories/:id used to accept
// any JSON body, silently drop the fields it did not recognise, and still
// answer 200 {ok:true} -- {"ping":1} against a real memory id changed nothing
// and looked like a success (Max, msg 5068). Same failure family as #1023
// (kanban PUT) and the 2026-07-27 securityProfile incident on PUT
// /api/agents/:name. checkMemoryPutFields is the extracted, testable rule.
import { describe, it, expect } from 'vitest'
import { checkMemoryPutFields, MEMORY_PUT_WRITABLE_FIELDS } from '../web/memory-put-fields.js'

describe('checkMemoryPutFields', () => {
  it('accepts the payloads real callers send', () => {
    // dashboard UI (web/app.js saveMemBtn): content, tier, agent_id, keywords
    expect(checkMemoryPutFields({ content: 'x', tier: 'warm', agent_id: 'bob', keywords: 'a, b' }).ok).toBe(true)
    // documented curl recipe (hot-tier-memory-cleanup skill): content only
    expect(checkMemoryPutFields({ content: 'x' }).ok).toBe(true)
    // category-only tier move (Dream Engine, hot -> cold), no content resend
    expect(checkMemoryPutFields({ category: 'cold' }).ok).toBe(true)
    // updated_by write-trace alongside a content edit
    expect(checkMemoryPutFields({ content: 'x', updated_by: 'bob' }).ok).toBe(true)
    expect(checkMemoryPutFields({}).ok).toBe(true)
  })

  it('rejects an unrecognised field even when it rides along with a real one', () => {
    const r = checkMemoryPutFields({ content: 'x', description_append: 'more text' })
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.rejected).toEqual(['description_append'])
    expect(r.message).toContain('description_append')
    for (const f of MEMORY_PUT_WRITABLE_FIELDS) expect(r.message).toContain(f)
  })

  it('rejects a body with zero recognised fields (the measured incident)', () => {
    const r = checkMemoryPutFields({ ping: 1 })
    expect(r.ok).toBe(false)
    if (r.ok) return
    expect(r.rejected).toEqual(['ping'])
  })

  it('rejects a non-object body', () => {
    expect(checkMemoryPutFields(null).ok).toBe(false)
    expect(checkMemoryPutFields('x').ok).toBe(false)
    expect(checkMemoryPutFields(42).ok).toBe(false)
  })
})
