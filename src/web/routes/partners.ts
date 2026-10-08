import { randomUUID } from 'node:crypto'
import {
  listPartners, getPartner, createPartner, updatePartner,
  listPartnerContacts, createPartnerContact,
  listPartnerInteractions, createPartnerInteraction,
  listPartnerCards, linkCardToPartner, createKanbanCard,
} from '../../db.js'
import { readBody, json } from '../http-helpers.js'
import type { RouteContext } from './types.js'

type PartnerType = import('../../db.js').PartnerType
type InteractionKind = import('../../db.js').PartnerInteractionRow['kind']

const VALID_TYPES = new Set<PartnerType>(['beszallito', 'vevo', 'szolgaltato', 'erdeklodo', 'partner'])
const VALID_KINDS = new Set<InteractionKind>(['level', 'hivas', 'talalkozo', 'jegyzet', 'rendeles', 'egyeb'])

/** Seconds since epoch for "now", matching the rest of the schema. */
function nowSec(): number {
  return Math.floor(Date.now() / 1000)
}

/**
 * A due date arrives either as an epoch number or as YYYY-MM-DD. The string form
 * is parsed as LOCAL midnight, not UTC: a deadline typed by a colleague in Budapest
 * means that day here, and UTC parsing silently shifts it by the offset.
 */
function parseDue(v: unknown): number | null | undefined {
  if (v === undefined) return undefined
  if (v === null || v === '') return null
  if (typeof v === 'number' && Number.isFinite(v)) return Math.floor(v)
  if (typeof v === 'string') {
    const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (m) return Math.floor(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() / 1000)
    const t = Date.parse(v)
    if (!Number.isNaN(t)) return Math.floor(t / 1000)
  }
  return undefined
}

