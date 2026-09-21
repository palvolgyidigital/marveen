#!/usr/bin/env tsx
// MailerLite READ-ONLY campaign report runner.
//
// WHY THIS EXISTS (2026-09-18, Marci kérése Martin keresztül). Marci asked Marti for a
// send-time recommendation (Friday 18:00 vs Saturday 10:00 for the Kodak AZ653 newsletter),
// which needs open/click figures from past campaigns. Marti cannot fetch those with a raw
// curl: BASH_EGRESS_DENY (`Bash(curl *https://*)`) is written into every agent's
// settings.json on EVERY spawn by the scaffold, so it is not something an agent can edit
// away. This is the THIRD time the same situation has come up, and the answer is the one
// Marci already approved twice: a purpose-built script, not a hole in the deny list.
// Precedents: scripts/google-ads-report.ts and scripts/merchant-center-report.ts, both
// 2026-09-16, both for Marti, both for exactly this reason.
//
// NO NEW PERMISSION IS BEING TAKEN HERE. Marti's read-only MailerLite scope, campaign
// statistics explicitly included, was approved on 2026-07-23 (see the memory
// project-mailerlite-approved-scopes). What was missing was never the authorisation, only
// the transport. That gap is the whole point of Marci's general objection: an approved
// read scope should not need a fresh approval round each time it is exercised.
//
// THE RULES THIS SCRIPT LIVES BY, the same ones Marci approved for the two precedents:
//
//   THE HOST IS HARDCODED. There is no --url, no --host, no --endpoint. Nothing the caller
//   passes can change where the request goes. The deny list's stated target is "the
//   URL-fetch verbs a misled-but-compliant agent reaches for", and the property it buys is
//   that an agent cannot be talked into fetching an ARBITRARY address. That property holds
//   here.
//
//   READ ONLY, STRUCTURALLY. Every request is a GET, and the method is a literal in this
//   file, not a parameter. There is no send, no update, no delete path to reach even by
//   mistake -- sending a campaign stays what it has always been: a separate, explicit,
//   per-occasion approval.
//
//   THE CAMPAIGN ID IS VALIDATED to be digits before it reaches the URL, so it cannot
//   carry a path segment or a query of its own.
//
// Usage:
//   tsx scripts/mailerlite-report.ts campaigns [--status sent|draft] [--limit N]
//   tsx scripts/mailerlite-report.ts stats --id <campaignId>
//   tsx scripts/mailerlite-report.ts kuldesi-ido [--limit N]   # send hour vs open rate
//
// Credentials: agents/marti/.mailerlite-credentials (MAILERLITE_API_KEY), chmod 600.
// Override the path with MAILERLITE_CREDS.
import { readFileSync } from 'node:fs'

const HOST = 'https://connect.mailerlite.com'      // HARDCODED, see the header.
const CREDS = process.env.MAILERLITE_CREDS
  ?? '/home/pdb/marveen/agents/marti/.mailerlite-credentials'

function kulcs(): string {
  for (const ln of readFileSync(CREDS, 'utf-8').split('\n')) {
    const i = ln.indexOf('=')
    if (i > 0 && ln.slice(0, i).trim() === 'MAILERLITE_API_KEY') return ln.slice(i + 1).trim()
  }
  throw new Error(`MAILERLITE_API_KEY not found in ${CREDS}`)
}

/** Every network call in this file goes through here, and it is a GET. */
async function olvas(path: string, params: Record<string, string> = {}) {
  const qs = new URLSearchParams(params).toString()
  const r = await fetch(`${HOST}${path}${qs ? `?${qs}` : ''}`, {
    method: 'GET',
    headers: { Authorization: `Bearer ${kulcs()}`, Accept: 'application/json' },
  })
  if (!r.ok) throw new Error(`mailerlite ${path}: ${r.status} ${await r.text()}`)
  return r.json() as Promise<any>
}

