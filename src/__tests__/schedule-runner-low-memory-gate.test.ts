// The scheduler's pre-injection low-memory gate (card 9b6e4e6e, Part 2,
// 2026-10-29 OOM incident).
//
// Unlike the usage-limit gate (sibling file schedule-runner-usage-limit-
// gate.test.ts), which is pure in-process decision logic, this gate shells
// out for real to scripts/fleet-memory-gate.sh --min-avail -- deliberately
// NOT mocked here, so this suite exercises the actual script via its own
// MEMGATE_PROC_MEMINFO test-stub seam (same seam scripts/__tests__/memgate-
// min-avail.test.sh uses directly on the script). That is what Pedro's
// acceptance criterion asked for ("stubolt meminfo-val"), not a mock of
// node:child_process standing in for the real decision.
//
//   MemAvailable below threshold -> NOT injected, recorded 'low-memory',
//     one inter-agent notice to the main agent (createAgentMessage).
//   MemAvailable above threshold -> injected, as before.
//   a remote-hosted agent (host != null) -> gate skipped entirely (same
//     scope decision as Part 1's agent-memory-scope.ts crossUser skip --
//     this box's /proc/meminfo says nothing about a remote host's memory).
//
// Driven through the real attemptFireTask via runScheduledTaskNow and one
// real cron tick, with tmux/DB mocked -- same fixture shape as the usage-
// limit-gate suite.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { ScheduledTask } from '../web/scheduled-tasks-io.js'

const CLEAN_PANE = [
  '> SCHEDULED TASK NOTICE',
  '● Nothing to drain.',
  '',
  '────────────────────────────────────────',
  '❯ ',
  '────────────────────────────────────────',
  '  ⏵⏵ bypass permissions on (shift+tab to cycle)',
].join('\n')

const mockAppendTaskRun = vi.fn()
const mockSendPrompt = vi.fn(async () => 'sent')
const mockCreateAgentMessage = vi.fn()
const mockListScheduledTasks = vi.fn(() => [] as ScheduledTask[])
const mockWarn = vi.fn()
const mockSendMessage = vi.fn(async () => {})
let remoteHostFor: Record<string, string> = {}

vi.mock('../logger.js', () => ({
  logger: { info: vi.fn(), warn: (...a: unknown[]) => mockWarn(...a), debug: vi.fn(), error: vi.fn() },
}))

vi.mock('../web/schedule-registry.js', () => ({
  filterRegisteredTasks: <T,>(tasks: T[]) => tasks,
  backfillScheduledTaskRegistryOnce: () => ({ ran: false, registered: [] }),
  verifyScheduledTask: () => ({ ok: true }),
  describeVerdict: () => '',
}))

vi.mock('../web/atomic-write.js', () => ({
  atomicWriteFileSync: vi.fn(),
}))

type RetryRow = {
  id: number; task_name: string; agent_name: string; first_attempt: number; last_attempt: number
  attempt_count: number; last_reason: string | null; alert_sent_at: number | null; owner_alert_sent_at: number | null
}
let retryRows: RetryRow[] = []
vi.mock('../db.js', () => ({
  appendTaskRun: (...a: unknown[]) => mockAppendTaskRun(...a),
  createAgentMessage: (...a: unknown[]) => mockCreateAgentMessage(...a),
  listPendingTaskRetries: () => retryRows.map(r => ({ ...r })),
  deletePendingTaskRetry: vi.fn((task: string, agent: string) => {
    const before = retryRows.length
    retryRows = retryRows.filter(r => !(r.task_name === task && r.agent_name === agent))
    return retryRows.length < before
  }),
  updatePendingTaskRetry: vi.fn((task: string, agent: string, now: number, reason: string) => {
    const row = retryRows.find(r => r.task_name === task && r.agent_name === agent)
    if (!row) return false
    Object.assign(row, { last_attempt: now, attempt_count: row.attempt_count + 1, last_reason: reason })
    return true
  }),
  insertPendingTaskRetryIfNew: vi.fn((task: string, agent: string, now: number, reason: string) => {
    if (retryRows.some(r => r.task_name === task && r.agent_name === agent)) return false
    retryRows.push({
      id: retryRows.length + 1, task_name: task, agent_name: agent, first_attempt: now, last_attempt: now,
      attempt_count: 1, last_reason: reason, alert_sent_at: null, owner_alert_sent_at: null,
    })
    return true
  }),
  markPendingTaskRetryAlert: vi.fn(() => false),
  clearPendingTaskRetryAlert: vi.fn(),
  markScheduledTaskKanbanWaiting: vi.fn(),
}))

