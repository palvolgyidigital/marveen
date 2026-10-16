#!/usr/bin/env node
/*
 * K&F Concept + Ulanzi heti konkurencia-ar-osszehasonlitas.
 *
 * Heti visszaterő feladat (Marci kerese, 2026-10-16). Referencia:
 * agents/salesagens/.claude/skills/kf-ulanzi-heti-konkurencia-arfigyeles/SKILL.md
 * -- ott van leirva oldalankent, melyik modszer miert ez, es mik a buktatok.
 *
 * Futtatas: cd /home/pdb/marveen/scripts && NODE_PATH=/home/pdb/marveen/node_modules node kf-ulanzi-heti-konkurencia-scraper.mjs
 *
 * A script a sajat (pdb.hu) es 6 konkurens host (fotoplus.hu, kamerapro.hu,
 * studioeszkozok.hu, syntexshop.hu, unidomestore.hu, film-technika.com) MARKA-/
 * KATEGORIA-listazo lapjait jarja be lapozva -- SOHA nem SKU-nkenti termeklap-
 * latogatassal --, es a gyartoi cikkszam alapjan parositja a sajat aktiv K&F+Ulanzi
 * katalogust (Rendelesi javaslat export, Kifuto szurve) a konkurens arakkal.
 *
 * Pedro johagyasa (2026-10-16, msg 6523, memoria #2047): KIZAROLAG ezekre a hostokra
 * szabad navigalni -- pdb.hu, fotoplus.hu, kamerapro.hu, studioeszkozok.hu,
 * syntexshop.hu, unidomestore.hu, film-technika.com. Off-site linket SOHA ne kovess.
 */

import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const ORDER_DIR = '/home/pdb/marveen/store/david-order-agent/output';
const OUT_BASE = '/home/pdb/marveen/agents/salesagens/store/kf-ulanzi-heti-konkurencia-arfigyeles';

const ALLOWED_HOSTS = new Set([
  'www.pdb.hu', 'pdb.hu',
  'www.fotoplus.hu', 'fotoplus.hu',
  'www.kamerapro.hu', 'kamerapro.hu',
  'studioeszkozok.hu', 'www.studioeszkozok.hu',
  'www.syntexshop.hu', 'syntexshop.hu',
  'www.unidomestore.hu', 'unidomestore.hu',
  'www.film-technika.com', 'film-technika.com',
]);

const NEM_TALALTAM = 'NEM TALÁLTAM';
const NOT_ATTEMPTED = 'NEM MEGKÍSÉRELT (nincs modellkód ezen a kategórián, kódmentes/alacsony-átfedésű oldal)';
const AMBIGUOUS = 'BIZONYTALAN (nem egyértelmű egyezés, kihagyva)';

const STAND_CATEGORIES = new Set([
  'Tripod', 'Mini állvány', 'Lámpaállvány',
  'Telefonos Asztali-, Miniállvány', 'Asztali állvány', 'Állvány Tartozék',
]);

function todayBudapest() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Budapest', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')}`;
}

function nowLabelBudapest() {
  const now = new Date();
  const d = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Budapest', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(now);
  const get = (t) => d.find((p) => p.type === t).value;
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}`;
}

function assertHost(url, label) {
  const host = new URL(url).hostname;
  if (!ALLOWED_HOSTS.has(host)) {
    throw new Error(`EGRESS-TILALOM: ${label} nem engedelyezett host-ra navigalt (${host}). Megallok.`);
  }
}

function runPython(code, args = []) {
  const tmp = path.join(os.tmpdir(), `kfulanzi_py_${Date.now()}_${Math.random().toString(36).slice(2)}.py`);
  fs.writeFileSync(tmp, code, 'utf-8');
  try {
    return execFileSync('python3', [tmp, ...args], { maxBuffer: 1024 * 1024 * 100 }).toString('utf-8');
  } finally {
    fs.unlinkSync(tmp);
  }
}

// ---------------------------------------------------------------------------
// 1. Sajat aktiv katalogus beolvasasa (legfrissebb Rendelesi javaslat export)
// ---------------------------------------------------------------------------

function loadOwnCatalog() {
  const files = fs.readdirSync(ORDER_DIR).filter((f) => /^Rendelesi_javaslat_\d{4}-\d{2}-\d{2}\.xlsx$/.test(f));
  if (files.length === 0) {
    throw new Error(`Nem talalhato Rendelesi_javaslat_*.xlsx a ${ORDER_DIR} mappaban.`);
  }
  files.sort(); // ISO-datum a nevben, lexikografikus rendezes = datum szerinti
  const latest = files[files.length - 1];
  const latestPath = path.join(ORDER_DIR, latest);

  const pyCode = `
import json, sys, openpyxl
wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
ws = wb.active
rows = list(ws.iter_rows(min_row=2, values_only=True))
out = []
for r in rows:
    gy = r[6]
    kifuto = r[7]
    if gy and ('K&F' in str(gy).upper() or 'ULANZI' in str(gy).upper()) and not kifuto:
        out.append({
            'cikkszam': r[0], 'nev': r[1], 'gyartoi_cikkszam': r[2],
            'gyarto': gy, 'cikkcsoport': r[5],
        })
print(json.dumps(out, ensure_ascii=False))
`;
  const jsonOut = runPython(pyCode, [latestPath]);
  return { file: latest, catalog: JSON.parse(jsonOut) };
}

// ---------------------------------------------------------------------------
// Parositasi segedfuggvenyek (2026-10-16-i felderites, lasd SKILL.md)
// ---------------------------------------------------------------------------

function suffix(code) {
  if (!code) return '';
  let c = code.toUpperCase();
  c = c.replace(/^\d+-/, '');
  c = c.replace(/^(KF|UL)-?/, '');
  c = c.replace(/[^A-Z0-9]/g, '');
  return c;
}

