#!/usr/bin/env tsx
// Thin CLI over src/graph-mail.ts, for operating the scoped M365 mailbox by
// hand (smoke test, quick read, one-off send) without writing code.
//
//   tsx scripts/graph-mail.ts verify
//   tsx scripts/graph-mail.ts list [--unread] [--top N] [--folder inbox|sentitems]
//   tsx scripts/graph-mail.ts headers --id <messageId> [--json]
//   tsx scripts/graph-mail.ts send --to a@b.hu[,c@d.hu] --subject "..." --body "..." [--cc ...] [--html]
//                                  [--signature hu|en]
//
// --signature appends the OFFICIAL PDB signature (store/email-signatures/
// hu-tight.html or en-tight.html) and attaches its logo INLINE, so the letter
// carries the image instead of hot-linking it. It implies --html. Use it for
// every letter Pedro signs himself; a company-voice marketing letter has its
// own signature (see the pdb-html-email-send skill).
//
// Credentials come from the gitignored marveen-mail-ugyfelkod file (override
// with MARVEEN_MAIL_CREDS). Send is intentionally CLI-explicit; the sub-agent
// email-send-gate hook still applies to any programmatic use elsewhere.

import { readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { classifyAutomated, getMessageHeaders, listMessages, sendMail, verifyAccess } from '../src/graph-mail.js'

function flag(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`)
  return i !== -1 ? process.argv[i + 1] : undefined
}
function has(name: string): boolean {
  return process.argv.includes(`--${name}`)
}

const SIGNATURE_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'store', 'email-signatures')
// The checked-in signature HTML carries a FIXED cid; every message needs its own,
// so the placeholder is swapped for a fresh contentId at send time. Hard-coding the
// old value here is deliberate: if the signature file is ever re-exported with a
// different cid, the build below throws instead of silently sending a broken image.
const SIGNATURE_CID_PLACEHOLDER = 'cid:8ed1c134-9039-4487-97b0-d6ee4fac2557'

/** Build the HTML body + inline logo attachment for an official-signature letter. */
function withSignature(lang: string, body: string) {
  if (lang !== 'hu' && lang !== 'en') {
    console.error(`unknown --signature "${lang}" (use hu or en)`)
    process.exit(2)
  }
  const html = readFileSync(join(SIGNATURE_DIR, `${lang}-tight.html`), 'utf8')
  if (!html.includes(SIGNATURE_CID_PLACEHOLDER)) {
    console.error(`signature ${lang}-tight.html no longer contains the expected cid placeholder -- refusing to send a broken logo`)
    process.exit(2)
  }
  const cid = randomUUID()
  const logo = readFileSync(join(SIGNATURE_DIR, `${lang}-logo.png`))
  // The body arrives as plain text on the command line (that is what the approval
  // gate can read and hash); turn its line breaks into HTML ones, nothing more.
  const escaped = body
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\n/g, '<br>')
  return {
    content: `<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.45">${escaped}</div><br>${html.replace(SIGNATURE_CID_PLACEHOLDER, `cid:${cid}`)}`,
    attachments: [{
      name: `${lang}-logo.png`,
      contentType: 'image/png',
      contentBytes: logo.toString('base64'),
      isInline: true,
      contentId: cid,
    }],
  }
}

async function main(): Promise<void> {
  const cmd = process.argv[2]
  switch (cmd) {
    case 'verify': {
      const r = await verifyAccess()
      console.log(`OK -- reachable mailbox: ${r.mailbox}`)
      break
    }
    case 'list': {
      const msgs = await listMessages({
        top: flag('top') ? Number(flag('top')) : undefined,
        folder: flag('folder'),
        unreadOnly: has('unread'),
      })
      if (msgs.length === 0) {
        console.log('(no messages)')
        break
      }
      for (const m of msgs) {
        const from = m.from?.emailAddress?.address ?? '?'
        const when = m.receivedDateTime ?? ''
        const unread = m.isRead === false ? '● ' : '  '
        // The id is printed because it is the only handle `headers` accepts,
        // and Graph does not expose any shorter one.
        console.log(
          `${unread}${when}  ${from}\n    ${m.subject ?? '(no subject)'}\n    ${m.bodyPreview ?? ''}\n    id: ${m.id}\n`,
        )
      }
      break
    }
    case 'headers': {
      const id = flag('id')
      if (!id) {
        console.error('headers requires --id <messageId> (take it from the `list` output)')
        process.exit(2)
      }
      const headers = await getMessageHeaders(id)
      const verdict = classifyAutomated(headers)
      if (has('json')) {
        console.log(JSON.stringify({ headers, verdict }, null, 2))
        break
      }
      if (headers.length === 0) {
        console.log('(no internet headers -- draft, or an item not received over SMTP)')
      }
      for (const h of headers) console.log(`${h.name}: ${h.value}`)
      console.log(
        `\nautomated: ${verdict.automated ? 'yes' : 'no'}` +
          (verdict.reasons.length > 0 ? `\n  ${verdict.reasons.join('\n  ')}` : ''),
      )
      break
    }
    case 'send': {
      const to = flag('to')
      const subject = flag('subject')
      const body = flag('body')
      if (!to || !subject || body === undefined) {
        console.error('send requires --to, --subject and --body')
        process.exit(2)
      }
      const signature = flag('signature')
      const signed = signature ? withSignature(signature, body) : undefined
      await sendMail({
        to: to.split(','),
        subject,
        body: signed ? signed.content : body,
        cc: flag('cc')?.split(','),
        contentType: signed || has('html') ? 'HTML' : 'Text',
        attachments: signed?.attachments,
      })
      console.log(`sent to ${to}`)
      break
    }
    default:
      console.error('usage: graph-mail.ts <verify|list|headers|send> [options] (see file header)')
      process.exit(2)
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
