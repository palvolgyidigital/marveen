import { readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { logger } from './logger.js'

// Microsoft Graph mail for a single M365 mailbox (marveen@pecibt.hu), via the
// app-only client-credentials flow. The app registration holds NO tenant-wide
// Mail.* Graph permission; access is scoped to one mailbox by an Exchange
// Online RBAC ManagementScope, so this module can only ever touch that box.
// See the m365-graph-mailbox-scoping skill for the full provisioning story.
//
// No @azure/msal-node dependency: the client-credentials flow is a single
// form-POST to the token endpoint, and Graph calls are plain fetch with a
// Bearer header. Adding an SDK for that would be more moving parts, not fewer.

const __dirname = dirname(fileURLToPath(import.meta.url))
const PROJECT_ROOT = join(__dirname, '..')

// Gitignored KEY=value credentials file at the repo root. Path is overridable
// so an operator can relocate it (e.g. outside the repo) without code changes.
const CREDS_PATH = process.env.MARVEEN_MAIL_CREDS || join(PROJECT_ROOT, 'store', '.m365-innova-credentials')

const GRAPH_BASE = 'https://graph.microsoft.com/v1.0'
const REQUEST_TIMEOUT_MS = 20_000

export interface MailCredentials {
  tenantId: string
  clientId: string
  clientSecret: string
  mailbox: string
}

export interface GraphMessage {
  id: string
  subject?: string
  from?: { emailAddress?: { name?: string; address?: string } }
  toRecipients?: Array<{ emailAddress?: { name?: string; address?: string } }>
  receivedDateTime?: string
  bodyPreview?: string
  isRead?: boolean
  webLink?: string
}

/** One RFC 5322 header as Graph returns it in `internetMessageHeaders`. */
export interface InternetMessageHeader {
  name: string
  value: string
}

/**
 * Result of the automated-sender check. `automated: true` means the message
 * is an auto-reply, out-of-office, bulk send or bounce, and must NOT be
 * answered by an automated chain -- two auto-responders would otherwise mail
 * each other in a loop. `reasons` lists the exact headers that triggered it,
 * so a dry-run can be audited by a human without re-reading the raw headers.
 */
export interface AutomatedVerdict {
  automated: boolean
  reasons: string[]
}

export interface SendMailOptions {
  to: string | string[]
  subject: string
  body: string
  cc?: string | string[]
  /** 'Text' (default) or 'HTML' for the Graph message body contentType. */
  contentType?: 'Text' | 'HTML'
  /** Persist the sent message to the mailbox Sent Items. Default true. */
  saveToSentItems?: boolean
}

export interface ListMessagesOptions {
  /** How many messages to return (Graph $top). Default 10, capped at 50. */
  top?: number
  /** Well-known folder id, e.g. 'inbox' (default) or 'sentitems'. */
  folder?: string
  /** Only unread messages (Graph $filter isRead eq false). */
  unreadOnly?: boolean
}

// Credentials cache with mtime invalidation -- same reasoning as google-api.ts:
// the file is edited out-of-process (operator rotates the secret), and a stale
// in-memory copy would keep authenticating with a revoked secret until a
// restart. Re-read whenever the file's mtime advances.
let cachedCreds: { value: MailCredentials; mtimeMs: number } | null = null

// Parse the gitignored KEY=value credentials file. Exported so the pure
// parsing logic is unit-testable without touching the filesystem.
export function parseCredentials(content: string): MailCredentials {
  const map: Record<string, string> = {}
  for (const line of content.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eqIdx = trimmed.indexOf('=')
    if (eqIdx === -1) continue
    const key = trimmed.slice(0, eqIdx).trim()
    let value = trimmed.slice(eqIdx + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    map[key] = value
  }
  const creds: MailCredentials = {
    tenantId: map.TENANT_ID ?? '',
    clientId: map.CLIENT_ID ?? '',
    clientSecret: map.CLIENT_SECRET ?? '',
    mailbox: map.MAILBOX ?? '',
  }
  const missing = (Object.keys(creds) as Array<keyof MailCredentials>).filter((k) => !creds[k])
  if (missing.length > 0) {
    throw new Error(
      `graph-mail: incomplete credentials, missing ${missing.join(', ')} ` +
        `(expected TENANT_ID / CLIENT_ID / CLIENT_SECRET / MAILBOX in ${CREDS_PATH})`,
    )
  }
  return creds
}

function loadCredentials(): MailCredentials {
  let currentMtime = 0
  try {
    currentMtime = statSync(CREDS_PATH).mtimeMs
  } catch {
    throw new Error(
      `graph-mail: credentials file not found at ${CREDS_PATH}. ` +
        `Set MARVEEN_MAIL_CREDS or create the file with TENANT_ID / CLIENT_ID / CLIENT_SECRET / MAILBOX.`,
    )
  }
  if (!cachedCreds || cachedCreds.mtimeMs !== currentMtime) {
    cachedCreds = { value: parseCredentials(readFileSync(CREDS_PATH, 'utf-8')), mtimeMs: currentMtime }
  }
  return cachedCreds.value
}

// Access-token cache. The client-credentials token lasts ~1h; we refresh once
// it is within 60s of expiry so an in-flight request never races the cutover.
let cachedToken: { value: string; expiresAt: number; clientId: string } | null = null

async function withTimeout<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    return await fn(controller.signal)
  } finally {
    clearTimeout(timer)
  }
}