function normTokBase(name) {
  if (!name) return null;
  let s = name.trim().replace(/^(K&F Concept|KF Concept|K&F|Ulanzi)\s+/i, '');
  s = s.split('+')[0].trim();
  const words = s.split(/[\s,]+/).filter(Boolean);
  if (words.length === 0) return null;
  const keep = [words[0]];
  if (!/\d/.test(words[0])) {
    for (let i = 1; i < words.length; i++) {
      const w = words[i].replace(/^[().,]+|[().,]+$/g, '');
      if (!w) continue;
      if (/^[A-Z0-9]/.test(w)) keep.push(w);
      else break;
    }
  }
  return keep.join(' ').replace(/[\s\-._]/g, '').toUpperCase();
}

const MODEL_RE = /\b([A-Z]{1,2}\d{3}[A-Z]\d)\b/;
function nameAnomaly(ownName, compName) {
  const a = new Set((ownName.toUpperCase().match(new RegExp(MODEL_RE, 'g')) || []));
  const b = new Set(((compName || '').toUpperCase().match(new RegExp(MODEL_RE, 'g')) || []));
  if (a.size === 0 || b.size === 0) return false;
  for (const x of a) if (b.has(x)) return false;
  return true;
}

function priceOfText(s) {
  if (s == null) return null;
  const digits = String(s).replace(/[^\d]/g, '');
  return digits ? parseInt(digits, 10) : null;
}

function pick(cands) {
  if (cands.length === 1) return [cands[0], 'OK'];
  if (cands.length > 1) {
    const prices = new Set(cands.map((c) => c.price));
    if (prices.size === 1) return [cands[0], 'OK'];
    return [null, 'AMBIGUOUS'];
  }
  return [null, 'MISSING'];
}

async function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// "Load more" gombos infinite-scroll oldalakhoz (syntexshop.hu, film-technika.com):
// DETERMINISZTIKUS leallasi feltetel, NEM idozites-fuggo. Minden kattintas UTAN
// a tenyleges DOM-elemszamot nezzuk (nem fix sleep-et) -- a megallas kizarolag
// azon alapul, hogy a darabszam NOTT-E, nem azon, hany masodpercet vartunk.
// Ha KET EGYMAS UTANI kattintas sem novel a darabszamot, az a valodi "nincs tobb".
// Felso korlat (maxClicks) a vegtelen ciklus ellen -- ha eleri, hitCap=true, es ez
// a hivo fuggvenyben KIMONDVA jelenik meg (konzol + coverage-log), nem elhallgatva.
async function clickLoadMoreUntilStable(page, { buttonSelector, itemSelector, maxClicks = 50, pollTimeoutMs = 6000, pollIntervalMs = 300 }) {
  let count = await page.evaluate((sel) => document.querySelectorAll(sel).length, itemSelector);
  let clicks = 0;
  let noGrowthRounds = 0;
  let hitCap = false;

  while (clicks < maxClicks) {
    const btn = await page.$(buttonSelector);
    if (!btn) break;
    const visible = await btn.isVisible().catch(() => false);
    if (!visible) break;
    try {
      await btn.click({ timeout: 3000 });
    } catch (e) {
      break; // gomb nem kattinthato -> nincs tobb
    }
    clicks += 1;

    // Tartalom-alapu varakozas: addig pollozunk, amig a darabszam NO, vagy
    // lejar a pollTimeoutMs -- ez helyettesiti a fix sleep-et, hogy lassu
    // halozat eseten se alljunk meg korai, hamis "stabil" allapotnal.
    const deadline = Date.now() + pollTimeoutMs;
    let newCount = count;
    while (Date.now() < deadline) {
      await sleep(pollIntervalMs);
      newCount = await page.evaluate((sel) => document.querySelectorAll(sel).length, itemSelector);
      if (newCount > count) break;
    }

    if (newCount > count) {
      count = newCount;
      noGrowthRounds = 0;
    } else {
      noGrowthRounds += 1;
      count = newCount;
      if (noGrowthRounds >= 2) break; // ket egymas utani kattintas sem novelt -> valodi veg
    }
  }

  if (clicks >= maxClicks) hitCap = true;
  return { finalCount: count, clicks, hitCap };
}

// ---------------------------------------------------------------------------
// Oldalankenti lekerok. Mindegyik MARKA-/KATEGORIA-listazo lapot jar be
// lapozva -- SOHA nem SKU-nkenti termeklap-latogatassal.
// ---------------------------------------------------------------------------

// pdb.hu (sajat) es fotoplus.hu: ugyanaz a UNAS motor, de MASHOGY jelenik meg
// a gyartoi kod -- pdb.hu-n a .product[data-sku] attributumban, fotoploson csak
// a lathato "Cikkszam:" szovegsorban (ezert ket kulon parser kell).

async function fetchUnasDataSku(page, host, query, label) {
  const all = [];
  let pageNum = 1;
  let totalLabel = null;
  for (;;) {
    const url = pageNum === 1
      ? `https://${host}/shop_search.php?search=${encodeURIComponent(query)}`
      : `https://${host}/shop_search.php?search=${encodeURIComponent(query)},${pageNum}&infinite_scroll=1&ajax_nodesign=1`;
    assertHost(url, label);
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(500);
    if (pageNum === 1) {
      const text = await page.evaluate(() => document.body.innerText);
      const m = text.match(/(\d+)\s*termék/);
      totalLabel = m ? parseInt(m[1], 10) : null;
    }
    const items = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('.product[data-sku]'));
      return cards.map((c) => {
        const priceEl = c.querySelector('[class*=price]');
        const a = c.querySelector('a[href]');
        const img = c.querySelector('img[alt]');
        return {
          code: c.dataset.sku,
          href: a ? a.href : null,
          priceText: priceEl ? priceEl.textContent.trim() : null,
          name: img ? img.alt.trim() : null,
        };
      });
    });
    if (items.length === 0) break;
    all.push(...items.map((it) => ({ ...it, price: priceOfText(it.priceText) })));
    pageNum += 1;
    if (pageNum > 60) break;
    await sleep(250);
  }
  const seen = new Set();
  const dedup = [];
  for (const it of all) {
    if (it.code && !seen.has(it.code)) { seen.add(it.code); dedup.push(it); }
  }
  return { totalLabel, collected: dedup.length, items: dedup };
}