vi.mock('../channel-provider.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../channel-provider.js')>()
  return {
    ...real,
    readChannelToken: () => 'test-token',
    getProvider: (type: Parameters<typeof real.getProvider>[0]) => ({
      ...real.getProvider(type),
      sendMessage: (...a: unknown[]) => mockSendMessage(...(a as [])),
      sendPhoto: vi.fn(async () => {}),
    }),
  }
})

vi.mock('../owner-chat.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../owner-chat.js')>()
  return { ...real, resolveOwnerChatId: () => 'test-owner-chat' }
})

vi.mock('../web/scheduled-tasks-io.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../web/scheduled-tasks-io.js')>()
  return {
    ...real,
    listScheduledTasks: () => mockListScheduledTasks(),
    SCHEDULED_TASKS_DIR: '/tmp/marveen-low-memory-gate-no-tasks-dir',
  }
})

vi.mock('../web/agent-process.js', () => ({
  clearFeedbackModalAndRecheck: vi.fn(async () => false),
  agentSessionName: (name: string) => `agent-${name}`,
  isAgentRunning: () => true,
  isSessionReadyForPrompt: vi.fn(async () => true),
  sendPromptToSession: (...a: unknown[]) => mockSendPrompt(...(a as [])),
  startAgentProcess: vi.fn(async () => ({ ok: true })),
  sessionExistsOnHost: () => true,
  capturePane: () => CLEAN_PANE,
  sendEnterToSession: vi.fn(),
  clearStaleParkedInput: vi.fn(async () => false),
  resolveAgentProvider: () => 'telegram',
  saturationRefusesDispatch: () => false,
}))

// Only readAgentRemoteHost's return value matters to the low-memory gate's
// host==null scope decision; everything else from this module passes through
// so unrelated schedule-runner codepaths (agent listing, worksource channel
// lookups, etc.) keep their real behaviour.
vi.mock('../web/agent-config.js', async (importOriginal) => {
  const real = await importOriginal<typeof import('../web/agent-config.js')>()
  return {
    ...real,
    readAgentRemoteHost: (agentName: string) => remoteHostFor[agentName] ?? null,
  }
})

function task(overrides: Partial<ScheduledTask> & { name: string }): ScheduledTask {
  return {
    description: 'low-memory gate fixture',
    prompt: 'Do the thing.',
    schedule: '0 8 * * *',
    agent: 'memagent',
    enabled: true,
    createdAt: 0,
    type: 'heartbeat',
    targetSession: 'low-memory-test-session',
    ...overrides,
  }
}

const gateWarned = () =>
  mockWarn.mock.calls.some(c => typeof c[1] === 'string' && c[1].includes('low-memory gate'))

