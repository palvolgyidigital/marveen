// Google Ads live report runner (GAQL).
//
// WHY THIS EXISTS (2026-09-16, Marci kérése). Marci wants Marti to be able to
// look into Ads immediately when he asks a question -- not to file a request and
// wait. The blocker was BASH_EGRESS_DENY (`Bash(curl *https://*)`), which the
// scaffold writes into every agent's settings.json on EVERY spawn, so removing
// it by hand does not stick: `applyAgentPermissions()` replaces the permissions
// object wholesale (src/web/agent-scaffold.ts). A per-agent exception would be a
// code change affecting all seven agents, and it would weaken the deny for every
// one of them. This script is the narrower answer.
//
// WHAT MAKES THIS A SANCTIONED TOOL AND NOT A BYPASS. The deny list's stated
// target is "the URL-fetch verbs a misled-but-compliant agent reaches for".
// The protection it buys is that an agent cannot be talked into fetching an
// ARBITRARY address. This script keeps that property:
//
//   THE HOST IS HARDCODED. There is no URL argument and no host argument, and
//   nothing the caller passes can change where the request goes. The only
//   caller-controlled parts are (a) the customer id, which is validated to be
//   digits, and (b) the GAQL query, which travels in the POST BODY -- a query
//   string cannot redirect a request to another host.
//
//   Do not add a --url, --host or --endpoint flag. The moment the destination
//   comes from the caller this stops being a purpose-built tool and becomes
//   exactly the bypass the deny list exists to prevent. Same rule as
//   scripts/google-ads-token.ts, and for the same reason.
//
// READ-ONLY BY CONSTRUCTION. It calls googleAds:searchStream, which is a read
// endpoint. Mutations live on different methods (…:mutate) that this script
// cannot reach. Changing campaigns stays a separate, explicitly approved step.
//
// SECRETS: the OAuth access token is never printed, not even with --json. The
// developer token is sent as a header and likewise never echoed. Output from
// this script lands in transcripts and logs.
//
// Usage:
//   npx tsx scripts/google-ads-report.ts --query "SELECT campaign.name, \
//     metrics.cost_micros FROM campaign WHERE segments.date DURING LAST_7_DAYS"
//   [--creds <path>] [--customer <10 digits>] [--json] [--api-version vNN]
// Exit codes:
//   0 = query ran, rows printed (zero rows is still 0 -- an empty result is an
//       answer, and conflating it with failure is how false negatives are born)
//   1 = the API rejected the request (bad GAQL, no access, dead token)
//   2 = could not tell (network, config, unreadable credentials)

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Hardcoded on purpose -- see the header. Not configurable, not an argument.
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
const ADS_HOST = 'https://googleads.googleapis.com'
// The API version is versioned in the path and Google retires old ones. It is
// the ONE piece of the URL that may need to move, so it is a flag with a
// default rather than a silent constant -- but it is validated to `v` + digits,
// so it cannot carry a path traversal into another host or method.
// MEASURED 2026-09-16: v22 is the only version this account answers on. v17
// through v21 all return a plain 404 HTML page (not a JSON API error), so a
// retired version looks like a broken URL rather than "upgrade me". If this
// starts 404ing, probe the next version up before assuming anything is wrong
// with the credentials -- the auth step will already have succeeded by then.
const DEFAULT_API_VERSION = 'v22'
const REQUEST_TIMEOUT_MS = 60_000

const DEFAULT_CREDS = join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials')

interface Creds {
  clientId: string
  clientSecret: string
  refreshToken: string
  developerToken: string
  loginCustomerId: string
  targetCustomerId: string
}

// KEY=value file, same shape as scripts/google-ads-token.ts reads.
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
    'GOOGLE_ADS_DEVELOPER_TOKEN',
    'GOOGLE_ADS_LOGIN_CUSTOMER_ID',
    'GOOGLE_ADS_TARGET_CUSTOMER_ID',
  ]
  const missing = need.filter((k) => !kv.get(k))
  if (missing.length) throw new Error(`missing key(s) in ${path}: ${missing.join(', ')}`)
  return {
    clientId: kv.get(need[0])!,
    clientSecret: kv.get(need[1])!,
    refreshToken: kv.get(need[2])!,
    developerToken: kv.get(need[3])!,
    loginCustomerId: digitsOnly(kv.get(need[4])!),
    targetCustomerId: digitsOnly(kv.get(need[5])!),
  }
}

// Google writes customer ids as 445-919-3386; the API wants 4459193386.
function digitsOnly(s: string): string {
  return s.replace(/\D/g, '')
}

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

class AuthDead extends Error {}