const STOCK_WORDS = [/nap$/, /elérhető$/, /^Rendelhető$/, /^Előrendelhető$/];
function isStockLine(l) { return STOCK_WORDS.some((re) => re.test(l)); }

function parseFotoplusBlock(text) {
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
  const items = [];
  for (let i = 0; i < lines.length; i++) {
    if (lines[i] === 'Cikkszám:') {
      const name = lines[i - 1] || null;
      const code = lines[i + 1] || null;
      let price = null;
      for (let j = i + 2; j < Math.min(i + 10, lines.length); j++) {
        const m = lines[j].match(/^([\d\s]+)\s*Ft$/);
        if (m) { price = parseInt(m[1].replace(/\s/g, ''), 10); break; }
        if (lines[j] === 'Cikkszám:') break;
      }
      items.push({ name, code, price });
    }
  }
  return items;
}

async function fetchFotoplus(page, query) {
  const host = 'www.fotoplus.hu';
  const all = [];
  let pageNum = 1;
  let totalLabel = null;
  for (;;) {
    const url = pageNum === 1
      ? `https://${host}/shop_search.php?search=${encodeURIComponent(query)}`
      : `https://${host}/shop_search.php?search=${encodeURIComponent(query)},${pageNum}&infinite_scroll=1&ajax_nodesign=1`;
    assertHost(url, 'fotoplus.hu');
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(500);
    const text = await page.evaluate(() => document.body.innerText);
    if (pageNum === 1) {
      const m = text.match(/(\d+)\s*termék/);
      totalLabel = m ? parseInt(m[1], 10) : null;
    }
    const items = parseFotoplusBlock(text);
    if (items.length === 0) break;
    all.push(...items);
    pageNum += 1;
    if (pageNum > 40) break;
    await sleep(300);
  }
  const seen = new Set();
  const dedup = [];
  for (const it of all) {
    if (it.code && !seen.has(it.code)) { seen.add(it.code); dedup.push(it); }
  }
  return { totalLabel, collected: dedup.length, items: dedup };
}

// kamerapro.hu: UGYANAZ a UNAS motor, de a gyartoi kod sem data-sku attributumban,
// sem lathato szovegben nincs -- a .product CSS classname-ben van elrejtve,
// "page_artlist_sku_KF06__unas__113" alakban ("__unas__" = kotojel helyere).

async function fetchKamerapro(page, query) {
  const host = 'www.kamerapro.hu';
  const all = [];
  let pageNum = 1;
  let totalLabel = null;
  for (;;) {
    const url = pageNum === 1
      ? `https://${host}/shop_search.php?search=${encodeURIComponent(query)}`
      : `https://${host}/shop_search.php?search=${encodeURIComponent(query)},${pageNum}&infinite_scroll=1&ajax_nodesign=1`;
    assertHost(url, 'kamerapro.hu');
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(600);
    if (pageNum === 1) {
      const text = await page.evaluate(() => document.body.innerText);
      const m = text.match(/(\d+)\s*termék/);
      totalLabel = m ? parseInt(m[1], 10) : null;
    }
    const items = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('.product'));
      return cards.map((c) => {
        const cls = c.className || '';
        const m = cls.match(/page_artlist_sku_([A-Za-z0-9_]+)/);
        if (!m) return null;
        const code = m[1].replace(/__unas__/g, '-');
        const priceEl = c.querySelector('[class*=price]');
        const a = c.querySelector('a[href]');
        const img = c.querySelector('img[alt]');
        let price = null;
        if (priceEl) {
          const nums = Array.from(priceEl.textContent.matchAll(/([\d\s]{3,})\s*Ft/g))
            .map((mm) => parseInt(mm[1].replace(/\s/g, ''), 10));
          if (nums.length) price = nums[nums.length - 1]; // utolso = akcios/vegleges ar
        }
        return { code, price, href: a ? a.href : null, name: img ? img.alt : null };
      }).filter(Boolean);
    });
    if (items.length === 0) break;
    all.push(...items);
    pageNum += 1;
    if (pageNum > 70) break;
    await sleep(300);
  }
  const seen = new Set();
  const dedup = [];
  for (const it of all) { if (!seen.has(it.code)) { seen.add(it.code); dedup.push(it); } }
  return { totalLabel, collected: dedup.length, items: dedup };
}

// studioeszkozok.hu: WooCommerce-szeru, NINCS gyartoi kod sehol (DOM-ban sem).
// Csak nev-alapu parositas lehetseges -- ezert csak az allvany-csaladra hasznald.

function parseStudioBlock(text) {
  const lines = text.split('\n').map((l) => l.trim()).filter((l) => l.length > 0);
  const items = [];
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^([\d\s]+)\s*Ft$/);
    if (m) {
      const price = parseInt(m[1].replace(/\s/g, ''), 10);
      let j = i - 1;
      while (j >= 0 && isStockLine(lines[j])) j -= 1;
      const name = j >= 0 ? lines[j] : null;
      if (name) items.push({ name, price });
    }
  }
  return items;
}

async function fetchStudioeszkozok(page, query) {
  const all = [];
  let pageNum = 1;
  let totalLabel = null;
  for (;;) {
    const url = pageNum === 1
      ? `https://studioeszkozok.hu/kereses?s=${encodeURIComponent(query)}`
      : `https://studioeszkozok.hu/kereses/oldal/${pageNum}?s=${encodeURIComponent(query)}`;
    assertHost(url, 'studioeszkozok.hu');
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(500);
    const text = await page.evaluate(() => document.body.innerText);
    if (pageNum === 1) {
      const m = text.match(/(\d+)\s*db-ból/);
      totalLabel = m ? parseInt(m[1], 10) : null;
    }
    const items = parseStudioBlock(text);
    if (items.length === 0) break;
    all.push(...items);
    pageNum += 1;
    if (pageNum > 60) break;
    await sleep(300);
  }
  return { totalLabel, collected: all.length, items: all };
}

