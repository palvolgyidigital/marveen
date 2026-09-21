// Google Ads: add or remove CAMPAIGN-LEVEL NEGATIVE KEYWORDS.
//
// WHY THIS EXISTS (2026-09-16). Marti built a negative keyword list from the
// search-term insights for the TOP50-PMax campaign and Marci approved it
// ("Mehet"). The existing write tool (google-ads-listing-filter.ts) can only
// touch assetGroupListingGroupFilters, by design, so it cannot do this.
//
// THIS IS THE SECOND WRITE-CAPABLE ADS TOOL IN THIS INSTALL. Same rules as the
// first one, and for the same reason: its limits matter more than its features.
//
//   ONE RESOURCE, ONE SHAPE. Only campaignCriteria can be created or removed,
//   and a create is ALWAYS negative:true with a keyword. There is no code path
//   that produces a positive criterion, a bid modifier, a budget or an audience.
//   If a future job needs one of those, it is a new decision and a new tool,
//   not a flag here.
//
//   BROAD AND PHRASE ONLY. EXACT is deliberately absent because nobody has
//   needed it yet. Adding it is one line, and should happen when someone has an
//   actual case, not in advance.
//
//   THE HOST IS HARDCODED. No --url, no --host, no --endpoint. The customer id
//   comes from the credentials file unless overridden with digits; the campaign
//   id is a required, digits-only argument. Both are regex-validated before
//   they reach the request, because they go into the URL and the body verbatim
//   and a typo is a change to the wrong campaign.
//
//   A DRY RUN ALWAYS HAPPENS FIRST, exactly as in the listing-filter tool.
//   --apply still runs the dry run first and only proceeds if it passed.
//
//   NO partialFailure IS SENT. Not an oversight: without it the batch is
//   all-or-nothing, and half an applied negative list is worse than none,
//   because nobody can tell afterwards which half landed.
//
// A NOTE ON WHAT NEGATIVE KEYWORDS DO, because it is easy to underestimate.
// A negative keyword does not cost money and does not change a bid, so it feels
// harmless. It is not: a too-wide negative silently removes traffic that was
// converting, and the loss is invisible precisely because the impressions never
// happen. Marti's own list shows the care this needs -- she left "canon" out of
// the broad negatives because "canon kamera taska" converts (2 conv / 6 clicks),
// and negated only the two specific non-converting Canon phrases.
//
// SECRETS: the access token is never printed.
//
// Usage:
//   # see what would happen (default -- nothing is changed):
//   npx tsx scripts/google-ads-negative-keyword.ts --campaign 1234567890 \
//     --broad sony --broad nikon --phrase "lg fenykepezogep"
//   # actually do it:
//   ... --apply
//   # undo one:
//   npx tsx scripts/google-ads-negative-keyword.ts --remove customers/1/campaignCriteria/2~3 --apply
// Exit codes:
//   0 = dry run passed (or, with --apply, the change was applied)
//   1 = the API rejected it (nothing was changed)
//   2 = could not tell (network, config) -- explicitly NOT "it failed"

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Hardcoded on purpose -- see the header. Not configurable, not an argument.
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
const ADS_HOST = 'https://googleads.googleapis.com'
// MEASURED 2026-09-16: v22 is the version this account answers on; v17-v21 give
// a plain 404 HTML page. See scripts/google-ads-report.ts for the same note.
const DEFAULT_API_VERSION = 'v22'
const REQUEST_TIMEOUT_MS = 60_000

const DEFAULT_CREDS = join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials')

// customers/<digits>/campaignCriteria/<digits>~<digits>. Validated because this
// string goes into the request body verbatim; a typo removes the wrong thing.
const RN_CRITERION = /^customers\/\d+\/campaignCriteria\/\d+~\d+$/
// Google's own limit is 80 characters and 10 words. Newlines and control
// characters are rejected here rather than sent and bounced.
const KEYWORD_TEXT = /^[^\n\r\t]{1,80}$/

interface Creds {
  clientId: string
  clientSecret: string
  refreshToken: string
  developerToken: string
  loginCustomerId: string
  targetCustomerId: string
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

interface MutateOutcome { ok: boolean; status: number; body: string }

async function mutate(
  token: string, creds: Creds, apiVersion: string, customerId: string,
  operations: unknown[], validateOnly: boolean,
): Promise<MutateOutcome> {
  const url = `${ADS_HOST}/${apiVersion}/customers/${customerId}/campaignCriteria:mutate`
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'developer-token': creds.developerToken,
        'login-customer-id': creds.loginCustomerId,
        'Content-Type': 'application/json',
      },
      // partialFailure is deliberately NOT sent -- see the header.
      body: JSON.stringify({ operations, validateOnly }),
      signal: ac.signal,
    })
    return { ok: res.ok, status: res.status, body: await res.text() }
  } finally {
    clearTimeout(timer)
  }
}

