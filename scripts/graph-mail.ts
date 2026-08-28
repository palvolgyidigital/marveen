#!/usr/bin/env tsx
// Thin CLI over src/graph-mail.ts, for operating the scoped M365 mailbox by
// hand (smoke test, quick read, one-off send) without writing code.
//
//   tsx scripts/graph-mail.ts verify
//   tsx scripts/graph-mail.ts list [--unread] [--top N] [--folder inbox|sentitems]
//   tsx scripts/graph-mail.ts headers --id <messageId> [--json]
//   tsx scripts/graph-mail.ts send --to a@b.hu[,c@d.hu] --subject "..." --body "..." [--cc ...] [--html]
//
// Credentials come from the gitignored marveen-mail-ugyfelkod file (override
// with MARVEEN_MAIL_CREDS). Send is intentionally CLI-explicit; the sub-agent
// email-send-gate hook still applies to any programmatic use elsewhere.

import { classifyAutomated, getMessageHeaders, listMessages, sendMail, verifyAccess } from '../src/graph-mail.js'

function flag(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`)
  return i !== -1 ? process.argv[i + 1] : undefined
}
function has(name: string): boolean {
  return process.argv.includes(`--${name}`)
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
      await sendMail({
        to: to.split(','),
        subject,
        body,
        cc: flag('cc')?.split(','),
        contentType: has('html') ? 'HTML' : 'Text',
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