// syntexshop.hu: pan-europai teljes katalogus, "load more" gombos infinite-scroll.
// Gyartoi kod a termek-URL SLUG VEGEN van (pl. "...kf01-2357"), nem DOM-attributumban.

function extractSyntexCode(url) {
  if (!url) return null;
  const m = url.match(/-([a-z]{2}\d{2}[-.]?\d{3,5}[a-z0-9]*)$/i);
  return m ? m[1].toUpperCase() : null;
}

async function fetchSyntexshop(page, query) {
  const url = `https://www.syntexshop.hu/search?q=${encodeURIComponent(query)}`;
  assertHost(url, 'syntexshop.hu');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(800);
  const text0 = await page.evaluate(() => document.body.innerText);
  const m0 = text0.match(/(\d+)\s*term[ée]k/i);
  const totalLabel = m0 ? parseInt(m0[1], 10) : null;

  // syntexshop.hu a sajat PAN-EUROPAI teljes katalogusat listazza (K&F onmagaban
  // 2439 tetel, ~30/kattintas -> ~82 kattintas kell a teljes listahoz) -- ezert
  // itt MAGASABB felso korlat kell, mint a tobbi (kisebb katalogusu) oldalon.
  // Mert 2026-10-16-i tesztfutaskor 50-es korlattal csonkolt (1530/2439) volt az eredmeny.
  const SYNTEX_MAX_CLICKS = 120;
  const { finalCount, clicks, hitCap } = await clickLoadMoreUntilStable(page, {
    buttonSelector: '.load-more-products',
    itemSelector: '.product-thumb',
    maxClicks: SYNTEX_MAX_CLICKS,
  });
  if (hitCap) {
    console.warn(`  FIGYELEM syntexshop.hu "${query}": a ${SYNTEX_MAX_CLICKS} kattintasos felso korlatot elertem (${finalCount} elem), LEHET hogy nem a teljes lista -- nincs tovabbi automatikus lapozas.`);
  }

  const items = await page.evaluate(() => {
    const thumbs = Array.from(document.querySelectorAll('.product-thumb'));
    return thumbs.map((t) => {
      const a = t.querySelector('h2 a');
      const priceEl = t.querySelector('.price-main strong');
      let price = null;
      if (priceEl) {
        const digits = priceEl.textContent.replace(/[^\d]/g, '');
        price = digits ? parseInt(digits, 10) : null;
      }
      return { name: a ? a.textContent.trim() : null, href: a ? a.href : null, price };
    });
  });
  for (const it of items) it.code = extractSyntexCode(it.href);
  return { totalLabel, collected: items.length, items, clicks, hitCap, domCountAtStop: finalCount };
}

// unidomestore.hu: ShopRenter, a kereso "#filter_keyword" mezon megy, de a mukodo
// URL kozvetlenul is hivhato: index.php?route=product/list&keyword=...&page=N.
// Kicsi, specializalt katalogus -- NINCS lathato gyartoi kod.

async function fetchUnidomestore(page, query) {
  const all = [];
  let pageNum = 1;
  for (;;) {
    const url = `https://www.unidomestore.hu/index.php?route=product/list&keyword=${encodeURIComponent(query)}&description=1&page=${pageNum}`;
    assertHost(url, 'unidomestore.hu');
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(600);
    const items = await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('.product-card'));
      return cards.map((c) => {
        const a = c.querySelector('.product-card-title a, h2 a');
        const name = a ? a.textContent.trim() : null;
        const href = a ? a.href : null;
        const m = c.textContent.match(/([\d.]{3,})\s*Ft/);
        const price = m ? parseInt(m[1].replace(/\./g, ''), 10) : null;
        return { name, href, price };
      }).filter((x) => x.name);
    });
    if (items.length === 0) break;
    all.push(...items);
    pageNum += 1;
    if (pageNum > 20) break;
    await sleep(400);
  }
  const seen = new Set();
  const dedup = [];
  for (const it of all) { if (!seen.has(it.href)) { seen.add(it.href); dedup.push(it); } }
  return { totalLabel: null, collected: dedup.length, items: dedup };
}

// film-technika.com/hu/: Shoptet (cseh platform), Enter a kereso mezoben GET-re
// valt ("/hu/kereses/?string=..."), "load more" gombos infinite-scroll.
// NINCS kiirt osszesen-darabszam -> a (a) lefedettsegi fogas itt NEM alkalmazhato.
// Gyartoi kod a termek NEVEBEN van (pl. "... KF13.087"), kulon "Kod:" mezo a
// SAJAT (nem gyartoi) belso kodjuk, azt NE hasznald.

function extractFilmtechnikaCode(name) {
  if (!name) return null;
  const m = name.match(/\bKF\d{2}\.\d{3,5}[A-Z0-9]*\b/i) || name.match(/\bUL[A-Z0-9.]{3,10}\b/i);
  return m ? m[0].toUpperCase() : null;
}

