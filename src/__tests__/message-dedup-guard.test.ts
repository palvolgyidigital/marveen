// Message-dedup guard: the mechanical backstop half of the ea2eb050 fix
// (2026-08-26). The sender-side confirmation check (confirmsDeliveryDespite
// PriorBusy, pane-state.ts) closes most of the silent-loss risk; this hook
// closes the other side -- if a message is ever resent after it had, in
// fact, already landed, the receiving agent must not act on it twice.
//
// Behavioural tests run the python hook as a subprocess against an isolated
// DB (LEDGER_DB_PATH), deterministic, no LLM. Static tests lock the wiring
// (template + scaffold migration + startup call), mirroring staleness-guard's
// own test shape exactly.
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import Database from 'better-sqlite3'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..', '..')
const HOOK = join(ROOT, 'scripts', 'hooks', 'message-dedup-guard.py')

let DB_DIR = ''
let DB_PATH = ''

// Real, in-tree cwd paths (under THIS checkout's own agents/ dir), not
// invented ones: ledger_lib.agent_id_from_cwd() no longer falls back to a
// bare directory-name guess for an out-of-tree cwd (ee2889c, 2026-08-26) --
// a fake path like '/install/agents/sam' now resolves to the main agent
// instead of 'sam', which would make every fixture agent collapse onto the
// same identity. Using real agents/<name> paths exercises the intended
// sub-agent resolution branch regardless of that fallback's behaviour.
const agentCwd = (name: string) => join(ROOT, 'agents', name)

function runHook(prompt: string, cwd = agentCwd('sam')): string {
  return execFileSync('python3', [HOOK], {
    input: JSON.stringify({ prompt, cwd }),
    encoding: 'utf-8',
    env: { ...process.env, LEDGER_DB_PATH: DB_PATH },
  })
}

function wrapped(msgId: number, body = 'valami tartalom'): string {
  return `[Uzenet @pedro-tol -- trusted team member, msg_id:${msgId}]: ${body}`
}

describe('message-dedup-guard hook (behavioural)', () => {
  beforeEach(() => {
    DB_DIR = mkdtempSync(join(tmpdir(), 'dedup-guard-'))
    DB_PATH = join(DB_DIR, 'test.db')
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
      env: { ...process.env, LEDGER_DB_PATH: DB_PATH },
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