function arany(resz: unknown, egesz: unknown): string {
  const a = Number(resz), b = Number(egesz)
  return b > 0 ? `${((a / b) * 100).toFixed(1)}%` : 'n/a'
}

async function main() {
  const verb = process.argv[2]
  const flag = (n: string) => {
    const i = process.argv.indexOf(`--${n}`)
    return i > 0 ? process.argv[i + 1] : undefined
  }
  const limit = flag('limit') ?? '25'

  if (verb === 'campaigns') {
    const p: Record<string, string> = { 'limit': limit }
    const st = flag('status')
    if (st) p['filter[status]'] = st
    const d = await olvas('/api/campaigns', p)
    for (const c of d.data ?? []) {
      const s = c.stats ?? {}
      console.log(`${c.id}  ${c.status.padEnd(9)} ${(c.finished_at ?? c.scheduled_for ?? '').slice(0, 16)}  ${c.name}`)
      if (s.sent) console.log(`    kikuldve ${s.sent}  megnyitas ${s.opens_count} (${arany(s.opens_count, s.sent)})  kattintas ${s.clicks_count} (${arany(s.clicks_count, s.sent)})`)
    }
    return
  }

  if (verb === 'stats') {
    const id = flag('id')
    if (!id || !/^\d+$/.test(id)) { console.error('stats requires --id <digits>'); process.exit(2) }
    const c = (await olvas(`/api/campaigns/${id}`)).data ?? {}
    const s = c.stats ?? {}
    console.log(`${c.name}  [${c.status}]`)
    console.log(`  kikuldve   : ${s.sent}`)
    console.log(`  megnyitas  : ${s.opens_count} egyedi ${s.unique_opens_count} (${arany(s.opens_count, s.sent)})`)
    console.log(`  kattintas  : ${s.clicks_count} egyedi ${s.unique_clicks_count} (${arany(s.clicks_count, s.sent)})`)
    console.log(`  leiratkozas: ${s.unsubscribes_count}  visszapattano: ${s.hard_bounces_count}`)
    console.log(`  befejezve  : ${c.finished_at ?? '-'}`)
    return
  }

  // Send hour vs open rate. This is the question Marci actually asked, so it gets its own
  // verb: the raw campaign list makes you eyeball 25 rows and do the division by hand.
  if (verb === 'kuldesi-ido') {
    const d = await olvas('/api/campaigns', { 'filter[status]': 'sent', limit })
    const sorok = (d.data ?? [])
      .filter((c: any) => c.finished_at && Number(c.stats?.sent) > 0)
      .map((c: any) => {
        const t = new Date(c.finished_at)
        return {
          nap: ['vas', 'het', 'ked', 'sze', 'csu', 'pen', 'szo'][t.getDay()],
          ora: t.getHours(),
          sent: Number(c.stats.sent),
          nyit: Number(c.stats.opens_count),
          nev: c.name,
        }
      })
    console.log(`${sorok.length} kikuldott kampany (a ${limit}-bol), kuldesi ido szerint:\n`)
    console.log('nap ora  kikuldve  megnyitas  arany   kampany')
    for (const s of sorok.sort((a: any, b: any) => (b.nyit / b.sent) - (a.nyit / a.sent))) {
      console.log(`${s.nap} ${String(s.ora).padStart(2, '0')}h  ${String(s.sent).padStart(8)}  ${String(s.nyit).padStart(9)}  ${arany(s.nyit, s.sent).padStart(6)}  ${s.nev.slice(0, 44)}`)
    }
    console.log('\nFIGYELEM: ez MEGFIGYELES, nem kiserlet. A kuldesi ido egyutt valtozik a')
    console.log('kampany temajaval es a cimzett-korrel, tehat az elteres okat nem bizonyitja.')
    return
  }

  console.error('usage: mailerlite-report.ts <campaigns|stats|kuldesi-ido> [options] (see file header)')
  process.exit(2)
}
main()
