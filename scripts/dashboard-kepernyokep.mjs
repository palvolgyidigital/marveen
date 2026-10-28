// Kepernyokep a dashboard kanban-tablajarol, opcionalis projekt-szuressel.
//
// Hasznalat:
//   node scripts/dashboard-kepernyokep.mjs <kimeneti.png> ["<projekt neve>"]
//
// MIERT A KONYVTAR ES NEM AZ MCP SZERVER: a Playwright MCP szerver ezen a
// telepitesen nem mukodik (chrome-csatorna), a konyvtar viszont igen. Ezert a
// kepernyokep mindig node-szkriptbol megy.
//
// MIERT A PROJEKT GYOKEREBEN ELJEN: a `playwright` import csak a projekt
// node_modules-abol oldodik fel. Egy /tmp alatti szkript ERR_MODULE_NOT_FOUND-dal
// hasal el (merve 2026-10-20).
import { chromium } from 'playwright'
// A kozos kimeno-ellenorzes. Itt a cel a SAJAT dashboardunk (localhost), amit a modul
// mindig atenged -- a bekotes azert all itt, hogy ha valaha mas cimre allitjak at, az
// ne csendben menjen ki.
import { ellenorizUrl } from './lib/egress-allowlist.mjs'
import { readFileSync } from 'node:fs'

const out = process.argv[2]
const projekt = process.argv[3] || ''
if (!out) { console.error('hasznalat: node scripts/dashboard-kepernyokep.mjs <kimenet.png> ["<projekt>"]'); process.exit(2) }

// A dashboard elott egy felhasznalonev-jelszo overlay all (#mv-login-overlay), ami
// elfogja a kattintasokat. NEM a gazda jelszavat hasznaljuk: a lap a `marveen-dashboard-token`
// localStorage-kulcsot is elfogadja (app.js 133. sor), es az a SAJAT API-tokenunk, ami mar
// a store/.dashboard-token fajlban all. Ezert a tokent a betoltes ELOTT tesszuk be.
const token = readFileSync(new URL('../store/.dashboard-token', import.meta.url), 'utf8').trim()
const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 1600, height: 1100 } })
await ctx.addInitScript((t) => {
  try { localStorage.setItem('marveen-dashboard-token', t) } catch { /* privat mod */ }
}, token)
const p = await ctx.newPage()
ellenorizUrl('http://localhost:3420/')
await p.goto('http://localhost:3420/', { waitUntil: 'networkidle' })
await p.waitForTimeout(800)

// A bal oldali sav linkjei `.sb-link` osztalyuak, es a Kanban is egy ilyen <a>.
// Egy sima `a,button` + hasText szuro a FEJLEC fuleit is megfogja, es azokra
// kattintva a Kanban-lap rejtve marad: a #kanbanProjectFilter letezik, de
// `hidden`, es a waitFor timeouttal hasal el (merve 2026-10-20).
const kanban = p.locator('.sb-link', { hasText: 'Kanban' }).first()
await kanban.click()
await p.waitForTimeout(1500)

if (projekt) {
  const sel = p.locator('#kanbanProjectFilter')
  await sel.waitFor({ timeout: 15000 })
  const opts = await sel.locator('option').allTextContents()
  console.log('projekt-opciok:', JSON.stringify(opts))
  await sel.selectOption({ label: projekt })
  await p.waitForTimeout(1500)
}

await p.screenshot({ path: out, fullPage: false })
console.log('mentve:', out)
await b.close()
