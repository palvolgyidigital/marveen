// Google Ads: add or remove products from a Performance Max listing group filter.
//
// WHY THIS EXISTS (2026-09-16). Marci approved write access for Marti on his own
// channel: "Engedd neki az írást. Amit kérek tőle, azt csinálja meg." The
// immediate job is the TOP50-PMax rework (WM-10 out because it is out of stock
// with no resupply, FZ55 in because Next says it is the #1 revenue line), and
// more of the same is expected.
//
// THIS IS THE ONLY WRITE-CAPABLE ADS TOOL IN THIS INSTALL, so its limits matter
// more than its features. It is deliberately narrow:
//
//   ONE RESOURCE. Only assetGroupListingGroupFilters can be created or removed.
//   Budgets, bids, campaign status, asset groups, ads and keywords are NOT
//   reachable from here and must not be added. A tool that can change spend is
//   a different decision with a different approval.
//
//   THE HOST IS HARDCODED, as in google-ads-report.ts. No --url, no --host.
//   The customer id comes from the credentials file unless overridden with
//   digits. Resource names are regex-validated before they reach the request.
//
//   A DRY RUN ALWAYS HAPPENS FIRST. Every invocation sends the mutate with
//   validateOnly=true and stops there unless --apply is given. With --apply the
//   dry run STILL runs first, and the live call only follows if it passed. This
//   is not belt-and-braces: the Ads API rejects a malformed listing-group tree
//   with a specific error, and finding that out AFTER a half-applied change is
//   how a campaign ends up in a state nobody intended.
//
//   NOTHING IS PARTIAL. All operations go in one request, and this service has
//   no partial-failure mode, so the batch applies whole or not at all.
//
// SECRETS: the access token is never printed.
//
// Usage:
//   # see what would happen (default -- nothing is changed):
//   npx tsx scripts/google-ads-listing-filter.ts --remove <resourceName>
//   npx tsx scripts/google-ads-listing-filter.ts --add-offer UL-2660 \
//     --asset-group customers/123/assetGroups/456 --parent <resourceName>
//   # actually do it:
//   ... --apply
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

