// Google Ads: two fixed changes on the TOP50-PMax campaign, and nothing else.
//
// WHY THIS EXISTS (2026-11-04). Marti asked for it (agent msg 7457) and Marci
// approved it directly on his own channel (Telegram 11832, "Menjen"), after
// being told that this is the first tool here that can change spend:
//   1. the campaign budget goes from 5 000 to 6 000 a day (amount_micros
//      5 000 000 000 -> 6 000 000 000, in the account currency);
//   2. the Maximize Conversion Value bidding gets a target ROAS of 900%
//      (target_roas 9.0); today it has none.
//
// IT IS DELIBERATELY NOT A GENERAL TOOL. google-ads-listing-filter.ts keeps
// budgets and bids out of reach on purpose ("a tool that can change spend is a
// different decision with a different approval"). This script is that separate
// decision, for exactly these two values on exactly this campaign:
//
//   EVERYTHING IS HARDCODED: customer, campaign, budget resource name, the new
//   values and the values it expects to find. No flag can point it elsewhere.
//
//   IT READS FIRST. A GAQL query fetches the live budget and target ROAS. If the
//   budget is not the expected 5 000 000 000 (or already the target), or the
//   target ROAS is already set to something else, it stops: the approval was
//   for this exact change from this exact state.
//
//   A DRY RUN ALWAYS HAPPENS FIRST, for both mutates (validateOnly=true). With
//   --apply the live calls only follow if both dry runs passed.
//
// SECRETS: the access token is never printed.
//
// Usage:
//   npx tsx scripts/google-ads-top50-pmax-tune.ts           # read + dry run, changes nothing
//   npx tsx scripts/google-ads-top50-pmax-tune.ts --apply   # read + dry run + live
// Exit codes: 0 = ok (dry run passed, or applied), 1 = rejected or unexpected
// state (nothing changed), 2 = could not tell (network/config).

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
const ADS_HOST = 'https://googleads.googleapis.com'
// MEASURED 2026-11-04 (Marti): v22 started answering UNSUPPORTED_VERSION around
// 2026-11-03, her read-only google-ads-report.ts works on v23.
const API_VERSION = 'v23'
const REQUEST_TIMEOUT_MS = 60_000
const CREDS_PATH = join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials')

const CUSTOMER_ID = '4459193386'
const CAMPAIGN_ID = '23574538250'
const CAMPAIGN_RN = `customers/${CUSTOMER_ID}/campaigns/${CAMPAIGN_ID}`
const BUDGET_RN = `customers/${CUSTOMER_ID}/campaignBudgets/15380455381`
const BUDGET_FROM_MICROS = '5000000000'
const BUDGET_TO_MICROS = '6000000000'
const TARGET_ROAS = 9.0

const TAG = '[ads-top50-tune]'

interface Creds {
  clientId: string; clientSecret: string; refreshToken: string
  developerToken: string; loginCustomerId: string; targetCustomerId: string
}

function readCreds(path: string): Creds {
  const kv = new Map<string, string>()
  for (const line of readFileSync(path, 'utf-8').split('\n')) {
    const t = line.trim()
    if (!t || t.startsWith('#')) continue
    const eq = t.indexOf('=')
    if (eq > 0) kv.set(t.slice(0, eq).trim(), t.slice(eq + 1).trim())
  }
  const need = ['GOOGLE_ADS_OAUTH_CLIENT_ID', 'GOOGLE_ADS_OAUTH_CLIENT_SECRET', 'GOOGLE_ADS_REFRESH_TOKEN',
    'GOOGLE_ADS_DEVELOPER_TOKEN', 'GOOGLE_ADS_LOGIN_CUSTOMER_ID', 'GOOGLE_ADS_TARGET_CUSTOMER_ID']
  const missing = need.filter((k) => !kv.get(k))
  if (missing.length) throw new Error(`missing key(s) in ${path}: ${missing.join(', ')}`)
  const d = (s: string) => s.replace(/\D/g, '')
  return {
    clientId: kv.get(need[0])!, clientSecret: kv.get(need[1])!, refreshToken: kv.get(need[2])!,
    developerToken: kv.get(need[3])!, loginCustomerId: d(kv.get(need[4])!), targetCustomerId: d(kv.get(need[5])!),
  }
}

