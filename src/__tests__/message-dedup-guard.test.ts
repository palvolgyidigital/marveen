// Message-dedup guard: the mechanical backstop half of the ea2eb050 fix
// (2026-08-26). The sender-side confirmation check (confirmsDeliveryDespite
// PriorBusy, pane-state.ts) closes most of the silent-loss risk; this hook
// closes the other side -- if a message is ever resent after it had, in
// fact, already landed, the receiving agent must not act on it twice.
//
// Behavioural tests run the python hook as a subprocess from a tmp install
// (<tmp>/scripts linked to the repo's, mirroring ledger-turn-failure.test.py
// and friends), so its ledger DB is <tmp>/store/claudeclaw.db. Since
// ENVRELAXGATE1104 no environment variable picks the ledger DB -- an isolated
// LEDGER_DB_PATH override is silently ignored by ledger_lib.db_path(), which
// used to make this suite write its test rows into the real install's
// store/claudeclaw.db instead of the tmp DB it thought it was using. Static
// tests lock the wiring (template + scaffold migration + startup call),
// mirroring staleness-guard's own test shape exactly.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync, mkdtempSync, mkdirSync, rmSync, existsSync, symlinkSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import Database from 'better-sqlite3'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..', '..')

let DB_DIR = ''
let DB_PATH = ''
let HOOK = ''

// <tmp>/scripts symlinked to the repo's scripts/, so ledger_lib.db_path()
// (dirname(dirname(abspath(__file__)))) resolves to <tmp>/store/claudeclaw.db
// -- the symlink keeps the hook's __file__ rooted under DB_DIR, not ROOT.
function installHooksDir(tmp: string): string {
  const link = join(tmp, 'scripts')
  if (!existsSync(link)) symlinkSync(join(ROOT, 'scripts'), link)
  return join(link, 'hooks')
}

// agent_id_from_cwd() derives the "install" the SAME way (from ledger_lib's
// own __file__: dirname(dirname(abspath(__file__))), unresolved), so a cwd
// must be in-tree under THAT tmp install, not under ROOT, or it falls
// outside every installs entry and collapses to the main agent for every
// name (ee2889c's safeguard against inventing an id from an out-of-tree
// path -- firing here for the wrong reason). agent_id_from_cwd does pure
// string-prefix matching, no filesystem access, so this path never needs to
// exist on disk -- it only needs to read as <tmp install>/agents/<name>.
const agentCwd = (name: string) => join(DB_DIR, 'agents', name)

function runHook(prompt: string, cwd = agentCwd('sam')): string {
  return execFileSync('python3', [HOOK], {
    input: JSON.stringify({ prompt, cwd }),
    encoding: 'utf-8',
  })
}

function wrapped(msgId: number, body = 'valami tartalom'): string {
  return `[Uzenet @pedro-tol -- trusted team member, msg_id:${msgId}]: ${body}`
}

describe('message-dedup-guard hook (behavioural)', () => {
  beforeEach(() => {
    DB_DIR = mkdtempSync(join(tmpdir(), 'dedup-guard-'))
    mkdirSync(join(DB_DIR, 'store'), { recursive: true })
    HOOK = join(installHooksDir(DB_DIR), 'message-dedup-guard.py')
    DB_PATH = join(DB_DIR, 'store', 'claudeclaw.db')
  })
  afterEach(() => {
    rmSync(DB_DIR, { recursive: true, force: true })
  })

  it('stays silent on the first sighting of a msg_id', () => {
    expect(runHook(wrapped(1622)).trim()).toBe('')
  })

  it('injects a stand-down instruction on a REPEAT sighting of the same msg_id', () => {
    runHook(wrapped(1622)) // first sighting, records it
    const out = runHook(wrapped(1622)) // same id again
    expect(out).toContain('MEGISMETLODOTT KEZBESITES')
    expect(out).toContain('msg_id:1622')
    expect(out.toUpperCase()).toContain('NE DOLGOZD FEL UJRA')
  })

  it('a DIFFERENT msg_id from the same agent is treated as new, not a duplicate', () => {
    runHook(wrapped(1622))
    expect(runHook(wrapped(1623)).trim()).toBe('')
  })

  it('the SAME msg_id delivered to a DIFFERENT agent is independent (no cross-agent bleed)', () => {
    runHook(wrapped(1622), agentCwd('sam'))
    // A fresh agent (max) seeing the same numeric id for the first time must
    // not be told it is a duplicate -- the dedup key is (agent, msg_id).
    expect(runHook(wrapped(1622), agentCwd('max')).trim()).toBe('')
  })

  it('stays silent when the prompt carries no msg_id at all (most turns)', () => {
    expect(runHook('sima belso heartbeat szoveg, semmi kezbesitett uzenet').trim()).toBe('')
  })

  it('never throws on unparseable stdin (fail-open)', () => {
    const out = execFileSync('python3', [HOOK], {
      input: 'not json at all {{{',
      encoding: 'utf-8',
    })
    expect(out.trim()).toBe('')
  })

  it('handles multiple msg_ids in one prompt independently', () => {
    runHook(wrapped(10) + '\n' + wrapped(11))
    const out = runHook(wrapped(10) + '\n' + wrapped(12)) // 10 repeats, 12 is new
    expect(out).toContain('msg_id:10')
    expect(out).not.toContain('msg_id:11')
    expect(out).not.toContain('msg_id:12')
  })

  it('persists across separate hook invocations (durable, not per-process)', () => {
    // Two fully separate subprocess runs, simulating two different turns --
    // proves this is NOT in-memory session state, since a real restart
    // between deliveries is exactly the scenario this backstop must survive.
    runHook(wrapped(500))
    const out = runHook(wrapped(500))
    expect(out).toContain('msg_id:500')
  })

  it('the durable record actually lands in the DB (not just hook-observable)', () => {
    runHook(wrapped(777))
    const db = new Database(DB_PATH, { readonly: true })
    try {
      const row = db.prepare(
        "SELECT agent_id, msg_id FROM seen_delivery_ids WHERE agent_id = 'sam' AND msg_id = 777",
      ).get()
      expect(row).toBeTruthy()
    } finally {
      db.close()
    }
  })
})

describe('message-dedup-guard wiring (static)', () => {
  it('is registered as a UserPromptSubmit hook in the settings template', () => {
    const tpl = readFileSync(join(ROOT, 'templates', 'settings.json.template'), 'utf-8')
    const parsed = JSON.parse(tpl.replace(/\{\{PROJECT_ROOT\}\}/g, '/ROOT'))
    const ups = parsed.hooks?.UserPromptSubmit
    expect(Array.isArray(ups)).toBe(true)
    expect(JSON.stringify(ups)).toContain('message-dedup-guard.py')
  })

  it('ensureMessageDedupGuardHook merges idempotently (keyed on the script path)', () => {
    const src = readFileSync(join(ROOT, 'src', 'web', 'agent-scaffold.ts'), 'utf-8')
    expect(src).toContain('export function ensureMessageDedupGuardHook')
    expect(src).toContain("includes('message-dedup-guard.py')")
  })

  it('is backfilled into existing agents on startup', () => {
    const web = readFileSync(join(ROOT, 'src', 'web.ts'), 'utf-8')
    expect(web).toContain('ensureMessageDedupGuardHook')
  })
})
