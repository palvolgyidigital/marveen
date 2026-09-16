/**
 * David kerese (2026-09-10): a Mini Kavezo ajanlat-level tenylegesen PISZKOZATKENT
 * keruljon be egy olyan postafiokba, amihez neki van hozzaferese (innova@pdb.hu,
 * kozos fiok) -- NEM elkuldve, csak a Draftok kozott varva az o jovahagyasara.
 *
 * A kozos src/graph-mail.ts sendMail fuggvenye csak KULDES-t tud, piszkozatot nem.
 * A Graph API POST /users/{mailbox}/messages viszont draft-ot hoz letre (nem kuld),
 * ugyanugy mint a send-keszletriport-mail.ts referencia, csak /messages vegpontra,
 * nem /sendMail-re, es "isDraft: true" (a Graph API alapertelmezetten is draft-ot
 * csinal POST /messages-szel, de expliciten kiirjuk).
 *
 * Hasznalat:
 *   MARVEEN_MAIL_CREDS=/home/pdb/marveen/store/.m365-innova-credentials \
 *     npx tsx scripts/create-draft-mini-kavezo.ts [--dry-run]
 */
import { readFileSync } from 'node:fs'

const dryRun = process.argv.includes('--dry-run')

const credPath = process.env.MARVEEN_MAIL_CREDS ?? '/home/pdb/marveen/store/.m365-innova-credentials'
const cred = readFileSync(credPath, 'utf8')
const get = (k: string) =>
  cred.split('\n').find((l) => l.startsWith(k + '='))?.split('=').slice(1).join('=').trim() ?? ''
const tenant = get('TENANT_ID')
const clientId = get('CLIENT_ID')
const clientSecret = get('CLIENT_SECRET')
const mailbox = get('MAILBOX')

const to = 'minikavezoesteahaz@gmail.com'
const subject = 'Digitális képkeret ajánlat - PDB'

const body = `<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.5">
<p>Kedves Mini Kávézó és Teaház csapata!</p>
<p>Örülök, hogy megismerhettük egymást. Ajánlanánk Önöknek egy digitális képkeretet, amivel könnyen megjeleníthetnek fotókat, videókat vagy akár akciós ajánlatokat a kávézóban - wifis modell, telefonos alkalmazásból bármikor frissíthető tartalommal. Néhány változatot is küldünk, hogy legyen miből választani:</p>
<ul style="padding-left:18px">
<li><strong>AgfaPhoto APF1000WIFI, 10", 32GB, videó/hang, mozgásérzékelő, Frameo, fekete</strong> - 53 990 Ft<br>
<a href="https://www.pdb.hu/Agfa-APF1000WIFI-digitalis-kepkeret-10-WIFI-video">https://www.pdb.hu/Agfa-APF1000WIFI-digitalis-kepkeret-10-WIFI-video</a></li>
<li><strong>AgfaPhoto APF1000WIFI, 10", 32GB, üveg előlappal, fekete</strong> - 41 990 Ft<br>
<a href="https://www.pdb.hu/AgfaPhoto-APF1000WIFI-digitalis-kepkeret-10-WIFI-v">https://www.pdb.hu/AgfaPhoto-APF1000WIFI-digitalis-kepkeret-10-WIFI-v</a></li>
<li><strong>AgfaPhoto APF1000WIFI, 10", 32GB, fa hatású</strong> - 53 990 Ft<br>
<a href="https://www.pdb.hu/spd/AG-APF1000WIFIWOOD/AgfaPhoto-APF1000WIFI-digitalis-kepkeret-10-video">https://www.pdb.hu/spd/AG-APF1000WIFIWOOD/AgfaPhoto-APF1000WIFI-digitalis-kepkeret-10-video</a></li>
<li><strong>AgfaPhoto APF1000WIFI ONE, 10", 16GB, fekete</strong> (egyszerűbb, kedvezőbb árú változat) - 39 990 Ft<br>
<a href="https://www.pdb.hu/AgfaPhoto-APF1000WIFIONE-digitalis-kepkeret-10-WIF">https://www.pdb.hu/AgfaPhoto-APF1000WIFIONE-digitalis-kepkeret-10-WIF</a></li>
</ul>
<p>Ha feliratkoznak a hírlevelünkre, 15% kedvezményt kapnak a vásárláshoz: <a href="https://www.pdb.hu/shop_newsletter.php">https://www.pdb.hu/shop_newsletter.php</a></p>
<p>Ha érdekli Önöket valamelyik, szívesen segítünk a rendelésben.</p>
</div>
<table cellpadding="0" cellspacing="0" border="0" style="margin-top:26px;border-top:1px solid #e2e2e2;padding-top:14px;font-family:Arial,Helvetica,sans-serif">
 <tr><td style="font-size:14px;color:#222;line-height:1.35;padding-bottom:8px">Üdv,<br><strong>PDB</strong></td></tr>
 <tr><td style="font-size:11px;line-height:1.35;color:#404040">
   <a href="https://www.google.com/maps/place/47%C2%B031'10.7%22N+19%C2%B011'31.1%22E/@47.519644,19.19196,572m" style="color:#0563C1;text-decoration:underline">1165 Budapest, Margit utca 114., Ikarus gyár, 44/6 épület</a><br>
   <strong style="font-size:12px">+36 70 611 70 78 &nbsp;|&nbsp; +36 30 550 70 75</strong><br>
   <span style="font-size:13px">
     <a href="http://www.pdb.hu/" style="color:#BF8F00;text-decoration:none">PDB</a> &nbsp;|&nbsp;
     <a href="https://www.facebook.com/pdb.hu/" style="color:#BF8F00;text-decoration:none">Facebook</a> &nbsp;|&nbsp;
     <a href="https://www.instagram.com/palvolgyi_digital/" style="color:#BF8F00;text-decoration:none">Instagram</a>
   </span>
 </td></tr>
</table>`

if (dryRun) {
  console.log('DRY RUN, nem hozok letre draft-ot.')
  console.log('  postafiok:', mailbox)
  console.log('  cimzett  :', to)
  console.log('  targy    :', subject)
  console.log('  body hossz:', body.length, 'karakter')
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

const res = await fetch(`https://graph.microsoft.com/v1.0/users/${encodeURIComponent(mailbox)}/messages`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${access_token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({
    subject,
    body: { contentType: 'HTML', content: body },
    toRecipients: [{ emailAddress: { address: to } }],
    isDraft: true,
  }),
})
if (!res.ok) {
  console.error('HIBA: draft letrehozas sikertelen', res.status, await res.text())
  process.exit(1)
}
const created = (await res.json()) as { id: string; webLink?: string }
console.log(`DRAFT LETREHOZVA -> postafiok: ${mailbox} | id: ${created.id}`)
if (created.webLink) console.log(`  webLink: ${created.webLink}`)
