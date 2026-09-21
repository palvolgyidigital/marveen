// Thin wrapper around google-oauth-token-health.ts, "ads" profile only.
//
// 2026-09-21: this file used to contain the full check (created 2026-09-15,
// see git history / OUTWARD915 for why it exists at all -- the fleet-wide
// `curl *https://*` deny). Pedro measured the same day that the Ads and Sheets
// credentials share one OAuth client and die together, and that a second copy
// of the same check-logic is exactly how two things quietly drift apart (see
// pdb_szoveg.py / hu_guard precedent, card afefa761). The real logic now lives
// once, in google-oauth-token-health.ts; this file exists only so existing
// callers (the daily google-ads-token-refresh-emlekezteto schedule) keep
// working unchanged.
//
// Usage (unchanged): npx tsx scripts/google-ads-token.ts [--creds <path>] [--json]
// Exit codes (unchanged): 0 = valid, 1 = rejected (invalid_grant), 2 = unknown

import { checkProfile } from './google-oauth-token-health.ts'

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const ci = argv.indexOf('--creds')
  const credsOverride = ci >= 0 && argv[ci + 1] ? argv[ci + 1] : (process.env.GOOGLE_ADS_CREDS || undefined)

  const result = await checkProfile('ads', credsOverride)

  if (asJson) {
    console.log(JSON.stringify({ status: result.status === 'ok' ? 'ok' : result.status === 'rejected' ? 'rejected' : 'unknown', expiresIn: result.expiresIn ?? null, error: result.error ?? null }))
  } else {
    if (result.status === 'ok') console.log(result.message.replace('[ads]', '[google-ads-token]'))
    else console.error(result.message.replace('[ads]', '[google-ads-token]'))
  }

  return result.status === 'ok' ? 0 : result.status === 'rejected' ? 1 : 2
}

process.exit(await main())
