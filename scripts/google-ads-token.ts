// Google Ads OAuth refresh-token health check.
//
// WHY THIS EXISTS (OUTWARD915 / egress deny, 2026-09-15). The upstream commit
// e19a641 (PR #1218) put BASH_EGRESS_DENY on every agent's settings.json, which
// denies `curl *https://*` fleet-wide. The documented daily check for this token
// was a raw curl to oauth2.googleapis.com, so it stopped working -- and worse,
// it stopped working QUIETLY: a heartbeat that cannot run looks the same as one
// that ran and found everything fine.
//
// The deny list is a deny list, not a sandbox. Its stated target is "the
// URL-fetch verbs a misled-but-compliant agent reaches for"; sanctioned tooling
// that speaks HTTPS on its own (git, gh, npm, and scripts like graph-mail.ts)
// is deliberately untouched. This script is meant to sit in that second group,
// and it earns that only by being unable to act as a general fetcher:
//
//   THE ENDPOINT IS HARDCODED AND THERE IS NO URL ARGUMENT. Do not add one.
//   The moment this takes a URL from its caller it stops being a purpose-built
//   tool and becomes exactly the bypass the deny list exists to prevent.
//
// Approved by Marci on 2026-09-15 (permission_change is autonomy level 1 here,
// so this was his call, not the fleet's).
//
// SECRETS: the access token this exchange returns is NEVER printed. A daily
// health check needs to know whether the refresh token still works, not what it
// minted -- and this output lands in logs and heartbeat transcripts.
//
// Usage:
//   npx tsx scripts/google-ads-token.ts [--creds <path>] [--json]
// Exit codes:
//   0 = refresh token valid
//   1 = refresh token REJECTED (needs re-authorisation by a human)
//   2 = could not tell (network/config error) -- explicitly NOT the same as 1

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Hardcoded on purpose -- see the header. Not configurable, not an argument.
const TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
const REQUEST_TIMEOUT_MS = 20_000

const DEFAULT_CREDS = join(PROJECT_ROOT, 'agents', 'marti', '.google-ads-credentials')

interface OAuthCreds {
  clientId: string
  clientSecret: string
  refreshToken: string
}

// KEY=value file, same shape as the M365 credentials (see src/graph-mail.ts).
// Values are NOT unquoted beyond a trim: a stray quote in a secret is better
// surfaced as an auth failure than silently stripped into a different secret.
function readCreds(path: string): OAuthCreds {
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
  const need = ['GOOGLE_ADS_OAUTH_CLIENT_ID', 'GOOGLE_ADS_OAUTH_CLIENT_SECRET', 'GOOGLE_ADS_REFRESH_TOKEN']
  const missing = need.filter((k) => !kv.get(k))
  if (missing.length) throw new Error(`missing key(s) in ${path}: ${missing.join(', ')}`)
  return {
    clientId: kv.get(need[0])!,
    clientSecret: kv.get(need[1])!,
    refreshToken: kv.get(need[2])!,
  }
}

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const asJson = argv.includes('--json')
  const ci = argv.indexOf('--creds')
  const credsPath = ci >= 0 && argv[ci + 1] ? argv[ci + 1] : (process.env.GOOGLE_ADS_CREDS || DEFAULT_CREDS)

  let creds: OAuthCreds
  try {
    creds = readCreds(credsPath)
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    console.error(`[google-ads-token] CONFIG ERROR: ${msg}`)
    return 2
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
    // so would send a human off to re-authorise a working token. Exit 2.
    const msg = err instanceof Error ? err.message : String(err)
    console.error(`[google-ads-token] COULD NOT CHECK (network): ${msg}`)
    return 2
  } finally {
    clearTimeout(timer)
  }

  const text = await res.text()
  if (res.ok) {
    // Deliberately reading only the non-secret fields. access_token is ignored.
    let expiresIn: unknown
    try { expiresIn = (JSON.parse(text) as { expires_in?: unknown }).expires_in } catch { /* ignore */ }
    const line = typeof expiresIn === 'number'
      ? `[google-ads-token] OK -- refresh token valid, minted a token good for ${expiresIn}s`
      : `[google-ads-token] OK -- refresh token valid`
    console.log(asJson ? JSON.stringify({ status: 'ok', expiresIn: expiresIn ?? null }) : line)
    return 0
  }

  // Google answers a dead/revoked refresh token with 400 invalid_grant. Other
  // 4xx/5xx are config or service problems, so they must not read as "revoked".
  let errCode = ''
  try { errCode = String((JSON.parse(text) as { error?: unknown }).error ?? '') } catch { /* ignore */ }
  if (res.status === 400 && errCode === 'invalid_grant') {
    const line = '[google-ads-token] REJECTED -- the refresh token is no longer valid, a human must re-authorise'
    console.error(asJson ? JSON.stringify({ status: 'rejected', error: errCode }) : line)
    return 1
  }
  const line = `[google-ads-token] COULD NOT CHECK (http ${res.status}${errCode ? ` ${errCode}` : ''})`
  console.error(asJson ? JSON.stringify({ status: 'unknown', http: res.status, error: errCode || null }) : line)
  return 2
}

process.exit(await main())
