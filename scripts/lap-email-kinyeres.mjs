#!/usr/bin/env node
// Exact contact-address extraction from a public page, via the real DOM.
//
// WHY THIS EXISTS: the quarantine-reader returns a MODEL-RECONSTRUCTED summary
// (WEBFETCHFAB819), so "there is no email address on this page" cannot rest on
// it -- a structural claim needs the actual DOM. Measured 2026-10-14: the
// playwright MCP server is pinned to the uninstalled 'chrome' channel, but the
// bundled chromium-1228 and the node library both work.
//
// AND WHY IT GATES ITSELF: a `node script.mjs` call triggers neither
// BASH_EGRESS_DENY nor the egress-gate hook (measured: classify('node ...')
// -> deny=false), so this path would otherwise reach hosts the allowlist
// refuses. A new capability must not open a way around the gate, so this
// script enforces store/egress-allowlist.json itself, over the union of
// `domains` and `quarantine_domains`. Approving a host stays a one-line
// operator config change; it is never an argument to this script.
//
// Usage:  node scripts/lap-email-kinyeres.mjs <url> [url ...]
// Output: one JSON object per line. Exit 0 = every URL resolved to a verdict
//         (an empty hit list IS a verdict). Exit 2 = at least one URL could not
//         be measured -- the THIRD STATE, never report it as "no address".
//
// MUST be run from the repo (the `playwright` import resolves against the
// project's node_modules; from a scratchpad it fails with ERR_MODULE_NOT_FOUND).
import { chromium } from 'playwright'
import { engedett } from './lib/egress-allowlist.mjs'

const CIM_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g

// A szabaly 2026-10-22 ota a KOZOS modulban all (scripts/lib/egress-allowlist.mjs), hogy
// a tobbi playwright-szkript ugyanazt a dontest hasznalja, ne egy-egy sajat masolatot.
// Ennek a szkriptnek a kimeneti szerzodese valtozatlan: a tiltott hostbol itt VERDIKT lesz
// (egy JSON-sor), nem kivetel -- ezert az `engedett`-et hasznalja, nem az `ellenorizUrl`-t.

const urlek = process.argv.slice(2)
if (urlek.length === 0) {
  console.error('Hasznalat: node scripts/lap-email-kinyeres.mjs <url> [url ...]')
  process.exit(2)
}

let bukott = false
const bongeszo = await chromium.launch({ headless: true })
try {
  for (const u of urlek) {
    let hostnev
    try {
      hostnev = new URL(u).hostname
    } catch {
      console.log(JSON.stringify({ url: u, allapot: 'ertelmezhetetlen-url' }))
      bukott = true
      continue
    }
    if (!engedett(hostnev)) {
      console.log(JSON.stringify({
        url: u, allapot: 'nincs-az-allowlisten', host: hostnev,
        teendo: 'A gazda vegye fel a store/egress-allowlist.json-ba. Ez a script nem kerulheto meg parameterrel.',
      }))
      bukott = true
      continue
    }
    const lap = await bongeszo.newPage()
    try {
      const v = await lap.goto(u, { waitUntil: 'domcontentloaded', timeout: 30000 })
      const mailtok = await lap.evaluate(() =>
        Array.from(document.querySelectorAll('a[href^="mailto:"]'))
          .map((a) => a.getAttribute('href').replace(/^mailto:/i, '').split('?')[0].trim())
          .filter(Boolean))
      const szovegbol = await lap.evaluate((re) =>
        Array.from(new Set(document.body.innerText.match(new RegExp(re, 'g')) || [])),
        CIM_RE.source)
      console.log(JSON.stringify({
        url: u,
        allapot: 'mert',
        http: v ? v.status() : null,
        mailto_linkek: Array.from(new Set(mailtok)),
        szovegbeli_cimek: szovegbol,
        // An empty pair of lists is a MEASURED negative on this page, and only
        // on this page -- never a statement about the whole site.
        osszegzes: (mailtok.length + szovegbol.length) === 0
          ? 'EZEN A LAPON nincs email cim (mert negativum, DOM-olvasasbol)'
          : 'talalat',
      }))
    } catch (e) {
      console.log(JSON.stringify({ url: u, allapot: 'nem-mertheto', hiba: String(e.message || e).slice(0, 200) }))
      bukott = true
    } finally {
      await lap.close()
    }
  }
} finally {
  await bongeszo.close()
}
process.exit(bukott ? 2 : 0)