async function getToken(): Promise<string> {
  const creds = loadCredentials()
  // Bind the cache to the clientId so a rotated app registration doesn't reuse
  // a token minted for the old client.
  if (cachedToken && cachedToken.clientId === creds.clientId && cachedToken.expiresAt > Date.now() + 60_000) {
    return cachedToken.value
  }
  const url = `https://login.microsoftonline.com/${creds.tenantId}/oauth2/v2.0/token`
  const body = new URLSearchParams({
    client_id: creds.clientId,
    client_secret: creds.clientSecret,
    scope: 'https://graph.microsoft.com/.default',
    grant_type: 'client_credentials',
  })
  const res = await withTimeout((signal) =>
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
      signal,
    }),
  )
  const text = await res.text()
  if (!res.ok) {
    // Do not log the response body verbatim -- AADSTS errors sometimes echo
    // request parameters. Log status + the short error code only.
    let code = 'unknown'
    try {
      code = JSON.parse(text).error ?? 'unknown'
    } catch {
      /* non-JSON body */
    }
    throw new Error(`graph-mail: token request failed (${res.status} ${code})`)
  }
  const json = JSON.parse(text) as { access_token: string; expires_in: number }
  cachedToken = {
    value: json.access_token,
    expiresAt: Date.now() + json.expires_in * 1000,
    clientId: creds.clientId,
  }
  return json.access_token
}

