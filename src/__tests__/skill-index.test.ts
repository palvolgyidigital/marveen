import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { execSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, writeFileSync, existsSync, readFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const SCRIPT = join(REPO_ROOT, 'scripts', 'skill-index.sh')

function makeSkillMd(name: string, description: string): string {
  return `---\nname: ${name}\ndescription: ${description}\n---\n\n# ${name}\n`
}

function runScript(args: string[], env: Record<string, string>): { stdout: string; exitCode: number } {
  try {
    const stdout = execSync(`bash "${SCRIPT}" ${args.map(a => `"${a}"`).join(' ')}`, {
      encoding: 'utf-8',
      env: { ...process.env, ...env },
    })
    return { stdout, exitCode: 0 }
  } catch (err: unknown) {
    const e = err as { stdout?: string; status?: number }
    return { stdout: e.stdout ?? '', exitCode: e.status ?? 1 }
  }
}

describe('skill-index.sh -- no-arg mode (backward compat)', () => {
  let tmpHome: string

  beforeEach(() => {
    tmpHome = mkdtempSync(join(tmpdir(), 'skill-index-test-'))
    mkdirSync(join(tmpHome, '.claude', 'skills', 'skill-alpha'), { recursive: true })
    writeFileSync(
      join(tmpHome, '.claude', 'skills', 'skill-alpha', 'SKILL.md'),
      makeSkillMd('skill-alpha', 'Global skill alpha description'),
    )
  })

  afterEach(() => {
    rmSync(tmpHome, { recursive: true, force: true })
  })

  it('writes the index to ~/.claude/skills/.skill-index.md', () => {
    runScript([], { HOME: tmpHome })
    const indexPath = join(tmpHome, '.claude', 'skills', '.skill-index.md')
    expect(existsSync(indexPath)).toBe(true)
  })

  it('includes global skill in the index', () => {
    runScript([], { HOME: tmpHome })
    const content = readFileSync(join(tmpHome, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    expect(content).toContain('skill-alpha')
    expect(content).toContain('Global skill alpha description')
  })

  it('uses the two-column table format (no Scope column)', () => {
    runScript([], { HOME: tmpHome })
    const content = readFileSync(join(tmpHome, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    expect(content).toContain('| Skill | Leírás |')
    expect(content).not.toContain('| Scope |')
  })

  it('does NOT create an index in any other directory', () => {
    const agentDir = join(tmpHome, 'agents', 'agent-a')
    mkdirSync(join(agentDir, '.claude', 'skills', 'skill-beta'), { recursive: true })
    writeFileSync(
      join(agentDir, '.claude', 'skills', 'skill-beta', 'SKILL.md'),
      makeSkillMd('skill-beta', 'Agent-specific skill beta'),
    )
    runScript([], { HOME: tmpHome })
    const agentIndex = join(agentDir, '.claude', 'skills', '.skill-index.md')
    expect(existsSync(agentIndex)).toBe(false)
  })
})

describe('skill-index.sh -- AGENT_DIR mode (merged index)', () => {
  let tmpHome: string
  let agentDir: string

  beforeEach(() => {
    tmpHome = mkdtempSync(join(tmpdir(), 'skill-index-test-'))
    // Global skill
    mkdirSync(join(tmpHome, '.claude', 'skills', 'skill-global'), { recursive: true })
    writeFileSync(
      join(tmpHome, '.claude', 'skills', 'skill-global', 'SKILL.md'),
      makeSkillMd('skill-global', 'A global skill visible to all agents'),
    )
    // Agent-specific skill
    agentDir = join(tmpHome, 'agents', 'agent-a')
    mkdirSync(join(agentDir, '.claude', 'skills', 'skill-local'), { recursive: true })
    writeFileSync(
      join(agentDir, '.claude', 'skills', 'skill-local', 'SKILL.md'),
      makeSkillMd('skill-local', 'An agent-local skill for agent-a only'),
    )
  })

  afterEach(() => {
    rmSync(tmpHome, { recursive: true, force: true })
  })

  it('writes the merged index to <AGENT_DIR>/.claude/skills/.skill-index.md', () => {
    runScript([agentDir], { HOME: tmpHome })
    const indexPath = join(agentDir, '.claude', 'skills', '.skill-index.md')
    expect(existsSync(indexPath)).toBe(true)
  })

  it('includes global skill in the merged index', () => {
    runScript([agentDir], { HOME: tmpHome })
    const content = readFileSync(join(agentDir, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    expect(content).toContain('skill-global')
    expect(content).toContain('A global skill visible to all agents')
  })

  it('includes agent-specific skill in the merged index', () => {
    // This is the core regression test: fails when AGENT_DIR handling is removed
    runScript([agentDir], { HOME: tmpHome })
    const content = readFileSync(join(agentDir, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    expect(content).toContain('skill-local')
    expect(content).toContain('An agent-local skill for agent-a only')
  })

  it('labels global and agent-specific skills with scope', () => {
    runScript([agentDir], { HOME: tmpHome })
    const content = readFileSync(join(agentDir, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    expect(content).toContain('| global |')
    expect(content).toContain('| agent |')
  })

  it('does NOT modify the global index when running in agent mode', () => {
    const globalIndexPath = join(tmpHome, '.claude', 'skills', '.skill-index.md')
    // Ensure there is no stale global index before the run
    expect(existsSync(globalIndexPath)).toBe(false)
    runScript([agentDir], { HOME: tmpHome })
    expect(existsSync(globalIndexPath)).toBe(false)
  })

  it('creates agent .claude/skills/ directory if it does not exist yet', () => {
    const freshAgentDir = join(tmpHome, 'agents', 'agent-b')
    // Only the agent dir exists, no .claude/skills/ inside
    mkdirSync(freshAgentDir, { recursive: true })
    runScript([freshAgentDir], { HOME: tmpHome })
    expect(existsSync(join(freshAgentDir, '.claude', 'skills', '.skill-index.md'))).toBe(true)
  })

  it('two different agents get independent indexes with their own agent-local skills', () => {
    // agent-b has a different local skill
    const agentBDir = join(tmpHome, 'agents', 'agent-b')
    mkdirSync(join(agentBDir, '.claude', 'skills', 'skill-b-only'), { recursive: true })
    writeFileSync(
      join(agentBDir, '.claude', 'skills', 'skill-b-only', 'SKILL.md'),
      makeSkillMd('skill-b-only', 'Only for agent-b'),
    )

    runScript([agentDir], { HOME: tmpHome })
    runScript([agentBDir], { HOME: tmpHome })

    const indexA = readFileSync(join(agentDir, '.claude', 'skills', '.skill-index.md'), 'utf-8')
    const indexB = readFileSync(join(agentBDir, '.claude', 'skills', '.skill-index.md'), 'utf-8')

    // agent-a sees skill-local but not skill-b-only
    expect(indexA).toContain('skill-local')
    expect(indexA).not.toContain('skill-b-only')

    // agent-b sees skill-b-only but not skill-local
    expect(indexB).toContain('skill-b-only')
    expect(indexB).not.toContain('skill-local')

    // both see the global skill
    expect(indexA).toContain('skill-global')
    expect(indexB).toContain('skill-global')
  })
})

describe('skill-index.sh -- graceful handling of missing global dir', () => {
  it('exits cleanly when ~/.claude/skills does not exist', () => {
    const emptyHome = mkdtempSync(join(tmpdir(), 'skill-index-test-'))
    try {
      const { exitCode } = runScript([], { HOME: emptyHome })
      expect(exitCode).toBe(0)
    } finally {
      rmSync(emptyHome, { recursive: true, force: true })
    }
  })
})

describe('skill-index.sh -- UTF-8-safe truncation (180d2ce0, 2026-08-28)', () => {
  // Root cause (found by Pedro, 2026-08-28): the description column is
  // truncated with `cut -c1-120`. In this environment cut -c does NOT
  // reliably respect multi-byte character boundaries -- a description whose
  // 120th character position falls mid-way through a multi-byte UTF-8
  // sequence gets an orphaned lead byte with no continuation byte, leaving
  // the WHOLE INDEX FILE invalid UTF-8.
  //
  // Confirmed mechanism for why that then makes skills unfindable (Pedro,
  // measured directly, corrected an earlier locale-based guess): it is NOT
  // about locale -- plain `/bin/grep` (GNU grep) reads the corrupted file
  // fine either way. The actual failure is that an agent's interactive Bash
  // tool runs `grep` through a Claude Code shell function that execs the
  // `claude` binary as `ugrep` with `-I` (skip binary files). ugrep
  // classifies the file as binary the moment it hits the orphaned byte and
  // -I then skips the WHOLE file silently -- including lines BEFORE the
  // corruption, not just after. A plain, non-interactive grep call (a hook,
  // a script, this test's subprocess) never goes through that wrapper and
  // is not affected. This is the exact live incident: szallitoi-arlista-
  // atvezetes's accented description corrupted the index and Pedro's own
  // newly-added skill became unfindable, from HIS interactive session.
  let tmpHome: string

  beforeEach(() => {
    tmpHome = mkdtempSync(join(tmpdir(), 'skill-index-utf8-test-'))
  })

  afterEach(() => {
    rmSync(tmpHome, { recursive: true, force: true })
  })

  // A description whose accented character sits exactly where a byte-based
  // (not character-based) cut at position 120 would split it: 119 plain
  // ASCII chars, then a 2-byte UTF-8 character (á), then more text. This is
  // the same shape as the real szallitoi-arlista-atvezetes description that
  // triggered the live incident.
  function boundaryStraddlingDescription(): string {
    return 'a'.repeat(119) + 'á' + 'bcdefgh, tovabbi ekezetes szoveg: arviztűrő tükörfúrógép'
  }

  it('produces a valid UTF-8 index file even when a description straddles the truncation boundary', () => {
    mkdirSync(join(tmpHome, '.claude', 'skills', 'skill-boundary'), { recursive: true })
    writeFileSync(
      join(tmpHome, '.claude', 'skills', 'skill-boundary', 'SKILL.md'),
      makeSkillMd('skill-boundary', boundaryStraddlingDescription()),
    )
    runScript([], { HOME: tmpHome })
    const indexPath = join(tmpHome, '.claude', 'skills', '.skill-index.md')
    const raw = readFileSync(indexPath)
    // The regression check: decoding as strict UTF-8 must not throw and
    // must not produce the U+FFFD replacement character an orphaned byte
    // would decode to.
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(raw)
    expect(decoded).not.toContain('�')
  })

  it('a skill listed AFTER a boundary-straddling description remains findable by grep (baseline sanity, not the ugrep incident itself)', () => {
    // Alphabetically/creation-order first, so its corrupted line lands
    // earlier in the file than skill-zzz-findable below, closest to how the
    // live incident actually laid out (the corrupted line was not the last
    // one in the index).
    mkdirSync(join(tmpHome, '.claude', 'skills', 'skill-aaa-boundary'), { recursive: true })
    writeFileSync(
      join(tmpHome, '.claude', 'skills', 'skill-aaa-boundary', 'SKILL.md'),
      makeSkillMd('skill-aaa-boundary', boundaryStraddlingDescription()),
    )
    mkdirSync(join(tmpHome, '.claude', 'skills', 'skill-zzz-findable'), { recursive: true })
    writeFileSync(
      join(tmpHome, '.claude', 'skills', 'skill-zzz-findable', 'SKILL.md'),
      makeSkillMd('skill-zzz-findable', 'A completely unrelated, later skill that must stay greppable'),
    )
    runScript([], { HOME: tmpHome })
    const indexPath = join(tmpHome, '.claude', 'skills', '.skill-index.md')
    // This runs plain GNU grep as a subprocess (a Node execSync child, not
    // an interactive bash session), which per the mechanism above is NOT
    // the path that ever went blind -- the ugrep -I wrapper only exists
    // inside an agent's own interactive Bash-tool shell function, which a
    // subprocess test harness does not go through and should not try to
    // fake (that would mean depending on the `claude` binary being present
    // and behaving identically in CI, which is out of scope for a unit
    // test). So this assertion does not reproduce the incident itself --
    // it pins a baseline contract ("plain grep must still find a valid,
    // later line"), backed by the unconditional guarantee in the test
    // above that no invalid UTF-8 can reach the file at all, which is what
    // actually prevents the ugrep -I incident from recurring.
    const found = (() => {
      try {
        execSync(`grep -c "skill-zzz-findable" "${indexPath}"`, { encoding: 'utf-8' })
        return true
      } catch {
        return false
      }
    })()
    expect(found).toBe(true)
  })
})