async function post(url: string, headers: Record<string, string>, body: string): Promise<{ ok: boolean; status: number; text: string }> {
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(url, { method: 'POST', headers, body, signal: ac.signal })
    return { ok: res.ok, status: res.status, text: await res.text() }
  } finally {
    clearTimeout(timer)
  }
}

async function mintAccessToken(c: Creds): Promise<string> {
  const r = await post(TOKEN_ENDPOINT, { 'Content-Type': 'application/x-www-form-urlencoded' },
    new URLSearchParams({ client_id: c.clientId, client_secret: c.clientSecret, refresh_token: c.refreshToken, grant_type: 'refresh_token' }).toString())
  if (!r.ok) throw new Error(`token exchange failed (http ${r.status})`)
  const tok = (JSON.parse(r.text) as { access_token?: unknown }).access_token
  if (typeof tok !== 'string' || !tok) throw new Error('token exchange returned no access_token')
  return tok
}

function adsHeaders(token: string, c: Creds): Record<string, string> {
  return {
    'Authorization': `Bearer ${token}`,
    'developer-token': c.developerToken,
    'login-customer-id': c.loginCustomerId,
    'Content-Type': 'application/json',
  }
}

interface LiveState { budgetMicros: string | null; budgetRn: string | null; targetRoas: number | null; bidding: string | null }

async function readState(token: string, c: Creds): Promise<LiveState> {
  const query = 'SELECT campaign.resource_name, campaign.bidding_strategy_type, ' +
    'campaign.maximize_conversion_value.target_roas, campaign_budget.resource_name, campaign_budget.amount_micros ' +
    `FROM campaign WHERE campaign.id = ${CAMPAIGN_ID}`
  const r = await post(`${ADS_HOST}/${API_VERSION}/customers/${CUSTOMER_ID}/googleAds:search`, adsHeaders(token, c), JSON.stringify({ query }))
  if (!r.ok) throw new Error(`read failed (http ${r.status}): ${r.text.slice(0, 800)}`)
  const rows = (JSON.parse(r.text) as { results?: Array<Record<string, any>> }).results ?? []
  if (rows.length !== 1) throw new Error(`expected exactly 1 campaign row, got ${rows.length}`)
  const row = rows[0]
  return {
    budgetMicros: row.campaignBudget?.amountMicros != null ? String(row.campaignBudget.amountMicros) : null,
    budgetRn: row.campaignBudget?.resourceName ?? null,
    targetRoas: typeof row.campaign?.maximizeConversionValue?.targetRoas === 'number' ? row.campaign.maximizeConversionValue.targetRoas : null,
    bidding: row.campaign?.biddingStrategyType ?? null,
  }
}

async function mutateBoth(token: string, c: Creds, validateOnly: boolean) {
  const budget = await post(`${ADS_HOST}/${API_VERSION}/customers/${CUSTOMER_ID}/campaignBudgets:mutate`, adsHeaders(token, c),
    JSON.stringify({ operations: [{ update: { resourceName: BUDGET_RN, amountMicros: BUDGET_TO_MICROS }, updateMask: 'amount_micros' }], validateOnly }))
  if (!budget.ok) return { step: 'budget', res: budget }
  const roas = await post(`${ADS_HOST}/${API_VERSION}/customers/${CUSTOMER_ID}/campaigns:mutate`, adsHeaders(token, c),
    JSON.stringify({ operations: [{ update: { resourceName: CAMPAIGN_RN, maximizeConversionValue: { targetRoas: TARGET_ROAS } }, updateMask: 'maximize_conversion_value.target_roas' }], validateOnly }))
  if (!roas.ok) return { step: 'target_roas', res: roas }
  return null
}