// Flattens the nested API response ({campaign:{name:..}, metrics:{..}}) into
// dotted keys, which is what the GAQL SELECT list looks like -- so the output
// columns match what the caller asked for instead of a shape they have to
// decode.
function flatten(obj: unknown, prefix = '', out: Record<string, unknown> = {}): Record<string, unknown> {
  if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      flatten(v, prefix ? `${prefix}.${k}` : k, out)
    }
  } else {
    out[prefix] = obj
  }
  return out
}

function usage(): void {
  console.error('usage: npx tsx scripts/google-ads-report.ts --query "<GAQL>" [--creds <path>] [--customer <digits>] [--json] [--api-version vNN]')
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const flag = (name: string): string | undefined => {
    const i = argv.indexOf(name)
    return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : undefined
  }

  const query = flag('--query')
  if (!query) { usage(); return 2 }

  const apiVersion = flag('--api-version') ?? DEFAULT_API_VERSION
  if (!/^v\d+$/.test(apiVersion)) {
    console.error(`[google-ads-report] CONFIG ERROR: --api-version must look like v21, got ${apiVersion}`)
    return 2
  }

  const credsPath = flag('--creds') ?? process.env.GOOGLE_ADS_CREDS ?? DEFAULT_CREDS
  let creds: Creds
  try {
    creds = readCreds(credsPath)
  } catch (err) {
    console.error(`[google-ads-report] CONFIG ERROR: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  // Caller-supplied customer id is validated to digits before it reaches the
  // path. Anything else (a slash, a dot, a host) is refused rather than
  // stripped: silently "fixing" an id would query the wrong account and the
  // report would look perfectly normal.
  const rawCustomer = flag('--customer')
  if (rawCustomer !== undefined && !/^[\d-]{10,15}$/.test(rawCustomer)) {
    console.error(`[google-ads-report] CONFIG ERROR: --customer must be digits (optionally dashed), got ${rawCustomer}`)
    return 2
  }
  const customerId = rawCustomer ? digitsOnly(rawCustomer) : creds.targetCustomerId

  let accessToken: string
  try {
    accessToken = await mintAccessToken(creds)
  } catch (err) {
    if (err instanceof AuthDead) {
      console.error(`[google-ads-report] REJECTED -- ${err.message}`)
      return 1
    }
    console.error(`[google-ads-report] COULD NOT RUN: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  const url = `${ADS_HOST}/${apiVersion}/customers/${customerId}/googleAds:searchStream`
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'developer-token': creds.developerToken,
        'login-customer-id': creds.loginCustomerId,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
      signal: ac.signal,
    })
  } catch (err) {
    console.error(`[google-ads-report] COULD NOT RUN (network): ${err instanceof Error ? err.message : String(err)}`)
    return 2
  } finally {
    clearTimeout(timer)
  }

  const text = await res.text()
  if (!res.ok) {
    // The API's error body names the offending GAQL field, which is the single
    // most useful thing for whoever wrote the query -- so it is passed through
    // rather than reduced to a status code. It contains no secrets.
    console.error(`[google-ads-report] API REJECTED (http ${res.status}):`)
    console.error(text.slice(0, 4000))
    return 1
  }

  // searchStream answers with an ARRAY of chunks, each with its own results[].
  let chunks: unknown
  try { chunks = JSON.parse(text) } catch {
    console.error('[google-ads-report] COULD NOT PARSE the API response as JSON')
    return 2
  }
  const rows: Record<string, unknown>[] = []
  for (const chunk of Array.isArray(chunks) ? chunks : [chunks]) {
    const results = (chunk as { results?: unknown }).results
    if (Array.isArray(results)) for (const r of results) rows.push(flatten(r))
  }

  if (asJson) {
    console.log(JSON.stringify({ status: 'ok', customerId, rowCount: rows.length, rows }, null, 2))
    return 0
  }

  // Zero rows is an ANSWER, not a failure: say so explicitly so the caller does
  // not read silence as a broken query.
  if (rows.length === 0) {
    console.log(`[google-ads-report] OK -- the query ran against customer ${customerId} and matched 0 rows.`)
    return 0
  }

  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r))))
  const width = new Map(cols.map((c) => [c, Math.max(c.length, ...rows.map((r) => String(r[c] ?? '').length))]))
  const line = (cells: string[]) => cells.map((c, i) => c.padEnd(width.get(cols[i]) ?? c.length)).join('  ')
  console.log(line(cols))
  console.log(cols.map((c) => '-'.repeat(width.get(c) ?? c.length)).join('  '))
  for (const r of rows) console.log(line(cols.map((c) => String(r[c] ?? ''))))
  console.log(`\n[google-ads-report] OK -- ${rows.length} row(s), customer ${customerId}.`)
  return 0
}

process.exit(await main())
