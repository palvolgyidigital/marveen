#!/usr/bin/env tsx
// One message's FULL body. `graph-mail.ts list` prints Graph's bodyPreview, which is
// capped around 255 characters -- measured 2026-09-18: Abel's EPR letter carried its
// actual instructions BELOW that cut, so the preview showed the topic and hid the task.
//
//   MARVEEN_MAIL_CREDS=store/.m365-innova-credentials tsx scripts/graph-mail-torzs.ts <messageId>
//
// Read-only. Uses the same credentials file and the same client-credentials flow as
// the rest of graph-mail; no send path here on purpose.
import { readFileSync } from 'node:fs'
import { parseCredentials } from '../src/graph-mail.js'

async function main() {
  const credsPath = process.env.MARVEEN_MAIL_CREDS
  const id = process.argv[2]
  if (!credsPath || !id) {
    console.error('usage: MARVEEN_MAIL_CREDS=<file> tsx scripts/graph-mail-torzs.ts <messageId>')
    process.exit(2)
  }
  const creds = parseCredentials(readFileSync(credsPath, 'utf-8'))
  const tr = await fetch(`https://login.microsoftonline.com/${creds.tenantId}/oauth2/v2.0/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: creds.clientId, client_secret: creds.clientSecret,
      scope: 'https://graph.microsoft.com/.default', grant_type: 'client_credentials',
    }),
  })
  if (!tr.ok) { console.error('token:', tr.status, await tr.text()); process.exit(1) }
  const { access_token } = (await tr.json()) as { access_token: string }
  const sel = 'subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments'
  const r = await fetch(
    `https://graph.microsoft.com/v1.0/users/${encodeURIComponent(creds.mailbox)}` +
    `/messages/${encodeURIComponent(id)}?$select=${sel}`,
    { headers: { Authorization: `Bearer ${access_token}` } })
  if (!r.ok) { console.error(r.status, await r.text()); process.exit(1) }
  const m = (await r.json()) as any
  const cim = (xs: any[]) => (xs ?? []).map((x) => x.emailAddress?.address).join(', ')
  console.log('TARGY :', m.subject)
  console.log('FELADO:', m.from?.emailAddress?.address)
  console.log('CIMZET:', cim(m.toRecipients))
  console.log('CC    :', cim(m.ccRecipients))
  console.log('IDO   :', m.receivedDateTime, '| melleklet:', m.hasAttachments)
  console.log('='.repeat(72))
  const t = String(m.body?.content ?? '')
  console.log(m.body?.contentType === 'html'
    ? t.replace(/<br\s*\/?>/gi, '\n').replace(/<\/(p|div|tr|li)>/gi, '\n')
       .replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&')
       .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\n{3,}/g, '\n\n').trim()
    : t)
}
main()
