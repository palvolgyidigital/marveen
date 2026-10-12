// DAVIDGRANT1009: the rule that ships to every agent's CLAUDE.md after Marci's
// 2026-10-09 decision ("Engedd amit Dávid kér").
//
// David asked three times that every permission he had approved for one
// assistant apply to all of them. The measured failure that triggered it was a
// LOOKUP failure, not a missing permission: anna's own CLAUDE.md had carried
// David's DHL-stamp grant since 2026-10-02, the main agent said no anyway and
// escalated, and 16 minutes went on an approval that already existed.
//
// Functional part mirrors message-close-section.test.ts (temp root, mocked
// config). The wiring part reads the two call sites with comment lines removed,
// so a commented-out call does not pass for a live one.
import { describe, it, expect, vi } from 'vitest'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const tmpRoot = mkdtempSync(join(tmpdir(), 'marveen-davidgrant-test-'))

vi.mock('../config.js', () => ({
  STORE_DIR: '/nonexistent/claudeclaw-test-store',
  PROJECT_ROOT: tmpRoot,
  OWNER_NAME: 'TestOwner',
  MAIN_AGENT_ID: 'agent-a',
  BOT_NAME: 'agent-a',
  CHANNEL_PROVIDER: 'telegram',
  WEB_PORT: 3420,
  OWNER_DRIVE_FOLDER: '',
  DASHBOARD_PUBLIC_URL: '',
  AGENT_API_ORIGIN: '',
  APP_TZ: 'Europe/Budapest',
}))

vi.mock('../web/agent-config.js', () => ({
  agentDir: (name: string) => join(tmpRoot, 'agents', name),
  agentConfigRoot: () => join(tmpRoot, 'agents'),
  listAgentNames: () => ['agent-a', 'agent-b'],
  readAgentCapabilities: () => [],
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: (path: string, content: string) => writeFileSync(path, content, 'utf-8'),
}))

const { ensureDavidGrantsSection, buildDavidGrantsBody } = await import('../web/agent-scaffold.js')

const BEGIN = '<!-- BEGIN GENERATED: david-grants-fleetwide (auto-generated, do not edit by hand) -->'
const END = '<!-- END GENERATED: david-grants-fleetwide -->'

function setup(agent: string, content: string) {
  const dir = join(tmpRoot, 'agents', agent)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'CLAUDE.md'), content, 'utf-8')
}
const read = (agent: string) => readFileSync(join(tmpRoot, 'agents', agent, 'CLAUDE.md'), 'utf-8')

describe('david-grants section: what it says (DAVIDGRANT1009)', () => {
  const body = buildDavidGrantsBody()

  it('quotes the owner decision that authorised it', () => {
    expect(body).toContain('Engedd amit Dávid kér')
  })

  it('states the rule: a grant to any assistant applies to all of them', () => {
    expect(body).toMatch(/BÁRMELYIK asszisztensnek[\s\S]{0,120}MINDEN asszisztensre áll/)
  })

  it('names where to look up an existing grant, with the measured example', () => {
    expect(body).toContain('agents/anna/CLAUDE.md')
    expect(body).toContain('2026-10-02')
  })

  it('keeps the three exclusions, so the section cannot be read as a blanket grant', () => {
    expect(body).toMatch(/Marci és Zoli SAJÁT jogadásai/)
    expect(body).toMatch(/KIFELÉ küldés/)
    expect(body).toMatch(/SOHA nem adott meg/)
  })

  it('carries the lookup step, because the measured failure was the lookup', () => {
    expect(body).toMatch(/OLVASD EL az érintett ügynök CLAUDE\.md/)
    expect(body).toMatch(/Tizenhat\s*\n?perc ment el|Tizenhat/)
  })

  it('contains no em dash, per the house rule', () => {
    expect(body).not.toContain('—')
  })
})

describe('david-grants section: idempotent insert and update', () => {
  it('appends the block once, and a second run changes nothing', () => {
    setup('agent-b', '# Agent B\n\nexisting text\n')
    ensureDavidGrantsSection('agent-b')
    const once = read('agent-b')
    expect(once).toContain('existing text')
    expect(once.split(BEGIN).length - 1).toBe(1)
    expect(once).toContain(END)
    ensureDavidGrantsSection('agent-b')
    expect(read('agent-b')).toBe(once)
  })

  it('replaces a stale block in place instead of adding a second one', () => {
    setup('agent-c', `# C\n\n${BEGIN}\nold wording\n${END}\n\ntail\n`)
    ensureDavidGrantsSection('agent-c')
    const out = read('agent-c')
    expect(out).not.toContain('old wording')
    expect(out.split(BEGIN).length - 1).toBe(1)
    expect(out).toContain('tail')
  })

  it('the main agent is written at PROJECT_ROOT/CLAUDE.md', () => {
    writeFileSync(join(tmpRoot, 'CLAUDE.md'), '# Main\n', 'utf-8')
    ensureDavidGrantsSection('agent-a')
    expect(readFileSync(join(tmpRoot, 'CLAUDE.md'), 'utf-8')).toContain(BEGIN)
  })

  it('does nothing when the agent has no CLAUDE.md', () => {
    expect(() => ensureDavidGrantsSection('agent-missing')).not.toThrow()
  })
})

describe('david-grants section: wired to BOTH surfaces', () => {
  const here = dirname(fileURLToPath(import.meta.url))
  const live = (rel: string) => readFileSync(join(here, '..', rel), 'utf-8')
    .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')

  it('web.ts ensures it for the main agent at boot', () => {
    expect(live('web.ts')).toMatch(/^\s*ensureDavidGrantsSection\(MAIN_AGENT_ID\)/m)
  })

  it('agent-process.ts ensures it for every agent start', () => {
    expect(live('web/agent-process.ts')).toMatch(/^\s*ensureDavidGrantsSection\(name\)/m)
  })
})
