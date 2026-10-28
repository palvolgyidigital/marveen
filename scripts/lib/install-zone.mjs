// The install's time zone for plain-Node (.mjs) helpers (ISSUE1895, #1895).
//
// src/config.ts resolves ONE zone for the whole install (APP_TZ): SCHEDULER_TZ
// from store/config-overrides.json over .env, and the host zone when it is
// unset or not a real zone. `scripts/lib/install-tz.sh` is the shell side and
// `scripts/lib/install_zone.py` the Python side; this is the same rule for a
// script that runs under node and therefore cannot import the TypeScript
// config. A hardcoded Europe/Budapest is right for exactly one install and
// silently an hour or more off on every other.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// scripts/lib/install-zone.mjs -> the repo root is two levels up.
const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

function valodiZona(nev) {
  if (!nev) return false
  try {
    new Intl.DateTimeFormat('en-CA', { timeZone: nev })
    return true
  } catch {
    // A rosszul irt zona rosszabb, mint a semmi: az Intl ilyenkor dob, es
    // config.ts is eldobja az erteket ahelyett, hogy csendben UTC-t hasznalna.
    return false
  }
}

/** The zone the operator pinned, or '' when none is readable. */
export function pinnedZone(repoRoot = REPO_ROOT) {
  const explicit = (process.env.MARVEEN_TZ || '').trim()
  if (explicit) return explicit
  try {
    const ov = JSON.parse(fs.readFileSync(path.join(repoRoot, 'store', 'config-overrides.json'), 'utf-8'))
    if (ov && typeof ov === 'object' && ov.SCHEDULER_TZ) return String(ov.SCHEDULER_TZ).trim()
  } catch { /* no overrides file, or not JSON: the .env is next */ }
  try {
    // Parity with src/env-parse.ts: the LAST occurrence wins, and one pair of
    // surrounding quotes is removed.
    let value = ''
    for (const raw of fs.readFileSync(path.join(repoRoot, '.env'), 'utf-8').split('\n')) {
      const line = raw.trim()
      if (!line.startsWith('SCHEDULER_TZ=')) continue
      value = line.slice('SCHEDULER_TZ='.length).trim()
      if (value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === '"' || value[0] === "'")) {
        value = value.slice(1, -1)
      }
    }
    return value
  } catch {
    return ''
  }
}

/** The install's zone name: the pinned one, else the host's, else 'UTC'. */
export function installZone(repoRoot = REPO_ROOT) {
  const pinned = pinnedZone(repoRoot)
  if (valodiZona(pinned)) return pinned
  const host = Intl.DateTimeFormat().resolvedOptions().timeZone
  return valodiZona(host) ? host : 'UTC'
}