// customers/<digits>/assetGroupListingGroupFilters/<digits>~<digits> and
// customers/<digits>/assetGroups/<digits>. Validated because these strings go
// into the request body verbatim; a typo here is a change to the wrong object.
const RN_FILTER = /^customers\/\d+\/assetGroupListingGroupFilters\/[\d~]+$/
const RN_ASSET_GROUP = /^customers\/\d+\/assetGroups\/\d+$/

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
  const url = `${ADS_HOST}/${apiVersion}/customers/${customerId}/assetGroupListingGroupFilters:mutate`
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
      // MEASURED 2026-09-16: this service's mutate has NO partialFailure field
      // (sending it gives 400 "Unknown name partialFailure"). That is fine and
      // in fact what we want: without it the batch is all-or-nothing, and a
      // half-applied listing tree is worse than no change at all, because
      // nobody can tell afterwards which half landed.
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
    '  --remove <assetGroupListingGroupFilter resourceName>   (repeatable)',
    '  --add-offer <offerId> --asset-group <resourceName> --parent <resourceName>',
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

  const removes = allFlags('--remove')
  const addOffer = flag('--add-offer')
  const assetGroup = flag('--asset-group')
  const parent = flag('--parent')

  if (removes.length === 0 && !addOffer) { usage(); return 2 }

  for (const r of removes) {
    if (!RN_FILTER.test(r)) {
      console.error(`[ads-listing-filter] CONFIG ERROR: --remove is not a listing group filter resource name: ${r}`)
      return 2
    }
  }
  if (addOffer) {
    if (!assetGroup || !RN_ASSET_GROUP.test(assetGroup)) {
      console.error('[ads-listing-filter] CONFIG ERROR: --add-offer needs a valid --asset-group customers/<id>/assetGroups/<id>')
      return 2
    }
    if (!parent || !RN_FILTER.test(parent)) {
      console.error('[ads-listing-filter] CONFIG ERROR: --add-offer needs a valid --parent listing group filter resource name')
      return 2
    }
    if (!/^[A-Za-z0-9._-]{1,50}$/.test(addOffer)) {
      console.error(`[ads-listing-filter] CONFIG ERROR: --add-offer looks wrong: ${addOffer}`)
      return 2
    }
  }

  const apiVersion = flag('--api-version') ?? DEFAULT_API_VERSION
  if (!/^v\d+$/.test(apiVersion)) {
    console.error(`[ads-listing-filter] CONFIG ERROR: --api-version must look like v22, got ${apiVersion}`)
    return 2
  }

  const credsPath = flag('--creds') ?? process.env.GOOGLE_ADS_CREDS ?? DEFAULT_CREDS
  let creds: Creds
  try { creds = readCreds(credsPath) } catch (err) {
    console.error(`[ads-listing-filter] CONFIG ERROR: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  const rawCustomer = flag('--customer')
  if (rawCustomer !== undefined && !/^[\d-]{10,15}$/.test(rawCustomer)) {
    console.error(`[ads-listing-filter] CONFIG ERROR: --customer must be digits, got ${rawCustomer}`)
    return 2
  }
  const customerId = rawCustomer ? digitsOnly(rawCustomer) : creds.targetCustomerId

  const operations: unknown[] = removes.map((r) => ({ remove: r }))
  if (addOffer) {
    operations.push({
      create: {
        assetGroup,
        parentListingGroupFilter: parent,
        type: 'UNIT_INCLUDED',
        listingSource: 'SHOPPING',
        caseValue: { productItemId: { value: addOffer } },
      },
    })
  }

  // Say out loud what is about to be attempted, BEFORE any call. If the run is
  // interrupted or the output is read later, this line is the record of intent.
  console.log(`[ads-listing-filter] customer ${customerId}, ${operations.length} operation(s): ` +
    `${removes.length} remove${addOffer ? `, 1 add (${addOffer})` : ''}. Mode: ${apply ? 'APPLY (dry run first)' : 'DRY RUN ONLY'}`)

  let token: string
  try { token = await mintAccessToken(creds) } catch (err) {
    if (err instanceof AuthDead) { console.error(`[ads-listing-filter] REJECTED -- ${err.message}`); return 1 }
    console.error(`[ads-listing-filter] COULD NOT RUN: ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }

  let dry: MutateOutcome
  try {
    dry = await mutate(token, creds, apiVersion, customerId, operations, true)
  } catch (err) {
    console.error(`[ads-listing-filter] COULD NOT RUN (network, dry run): ${err instanceof Error ? err.message : String(err)}`)
    return 2
  }
  if (!dry.ok) {
    console.error(`[ads-listing-filter] DRY RUN REJECTED (http ${dry.status}) -- NOTHING WAS CHANGED:`)
    console.error(dry.body.slice(0, 4000))
    return 1
  }
  console.log('[ads-listing-filter] dry run passed.')

  if (!apply) {
    console.log('[ads-listing-filter] STOPPING HERE. Nothing was changed. Re-run with --apply to perform it.')
    return 0
  }

  let live: MutateOutcome
  try {
    live = await mutate(token, creds, apiVersion, customerId, operations, false)
  } catch (err) {
    // The dry run passed and the live call did not come back. The change MAY
    // have landed. Saying "failed" here would be a guess, and acting on that
    // guess (retrying) could double-apply. Exit 2 and make a human look.
    console.error(`[ads-listing-filter] UNCERTAIN (network during the live call): ${err instanceof Error ? err.message : String(err)}`)
    console.error('  The change may or may not have been applied. CHECK the campaign before retrying.')
    return 2
  }
  if (!live.ok) {
    console.error(`[ads-listing-filter] APPLY REJECTED (http ${live.status}):`)
    console.error(live.body.slice(0, 4000))
    return 1
  }

  if (asJson) { console.log(live.body); return 0 }
  let results: unknown[] = []
  try { results = (JSON.parse(live.body) as { results?: unknown[] }).results ?? [] } catch { /* ignore */ }
  console.log(`[ads-listing-filter] APPLIED -- ${results.length} result(s).`)
  for (const r of results) console.log('  ', (r as { resourceName?: string }).resourceName ?? JSON.stringify(r))
  return 0
}

process.exit(await main())