describe('scheduler low-memory gate (attemptFireTask, real fleet-memory-gate.sh --min-avail)', () => {
  let sandbox: string

  beforeEach(() => {
    sandbox = mkdtempSync(join(tmpdir(), 'sched-lowmem-'))
    vi.stubEnv('SCHEDULER_TZ', 'Europe/Budapest')
    // MARVEEN_STORE: an empty, throwaway dir -- the --min-avail path never
    // reads or writes state there, but pointing it away from the real
    // install's store/ keeps this test fully hermetic regardless.
    vi.stubEnv('MARVEEN_STORE', sandbox)
    vi.stubEnv('MARVEEN_MEM_GATE_OBSERVE', '0')
    vi.stubEnv('MARVEEN_MEM_GATE_DISABLE', '0')
    vi.stubEnv('MARVEEN_SCHED_MIN_AVAILABLE_MB', '')
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-29T18:30:00.000Z'))
    retryRows = []
    remoteHostFor = {}
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllEnvs()
    rmSync(sandbox, { recursive: true, force: true })
  })

  function writeMeminfo(availMb: number): void {
    const p = join(sandbox, 'meminfo')
    writeFileSync(p, `MemTotal:       16000000 kB\nMemAvailable:   ${availMb * 1024} kB\n`)
    vi.stubEnv('MEMGATE_PROC_MEMINFO', p)
  }

  async function runNow(t: ScheduledTask) {
    vi.resetModules()
    mockListScheduledTasks.mockReturnValue([t])
    const { runScheduledTaskNow } = await import('../web/schedule-runner.js')
    return runScheduledTaskNow(t.name)
  }

  it('injects normally when MemAvailable is above the (default 1536 MB) threshold', async () => {
    writeMeminfo(5000) // well above default
    const res = await runNow(task({ name: 'lm-plenty' }))
    expect(res.result).toBe('memagent: fired')
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
    expect(gateWarned()).toBe(false)
    expect(mockCreateAgentMessage).not.toHaveBeenCalled()
  })

  for (const type of ['heartbeat', 'task'] as const) {
    it(`does NOT inject a ${type} when MemAvailable is below the default threshold`, async () => {
      writeMeminfo(900) // below default 1536 MB
      const res = await runNow(task({ name: `lm-low-${type}`, type }))
      expect(res.result).toBe('memagent: low-memory')
      expect(mockSendPrompt).not.toHaveBeenCalled()
      expect(gateWarned()).toBe(true)
      // One inter-agent notice to the main agent for this episode.
      expect(mockCreateAgentMessage).toHaveBeenCalledTimes(1)
      const [from, to, text] = mockCreateAgentMessage.mock.calls[0] as [string, string, string]
      expect(from).toBe('system')
      expect(text).toContain('lm-low')
      void to
    })
  }

  it('MARVEEN_SCHED_MIN_AVAILABLE_MB overrides the default threshold', async () => {
    writeMeminfo(900)
    vi.stubEnv('MARVEEN_SCHED_MIN_AVAILABLE_MB', '500') // 900 MB clears a 500 MB bar
    const res = await runNow(task({ name: 'lm-override' }))
    expect(res.result).toBe('memagent: fired')
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
  })

  it('a remote-hosted agent is NOT gated (host != null is out of scope, same as Part 1)', async () => {
    writeMeminfo(10) // deep below any sane threshold
    remoteHostFor.memagent = 'laptop.example'
    // No targetSession override here: resolveTaskTarget only consults
    // readAgentRemoteHost when the task does NOT pin a custom session (a
    // targetSession override always resolves host=null, by design -- see
    // resolveTaskTarget's own comment). The fixture's default task() sets
    // targetSession, so this one case must omit it to actually exercise
    // host != null.
    const res = await runNow(task({ name: 'lm-remote', targetSession: undefined }))
    expect(res.result).toBe('memagent: fired')
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
    expect(gateWarned()).toBe(false)
  })

  it('a short-cadence (skipIfBusy) cron occurrence held back by the gate is recorded as skipped-low-memory, not queued', async () => {
    writeMeminfo(900)
    vi.resetModules()
    mockListScheduledTasks.mockReturnValue([task({ name: 'lm-cron', schedule: '* * * * *', skipIfBusy: true })])
    const { startScheduleRunner } = await import('../web/schedule-runner.js')
    const stop = startScheduleRunner()
    await vi.advanceTimersByTimeAsync(6_000)
    clearInterval(stop)

    expect(mockSendPrompt).not.toHaveBeenCalled()
    expect(mockAppendTaskRun).toHaveBeenCalledWith('lm-cron', 'memagent', 'skipped-low-memory')
    expect(mockAppendTaskRun).not.toHaveBeenCalledWith('lm-cron', 'memagent', 'fired')
  })

  it('a daily task held back by the gate is QUEUED for retry, not dropped for the day, and the retry is not lost once memory recovers', async () => {
    writeMeminfo(900)
    vi.resetModules()
    const db = await import('../db.js')
    mockListScheduledTasks.mockReturnValue([task({ name: 'lm-daily', type: 'task', schedule: '* * * * *' })])
    const runner = await import('../web/schedule-runner.js')
    const stop = runner.startScheduleRunner()
    await vi.advanceTimersByTimeAsync(6_000)

    expect(mockSendPrompt).not.toHaveBeenCalled()
    expect(db.insertPendingTaskRetryIfNew).toHaveBeenCalledWith('lm-daily', 'memagent', expect.any(Number), 'low-memory')
    expect(retryRows).toHaveLength(1)

    // Memory recovers: the retry loop re-checks the same gate and delivers.
    writeMeminfo(5000)
    await vi.advanceTimersByTimeAsync(runner.SCHEDULE_TICK_MS)
    clearInterval(stop)
    expect(mockSendPrompt).toHaveBeenCalledTimes(1)
    expect(retryRows).toHaveLength(0)
  })

  it('at most one owner notice per 30 minutes, even across repeated low-memory ticks', async () => {
    writeMeminfo(900)
    vi.resetModules()
    mockListScheduledTasks.mockReturnValue([task({ name: 'lm-notice-cap', schedule: '* * * * *', skipIfBusy: true })])
    const { startScheduleRunner, SCHEDULE_TICK_MS } = await import('../web/schedule-runner.js')
    const stop = startScheduleRunner()
    await vi.advanceTimersByTimeAsync(6_000)
    await vi.advanceTimersByTimeAsync(SCHEDULE_TICK_MS)
    await vi.advanceTimersByTimeAsync(SCHEDULE_TICK_MS)
    clearInterval(stop)
    expect(mockCreateAgentMessage.mock.calls.length).toBeLessThanOrEqual(1)
  })
})