async function main(): Promise<number> {
  const apply = process.argv.includes('--apply')
  let creds: Creds
  try { creds = readCreds(CREDS_PATH) } catch (err) {
    console.error(`${TAG} CONFIG ERROR: ${err instanceof Error ? err.message : String(err)}`); return 2
  }
  if (creds.targetCustomerId !== CUSTOMER_ID) {
    console.error(`${TAG} CONFIG ERROR: the credentials target customer ${creds.targetCustomerId} is not ${CUSTOMER_ID}`); return 2
  }
  console.log(`${TAG} ${CAMPAIGN_RN}: budget ${BUDGET_FROM_MICROS} -> ${BUDGET_TO_MICROS} micros, target ROAS -> ${TARGET_ROAS}. ` +
    `Mode: ${apply ? 'APPLY (read + dry run first)' : 'DRY RUN ONLY'}`)

  let token: string
  try { token = await mintAccessToken(creds) } catch (err) {
    console.error(`${TAG} COULD NOT RUN: ${err instanceof Error ? err.message : String(err)}`); return 2
  }

  let st: LiveState
  try { st = await readState(token, creds) } catch (err) {
    console.error(`${TAG} COULD NOT READ the live state: ${err instanceof Error ? err.message : String(err)}`); return 2
  }
  console.log(`${TAG} live now: budget ${st.budgetMicros} (${st.budgetRn}), bidding ${st.bidding}, target ROAS ${st.targetRoas ?? 'none'}`)
  if (st.budgetRn !== BUDGET_RN) { console.error(`${TAG} STOP: the campaign uses budget ${st.budgetRn}, not ${BUDGET_RN}. Nothing changed.`); return 1 }
  if (st.bidding !== 'MAXIMIZE_CONVERSION_VALUE') { console.error(`${TAG} STOP: bidding is ${st.bidding}, not MAXIMIZE_CONVERSION_VALUE. Nothing changed.`); return 1 }
  if (st.budgetMicros !== BUDGET_FROM_MICROS) { console.error(`${TAG} STOP: budget is ${st.budgetMicros}, the approval was for ${BUDGET_FROM_MICROS} -> ${BUDGET_TO_MICROS}. Nothing changed.`); return 1 }
  if (st.targetRoas !== null) { console.error(`${TAG} STOP: a target ROAS (${st.targetRoas}) is already set. Nothing changed.`); return 1 }

  let fail
  try { fail = await mutateBoth(token, creds, true) } catch (err) {
    console.error(`${TAG} COULD NOT RUN (network, dry run): ${err instanceof Error ? err.message : String(err)}`); return 2
  }
  if (fail) {
    console.error(`${TAG} DRY RUN REJECTED at ${fail.step} (http ${fail.res.status}) -- NOTHING WAS CHANGED:`)
    console.error(fail.res.text.slice(0, 4000)); return 1
  }
  console.log(`${TAG} dry run passed for both changes.`)
  if (!apply) { console.log(`${TAG} STOPPING HERE. Nothing was changed. Re-run with --apply to perform it.`); return 0 }

  try { fail = await mutateBoth(token, creds, false) } catch (err) {
    console.error(`${TAG} UNCERTAIN (network during the live calls): ${err instanceof Error ? err.message : String(err)}`)
    console.error('  One or both changes may have landed. Re-run WITHOUT --apply: the read step shows the live state.'); return 2
  }
  if (fail) {
    console.error(`${TAG} APPLY REJECTED at ${fail.step} (http ${fail.res.status}):`)
    console.error(fail.res.text.slice(0, 4000))
    if (fail.step === 'target_roas') console.error('  NOTE: the budget change before it WAS applied. Check the campaign.')
    return 1
  }
  try {
    const after = await readState(token, creds)
    console.log(`${TAG} APPLIED. Live after: budget ${after.budgetMicros}, target ROAS ${after.targetRoas ?? 'none'}`)
  } catch {
    console.log(`${TAG} APPLIED (both mutates returned ok); the read-back failed, check in the Ads UI.`)
  }
  return 0
}

process.exit(await main())
