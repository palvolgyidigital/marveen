// Merchant Center (Merchant API v1) read-only product lister.
//
// WHY THIS EXISTS (2026-09-16). Marci asked Marti how many products the whole
// catalogue holds beyond the 50 in the TOP50-PMax campaign. Marti cannot answer
// that with a raw curl: BASH_EGRESS_DENY (`Bash(curl *https://*)`) is written
// into every agent's settings.json on EVERY spawn by the scaffold, so it is not
// something an agent can edit away. Same situation as the Google Ads question a
// few hours earlier, and the same answer: a purpose-built script rather than a
// hole in the deny list.
//
// THE RULES THIS SCRIPT LIVES BY are the ones Marci approved for
// scripts/google-ads-report.ts, and they are not negotiable here either:
//
//   THE HOST IS HARDCODED. No --url, no --host, no --endpoint. The only
//   caller-controlled values are the merchant id (validated to digits) and
//   paging/filter options that travel as query parameters on a fixed path.
//   A parameter cannot move the request to another host; a URL argument can,
//   and that is precisely the bypass the deny list exists to prevent.
//
//   READ-ONLY BY CONSTRUCTION. Only the products LIST method is reachable. The
//   write methods (insert, update, delete) are not implemented and must not be
//   added here: changing what is listed in a live shopping feed is a separate
//   decision with a separate approval.
//
// SECRETS: the OAuth access token is never printed. The credentials file is the
// same one the Ads scripts read, so the same file permissions apply (chmod 600).
//
// SCOPE NOTE: this needs the `content` OAuth scope, which the weekly refresh
// asks for alongside `adwords` (see the google-ads-token-weekly-refresh skill).
// If the scope is missing the API answers 403 with insufficientPermissions --
// that is a re-consent task for a human, NOT a bug in this script, and the
// error handling below says so in those words rather than failing vaguely.
//
// Usage:
//   npx tsx scripts/merchant-center-report.ts [--count] [--limit N] [--json]
//     [--creds <path>] [--merchant <digits>] [--api-version vN]
//   --count  only the total number of products (cheapest question)
//
// MEASURED 2026-09-16 on the live account: 2133 products, Merchant API v1.
// v1beta answers 409 (discontinued 2026-02-28), and the old Content API v2.1
// answers 410 (sunset 2026-08-18). Both are dead ends, not transient errors.
// Exit codes:
//   0 = the query ran (zero products is an answer, not a failure)
//   1 = the API rejected the request (auth, scope, no access to that merchant)
//   2 = could not tell (network, config, unreadable credentials)

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Hardcoded on purpose -- see the header. Not configurable, not an argument.
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
// MEASURED 2026-09-16: the OLD Content API for Shopping
// (shoppingcontent.googleapis.com/content/v2.1) is SUNSET for our GCP project
// as of 2026-08-18 and answers 410 content_api_sunset. Google's replacement is
// the Merchant API. Do not "fix" a 410 by retrying the old host.
const CONTENT_HOST = 'https://merchantapi.googleapis.com'
const CONTENT_VERSION = 'v1'
const PAGE_SIZE = 250
const REQUEST_TIMEOUT_MS = 60_000
// A catalogue walk must terminate even if the API keeps handing back tokens.
// Without this a paging bug becomes an unbounded loop inside a heartbeat.
const MAX_PAGES = 200

const DEFAULT_CREDS = join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials')

interface Creds {
  clientId: string
  clientSecret: string
  refreshToken: string
  merchantId: string
}

function digitsOnly(s: string): string {
  return s.replace(/\D/g, '')
}