export async function tryHandlePartners(ctx: RouteContext): Promise<boolean> {
  const { res, req, path, method, url } = ctx

  // --- list ---------------------------------------------------------------
  if (path === '/api/partners' && method === 'GET') {
    const type = url.searchParams.get('type') ?? undefined
    if (type && !VALID_TYPES.has(type as PartnerType)) {
      json(res, { error: 'unknown type' }, 400); return true
    }
    const rows = listPartners({
      type: type as PartnerType | undefined,
      owner: url.searchParams.get('owner') ?? undefined,
      status: (url.searchParams.get('status') as 'active' | 'archived' | null) ?? undefined,
      q: url.searchParams.get('q') ?? undefined,
      // A feladat felelose, nem a partner ownere -- David 2026-10-08 11:46.
      assignee: url.searchParams.get('assignee') ?? undefined,
    })
    const today = nowSec()
    // The three buckets the daily view is built from. A partner with no next step
    // is NOT "fine by default" -- that is the state we most want to see.
    type WithCounts = typeof rows[number] & { open_tasks: number; all_tasks: number }
    const summary = {
      total: rows.length,
      lejart: rows.filter(r => r.next_step_due !== null && r.next_step_due < today).length,
      nincs_lepes: rows.filter(r => r.next_step_due === null).length,
      // David 2026-10-08: a listan a FELADAT-darabszam a kerdes, nem a kovetkezo lepes.
      nyitott_feladat: rows.reduce((a, r) => a + ((r as WithCounts).open_tasks || 0), 0),
      osszes_feladat: rows.reduce((a, r) => a + ((r as WithCounts).all_tasks || 0), 0),
      van_nyitott: rows.filter(r => ((r as WithCounts).open_tasks || 0) > 0).length,
    }
    json(res, { partners: rows, summary })
    return true
  }

  // --- create -------------------------------------------------------------
  if (path === '/api/partners' && method === 'POST') {
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    const name = typeof data.name === 'string' ? data.name.trim() : ''
    if (!name) { json(res, { error: 'name required' }, 400); return true }
    const type = (data.type as PartnerType) ?? 'partner'
    if (!VALID_TYPES.has(type)) { json(res, { error: 'unknown type' }, 400); return true }
    const due = parseDue(data.next_step_due)
    if (due === undefined && data.next_step_due !== undefined) {
      json(res, { error: 'next_step_due must be epoch seconds or YYYY-MM-DD' }, 400); return true
    }
    const id = randomUUID().slice(0, 8)
    createPartner({
      id,
      name,
      type,
      owner: (data.owner as string) ?? null,
      country: (data.country as string) ?? null,
      note: (data.note as string) ?? null,
      next_step: (data.next_step as string) ?? null,
      next_step_due: due ?? null,
      next_step_owner: (data.next_step_owner as string) ?? null,
      status: 'active',
    })
    json(res, { ok: true, id })
    return true
  }

  const m = path.match(/^\/api\/partners\/([^/]+)$/)
  const mSub = path.match(/^\/api\/partners\/([^/]+)\/(contacts|interactions|cards)$/)

  // --- one partner, with everything that hangs off it ---------------------
  if (m && method === 'GET') {
    const id = decodeURIComponent(m[1])
    const partner = getPartner(id)
    if (!partner) { json(res, { error: 'not found' }, 404); return true }
    // includeDone defaults to true: David asked that closed tasks stay visible,
    // with an easy toggle, rather than vanish.
    const includeDone = url.searchParams.get('done') !== '0'
    json(res, {
      partner,
      contacts: listPartnerContacts(id),
      interactions: listPartnerInteractions(id),
      cards: listPartnerCards(id, includeDone),
    })
    return true
  }

  if (m && method === 'PUT') {
    const id = decodeURIComponent(m[1])
    if (!getPartner(id)) { json(res, { error: 'not found' }, 404); return true }
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    if (data.type !== undefined && !VALID_TYPES.has(data.type as PartnerType)) {
      json(res, { error: 'unknown type' }, 400); return true
    }
    const patch: Record<string, unknown> = {}
    for (const k of ['name', 'type', 'owner', 'country', 'note', 'next_step', 'next_step_owner', 'status']) {
      if (data[k] !== undefined) patch[k] = data[k]
    }
    const due = parseDue(data.next_step_due)
    if (data.next_step_due !== undefined) {
      if (due === undefined) { json(res, { error: 'next_step_due must be epoch seconds or YYYY-MM-DD' }, 400); return true }
      patch.next_step_due = due
    }
    json(res, { ok: updatePartner(id, patch) })
    return true
  }

  // --- contacts -----------------------------------------------------------
  if (mSub && mSub[2] === 'contacts' && method === 'POST') {
    const partnerId = decodeURIComponent(mSub[1])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    const name = typeof data.name === 'string' ? data.name.trim() : ''
    if (!name) { json(res, { error: 'name required' }, 400); return true }
    const id = randomUUID().slice(0, 8)
    createPartnerContact({
      id,
      partner_id: partnerId,
      name,
      email: (data.email as string) ?? null,
      phone: (data.phone as string) ?? null,
      role: (data.role as string) ?? null,
      note: (data.note as string) ?? null,
      status: 'active',
    })
    json(res, { ok: true, id })
    return true
  }

  // --- interactions -------------------------------------------------------
  if (mSub && mSub[2] === 'interactions' && method === 'POST') {
    const partnerId = decodeURIComponent(mSub[1])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    const summary = typeof data.summary === 'string' ? data.summary.trim() : ''
    if (!summary) { json(res, { error: 'summary required' }, 400); return true }
    const kind = (data.kind as InteractionKind) ?? 'jegyzet'
    if (!VALID_KINDS.has(kind)) { json(res, { error: 'unknown kind' }, 400); return true }
    const happened = parseDue(data.happened_at)
    if (data.happened_at !== undefined && happened === undefined) {
      json(res, { error: 'happened_at must be epoch seconds or YYYY-MM-DD' }, 400); return true
    }
    const id = randomUUID().slice(0, 8)
    createPartnerInteraction({
      id,
      partner_id: partnerId,
      contact_id: (data.contact_id as string) ?? null,
      happened_at: happened ?? nowSec(),
      kind,
      summary,
      source: (data.source as string) ?? null,
      created_by: ctx.auth?.user ?? (data.created_by as string) ?? null,
    })
    json(res, { ok: true, id })
    return true
  }

  // Uj feladat a partner lapjarol. David kerese, 2026-10-08: a partner-lapon
  // kozvetlenul lehessen feladatot felvenni. EGY lista marad: ez egy rendes
  // kanban-kartya, csak a partner_id ra van allitva.
  if (mSub && mSub[2] === 'cards' && method === 'POST') {
    const partnerId = decodeURIComponent(mSub[1])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    const title = typeof data.title === 'string' ? data.title.trim() : ''
    if (!title) { json(res, { error: 'title required' }, 400); return true }
    const status = (data.status as string) ?? 'planned'
    if (!['planned', 'in_progress', 'waiting', 'done'].includes(status)) {
      json(res, { error: 'unknown status' }, 400); return true
    }
    const priority = (data.priority as string) ?? 'normal'
    if (!['low', 'normal', 'high', 'urgent'].includes(priority)) {
      json(res, { error: 'unknown priority' }, 400); return true
    }
    // A due_date a kanbanban SZOVEG (YYYY-MM-DD), nem epoch -- ne alakitsd at.
    const due = typeof data.due_date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(data.due_date)
      ? data.due_date : undefined
    if (data.due_date && !due) { json(res, { error: 'due_date must be YYYY-MM-DD' }, 400); return true }
    const id = randomUUID().slice(0, 8)
    createKanbanCard({
      id,
      title,
      description: (data.description as string) ?? undefined,
      status: status as 'planned' | 'in_progress' | 'waiting' | 'done',
      assignee: (data.assignee as string) ?? undefined,
      priority: priority as 'low' | 'normal' | 'high' | 'urgent',
      project: (data.project as string) ?? undefined,
      ...(due ? { due_date: due as unknown as number } : {}),
    })
    linkCardToPartner(id, partnerId)
    json(res, { ok: true, id })
    return true
  }

  if (mSub && mSub[2] === 'cards' && method === 'GET') {
    const partnerId = decodeURIComponent(mSub[1])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    json(res, { cards: listPartnerCards(partnerId, url.searchParams.get('done') !== '0') })
    return true
  }

  return false
}
