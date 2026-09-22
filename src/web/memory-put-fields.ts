// Which fields PUT/PATCH /api/memories/:id will actually act on.
//
// Split out of the route handler for the same reason as checkAgentPutFields
// (agent-put-fields.ts): the rule needs its own test, because its failure mode
// is silence. Background (kanban card eb063e6c, CSEND-2026-09-26): the handler
// used to destructure the fields it understood, silently drop everything else,
// and answer 200 {ok:true} even when the body carried NO recognised field at
// all -- {"ping":1} against a real memory id updated nothing and still looked
// like a success. Same failure family as #1023 (kanban PUT) and the
// securityProfile incident on PUT /api/agents/:name (2026-07-27): a caller who
// sees 200 does not read back, so a typoed or renamed field name disappears
// without a trace.
//
// The fix mirrors those two precedents rather than inventing a narrower rule:
// reject any UNKNOWN field with 400, not just a body with zero known fields --
// measured (kanban card eb063e6c comments) against every caller in the fleet
// (dashboard UI, the documented curl recipes, hu_guard.py, every agent's own
// CLAUDE.md / .claude/skills) and none of them send an unrecognised field, so
// the strict rule costs nothing today and catches more typos tomorrow.

export const MEMORY_PUT_WRITABLE_FIELDS = [
  'content', 'category', 'tier', 'agent_id', 'keywords', 'updated_by',
] as const

export type MemoryPutFieldCheck =
  | { ok: true }
  | { ok: false; rejected: string[]; message: string }

// Rejects the UNKNOWN rather than allow-listing the known at the call site: a
// field a caller mistypes or a client adds tomorrow surfaces as a loud 400
// instead of disappearing quietly.
export function checkMemoryPutFields(body: unknown): MemoryPutFieldCheck {
  if (body === null || typeof body !== 'object') {
    return { ok: false, rejected: [], message: 'Request body must be a JSON object.' }
  }
  const writable = new Set<string>(MEMORY_PUT_WRITABLE_FIELDS)
  const rejected = Object.keys(body as Record<string, unknown>).filter((k) => !writable.has(k))
  if (!rejected.length) return { ok: true }

  const message = `Unknown field(s): ${rejected.join(', ')}. Accepted: ${MEMORY_PUT_WRITABLE_FIELDS.join(', ')}`
  return { ok: false, rejected, message }
}