function usage(): void {
  console.error([
    'usage:',
    '  --campaign <digits>            required for --broad/--phrase',
    '  --broad  <text>                add a BROAD negative keyword   (repeatable)',
    '  --phrase <text>                add a PHRASE negative keyword  (repeatable)',
    '  --remove <campaignCriterion resourceName>                     (repeatable)',
    '  [--apply]  actually perform the change (default: dry run only)',
    '  [--creds <path>] [--customer <digits>] [--api-version vNN] [--json]',
  ].join('\n'))
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const apply = argv.includes('--apply')
  const flag = (name: string): string | undefined => {
    const i = argv.indexOf(name)
    return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : undefined
  }
  const allFlags = (name: string): string[] => {
    const out: string[] = []
    argv.forEach((a, i) => { if (a === name && argv[i + 1] && !argv[i + 1].startsWith('--')) out.push(argv[i + 1]) })
    return out
  }

  const broads = allFlags('--broad')
  const phrases = allFlags('--phrase')
  const removes = allFlags('--remove')
  const adds = [
    ...broads.map((text) => ({ text, matchType: 'BROAD' as const })),
    ...phrases.map((text) => ({ text, matchType: 'PHRASE' as const })),
  ]

  if (adds.length === 0 && removes.length === 0) { usage(); return 2 }

  for (const r of removes) {
    if (!RN_CRITERION.test(r)) {
      console.error(`[ads-negative-keyword] CONFIG ERROR: --remove is not a campaign criterion resource name: ${r}`)
      return 2
    }
  }
  for (const a of adds) {
    if (!KEYWORD_TEXT.test(a.text)) {
      console.error(`[ads-negative-keyword] CONFIG ERROR: keyword text rejected (1-80 chars, no newlines): ${JSON.stringify(a.text)}`)
      return 2
    }
    if (a.text.trim().split(/\s+/).length > 10) {
      console.error(`[ads-negative-keyword] CONFIG ERROR: keyword has more than 10 words: ${JSON.stringify(a.text)}`)
      return 2
    }
  }

  const rawCampaign = flag('--campaign')
  if (adds.length > 0 && (!rawCampaign || !/^\d{1,20}$/.test(rawCampaign))) {
    console.error('[ads-negative-keyword] CONFIG ERROR: --broad/--phrase need --campaign <digits>')
    return 2
  }

  const apiVersion = flag('--api-version') ?? DEFAULT_API_VERSION
  if (!/^v\d+$/.test(apiVersion)) {
    console.error(`[ads-negative-keyword] CONFIG ERROR: --api-version must look like v22, got ${apiVersion}`)
    return 2
  }

  const credsPath = flag('--creds') ?? process.env.GOOGLE_ADS_CREDS ?? DEFAULT_CREDS
  let creds: Creds
  try { creds = readCreds(credsPath) } catch (err) {
    console.error(`[ads-negative-keyword] CONFIG ERROR: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  const rawCustomer = flag('--customer')
  if (rawCustomer !== undefined && !/^[\d-]{10,15}$/.test(rawCustomer)) {
    console.error(`[ads-negative-keyword] CONFIG ERROR: --customer must be digits, got ${rawCustomer}`)
    return 2
  }
  const customerId = rawCustomer ? digitsOnly(rawCustomer) : creds.targetCustomerId

  // The only two shapes this tool can build. negative:true is not a parameter.
  const operations: unknown[] = [
    ...removes.map((r) => ({ remove: r })),
    ...adds.map((a) => ({
      create: {
        campaign: `customers/${customerId}/campaigns/${rawCampaign}`,
        negative: true,
        keyword: { text: a.text, matchType: a.matchType },
      },
    })),
  ]

  // Say out loud what is about to be attempted, BEFORE any call, and list every
  // keyword. If this run is interrupted or read later, this is the record of
  // intent -- and a wrong keyword is much easier to spot here than in a diff.
  console.log(`[ads-negative-keyword] customer ${customerId}` +
    (adds.length ? `, campaign ${rawCampaign}` : '') +
    `, ${operations.length} operation(s): ${removes.length} remove, ${adds.length} add. ` +
    `Mode: ${apply ? 'APPLY (dry run first)' : 'DRY RUN ONLY'}`)
  for (const a of adds) console.log(`   + ${a.matchType.padEnd(6)} ${a.text}`)
  for (const r of removes) console.log(`   - ${r}`)

  let token: string
  try { token = await mintAccessToken(creds) } catch (err) {
    if (err instanceof AuthDead) { console.error(`[ads-negative-keyword] REJECTED -- ${err.message}`); return 1 }
    console.error(`[ads-negative-keyword] COULD NOT RUN: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  let dry: MutateOutcome
  try {
    dry = await mutate(token, creds, apiVersion, customerId, operations, true)
  } catch (err) {
    console.error(`[ads-negative-keyword] COULD NOT RUN (network, dry run): ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }
  if (!dry.ok) {
    console.error(`[ads-negative-keyword] DRY RUN REJECTED (http ${dry.status}) -- NOTHING WAS CHANGED:`)
    console.error(dry.body.slice(0, 4000))
    return 1
  }
  console.log('[ads-negative-keyword] dry run passed.')

  if (!apply) {
    console.log('[ads-negative-keyword] STOPPING HERE. Nothing was changed. Re-run with --apply to perform it.')
    return 0
  }

  let live: MutateOutcome
  try {
    live = await mutate(token, creds, apiVersion, customerId, operations, false)
  } catch (err) {
    // The dry run passed and the live call did not come back. The change MAY
    // have landed. Saying "failed" here would be a guess, and acting on that
    // guess (retrying) could double-apply.
    console.error(`[ads-negative-keyword] UNCERTAIN (network during the live call): ${err instanceof Error ? err.message : String(err)}`)
    console.error('  The change may or may not have been applied. CHECK the campaign before retrying.')
    return 2
  }
  if (!live.ok) {
    console.error(`[ads-negative-keyword] APPLY REJECTED (http ${live.status}):`)
    console.error(live.body.slice(0, 4000))
    return 1
  }

  if (asJson) { console.log(live.body); return 0 }
  let results: unknown[] = []
  try { results = (JSON.parse(live.body) as { results?: unknown[] }).results ?? [] } catch { /* ignore */ }
  console.log(`[ads-negative-keyword] APPLIED -- ${results.length} result(s).`)
  // The resource names are the ONLY way to undo this later. Print them.
  for (const r of results) console.log('  ', (r as { resourceName?: string }).resourceName ?? JSON.stringify(r))
  return 0
}

process.exit(await main())
