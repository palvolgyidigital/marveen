// Feladat-csatolmanyok kozos resze: a tarolo gyokere, a biztonsagos nev, az
// utvonal-ellenorzes es a kartyahoz tartozo fajlok takaritasa.
//
// MIERT KULON MODUL: a csatolmanyokat a kanban-route kezeli, de egy kartyat KET
// helyrol lehet torolni (a kanban-rol es a partner-laprol). Ha a fajl-takaritas
// csak az egyikben allna, a masik uton minden torles egy arva fajlt hagyna a
// lemezen -- nema szivargas, amit semmi nem jelez.
import { existsSync, readdirSync, rmdirSync, unlinkSync } from 'node:fs'
import { relative, resolve, sep } from 'node:path'
import { PROJECT_ROOT } from '../config.js'
import { listKanbanAttachments } from '../db.js'
import { logger } from '../logger.js'

export const CSATOLMANY_GYOKER = resolve(PROJECT_ROOT, 'store', 'kanban-csatolmanyok')
export const CSATOLMANY_MAX_BYTE = 20 * 1024 * 1024

export function biztonsagosFajlnev(nev: string): string {
  const level = nev.replace(/^.*[\\/]/, '')
  return (level.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/_+/g, '_').replace(/^\.+/, '').slice(0, 100) || 'csatolmany')
}

/** A tarolt utvonal CSAK a csatolmany-gyokeren belul mutathat. Ez nem formaseg: a
 *  letoltes es a torles is ezt az utvonalat koveti, es egy kiszokott ertek barmelyik
 *  fajlt elerhetove vagy torolhetove tenne. */
export function csatolmanyAbszolut(taroltUtvonal: string): string | null {
  const teljes = resolve(PROJECT_ROOT, taroltUtvonal)
  const rel = relative(CSATOLMANY_GYOKER, teljes)
  return rel && !rel.startsWith(`..${sep}`) && rel !== '..' ? teljes : null
}

/** Egy kartya osszes csatolmany-FAJLJA a lemezrol. A SOROKAT a deleteKanbanCard
 *  tranzakcioja torli; ez a fuggveny azelott fusson, amig a sorok meg megvannak. */
export function torolKartyaCsatolmanyFajljait(cardId: string): number {
  let db = 0
  for (const sor of listKanbanAttachments(cardId)) {
    const fajl = csatolmanyAbszolut(sor.stored_path)
    if (!fajl) {
      logger.warn({ cardId, attachmentId: sor.id, storedPath: sor.stored_path },
        'csatolmany a tarolo gyokeren kivul, fajl nem torolve')
      continue
    }
    try { unlinkSync(fajl); db++ } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== 'ENOENT') {
        logger.warn({ err, cardId, attachmentId: sor.id }, 'csatolmany fajl torlese nem sikerult')
      }
    }
  }
  const konyvtar = resolve(CSATOLMANY_GYOKER, biztonsagosFajlnev(cardId))
  // Csak URES konyvtarat takaritunk, es csak a gyokeren belul: ha maradt benne
  // valami, az inkabb maradjon meg, mint hogy vakon toroljunk.
  if (csatolmanyAbszolut(relative(PROJECT_ROOT, konyvtar)) && existsSync(konyvtar)) {
    try { if (readdirSync(konyvtar).length === 0) rmdirSync(konyvtar) } catch { /* legjobb szandek */ }
  }
  return db
}