async function graphFetch(path: string, init?: RequestInit): Promise<Response> {
  const token = await getToken()
  return withTimeout((signal) =>
    fetch(`${GRAPH_BASE}${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(init?.headers ?? {}),
      },
      signal,
    }),
  )
}

function mailboxPath(): string {
  return `/users/${encodeURIComponent(loadCredentials().mailbox)}`
}

function toRecipientList(addrs: string | string[]): Array<{ emailAddress: { address: string } }> {
  return (Array.isArray(addrs) ? addrs : [addrs])
    .map((a) => a.trim())
    .filter(Boolean)
    .map((address) => ({ emailAddress: { address } }))
}

/** List messages from the scoped mailbox (default: 10 newest from Inbox). */
export async function listMessages(options: ListMessagesOptions = {}): Promise<GraphMessage[]> {
  const top = Math.min(Math.max(options.top ?? 10, 1), 50)
  const folder = options.folder ?? 'inbox'
  const params = new URLSearchParams({
    $top: String(top),
    $orderby: 'receivedDateTime desc',
    $select: 'id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,webLink',
  })
  if (options.unreadOnly) params.set('$filter', 'isRead eq false')
  const res = await graphFetch(`${mailboxPath()}/mailFolders/${encodeURIComponent(folder)}/messages?${params}`)
  if (!res.ok) {
    throw new Error(`graph-mail: listMessages failed (${res.status} ${await res.text()})`)
  }
  const json = (await res.json()) as { value?: GraphMessage[] }
  return json.value ?? []
}

/** Send mail from the scoped mailbox via Graph /sendMail. */
export async function sendMail(options: SendMailOptions): Promise<void> {
  const message: Record<string, unknown> = {
    subject: options.subject,
    body: { contentType: options.contentType ?? 'Text', content: options.body },
    toRecipients: toRecipientList(options.to),
  }
  if (options.cc) message.ccRecipients = toRecipientList(options.cc)
  const res = await graphFetch(`${mailboxPath()}/sendMail`, {
    method: 'POST',
    body: JSON.stringify({ message, saveToSentItems: options.saveToSentItems ?? true }),
  })
  if (!res.ok && res.status !== 202) {
    throw new Error(`graph-mail: sendMail failed (${res.status} ${await res.text()})`)
  }
  logger.info({ to: options.to, subject: options.subject }, 'graph-mail: sent')
}

/**
 * Connectivity + scope smoke check: confirms the token mints and the scoped
 * mailbox is reachable. Returns the mailbox address on success, throws on any
 * auth/permission failure. Does not prove the RBAC *restriction* (that another
 * mailbox is denied) -- that is verified once, out of band, at provisioning.
 */
export async function verifyAccess(): Promise<{ mailbox: string; messageCount: number }> {
  const creds = loadCredentials()
  const res = await graphFetch(`${mailboxPath()}/messages?$top=1&$select=id`)
  if (!res.ok) {
    throw new Error(`graph-mail: verifyAccess failed for ${creds.mailbox} (${res.status} ${await res.text()})`)
  }
  const json = (await res.json()) as { value?: unknown[] }
  return { mailbox: creds.mailbox, messageCount: json.value?.length ?? 0 }
}

// --- Header reading and automated-sender classification -------------------
//
// The unsubscribe-confirmation chain (store/leiratkozas-agent/ELJARAS.md) may
// only answer a message that a human actually sent. Matching on the subject
// line is not enough: an out-of-office or a bounce can carry the same words,
// and answering one of those puts two robots in a loop. RFC 3834 and the
// de-facto X-headers below are the only reliable signal, and they live in the
// internet headers, which Graph does not return in a message list.

/**
 * Fetch the RFC 5322 internet headers of a single message.
 *
 * Graph only returns `internetMessageHeaders` when it is explicitly selected,
 * and only on the single-message endpoint -- a `$select` on a message
 * *collection* silently omits it. So a caller must list first, then fetch the
 * headers per message id. Graph also caps the array at the first 256 headers,
 * which is far more than the classification below needs.
 *
 * Returns an empty array for a message that has no internet headers at all
 * (drafts, and items created inside the mailbox rather than received by SMTP).
 */
export async function getMessageHeaders(messageId: string): Promise<InternetMessageHeader[]> {
  const params = new URLSearchParams({ $select: 'internetMessageHeaders' })
  const res = await graphFetch(`${mailboxPath()}/messages/${encodeURIComponent(messageId)}?${params}`)
  if (!res.ok) {
    throw new Error(`graph-mail: getMessageHeaders failed (${res.status} ${await res.text()})`)
  }
  const json = (await res.json()) as { internetMessageHeaders?: InternetMessageHeader[] }
  return json.internetMessageHeaders ?? []
}

/** Case-insensitive lookup of every value sent under one header name. */
function headerValues(headers: InternetMessageHeader[], name: string): string[] {
  const wanted = name.toLowerCase()
  return headers.filter((h) => h?.name?.toLowerCase() === wanted).map((h) => (h.value ?? '').trim())
}

// Precedence values that mark a message as machine-generated. `Precedence` is
// not a standard header, but bulk/list/junk/auto_reply are the values mailers
// have used for it for decades, and Exchange passes it through untouched.
const AUTOMATED_PRECEDENCE = new Set(['bulk', 'list', 'junk', 'auto_reply'])

/**
 * Decide whether a message was machine-generated, from its headers alone.
 *
 * Deliberately conservative in one direction: a false "automated" only costs
 * us a confirmation mail that a human has to send by hand, while a false
 * "human" starts a mail loop with another robot.
 */
export function classifyAutomated(headers: InternetMessageHeader[]): AutomatedVerdict {
  const reasons: string[] = []

  // RFC 3834. Any value other than "no" means the message was generated by an
  // automatic process; "auto-replied" and "auto-generated" are the common ones.
  for (const v of headerValues(headers, 'Auto-Submitted')) {
    if (v.toLowerCase().split(';')[0].trim() !== 'no') reasons.push(`Auto-Submitted: ${v}`)
  }

  // Set by Exchange senders to ask recipients not to auto-reply. Its presence
  // means an automated answer is unwanted, whichever side generated the mail.
  for (const v of headerValues(headers, 'X-Auto-Response-Suppress')) {
    reasons.push(`X-Auto-Response-Suppress: ${v}`)
  }

  for (const v of headerValues(headers, 'Precedence')) {
    if (AUTOMATED_PRECEDENCE.has(v.toLowerCase())) reasons.push(`Precedence: ${v}`)
  }

  // A null return-path is the RFC 5321 null sender: every bounce (DSN) and
  // most auto-replies use it precisely so that they cannot be replied to.
  // Measured against the live tenant (2026-08-29): Graph strips the angle
  // brackets, so a normal address arrives as `abel.kondics@pdb.hu`, not
  // `<abel.kondics@pdb.hu>`. The null sender therefore reaches us as an empty
  // value just as plausibly as a literal `<>`, and both must count.
  for (const v of headerValues(headers, 'Return-Path')) {
    const stripped = v.replace(/\s+/g, '')
    if (stripped === '' || stripped === '<>') reasons.push('Return-Path: null sender')
  }

  // Bounce reports proper. X-Failed-Recipients is the Postfix/Exim marker;
  // multipart/report with a delivery-status part is the RFC 6522 form.
  for (const v of headerValues(headers, 'X-Failed-Recipients')) {
    reasons.push(`X-Failed-Recipients: ${v}`)
  }
  for (const v of headerValues(headers, 'Content-Type')) {
    const lowered = v.toLowerCase()
    if (lowered.includes('multipart/report') && lowered.includes('report-type=delivery-status')) {
      reasons.push('Content-Type: multipart/report; report-type=delivery-status')
    }
  }

  // Older auto-responders that predate RFC 3834 and still ship today.
  for (const name of ['X-Autoreply', 'X-Autorespond', 'X-Autoresponder']) {
    for (const v of headerValues(headers, name)) reasons.push(`${name}: ${v}`)
  }

  return { automated: reasons.length > 0, reasons }
}
