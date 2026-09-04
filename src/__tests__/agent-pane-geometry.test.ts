import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { AGENT_PANE_COLS, AGENT_PANE_ROWS, tmuxPaneSizeArgs } from '../config.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const read = (p: string) => readFileSync(join(__dirname, '..', p), 'utf-8')

// tmux gives a DETACHED session 80x24. On 2026-09-01 those 24 rows were the
// shared cause of two separate delivery failures (card 874e124d): an 81-line
// scheduled prompt whose head scrolled away with the parked-input marker in it,
// and a full pane whose idle footer never rendered, so the router read a busy
// session as idle. Anna's pane was resized by hand that day; this pins the
// fleet default so a respawn does not silently go back to 24 rows.
describe('agent tmux pane geometry', () => {
  it('is 60 rows, not tmux\'s detached default of 24', () => {
    expect(AGENT_PANE_ROWS).toBe(60)
    expect(AGENT_PANE_ROWS).toBeGreaterThan(24)
  })
  it('emits size flags tmux new-session understands', () => {
    expect(tmuxPaneSizeArgs()).toEqual(['-x', String(AGENT_PANE_COLS), '-y', String(AGENT_PANE_ROWS)])
  })
  it('every agent spawn site passes the size, so no agent starts at 80x24', () => {
    for (const file of ['web/agent-process.ts', 'web/agent-worker.ts']) {
      const src = read(file)
      const spawns = src.split('\n').filter((l) => l.includes("'new-session'"))
      expect(spawns.length).toBeGreaterThan(0)
      for (const line of spawns) expect(line).toContain('tmuxPaneSizeArgs()')
    }
  })
})
