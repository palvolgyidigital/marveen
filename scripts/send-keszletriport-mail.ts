/**
 * Kuldi a napi MM keszletriportot Abelnek emailben, csatolmannyal.
 * Abel kerese 2026-08-18. Az innova@pdb.hu-rol megy, Abel tovabbitja a partnernek.
 *
 * Hasznalat:
 *   MARVEEN_MAIL_CREDS=/home/pdb/marveen/store/.m365-innova-credentials \
 *     npx tsx scripts/send-keszletriport-mail.ts <fajl.xlsx> [cimzett] [--dry-run]
 *
 * A graph-mail konyvtar sendMail fuggvenye NEM tud csatolmanyt, ezert ez a script
 * kozvetlenul a Graph API-t hivja. A megosztott src/graph-mail.ts-hez NEM nyulunk.
 */
import { readFileSync, existsSync } from 'node:fs'
import { basename } from 'node:path'

const [, , filePath, toArg, ...rest] = process.argv
const dryRun = rest.includes('--dry-run') || toArg === '--dry-run'
const to = toArg && !toArg.startsWith('--') ? toArg : 'abel.kondics@pdb.hu'

if (!filePath || !existsSync(filePath)) {
  console.error('HIBA: add meg a csatolando xlsx utvonalat. Kapott:', filePath)
  process.exit(1)
}

const credPath = process.env.MARVEEN_MAIL_CREDS ?? '/home/pdb/marveen/store/.m365-innova-credentials'
const cred = readFileSync(credPath, 'utf8')
const get = (k: string) =>
  cred.split('\n').find((l) => l.startsWith(k + '='))?.split('=').slice(1).join('=').trim() ?? ''
const tenant = get('TENANT_ID')
const clientId = get('CLIENT_ID')
const clientSecret = get('CLIENT_SECRET')
const mailbox = get('MAILBOX')

// Targy: "Keszlet riport EEEEHHNN" -- a mai datum Europe/Budapest szerint
const now = new Date()
const hu = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Budapest' }).format(now) // YYYY-MM-DD
const stamp = hu.replaceAll('-', '')
const subject = `Készlet riport ${stamp}`

const LOGO_PATH = '/home/pdb/marveen/store/email-signatures/hu-logo.png'
const LOGO_CID = 'pdb-logo-keszletriport'
const hasLogo = existsSync(LOGO_PATH)

const SIGNATURE = `
<table cellpadding="0" cellspacing="0" border="0" style="margin-top:18px;font-family:Arial,Helvetica,sans-serif;border-collapse:collapse">
 <tr><td style="font-size:13px;color:#222;line-height:1.3;padding:0;margin:0">
   <strong>Kondics Ábel</strong> | Back Office Manager${hasLogo ? `<br><img src="cid:${LOGO_CID}" width="203" height="70" alt="PDB" style="width:203px;height:70px;display:block;border:0;margin:2px 0 2px -2px">` : '<br>'}<div style="font-size:11px;color:#404040;line-height:1.3">1165 Budapest, Margit u. 114. 44/6 épület<br><strong style="font-size:12px">+36 30 550 70 75 &nbsp;|&nbsp; +36 20 402 50 13</strong><br><span style="font-size:13px"><a href="http://www.pdb.hu/" style="color:#BF8F00;text-decoration:none">PDB</a> &nbsp;|&nbsp; <a href="https://www.facebook.com/pdb.hu/" style="color:#BF8F00;text-decoration:none">Facebook</a> &nbsp;|&nbsp; <a href="https://www.instagram.com/palvolgyi_digital/" style="color:#BF8F00;text-decoration:none">Instagram</a></span></div>
 </td></tr>
</table>`

const body = `<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.5">
<p>Kedves Partnerünk!</p>
<p>Csatolva küldöm az aktuális készlet riportot.</p>
<p>Köszönettel:</p>
${SIGNATURE}
</div>`

const contentBytes = readFileSync(filePath).toString('base64')
const attachmentName = basename(filePath)

if (dryRun) {
  console.log('DRY RUN, nem kuldok levelet.')
  console.log('  cimzett :', to)
  console.log('  targy   :', subject)
  console.log('  csatolm.:', attachmentName, readFileSync(filePath).length, 'byte')
  console.log('  logo    :', hasLogo ? LOGO_PATH : 'NINCS (a fajl hianyzik, alairas logo nelkul megy)')
  process.exit(0)
}

const tokRes = await fetch(`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    scope: 'https://graph.microsoft.com/.default',
    grant_type: 'client_credentials',
  }),
})
if (!tokRes.ok) {
  console.error('HIBA: token keres sikertelen', tokRes.status)
  process.exit(1)
}
const { access_token } = (await tokRes.json()) as { access_token: string }

const res = await fetch(`https://graph.microsoft.com/v1.0/users/${encodeURIComponent(mailbox)}/sendMail`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({
    message: {
      subject,
      body: { contentType: 'HTML', content: body },
      toRecipients: [{ emailAddress: { address: to } }],
      attachments: [
        {
          '@odata.type': '#microsoft.graph.fileAttachment',
          name: attachmentName,
          contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          contentBytes,
        },
        // A logo INLINE kep: contentId + isInline, a HTML-ben cid: hivatkozassal.
        // Ez azert lehetseges, mert ez a script kozvetlenul a Graph API-t hivja --
        // a kozos src/graph-mail.ts sendMail fuggvenye NEM tud csatolmanyt/inline kepet.
        ...(hasLogo
          ? [
              {
                '@odata.type': '#microsoft.graph.fileAttachment',
                name: 'pdb-logo.png',
                contentType: 'image/png',
                contentId: LOGO_CID,
                isInline: true,
                contentBytes: readFileSync(LOGO_PATH).toString('base64'),
              },
            ]
          : []),
      ],
    },
    saveToSentItems: true,
  }),
})
if (!res.ok && res.status !== 202) {
  console.error('HIBA: sendMail sikertelen', res.status, await res.text())
  process.exit(1)
}
console.log(`ELKULDVE -> ${to} | targy: ${subject} | csatolmany: ${attachmentName}`)
