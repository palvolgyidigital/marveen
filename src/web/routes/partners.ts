import { randomUUID } from 'node:crypto'
import {
  listPartners, getPartner, createPartner, updatePartner,
  listPartnerContacts, createPartnerContact, updatePartnerContact, getPartnerContact, deletePartnerContact,
  listPartnerInteractions, createPartnerInteraction,
  listPartnerCards, linkCardToPartner, createKanbanCard, getKanbanCard, countKanbanChildren,
  deleteKanbanCard, revertIdeaFromKanban, listKanbanAttachmentsForCards,
} from '../../db.js'
import { execFile } from 'node:child_process'
import { readBody, json } from '../http-helpers.js'
import { torolKartyaCsatolmanyFajljait } from '../kanban-csatolmany.js'
import type { RouteContext } from './types.js'

type PartnerType = import('../../db.js').PartnerType
type InteractionKind = import('../../db.js').PartnerInteractionRow['kind']

// A 'feladatok' tipust David kerte, 2026-10-20 13:41 (Telegram 10196), szo szerint:
// "Uj tipus: Feladatok". Nem a megleve harom kozul valasztott, hanem ujat kert, es a
// tabla szerkezete az o dontese. A CHECK-lista a db.ts-ben tart ezzel lepest.
const VALID_TYPES = new Set<PartnerType>(['beszallito', 'vevo', 'szolgaltato', 'erdeklodo', 'partner', 'feladatok'])
const VALID_KINDS = new Set<InteractionKind>(['level', 'hivas', 'talalkozo', 'jegyzet', 'rendeles', 'egyeb'])

/** Seconds since epoch for "now", matching the rest of the schema. */
function nowSec(): number {
  return Math.floor(Date.now() / 1000)
}

/**
 * AZONOSITO-DUPLIKACIO KAPU A PARTNER-JEGYZETRE. David kerese, 2026-10-14
 * (Telegram 9738), szo szerint: "fontos, hogy minden partnernel majd ezt
 * ellenorizd amit felvittel a MM-ekhez: NEXT ID: 4945 / nem lehet duplikalas!!"
 *
 * MIT MER: a jegyzetbe irt `NEXT ID: <szam>` es `SAP kod: <X###>` ertekeket, es
 * azt, hogy ugyanaz az ertek szerepel-e MAS partner jegyzeteben. Egy duplikalt
 * NEXT ID azt jelenti, hogy ket CRM-partner ugyanarra az ERP-rekordra hivatkozik,
 * egy duplikalt SAP kod pedig azt, hogy ket partnerre ugyanaz az IDP-aruhazi
 * kimutatas futna le. Mindketto CSENDES hiba: a lap mindket helyen helyesnek
 * latszik, a jelentes viszont rossz partnerre keszul.
 *
 * MIERT KAPU ES NEM DETEKTOR: egy napi ellenorzes a BEIRAS UTAN talal, es addig
 * egy kimutatas mar kimehet a rossz adattal. A 409 a beirast allitja meg.
 *
 * AMIT SZANDEKOSAN NEM TILT: ha a partner a SAJAT, mar meglevo erteket tartja meg
 * (jegyzet-atirasnal ez a normalis eset). Csak a MAS partnernel meglevo ertek
 * utkozik, es a hibaszoveg MEGNEVEZI, melyik partnernel.
 */
const NEXT_ID_RE = /NEXT\s*ID\s*:\s*(\d+)/gi
const SAP_KOD_RE = /SAP\s*k[o\u00f3]d\s*:\s*([A-Za-z]\d{3})/gi

function azonositokAJegyzetbol(note: string | null | undefined): { nextIds: string[]; sapKodok: string[] } {
  const t = note ?? ''
  return {
    nextIds: [...t.matchAll(NEXT_ID_RE)].map(m => m[1]),
    sapKodok: [...t.matchAll(SAP_KOD_RE)].map(m => m[1].toUpperCase()),
  }
}