function readCreds(path: string): Creds {
  let raw: string
  try {
    raw = readFileSync(path, 'utf-8')
  } catch {
    throw new Error(`credentials file not readable at ${path}`)
  }
  const kv = new Map<string, string>()
  for (const line of raw.split('\n')) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const eq = t.indexOf('=')
    if (eq < 1) continue
    kv.set(t.slice(0, eq).trim(), t.slice(eq + 1).trim())
  }
  const need = [
    'GOOGLE_ADS_OAUTH_CLIENT_ID',
    'GOOGLE_ADS_OAUTH_CLIENT_SECRET',
    'GOOGLE_ADS_REFRESH_TOKEN',
    'GOOGLE_MERCHANT_CENTER_ID',
  ]
  const missing = need.filter((k) => !kv.get(k))
  if (missing.length) throw new Error(`missing key(s) in ${path}: ${missing.join(', ')}`)
  return {
    clientId: kv.get(need[0])!,
    clientSecret: kv.get(need[1])!,
    refreshToken: kv.get(need[2])!,
    merchantId: digitsOnly(kv.get(need[3])!),
  }
}

class AuthDead extends Error {}

async function mintAccessToken(c: Creds): Promise<string> {
  const body = new URLSearchParams({
    client_id: c.clientId,
    client_secret: c.clientSecret,
    refresh_token: c.refreshToken,
    grant_type: 'refresh_token',
  })
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(TOKEN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
      signal: ac.signal,
    })
    const text = await res.text()
    if (!res.ok) {
      let errCode = ''
      try { errCode = String((JSON.parse(text) as { error?: unknown }).error ?? '') } catch { /* ignore */ }
      if (res.status === 400 && errCode === 'invalid_grant') {
        throw new AuthDead('the refresh token is no longer valid, a human must re-authorise')
      }
      throw new Error(`token exchange failed (http ${res.status}${errCode ? ` ${errCode}` : ''})`)
    }
    const tok = (JSON.parse(text) as { access_token?: unknown }).access_token
    if (typeof tok !== 'string' || !tok) throw new Error('token exchange returned no access_token')
    return tok
  } finally {
    clearTimeout(timer)
  }
}

// CORRECTED 2026-09-16, same day. My first reading of this response was WRONG:
// I looked at the first 40 lines of one product, saw only identity fields, and
// concluded the LIST method carries no title/brand/price. It does -- they live
// one level down under `productAttributes`, past where I had truncated the
// output. The lesson is the plain one: a truncated look at a nested object is
// not a measurement of the object.
interface ProductAttributes {
  title?: string
  brand?: string
  availability?: string
  price?: { amountMicros?: string; currencyCode?: string }
  gtins?: string[]
  link?: string
  [k: string]: unknown
}
interface Product {
  name?: string
  offerId?: string
  contentLanguage?: string
  feedLabel?: string
  productAttributes?: ProductAttributes
  productStatus?: { destinationStatuses?: { reportingContext?: string; approvedCountries?: string[]; disapprovedCountries?: string[] }[] }
  [k: string]: unknown
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const countOnly = argv.includes('--count')
  const flag = (name: string): string | undefined => {
    const i = argv.indexOf(name)
    return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : undefined
  }

  const limitRaw = flag('--limit')
  const limit = limitRaw ? Number(limitRaw) : Infinity
  if (limitRaw && (!Number.isFinite(limit) || limit <= 0)) {
    console.error(`[merchant-center] CONFIG ERROR: --limit must be a positive number, got ${limitRaw}`)
    return 2
  }

