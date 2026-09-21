// Google OAuth refresh-token health check -- multi-profile.
//
// WHY THIS EXISTS (OUTWARD915 / egress deny, 2026-09-15, extended 2026-09-21).
// The upstream commit e19a641 (PR #1218) put BASH_EGRESS_DENY on every agent's
// settings.json, which denies `curl *https://*` fleet-wide. The documented
// daily check for the Google Ads token was a raw curl to oauth2.googleapis.com,
// so it stopped working -- and worse, quietly: a heartbeat that cannot run
// looks the same as one that ran and found everything fine. google-ads-token.ts
// (2026-09-15) fixed that for the Ads profile alone.
//
// 2026-09-21: Pedro measured that the Ads and Sheets credentials share the same
// OAuth client (identical client_id) and therefore die together -- confirmed
// live the same day, both went invalid_grant within the same window. A
// single-profile checker made that a blind spot: the Ads check could report OK
// forever while nobody looked at Sheets. This file replaces the single-purpose
// checker with one script, two profiles, so the two credentials can never drift
// out of sync the way two copies of the same logic would (see pdb_szoveg.py /
// hu_guard precedent, card afefa761 -- a second copy of the same check is how
// a fleet quietly starts checking two different things).
//
// THE ENDPOINT IS HARDCODED AND THERE IS NO URL ARGUMENT, on purpose, for
// EITHER profile. The moment this takes a URL from its caller it stops being a
// purpose-built tool and becomes exactly the bypass the deny list exists to
// prevent. Only the credential FILE PATH is configurable, and only to point at
// a differently-located file in the same two known shapes.
//
// Approved by Marci on 2026-09-15 (permission_change is autonomy level 1 here,
// so this was his call, not the fleet's) for the Ads profile; the Sheets
// profile is the same approved read (token-validity check only), same pattern.
//
// SECRETS: the access token each exchange returns is NEVER printed. A health
// check needs to know whether the refresh token still works, not what it
// minted -- and this output lands in logs and heartbeat transcripts.
//
// OUTPUT CONTRACT: every line -- human or --json -- names WHICH profile it is
// about. A bare "token OK" that does not say which credential it checked is
// exactly the kind of reassuring output that hides a divergence (2026-09-21
// lesson). In --json mode with multiple profiles, statuses are also compared:
// if they differ, that is reported explicitly (`divergent: true`), because two
// credentials sharing one OAuth client are expected to live and die together --
// a difference is itself a finding, not a partial success.
//
// Usage:
//   npx tsx scripts/google-oauth-token-health.ts [--profile ads|sheets|all] [--creds <path>] [--json]
//   --profile defaults to "all" (checks every known profile).
//   --creds overrides the credentials file path for a SINGLE named profile;
//     it is a config error to combine --creds with --profile all (ambiguous).
//
// Exit codes (single profile, or the worst case across "all"):
//   0 = every checked profile's refresh token is valid
//   1 = at least one checked profile's refresh token was REJECTED (needs a human)
//   2 = could not fully tell (network/config error on at least one profile,
//       and none were rejected) -- explicitly NOT the same as 1

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Hardcoded on purpose -- see the header. Not configurable, not an argument.
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
const REQUEST_TIMEOUT_MS = 20_000

interface ProfileSpec {
  label: string
  defaultPath: string
  keys: { id: string; secret: string; refresh: string }
}

export const PROFILES: Record<string, ProfileSpec> = {
  ads: {
    label: 'ads',
    defaultPath: join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials'),
    keys: { id: 'GOOGLE_ADS_OAUTH_CLIENT_ID', secret: 'GOOGLE_ADS_OAUTH_CLIENT_SECRET', refresh: 'GOOGLE_ADS_REFRESH_TOKEN' },
  },
  sheets: {
    label: 'sheets',
    defaultPath: join(PROJECT_ROOT, 'store', '.google-sheets-credentials'),
    keys: { id: 'CLIENT_ID', secret: 'CLIENT_SECRET', refresh: 'REFRESH_TOKEN' },
  },
}

interface OAuthCreds {
  clientId: string
  clientSecret: string
  refreshToken: string
}

export type CheckStatus = 'ok' | 'rejected' | 'unknown'

export interface CheckResult {
  profile: string
  status: CheckStatus
  expiresIn?: number | null
  error?: string | null
  http?: number | null
  message: string
}

// KEY=value file, same shape as the M365 credentials (see src/graph-mail.ts).
// Values are NOT unquoted beyond a trim: a stray quote in a secret is better
// surfaced as an auth failure than silently stripped into a different secret.
function readCreds(path: string, spec: ProfileSpec): OAuthCreds {
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
  const need = [spec.keys.id, spec.keys.secret, spec.keys.refresh]
  const missing = need.filter((k) => !kv.get(k))
  if (missing.length) throw new Error(`missing key(s) in ${path}: ${missing.join(', ')}`)
  return {
    clientId: kv.get(need[0])!,
    clientSecret: kv.get(need[1])!,
    refreshToken: kv.get(need[2])!,
  }
}