/** Visszaadja az ELSO utkozest, vagy null-t. A sajat id-t kihagyja (frissites). */
function jegyzetUtkozes(note: string | null | undefined, sajatId: string | null): string | null {
  const { nextIds, sapKodok } = azonositokAJegyzetbol(note)
  if (nextIds.length === 0 && sapKodok.length === 0) return null
  // EGY partneren BELUL sem lehet ket kulonbozo NEXT ID: az nem utkozes mas
  // partnerrel, hanem onmagaban hibas rekord, es ugyanugy rossz kimutatast ad.
  const egyediNext = [...new Set(nextIds)]
  if (egyediNext.length > 1) {
    return `ebben a jegyzetben TOBB NEXT ID van (${egyediNext.join(', ')}). Egy partnerhez egy ERP-rekord tartozik.`
  }
  const egyediSap = [...new Set(sapKodok)]
  if (egyediSap.length > 1) {
    return `ebben a jegyzetben TOBB SAP kod van (${egyediSap.join(', ')}). Egy partnerhez egy IDP-aruhaz tartozik.`
  }
  for (const p of listPartners({})) {
    if (sajatId && p.id === sajatId) continue
    const masik = azonositokAJegyzetbol(p.note)
    const nId = egyediNext.find(v => masik.nextIds.includes(v))
    if (nId) return `a NEXT ID ${nId} mar a "${p.name}" partnernel van (${p.id}). Duplikalas nem lehet.`
    const sK = egyediSap.find(v => masik.sapKodok.map(x => x.toUpperCase()).includes(v))
    if (sK) return `a SAP kod ${sK} mar a "${p.name}" partnernel van (${p.id}). Duplikalas nem lehet.`
  }
  return null
}

/**
 * NEV-DUPLIKACIO KAPU. David kerese, 2026-10-14 (Telegram 9741), szo szerint:
 * "uj partner letrehozasanal fontos, nem lehet ugyan az a partner majd 2x".
 *
 * KET NORMALIZALAS, es ez szandekos: egy azonosito-osszevetes akkor er valamit,
 * ha szigoruan ES normalizalva is mer. A `nevNorm` az ekezetet, a kis- es
 * nagybetut es a tobbes szokozt vonja ossze; a `nevSzigoru` ezen tul a cegformat
 * (Kft, Zrt, Bt, GmbH, Ltd...) es MINDEN irasjelet eldob. Igy a "MM Allee" es a
 * "MM Allee Kft." is utkozik, pedig betu szerint kulonbozik.
 *
 * AMIT NEM TESZ: nem keres HASONLOSAGOT (sem Levenshtein, sem reszszo). Egy
 * fuzzy kapu valodi, kulonbozo partnereket is blokkolna (MM Buda / MM Budaors),
 * es egy tevesen elutasitott letrehozas rosszabb, mint egy atnezheto duplikatum:
 * az elutasitas megallitja a munkat, a duplikatum viszont latszik es javithato.
 */
function nevNorm(s: string): string {
  return s.normalize('NFD').replace(/\p{Mn}/gu, '').toLowerCase().replace(/\s+/g, ' ').trim()
}

const CEGFORMA_RE = /\b(kft|zrt|bt|nyrt|kkt|ev|gmbh|ltd|inc|sro|sa|srl|oy|ab|as)\b/g

function nevSzigoru(s: string): string {
  return nevNorm(s).replace(CEGFORMA_RE, '').replace(/[^a-z0-9]+/g, '')
}