  const credsPath = flag('--creds') ?? process.env.GOOGLE_ADS_CREDS ?? DEFAULT_CREDS
  let creds: Creds
  try {
    creds = readCreds(credsPath)
  } catch (err) {
    console.error(`[merchant-center] CONFIG ERROR: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  const rawMerchant = flag('--merchant')
  if (rawMerchant !== undefined && !/^[\d-]{4,20}$/.test(rawMerchant)) {
    console.error(`[merchant-center] CONFIG ERROR: --merchant must be digits, got ${rawMerchant}`)
    return 2
  }
  const merchantId = rawMerchant ? digitsOnly(rawMerchant) : creds.merchantId

  let accessToken: string
  try {
    accessToken = await mintAccessToken(creds)
  } catch (err) {
    if (err instanceof AuthDead) {
      console.error(`[merchant-center] REJECTED -- ${err.message}`)
      return 1
    }
    console.error(`[merchant-center] COULD NOT RUN: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  const apiVersion = flag('--api-version') ?? CONTENT_VERSION
  if (!/^v\d+[a-z0-9]*$/.test(apiVersion)) {
    console.error(`[merchant-center] CONFIG ERROR: --api-version must look like v1 or v1beta, got ${apiVersion}`)
    return 2
  }
  const resource = 'products'
  const items: Product[] = []
  let pageToken: string | undefined
  let pages = 0

  while (pages < MAX_PAGES) {
    pages++
    const qs = new URLSearchParams({ pageSize: String(PAGE_SIZE) })
    if (pageToken) qs.set('pageToken', pageToken)
    const url = `${CONTENT_HOST}/${resource}/${apiVersion}/accounts/${merchantId}/${resource}?${qs}`

    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
    let res: Response
    try {
      res = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` }, signal: ac.signal })
    } catch (err) {
      console.error(`[merchant-center] COULD NOT RUN (network, page ${pages}): ${err instanceof Error ? err.message : String(err)}`)
      return 2
    } finally {
      clearTimeout(timer)
    }

    const text = await res.text()
    if (!res.ok) {
      // A missing `content` scope is the most likely 403 here, and it is a
      // human re-consent task, not a script failure. Naming it explicitly saves
      // the next reader from debugging working code.
      if (res.status === 403 && /insufficient|scope/i.test(text)) {
        console.error('[merchant-center] REJECTED -- the refresh token lacks the `content` scope.')
        console.error('  A human must re-consent with BOTH scopes (adwords + content); see the')
        console.error('  google-ads-token-weekly-refresh skill. Nothing to fix in this script.')
        return 1
      }
      console.error(`[merchant-center] API REJECTED (http ${res.status}, page ${pages}):`)
      console.error(text.slice(0, 2000))
      return 1
    }

    let body: { products?: Product[]; resources?: Product[]; nextPageToken?: string }
    try { body = JSON.parse(text) } catch {
      console.error('[merchant-center] COULD NOT PARSE the API response as JSON')
      return 2
    }
    for (const r of body.products ?? body.resources ?? []) {
      items.push(r)
      if (items.length >= limit) break
    }
    if (items.length >= limit) break
    pageToken = body.nextPageToken
    if (!pageToken) break
  }

  // Say so if paging stopped at the guard rather than at the end of the data --
  // otherwise a truncated walk reads as a complete catalogue count.
  const truncated = pages >= MAX_PAGES && pageToken !== undefined
  if (truncated) {
    console.error(`[merchant-center] WARNING: stopped at the ${MAX_PAGES}-page guard; the count below is a LOWER BOUND.`)
  }

  if (asJson) {
    console.log(JSON.stringify({
      status: 'ok', merchantId, resource, complete: !truncated,
      count: items.length, items: countOnly ? undefined : items,
    }, null, 2))
    return 0
  }

  if (countOnly) {
    console.log(`[merchant-center] ${merchantId}: ${items.length} ${resource}${truncated ? ' (LOWER BOUND, paging guard hit)' : ''}`)
    return 0
  }

  if (items.length === 0) {
    console.log(`[merchant-center] OK -- merchant ${merchantId} has 0 ${resource}.`)
    return 0
  }

  for (const p of items) {
    const a = p.productAttributes ?? {}
    const shopping = p.productStatus?.destinationStatuses?.find((d) => d.reportingContext === 'SHOPPING_ADS')
    const bad = shopping?.disapprovedCountries?.join(',') ?? ''
    // Price arrives in micros of the account currency; divide rather than print
    // 67990000000, which no reader can scan.
    const micros = a.price?.amountMicros ? Number(a.price.amountMicros) / 1_000_000 : undefined
    const price = micros !== undefined ? `${micros.toLocaleString('hu-HU')} ${a.price?.currencyCode ?? ''}`.trim() : ''
    console.log([
      p.offerId ?? '',
      (a.title ?? '').slice(0, 55),
      a.brand ?? '',
      a.availability ?? '',
      price,
      bad ? `ELUTASITVA:${bad}` : '',
    ].filter(Boolean).join(' | '))
  }
  console.log(`\n[merchant-center] OK -- ${items.length} ${resource}, merchant ${merchantId}${truncated ? ' (LOWER BOUND)' : ''}.`)
  return 0
}

process.exit(await main())
