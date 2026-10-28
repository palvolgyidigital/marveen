// A kimeno allowlist KOZOS olvasoja a `node script.mjs` utra (playwright es tarsai).
//
// MIERT LETEZIK: egy `node script.mjs` hivas sem a BASH_EGRESS_DENY parancsnev-listat,
// sem az egress-gate WebFetch-horgot nem valtja ki -- merve 2026-10-22: a fo ugynok
// jogosultsagi deny-listaja NULLA elemu, a bash-egress-parser.mjs pedig a kodban
// kifejezetten a sub-agensekre van kotve, nem a fo ugynokre (src/web/agent-scaffold.ts
// 1162. sor). Tehat ez az ut alapbol ORIZETLEN.
//
// A mintat a scripts/lap-email-kinyeres.mjs hozta, ami maganak irta meg ugyanezt. Itt
// azert all kozos modulkent, hogy a TOBBI playwright-szkript is ugyanazt a szabalyt
// hasznalja, ne egy-egy sajat masolatot, ami kulon-kulon elavul.
//
// AMI EZ NEM: ez nem kapu, hanem egy KONYVTAR. Csak azokat a szkripteket vedi, amelyek
// meghivjak. Egy UJ szkript, ami nem hivja meg, ugyanugy orizetlen marad -- ezt a
// hibaosztalyt csak az oldja meg, ha a kapu a MUVELETHEZ kotodik, nem az eszkoz nevehez
// (kartya 3bda4752, Marci dontese alatt).
//
// Marci dontese, 2026-10-22 15:07 (Telegram 10583), a "2. Igen" valasza arra a kerdesre,
// hogy a playwright-ut bekotheto-e a kimeno listahoz.
import fs from 'node:fs'
import path from 'node:path'

const GYOKER = path.resolve(import.meta.dirname, '..', '..')
const LISTA = path.join(GYOKER, 'store/egress-allowlist.json')

/** A lista UNIOJA: `domains` + `quarantine_domains`.
 *
 *  MINDEN HIVASKOR UJRAOLVAS, szandekosan: egy jovahagyas igy egy sornyi config-valtoztatas
 *  marad, ujraindítas nelkul. A fajl hianya vagy hibas JSON-ja NEM fail-open: kivetelt dob,
 *  mert egy ures lista azt jelentene, hogy semmi nem engedett -- de a nema ures lista
 *  ugy nezne ki, mint egy szandekos tiltas, es elfedne a config-hibat.
 */
export function engedettHosztok() {
  const nyers = JSON.parse(fs.readFileSync(LISTA, 'utf8'))
  return [...(nyers.domains ?? []), ...(nyers.quarantine_domains ?? [])]
}

/** Pontos hosztnev VAGY valodi aldomain.
 *
 *  A vezeto pont az, ami megallitja a 'frameo.com.evil.com' alaku becsapast: a puszta
 *  endsWith('frameo.com') ratt illeszkedne.
 */
export function engedett(hostnev, lista = engedettHosztok()) {
  return lista.some((d) => hostnev === d || hostnev.endsWith('.' + d))
}

/** Localhost es a privat halozat ATENGEDVE, a bash-egress-parser sajat szabalyaval egyezoen.
 *  A dashboard sajat hivasai (http://localhost:3420) kulonben elakadnanak.
 *  A dontes a LITERALIS hosztnevbol jon, soha nem DNS-bol. */
export function helyi(hostnev) {
  if (hostnev === 'localhost' || hostnev === '127.0.0.1' || hostnev === '::1' || hostnev === '[::1]') return true
  if (/^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostnev)) return true
  if (/^192\.168\.\d{1,3}\.\d{1,3}$/.test(hostnev)) return true
  if (/^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$/.test(hostnev)) return true
  if (/^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(hostnev)) return true
  return hostnev.endsWith('.local')
}

/** Egy URL ellenorzese hasznalat ELOTT. Dob, ha a hoszt nincs a listan.
 *
 *  A DOBAS A LENYEG: egy `false` visszateresi erteket a hivo elfelejtheti megnezni, es a
 *  szkript attol meg betoltene a lapot. A kivetel megallitja.
 */
export function ellenorizUrl(u) {
  let hostnev
  try {
    hostnev = new URL(u).hostname
  } catch {
    throw new Error(`ertelmezhetetlen URL: ${u}`)
  }
  if (helyi(hostnev)) return hostnev
  if (!engedett(hostnev)) {
    throw new Error(
      `a kimeno lista nem engedi: ${hostnev}. A jovahagyas egy sor a store/egress-allowlist.json `
      + `fajlban (domains vagy quarantine_domains), nem egy kapcsolo ebben a szkriptben.`,
    )
  }
  return hostnev
}

/** Playwright-hoz: ellenorzott navigacio. Ugyanaz, mint page.goto, csak elotte merd le a hosztot. */
export async function biztonsagosGoto(page, u, opciok) {
  ellenorizUrl(u)
  return page.goto(u, opciok)
}