async function fetchFilmtechnika(page, query) {
  const url = `https://www.film-technika.com/hu/kereses/?string=${encodeURIComponent(query)}`;
  assertHost(url, 'film-technika.com');
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(800);

  const { finalCount, clicks, hitCap } = await clickLoadMoreUntilStable(page, {
    buttonSelector: '.js-loadMore__button--productsSearch',
    itemSelector: '.product',
    maxClicks: 50,
  });
  if (hitCap) {
    console.warn(`  FIGYELEM film-technika.com "${query}": a 50 kattintasos felso korlatot elertem (${finalCount} elem), LEHET hogy nem a teljes lista -- nincs tovabbi automatikus lapozas.`);
  }

  const items = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('.product'));
    return cards.map((c) => {
      const nameEl = c.querySelector('.name');
      const name = nameEl ? nameEl.textContent.trim() : null;
      const href = nameEl ? nameEl.href : null;
      const matches = Array.from(c.textContent.matchAll(/([\d\s]{3,})\s*Ft/g))
        .map((m) => parseInt(m[1].replace(/\s/g, ''), 10));
      const price = matches.length ? matches[matches.length - 1] : null; // brutto/akcios ar
      return { name, href, price };
    }).filter((x) => x.name);
  });
  for (const it of items) it.code = extractFilmtechnikaCode(it.name);

  const seen = new Set();
  const dedup = [];
  for (const it of items) { if (!seen.has(it.href)) { seen.add(it.href); dedup.push(it); } }
  // NINCS osszesen-szamlalo ezen az oldalon -- totalLabel szandekosan null,
  // a riportban ezt NEM TELJESKENT kell feltuntetni.
  return { totalLabel: null, collected: dedup.length, items: dedup, clicks, hitCap, domCountAtStop: finalCount };
}

// ---------------------------------------------------------------------------
// Parositas: sajat katalogus -> oldal eredmenyek
// ---------------------------------------------------------------------------

function matchByCodeSuffix(ownCode, siteItemsByCodeSuffix) {
  const cands = siteItemsByCodeSuffix.get(suffix(ownCode)) || [];
  return pick(cands);
}

function matchByNameToken(ownName, siteItemsByNameTok) {
  const tok = normTokBase(ownName);
  if (!tok) return [null, 'MISSING'];
  const cands = siteItemsByNameTok.get(tok) || [];
  return pick(cands);
}

function buildCodeIndex(items, codeField = 'code') {
  const idx = new Map();
  for (const it of items) {
    if (!it[codeField]) continue;
    const key = suffix(it[codeField]);
    if (!idx.has(key)) idx.set(key, []);
    idx.get(key).push(it);
  }
  return idx;
}

function buildNameTokIndex(items) {
  const idx = new Map();
  for (const it of items) {
    const tok = normTokBase(it.name);
    if (!tok) continue;
    if (!idx.has(tok)) idx.set(tok, []);
    idx.get(tok).push(it);
  }
  return idx;
}

// Kod-elsobbsegu parositas, allvany-csalad eseten nev-alapu fallback-kel.
// Visszaad: {item, status: OK|AMBIGUOUS|MISSING|NOT_ATTEMPTED, method: CODE|NAME|NONE}
function matchRow(ownRow, codeIndex, nameTokIndex, { allowNameFallback }) {
  let [item, status] = matchByCodeSuffix(ownRow.gyartoi_cikkszam, codeIndex);
  let method = 'CODE';
  if (status === 'MISSING') {
    if (allowNameFallback && STAND_CATEGORIES.has(ownRow.cikkcsoport)) {
      [item, status] = matchByNameToken(ownRow.nev, nameTokIndex);
      method = status === 'OK' ? 'NAME' : 'NAME_ATTEMPT';
    } else if (allowNameFallback) {
      status = 'NOT_ATTEMPTED';
      method = 'NONE';
    }
    // allowNameFallback=false (pl. fotoplus/kamerapro/pdb, ahol van kod): sima MISSING marad
  }
  return { item, status, method };
}

// studioeszkozok-specifikus: SOHA nincs kod, csak nev-alapu, csak allvany-csaladra
function matchRowNameOnly(ownRow, nameTokIndex) {
  if (!STAND_CATEGORIES.has(ownRow.cikkcsoport)) {
    return { item: null, status: 'NOT_ATTEMPTED', method: 'NONE' };
  }
  const [item, status] = matchByNameToken(ownRow.nev, nameTokIndex);
  return { item, status, method: status === 'OK' ? 'NAME' : 'NAME_ATTEMPT' };
}

// ---------------------------------------------------------------------------
// Excel-iras (openpyxl-en keresztul, mert nincs telepitett Node xlsx-iro)
// ---------------------------------------------------------------------------

function writeFinalExcel(finalRows, outPath, timestampLabel) {
  const payload = { rows: finalRows, out_path: outPath, timestamp: timestampLabel,
    labels: { NEM_TALALTAM, NOT_ATTEMPTED, AMBIGUOUS } };
  const payloadFile = path.join(os.tmpdir(), `kfulanzi_rows_${Date.now()}.json`);
  fs.writeFileSync(payloadFile, JSON.stringify(payload), 'utf-8');

  const pyCode = `
import json, sys, os, openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)

rows = data['rows']
out_path = data['out_path']
now = data['timestamp']
NEM_TALALTAM = data['labels']['NEM_TALALTAM']
NOT_ATTEMPTED = data['labels']['NOT_ATTEMPTED']
AMBIGUOUS = data['labels']['AMBIGUOUS']

os.makedirs(os.path.dirname(out_path), exist_ok=True)

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "KF-Ulanzi heti arfigyeles"

headers = [
    "Cikkszám", "Megnevezés", "Gyártói cikkszám", "Gyártó", "Cikkcsoport",
    "Saját ár (Ft)", "Saját termék-URL",
    "Fotoplus ár (Ft)", "Fotoplus megnevezés/Forrás",
    "Kamerapro ár (Ft)", "Kamerapro megnevezés/Forrás",
    "Stúdióeszközök ár (Ft)", "Stúdióeszközök megnevezés/Forrás",
    "Syntexshop ár (Ft)", "Syntexshop megnevezés/Forrás",
    "Unidomestore ár (Ft)", "Unidomestore megnevezés/Forrás",
    "Film-technika ár (Ft)", "Film-technika megnevezés/Forrás",
    "Lekérdezés időpontja",
]
ws.append(headers)
header_font = Font(bold=True, color="FFFFFF")
header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
for c in range(1, len(headers) + 1):
    cell = ws.cell(row=1, column=c)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(wrap_text=True, vertical="center")

MISSING_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
NOTATT_FILL = PatternFill(start_color="EAD1DC", end_color="EAD1DC", fill_type="solid")
ANOM_FILL = PatternFill(start_color="F4CCCC", end_color="F4CCCC", fill_type="solid")

for r in rows:
    row_vals = [
        r['cikkszam'], r['nev'], r['gyartoi_cikkszam'], r['gyarto'], r['cikkcsoport'],
        r['own_price'], r['own_url'],
        r['foto_price'], r['foto_src'],
        r['kam_price'], r['kam_src'],
        r['studio_price'], r['studio_src'],
        r['syntex_price'], r['syntex_src'],
        r['unidome_price'], r['unidome_src'],
        r['filmtechnika_price'], r['filmtechnika_src'],
        now,
    ]
    ws.append(row_vals)

widths = [10, 45, 16, 12, 18, 12, 32, 12, 38, 12, 38, 12, 42, 12, 32, 12, 32, 12, 32, 16]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w

for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
    for cell in row:
        v = cell.value
        if v == NEM_TALALTAM:
            cell.fill = MISSING_FILL
        elif v == NOT_ATTEMPTED:
            cell.fill = NOTATT_FILL
        elif v == AMBIGUOUS:
            cell.fill = ANOM_FILL
        elif isinstance(v, str) and 'ANOMÁLIA' in v:
            cell.fill = ANOM_FILL

ws.freeze_panes = "A2"
wb.save(out_path)
print(json.dumps({'rows': ws.max_row - 1, 'cols': ws.max_column, 'path': out_path}))
`;
  const result = runPython(pyCode, [payloadFile]);
  fs.unlinkSync(payloadFile);
  return JSON.parse(result);
}