export async function checkProfile(profileName: string, credsPathOverride?: string): Promise<CheckResult> {
  const spec = PROFILES[profileName]
  if (!spec) {
    return { profile: profileName, status: 'unknown', message: `[${profileName}] CONFIG ERROR: unknown profile (known: ${Object.keys(PROFILES).join(', ')})` }
  }
  const credsPath = credsPathOverride || spec.defaultPath

  let creds: OAuthCreds
  try {
    creds = readCreds(credsPath, spec)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    return { profile: spec.label, status: 'unknown', message: `[${spec.label}] CONFIG ERROR: ${msg}` }
  }

  const body = new URLSearchParams({
    client_id: creds.clientId,
    client_secret: creds.clientSecret,
    refresh_token: creds.refreshToken,
    grant_type: 'refresh_token',
  })

  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), REQUEST_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(TOKEN_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
      signal: ac.signal,
    })
  } catch (err) {
    // Network failure, DNS, timeout. This is NOT "the token is dead" -- saying
    // so would send a human off to re-authorise a working token.
    const msg = err instanceof Error ? err.message : String(err)
    return { profile: spec.label, status: 'unknown', message: `[${spec.label}] COULD NOT CHECK (network): ${msg}` }
  } finally {
    clearTimeout(timer)
  }

  const text = await res.text()
  if (res.ok) {
    // Deliberately reading only the non-secret fields. access_token is ignored.
    let expiresIn: unknown
    let scope: unknown
    try {
      const parsed = JSON.parse(text) as { expires_in?: unknown; scope?: unknown }
      expiresIn = parsed.expires_in
      scope = parsed.scope
    } catch { /* ignore */ }
    const scopeSuffix = typeof scope === 'string' ? `, scope: ${scope}` : ''
    const message = typeof expiresIn === 'number'
      ? `[${spec.label}] OK -- refresh token valid, minted a token good for ${expiresIn}s${scopeSuffix}`
      : `[${spec.label}] OK -- refresh token valid${scopeSuffix}`
    return { profile: spec.label, status: 'ok', expiresIn: typeof expiresIn === 'number' ? expiresIn : null, message }
  }

  // Google answers a dead/revoked refresh token with 400 invalid_grant. Other
  // 4xx/5xx are config or service problems, so they must not read as "revoked".
  let errCode = ''
  try { errCode = String((JSON.parse(text) as { error?: unknown }).error ?? '') } catch { /* ignore */ }
  if (res.status === 400 && errCode === 'invalid_grant') {
    return {
      profile: spec.label,
      status: 'rejected',
      error: errCode,
      message: `[${spec.label}] REJECTED -- the refresh token is no longer valid, a human must re-authorise`,
    }
  }
  return {
    profile: spec.label,
    status: 'unknown',
    http: res.status,
    error: errCode || null,
    message: `[${spec.label}] COULD NOT CHECK (http ${res.status}${errCode ? ` ${errCode}` : ''})`,
  }
}

function worstStatus(results: CheckResult[]): CheckStatus {
  if (results.some((r) => r.status === 'rejected')) return 'rejected'
  if (results.some((r) => r.status === 'unknown')) return 'unknown'
  return 'ok'
}

function exitCodeFor(status: CheckStatus): number {
  return status === 'ok' ? 0 : status === 'rejected' ? 1 : 2
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const pi = argv.indexOf('--profile')
  const profileArg = pi >= 0 && argv[pi + 1] ? argv[pi + 1] : 'all'
  const ci = argv.indexOf('--creds')
  const credsOverride = ci >= 0 && argv[ci + 1] ? argv[ci + 1] : undefined

  const profileNames = profileArg === 'all' ? Object.keys(PROFILES) : [profileArg]

  if (credsOverride && profileArg === 'all') {
    const msg = '[google-oauth-token-health] CONFIG ERROR: --creds requires a single --profile, ambiguous with --profile all'
    console.error(msg)
    if (asJson) console.log(JSON.stringify({ overall: 'unknown', error: msg }))
    return 2
  }
  if (!PROFILES[profileNames[0]] && profileArg !== 'all') {
    const msg = `[google-oauth-token-health] CONFIG ERROR: unknown profile "${profileArg}" (known: ${Object.keys(PROFILES).join(', ')})`
    console.error(msg)
    if (asJson) console.log(JSON.stringify({ overall: 'unknown', error: msg }))
    return 2
  }

  const results: CheckResult[] = []
  for (const name of profileNames) {
    results.push(await checkProfile(name, credsOverride))
  }

  const overall = worstStatus(results)

  if (asJson) {
    const byProfile: Record<string, unknown> = {}
    for (const r of results) {
      byProfile[r.profile] = { status: r.status, expiresIn: r.expiresIn ?? null, error: r.error ?? null, http: r.http ?? null }
    }
    const statuses = new Set(results.map((r) => r.status))
    const divergent = results.length > 1 && statuses.size > 1
    console.log(JSON.stringify({ overall, divergent, profiles: byProfile }))
  } else {
    for (const r of results) {
      if (r.status === 'ok') console.log(r.message)
      else console.error(r.message)
    }
    if (results.length > 1) {
      const statuses = new Set(results.map((r) => r.status))
      if (statuses.size > 1) {
        console.error(
          `[google-oauth-token-health] DIVERGENT -- these profiles share one OAuth client and were expected to live/die together, but their statuses differ (${results.map((r) => `${r.profile}=${r.status}`).join(', ')}). Treat the divergence itself as a finding.`,
        )
      }
    }
  }

  return exitCodeFor(overall)
}

// Only run the CLI when this file is the entry point, so google-ads-token.ts
// can import checkProfile()/PROFILES without triggering a second run.
const isMain = process.argv[1] && import.meta.url === `file://${process.argv[1]}`
if (isMain) {
  process.exit(await main())
}