/** Az ELSO nev-utkozes, vagy null. A sajat id-t kihagyja (atnevezes). */
function nevUtkozes(nev: string, sajatId: string | null): string | null {
  const n = nevNorm(nev)
  const sz = nevSzigoru(nev)
  for (const p of listPartners({})) {
    if (sajatId && p.id === sajatId) continue
    if (nevNorm(p.name) === n) {
      return `"${p.name}" mar szerepel a partnerek kozott (${p.id}). Ugyanaz a partner nem lehet ketszer.`
    }
    // A szigoru egyezes kulon szoveget kap: itt a NEV betu szerint kulonbozik,
    // es a hasznalonak latnia kell, MIERT utkozik megis.
    if (sz.length > 0 && nevSzigoru(p.name) === sz) {
      return `"${p.name}" mar szerepel a partnerek kozott (${p.id}), es a ket nev csak cegformaban vagy irasjelben ter el. Ugyanaz a partner nem lehet ketszer.`
    }
  }
  return null
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
    const nevUtk = nevUtkozes(name, null)
    if (nevUtk) { json(res, { error: nevUtk }, 409); return true }
    const utkozes = jegyzetUtkozes(data.note as string | undefined, null)
    if (utkozes) { json(res, { error: utkozes }, 409); return true }
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
  const mSub = path.match(/^\/api\/partners\/([^/]+)\/(contacts|interactions|cards|aruhaz-kimutatas)$/)

  // --- one partner, with everything that hangs off it ---------------------
  if (m && method === 'GET') {
    const id = decodeURIComponent(m[1])
    const partner = getPartner(id)
    if (!partner) { json(res, { error: 'not found' }, 404); return true }
    // includeDone defaults to true: David asked that closed tasks stay visible,
    // with an easy toggle, rather than vanish.
    const includeDone = url.searchParams.get('done') !== '0'
    const cards = listPartnerCards(id, includeDone)
    // A csatolmanyok EGY lekerdezessel jonnek, nem kartyankent: a partner-lap
    // husz feladatot is rajzolhat, es ott az N+1 mar latszana a megnyitason.
    const csatolmanyok = listKanbanAttachmentsForCards(cards.map(c => c.id))
    json(res, {
      partner,
      contacts: listPartnerContacts(id),
      interactions: listPartnerInteractions(id),
      cards: cards.map(c => ({
        ...c,
        // stored_path NEM megy ki: az szerver-oldali utvonal, a kliens az id-vel
        // tolti le a fajlt.
        attachments: (csatolmanyok.get(c.id) ?? []).map(({ stored_path: _ut, ...tobbi }) => tobbi),
      })),
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
    if (typeof patch.name === 'string') {
      const ujNev = patch.name.trim()
      if (!ujNev) { json(res, { error: 'name cannot be empty' }, 400); return true }
      // Az ATNEVEZES ugyanugy tud duplikatumot csinalni, mint a letrehozas, csak
      // kesobb es csendesebben: a lista ket egyforma sort fog mutatni.
      const nevUtk = nevUtkozes(ujNev, id)
      if (nevUtk) { json(res, { error: nevUtk }, 409); return true }
      patch.name = ujNev
    }
    if (patch.note !== undefined) {
      const utkozes = jegyzetUtkozes(patch.note as string, id)
      if (utkozes) { json(res, { error: utkozes }, 409); return true }
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

  // Egy kapcsolattarto modositasa. David kerese, 2026-10-14 (Telegram 9720):
  // "Kapcsolattartokat szinten lehessen szerkeszteni". Sajat utvonal, nem a
  // partner PUT-ja: a kapcsolattarto onallo rekord, es egy partner-patchbe
  // becsomagolva nem lehetne egy sort celozni belole.
  const mContact = path.match(/^\/api\/partners\/([^/]+)\/contacts\/([^/]+)$/)
  if (mContact && method === 'PUT') {
    const partnerId = decodeURIComponent(mContact[1])
    const contactId = decodeURIComponent(mContact[2])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const current = getPartnerContact(contactId)
    if (!current) { json(res, { error: 'contact not found' }, 404); return true }
    // A kapcsolattarto MAS partnere alatt is letezhet: ha az utvonal partnere nem
    // egyezik a rekorddal, ez nem "nem talaltam", hanem rossz utvonal. Nemán atirni
    // egy masik partner kapcsolattartojat a legdragabb kimenet lenne.
    if (current.partner_id !== partnerId) {
      json(res, { error: 'contact belongs to another partner' }, 409); return true
    }
    const data = JSON.parse((await readBody(req)).toString()) as Record<string, unknown>
    const patch: Record<string, unknown> = {}
    if (data.name !== undefined) {
      const name = typeof data.name === 'string' ? data.name.trim() : ''
      // Nev nelkul a sor azonosithatatlanna valna a lapon, ezert ez 400, nem
      // csendes elfogadas -- ugyanaz a kikotes, mint a POST-on.
      if (!name) { json(res, { error: 'name cannot be empty' }, 400); return true }
      patch.name = name
    }
    for (const k of ['email', 'phone', 'role', 'note'] as const) {
      // Az ures sztring itt SZANDEKOS torles -> NULL, hogy egy felvitt rossz
      // telefonszamot ki lehessen urteni, ne csak atirni.
      if (data[k] !== undefined) {
        const v = typeof data[k] === 'string' ? (data[k] as string).trim() : data[k]
        patch[k] = v === '' ? null : v
      }
    }
    if (data.status !== undefined) {
      if (data.status !== 'active' && data.status !== 'inactive') {
        json(res, { error: "status must be 'active' or 'inactive'" }, 400); return true
      }
      patch.status = data.status
    }
    if (Object.keys(patch).length === 0) {
      json(res, { error: 'no writable field given. Accepted: name, email, phone, role, note, status' }, 400)
      return true
    }
    json(res, { ok: updatePartnerContact(contactId, patch) })
    return true
  }

  if (mContact && method === 'DELETE') {
    const partnerId = decodeURIComponent(mContact[1])
    const contactId = decodeURIComponent(mContact[2])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const current = getPartnerContact(contactId)
    if (!current) { json(res, { error: 'contact not found' }, 404); return true }
    // Ugyanaz a kikotes, mint a PUT-on, es itt MEG dragabb: egy MAS partner
    // kapcsolattartojanak torlese visszafordithatatlan.
    if (current.partner_id !== partnerId) {
      json(res, { error: 'contact belongs to another partner' }, 409); return true
    }
    json(res, { ok: deletePartnerContact(contactId) })
    return true
  }

  // Egy partnerhez kotott kartya (feladat vagy lepes) torlese a partner lapjarol.
  // David kerese, 2026-10-14 (Telegram 9734): "torolni lehet sort?"
  const mCard = path.match(/^\/api\/partners\/([^/]+)\/cards\/([^/]+)$/)
  if (mCard && method === 'DELETE') {
    const partnerId = decodeURIComponent(mCard[1])
    const cardId = decodeURIComponent(mCard[2])
    if (!getPartner(partnerId)) { json(res, { error: 'partner not found' }, 404); return true }
    const card = getKanbanCard(cardId)
    if (!card) { json(res, { error: 'card not found' }, 404); return true }
    if (card.partner_id !== partnerId) {
      json(res, { error: 'card belongs to another partner' }, 409); return true
    }
    // A LEPESEKKEL RENDELKEZO FELADAT TORLESE TILTOTT, es ez tudatos szukites,
    // nem technikai korlat. A `parent_id` nem ON DELETE CASCADE, tehat a lepesek
    // nem tunnenek el, csak ARVAN maradnanak: a partner-lap a lista vegen mutatna
    // oket, kimondva, hogy a szulojuk nem latszik. Egy torles, ami eltunteti a
    // feladatot es kint hagy ket felszabadult lepest, rosszabb, mint egy
    // visszautasitas, ami megmondja a sorrendet.
    const lepesek = countKanbanChildren(cardId)
    if (lepesek > 0) {
      json(res, {
        error: `ennek a feladatnak ${lepesek} lepese van. Eloszor a lepeseket torold, utana a feladatot.`,
        steps: lepesek,
      }, 409)
      return true
    }
    // UGYANAZ a ket lepes, mint a kanban sajat DELETE route-jan (kanban.ts):
    // eloszb a kanbanra emelt otlet visszaforditasa, aztan a kartya torlese.
    // Szandekosan a FUGGVENYEKET hivjuk, nem a sajat HTTP-vegpontunkat: egy
    // sajat magahoz szolo HTTP-keres auth-ot es portot igenyelne, es egy
    // mukodo kod-utat cserelne egy halozati uttal, ami elromolhat.
    revertIdeaFromKanban(cardId)
    // Ugyanaz, mint a kanban-uton: a csatolmany-fajlok a sorok torlese ELOTT
    // mennek, kulonben arvan maradnanak a lemezen.
    torolKartyaCsatolmanyFajljait(cardId)
    if (deleteKanbanCard(cardId)) { json(res, { ok: true }); return true }
    json(res, { error: 'card not found' }, 404)
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
    // LEPES: a feladat alkartyaja. David dontese, 2026-10-14 (Telegram 9727, az
    // (a) valtozat): minden lepes onallo alfeladat, sajat felelossel es
    // hataridovel, es a kanban tablan is latszik. A kanban `parent_id`-ja ezt
    // mar tudja, uj tarolo nem kellett hozza.
    let parentId: string | undefined
    if (data.parent_id !== undefined && data.parent_id !== null && data.parent_id !== '') {
      if (typeof data.parent_id !== 'string') { json(res, { error: 'parent_id must be a string' }, 400); return true }
      const parent = getKanbanCard(data.parent_id)
      if (!parent) { json(res, { error: 'parent card not found' }, 404); return true }
      // A szulo UGYANAHHOZ a partnerhez kell tartozzon. Kulonben egy lepes egy MAS
      // partner feladata ala kerulne, es a partner-lapon egyik helyen sem latszana
      // rendesen -- nema adatvesztes, HTTP 200-cal.
      if (parent.partner_id !== partnerId) {
        json(res, { error: 'parent card belongs to another partner' }, 409); return true
      }
      // Egy lepesnek NE legyen lepese: a lap egy szintet rajzol, es egy melyebb
      // lanc ott lathatatlan maradna. Ez tudatos korlat, nem technikai.
      if (parent.parent_id) {
        json(res, { error: 'a step cannot have steps of its own (one level only)' }, 400); return true
      }
      parentId = data.parent_id
    }
    const id = randomUUID().slice(0, 8)
    createKanbanCard({
      id,
      title,
      description: (data.description as string) ?? undefined,
      status: status as 'planned' | 'in_progress' | 'waiting' | 'done',
      assignee: (data.assignee as string) ?? undefined,
      priority: priority as 'low' | 'normal' | 'high' | 'urgent',
      project: (data.project as string) ?? undefined,
      ...(parentId ? { parent_id: parentId } : {}),
      ...(due ? { due_date: due as unknown as number } : {}),
    })
    linkCardToPartner(id, partnerId)
    json(res, { ok: true, id })
    return true
  }

  // Aruhaz-kimutatas gomb a partner lapjarol. David kerese, 2026-10-14 (msg 9660,
  // 9663): a MediaMarkt aruhazaknal legyen gomb, ami lekeri az IDP-riportot es
  // osszeveti a sajat keszletunkkel.
  //
  // A GOMB CSAK OTT JELENIK MEG, AHOL VAN SAP-KOD, es ez nem kenyelmi szures: a
  // SAP-kod AZ aruhaz-azonosito, ami nelkul a riport le sem kerdezheto. A 43
  // MediaMarkt partner note-jaban ott all, mashol nem -- tehat a "minden MediaMarkt
  // partnernel" feltetel GEPILEG ellenorizheto, nem nev-egyezesbol talalgatott.
  if (mSub && mSub[2] === 'aruhaz-kimutatas' && method === 'POST') {
    const partnerId = decodeURIComponent(mSub[1])
    const p = getPartner(partnerId)
    if (!p) { json(res, { error: 'partner not found' }, 404); return true }
    const sap = (p.note ?? '').match(/SAP k[oó]d:\s*([A-Z]\d{3})/)
    if (!sap) {
      json(res, { error: 'ehhez a partnerhez nincs IDP aruhazi SAP kod rogzitve' }, 400)
      return true
    }
    // A szkript letolti a friss IDP-riportot es osszeveti a Next-exporttal.
    // Hosszu muvelet (bejelentkezes + letoltes), ezert bo idokorlat; a timeout
    // NEM hiba-elnyelo: lejartakor hibat adunk vissza, nem ures kimutatast.
    const out = await new Promise<{ ok: boolean; text: string }>((resolve) => {
      execFile('python3', ['scripts/aruhaz-kimutatas.py', sap[1]],
        { cwd: '/home/pdb/marveen', timeout: 10 * 60 * 1000, maxBuffer: 8 * 1024 * 1024 },
        (err, stdout, stderr) => {
          if (err) resolve({ ok: false, text: String(stderr || err.message).slice(0, 2000) })
          else resolve({ ok: true, text: stdout })
        })
    })
    if (!out.ok) { json(res, { error: out.text }, 500); return true }
    // Blokkokra bontva adjuk vissza: a kimutatas szekciónkent kulon uzenet,
    // mert egyben osszefolyik (David, msg 9652).
    const blokkok = out.text.split(/^===== UZENET \d+ =====$/m)
      .map((s) => s.trim()).filter(Boolean)
    json(res, { ok: true, sap: sap[1], blokkok })
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