// ---------------------------------------------------------------------------
// Fo folyamat
// ---------------------------------------------------------------------------

async function main() {
  console.log('=== K&F + Ulanzi heti konkurencia-ar-osszehasonlitas ===');

  const { file: ownCatalogFile, catalog: ownCatalog } = loadOwnCatalog();
  console.log(`Sajat katalogus forras: ${ownCatalogFile}, aktiv K&F+Ulanzi cikk: ${ownCatalog.length}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const coverage = {};

  console.log('--- pdb.hu (sajat) ---');
  const pdbKf = await fetchUnasDataSku(page, 'www.pdb.hu', 'K&F Concept', 'pdb.hu');
  const pdbUl = await fetchUnasDataSku(page, 'www.pdb.hu', 'Ulanzi', 'pdb.hu');
  coverage.pdb = { kf: pdbKf, ul: pdbUl };
  console.log(`pdb.hu K&F: label=${pdbKf.totalLabel} collected=${pdbKf.collected} | Ulanzi: label=${pdbUl.totalLabel} collected=${pdbUl.collected}`);
  await sleep(1000);

  console.log('--- fotoplus.hu ---');
  const fotoKf = await fetchFotoplus(page, 'K&F Concept');
  const fotoUl = await fetchFotoplus(page, 'Ulanzi');
  coverage.fotoplus = { kf: fotoKf, ul: fotoUl };
  console.log(`fotoplus.hu K&F: label=${fotoKf.totalLabel} collected=${fotoKf.collected} | Ulanzi: label=${fotoUl.totalLabel} collected=${fotoUl.collected}`);
  await sleep(1500);

  console.log('--- kamerapro.hu ---');
  const kamKf = await fetchKamerapro(page, 'K&F Concept');
  const kamUl = await fetchKamerapro(page, 'Ulanzi');
  coverage.kamerapro = { kf: kamKf, ul: kamUl };
  console.log(`kamerapro.hu K&F: label=${kamKf.totalLabel} collected=${kamKf.collected} | Ulanzi: label=${kamUl.totalLabel} collected=${kamUl.collected}`);
  await sleep(1500);

  console.log('--- studioeszkozok.hu ---');
  const studioKf = await fetchStudioeszkozok(page, 'K&F Concept');
  const studioUl = await fetchStudioeszkozok(page, 'Ulanzi');
  coverage.studioeszkozok = { kf: studioKf, ul: studioUl };
  console.log(`studioeszkozok.hu K&F: label=${studioKf.totalLabel} collected=${studioKf.collected} | Ulanzi: label=${studioUl.totalLabel} collected=${studioUl.collected}`);
  await sleep(1500);

  console.log('--- syntexshop.hu (pan-europai teljes katalogus, ennek megfeleloen nagy) ---');
  const synKf = await fetchSyntexshop(page, 'K&F Concept');
  const synUl = await fetchSyntexshop(page, 'Ulanzi');
  coverage.syntexshop = { kf: synKf, ul: synUl };
  console.log(`syntexshop.hu K&F: label=${synKf.totalLabel} collected=${synKf.collected} (kattintas=${synKf.clicks}, felsokorlat-erintve=${synKf.hitCap}) | Ulanzi: label=${synUl.totalLabel} collected=${synUl.collected} (kattintas=${synUl.clicks}, felsokorlat-erintve=${synUl.hitCap})`);
  await sleep(1500);

  console.log('--- unidomestore.hu ---');
  const uniKf = await fetchUnidomestore(page, 'K&F Concept');
  const uniUl = await fetchUnidomestore(page, 'Ulanzi');
  coverage.unidomestore = { kf: uniKf, ul: uniUl };
  console.log(`unidomestore.hu K&F: collected=${uniKf.collected} | Ulanzi: collected=${uniUl.collected} (nincs oldal-szamlalo)`);
  await sleep(1500);

  console.log('--- film-technika.com/hu/ (NINCS osszesen-szamlalo az oldalon) ---');
  const ftKf = await fetchFilmtechnika(page, 'K&F Concept');
  const ftUl = await fetchFilmtechnika(page, 'Ulanzi');
  coverage.filmtechnika = { kf: ftKf, ul: ftUl };
  console.log(`film-technika.com K&F: collected=${ftKf.collected} (kattintas=${ftKf.clicks}, felsokorlat-erintve=${ftKf.hitCap}) | Ulanzi: collected=${ftUl.collected} (kattintas=${ftUl.clicks}, felsokorlat-erintve=${ftUl.hitCap})`);

  await browser.close();

  // --- Indexek felepitese ---
  const pdbIndex = buildCodeIndex([...pdbKf.items, ...pdbUl.items]);
  const fotoIndex = buildCodeIndex([...fotoKf.items, ...fotoUl.items]);
  const kamIndex = buildCodeIndex([...kamKf.items, ...kamUl.items]);
  const studioNameIndex = buildNameTokIndex([...studioKf.items, ...studioUl.items]);
  const synCodeIndex = buildCodeIndex([...synKf.items, ...synUl.items]);
  const synNameIndex = buildNameTokIndex([...synKf.items, ...synUl.items]);
  const uniCodeIndexFromName = (() => {
    // unidomestore: nincs kulon code mezo, de a nevben neha benne van (pl. "KF-V99") --
    // a 2026-10-16-i felderites szerint ez ritkan ad biztonsagos egyezest, ezert itt
    // csak a nev-alapu allvany-csalad fallback-ot hasznaljuk, kod-indexet nem epitunk.
    return new Map();
  })();
  const uniNameIndex = buildNameTokIndex([...uniKf.items, ...uniUl.items]);
  const ftCodeIndex = buildCodeIndex([...ftKf.items, ...ftUl.items]);
  const ftNameIndex = buildNameTokIndex([...ftKf.items, ...ftUl.items]);

  // --- Parositas minden sajat cikkre ---
  const finalRows = [];
  const stats = {
    own: 0, foto: 0, kam: 0, studio: 0, syntex: 0, unidome: 0, filmtechnika: 0,
    fotoAmbig: 0, kamAmbig: 0, studioAmbig: 0, synAmbig: 0, uniAmbig: 0, ftAmbig: 0,
    anomalies: 0,
  };

  const tsLabel = nowLabelBudapest();

  for (const row of ownCatalog) {
    const ownItem = (pdbIndex.get(suffix(row.gyartoi_cikkszam)) || [])[0];
    const ownPrice = ownItem ? ownItem.price : null;
    const ownUrl = ownItem ? ownItem.href : null;
    if (ownPrice != null) stats.own += 1;

    const fotoM = matchRow(row, fotoIndex, null, { allowNameFallback: false });
    let fotoPrice = NEM_TALALTAM;
    let fotoSrc = '';
    if (fotoM.status === 'OK') {
      fotoPrice = fotoM.item.price;
      fotoSrc = `${fotoM.item.name} | fotoplus.hu`;
      if (nameAnomaly(row.nev, fotoM.item.name)) {
        fotoSrc += ' -- ANOMÁLIA: a névben eltérő modellkód szerepel, de a gyártói cikkszám pontosan egyezik';
        stats.anomalies += 1;
      }
      stats.foto += 1;
    } else if (fotoM.status === 'AMBIGUOUS') {
      fotoPrice = AMBIGUOUS; fotoSrc = AMBIGUOUS; stats.fotoAmbig += 1;
    }

    const kamM = matchRow(row, kamIndex, null, { allowNameFallback: false });
    let kamPrice = NEM_TALALTAM;
    let kamSrc = '';
    if (kamM.status === 'OK') {
      kamPrice = kamM.item.price;
      kamSrc = `${kamM.item.name} | kamerapro.hu`;
      if (nameAnomaly(row.nev, kamM.item.name)) {
        kamSrc += ' -- ANOMÁLIA: a névben eltérő modellkód szerepel, de a gyártói cikkszám pontosan egyezik';
        stats.anomalies += 1;
      }
      stats.kam += 1;
    } else if (kamM.status === 'AMBIGUOUS') {
      kamPrice = AMBIGUOUS; kamSrc = AMBIGUOUS; stats.kamAmbig += 1;
    }

    const studioM = matchRowNameOnly(row, studioNameIndex);
    let studioPrice = NOT_ATTEMPTED;
    let studioSrc = NOT_ATTEMPTED;
    if (studioM.status === 'OK') {
      studioPrice = studioM.item.price;
      studioSrc = `${studioM.item.name} | studioeszkozok.hu (név-alapú párosítás, nincs gyártói kód az oldalon)`;
      stats.studio += 1;
    } else if (studioM.status === 'AMBIGUOUS') {
      studioPrice = AMBIGUOUS; studioSrc = AMBIGUOUS; stats.studioAmbig += 1;
    } else if (studioM.status === 'MISSING') {
      studioPrice = NEM_TALALTAM; studioSrc = '';
    }

    const synM = matchRow(row, synCodeIndex, synNameIndex, { allowNameFallback: true });
    let synPrice = NOT_ATTEMPTED;
    let synSrc = NOT_ATTEMPTED;
    if (synM.status === 'OK') {
      synPrice = synM.item.price;
      synSrc = `${synM.item.name} | syntexshop.hu`;
      if (synM.method === 'NAME') synSrc += ' (név-alapú, állvány-család)';
      if (nameAnomaly(row.nev, synM.item.name)) {
        synSrc += ' -- ANOMÁLIA: a névben eltérő modellkód szerepel';
        stats.anomalies += 1;
      }
      stats.syntex += 1;
    } else if (synM.status === 'AMBIGUOUS') {
      synPrice = AMBIGUOUS; synSrc = AMBIGUOUS; stats.synAmbig += 1;
    } else if (synM.status === 'MISSING') {
      synPrice = NEM_TALALTAM; synSrc = '';
    }

    const uniM = matchRow(row, uniCodeIndexFromName, uniNameIndex, { allowNameFallback: true });
    let uniPrice = NOT_ATTEMPTED;
    let uniSrc = NOT_ATTEMPTED;
    if (uniM.status === 'OK') {
      uniPrice = uniM.item.price;
      uniSrc = `${uniM.item.name} | unidomestore.hu`;
      if (uniM.method === 'NAME') uniSrc += ' (név-alapú, állvány-család)';
      stats.unidome += 1;
    } else if (uniM.status === 'AMBIGUOUS') {
      uniPrice = AMBIGUOUS; uniSrc = AMBIGUOUS; stats.uniAmbig += 1;
    } else if (uniM.status === 'MISSING') {
      uniPrice = NEM_TALALTAM; uniSrc = '';
    }

    const ftM = matchRow(row, ftCodeIndex, ftNameIndex, { allowNameFallback: true });
    let ftPrice = NOT_ATTEMPTED;
    let ftSrc = NOT_ATTEMPTED;
    if (ftM.status === 'OK') {
      ftPrice = ftM.item.price;
      ftSrc = `${ftM.item.name} | film-technika.com`;
      if (ftM.method === 'NAME') ftSrc += ' (név-alapú, állvány-család)';
      stats.filmtechnika += 1;
    } else if (ftM.status === 'AMBIGUOUS') {
      ftPrice = AMBIGUOUS; ftSrc = AMBIGUOUS; stats.ftAmbig += 1;
    } else if (ftM.status === 'MISSING') {
      ftPrice = NEM_TALALTAM; ftSrc = '';
    }

    finalRows.push({
      cikkszam: row.cikkszam, nev: row.nev, gyartoi_cikkszam: row.gyartoi_cikkszam,
      gyarto: row.gyarto, cikkcsoport: row.cikkcsoport,
      own_price: ownPrice != null ? ownPrice : NEM_TALALTAM,
      own_url: ownUrl || NEM_TALALTAM,
      foto_price: fotoPrice, foto_src: fotoSrc,
      kam_price: kamPrice, kam_src: kamSrc,
      studio_price: studioPrice, studio_src: studioSrc,
      syntex_price: synPrice, syntex_src: synSrc,
      unidome_price: uniPrice, unidome_src: uniSrc,
      filmtechnika_price: ftPrice, filmtechnika_src: ftSrc,
    });
  }

  // --- Excel iras ---
  const dateStr = todayBudapest();
  const outDir = path.join(OUT_BASE, dateStr);
  const outPath = path.join(outDir, `KF_Ulanzi_konkurencia_arosszehasonlitas_${dateStr}.xlsx`);
  const writeResult = writeFinalExcel(finalRows, outPath, tsLabel);

  console.log('\n=== OSSZEFOGLALO ===');
  console.log(`Sajat aktiv katalogus: ${ownCatalog.length} cikk (forras: ${ownCatalogFile})`);
  console.log(`Kimeneti fajl: ${writeResult.path} (${writeResult.rows} sor, ${writeResult.cols} oszlop)`);
  console.log(`Saját ár megtalálva: ${stats.own}/${ownCatalog.length}`);
  console.log(`Fotoplus: ${stats.foto} egyezés, ${stats.fotoAmbig} bizonytalan`);
  console.log(`Kamerapro: ${stats.kam} egyezés, ${stats.kamAmbig} bizonytalan`);
  console.log(`Stúdióeszközök: ${stats.studio} egyezés, ${stats.studioAmbig} bizonytalan (csak állvány-család)`);
  console.log(`Syntexshop: ${stats.syntex} egyezés, ${stats.synAmbig} bizonytalan`);
  console.log(`Unidomestore: ${stats.unidome} egyezés, ${stats.uniAmbig} bizonytalan`);
  console.log(`Film-technika: ${stats.filmtechnika} egyezés, ${stats.ftAmbig} bizonytalan (NINCS oldal-szintű összesen-számláló)`);
  console.log(`Anomáliák (kód egyezik, név eltérő modellkódot mutat): ${stats.anomalies}`);
  console.log('\nLefedettség-számlálók oldalanként (label = oldal saját "X termék" száma, collected = tényleg összegyűjtött):');
  for (const [site, d] of Object.entries(coverage)) {
    console.log(`  ${site}: K&F label=${d.kf.totalLabel} collected=${d.kf.collected} | Ulanzi label=${d.ul.totalLabel} collected=${d.ul.collected}`);
  }

  // Heti osszehasonlithato lefedettsegi naplo -- ez potolja azoknal az oldalaknal
  // (syntexshop "load more", unidomestore, film-technika), ahol nincs saját "X
  // termék" szamlalo, a 3-fogasos lefedettsegi igazolas (a) pontjat: ha egyik
  // heten nagyot ugrik a collected szam ugyanazon az oldalon, EZ a fajl mutatja meg.
  const historyPath = path.join(OUT_BASE, 'coverage-history.jsonl');
  const historyLine = {
    timestamp: tsLabel,
    date: dateStr,
    own_catalog_file: ownCatalogFile,
    own_catalog_size: ownCatalog.length,
    coverage: Object.fromEntries(Object.entries(coverage).map(([site, d]) => [site, {
      kf_label: d.kf.totalLabel, kf_collected: d.kf.collected,
      kf_clicks: d.kf.clicks ?? null, kf_hit_cap: d.kf.hitCap ?? null,
      ul_label: d.ul.totalLabel, ul_collected: d.ul.collected,
      ul_clicks: d.ul.clicks ?? null, ul_hit_cap: d.ul.hitCap ?? null,
    }])),
    stats,
  };
  fs.appendFileSync(historyPath, `${JSON.stringify(historyLine)}\n`, 'utf-8');
  console.log(`\nLefedettségi napló bővítve: ${historyPath}`);

  const anyCapHit = Object.values(coverage).some((d) => d.kf.hitCap || d.ul.hitCap);
  if (anyCapHit) {
    console.warn('\nFIGYELEM: legalább egy oldalon elértük a kattintás-felsőkorlátot -- a jelzett "collected" szám ott NEM garantáltan a teljes lista. Lásd a fenti FIGYELEM-sorokat.');
  }
}

main().catch((err) => {
  console.error('HIBA:', err.stack || err.message);
  process.exit(1);
});
