import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { chatIdFromAccessConfig, channelDeliveryName, resolveSchedulerAlertToken, resolveBoundChannel } from '../web/schedule-runner.js'
import { PROJECT_ROOT } from '../config.js'
import { channelStateDir, type ChannelProviderType } from '../channel-provider.js'
import { normalizeChatId } from '../owner-chat.js'

// Regression guard for 2026-07-27 (Zara report, Marveen diagnosis): the
// scheduled-task prompt prefix carried a "chat_id: 0" sentinel from a
// pre-plugin channel implementation. The official Telegram plugin rejects it
// (assertAllowedChat: "0" is never allowlisted), so every non-heartbeat
// scheduled task threw at delivery. The fix resolves the agent's own bound
// chat from its channel access.json at prompt-build time.
//
// Second regression guard for 2026-08-19 (WRONGRECIP819, Marci, kanban
// f1217c23): the "resolve to the first allowlist entry" heuristic below
// silently misdirected sub-agent task results whenever an agent had 2+ DM
// contacts -- measured on the live install, 6 of 7 currently-enabled
// sub-agent `task`-type schedules were affected, either contradicting their
// own explicit recipient or carrying no real Telegram target at all. Fixed
// by resolveBoundChannel: a sub-agent with 2+ candidates and no
// task.telegramChatId pin gets chatId: null + ambiguousCandidates set, never
// a guessed chat id -- on ANY provider, not just Telegram.

describe('chatIdFromAccessConfig (pure core)', () => {
  it('returns the first DM allowlist entry', () => {
    expect(chatIdFromAccessConfig({ allowFrom: ['1268077055'], groups: {} })).toBe('1268077055')
    expect(chatIdFromAccessConfig({ allowFrom: ['111', '222'] })).toBe('111')
  })

  it('accepts numeric entries and trims strings', () => {
    expect(chatIdFromAccessConfig({ allowFrom: [1268077055] })).toBe('1268077055')
    expect(chatIdFromAccessConfig({ allowFrom: [' 42 '] })).toBe('42')
  })

  it('falls back to the first allowed group when no DM entry exists', () => {
    expect(chatIdFromAccessConfig({ allowFrom: [], groups: { '-100123': {} } })).toBe('-100123')
  })

  it('falls back to the Slack channels map when no DM entry exists', () => {
    // Slack access.json uses `channels`, not `groups` -- the same helper must
    // cover it so a Slack-bound agent with only a channel (no DM allowlist)
    // still resolves a deliverable id.
    expect(chatIdFromAccessConfig({ allowFrom: [], channels: { C0000000001: {} } })).toBe('C0000000001')
  })

  it('prefers the DM allowlist entry over a group/channel fallback', () => {
    expect(chatIdFromAccessConfig({ allowFrom: ['U0000000001'], channels: { C0123: {} } })).toBe('U0000000001')
  })

  it('returns null for missing/empty/corrupt bindings (config gap, not a default)', () => {
    expect(chatIdFromAccessConfig(null)).toBeNull()
    expect(chatIdFromAccessConfig('nope')).toBeNull()
    expect(chatIdFromAccessConfig({})).toBeNull()
    expect(chatIdFromAccessConfig({ allowFrom: [], groups: {} })).toBeNull()
    expect(chatIdFromAccessConfig({ allowFrom: [''] })).toBeNull()
  })
})

describe('channelDeliveryName (provider -> Hungarian channel noun)', () => {
  it('names each provider for the "kuldd el <ide>" instruction', () => {
    expect(channelDeliveryName('telegram')).toBe('Telegramon')
    expect(channelDeliveryName('slack')).toBe('Slacken')
    expect(channelDeliveryName('discord')).toBe('Discordon')
    expect(channelDeliveryName('googlechat')).toBe('Google Chaten')
    expect(channelDeliveryName('teams')).toBe('Teamsen')
  })
})

// Regression guard for the 2026-07-08 fix: the scheduler-alert bot token is
// looked up in marveen/.env FIRST and the main agent's channel .env SECOND, for
// every provider that has a bot token. The provider-aware rewrite once dropped
// the second location for Telegram and every alert went silent on hosts whose
// token lives in the plugin env. The reader is stubbed so the test pins the
// lookup ORDER and the empty-value fall-through, not the filesystem.
describe('resolveSchedulerAlertToken (lookup order via injected reader)', () => {
  const PROJECT_ENV = join(PROJECT_ROOT, '.env')
  const channelEnv = (p: ChannelProviderType) => join(channelStateDir(p), '.env')

  /** Reader stub: answers per path, records the calls in order. */
  function stub(answers: Record<string, string | null>) {
    const calls: Array<[ChannelProviderType, string]> = []
    const read = (p: ChannelProviderType, path: string) => {
      calls.push([p, path])
      return answers[path] ?? null
    }
    return { read, calls }
  }

  it('telegram: marveen/.env wins and the channel .env is not consulted', () => {
    const { read, calls } = stub({ [PROJECT_ENV]: '111:project', [channelEnv('telegram')]: '222:plugin' })
    expect(resolveSchedulerAlertToken('telegram', read)).toBe('111:project')
    expect(calls).toEqual([['telegram', PROJECT_ENV]])
  })

  it('telegram: falls back to ~/.claude/channels/telegram/.env (the plugin env)', () => {
    const { read, calls } = stub({ [PROJECT_ENV]: null, [channelEnv('telegram')]: '222:plugin' })
    expect(resolveSchedulerAlertToken('telegram', read)).toBe('222:plugin')
    expect(calls).toEqual([['telegram', PROJECT_ENV], ['telegram', channelEnv('telegram')]])
  })

  it('an EMPTY value in marveen/.env falls through, like the old `if (token)` did', () => {
    const { read } = stub({ [PROJECT_ENV]: '', [channelEnv('telegram')]: '222:plugin' })
    expect(resolveSchedulerAlertToken('telegram', read)).toBe('222:plugin')
  })

  it('slack: same two locations in the same order, provider passed through to the reader', () => {
    const { read, calls } = stub({ [PROJECT_ENV]: null, [channelEnv('slack')]: 'xoxb-channel' })
    expect(resolveSchedulerAlertToken('slack', read)).toBe('xoxb-channel')
    expect(calls).toEqual([['slack', PROJECT_ENV], ['slack', channelEnv('slack')]])
  })

  it('no token anywhere -> undefined (callers take the log-only branch)', () => {
    const { read } = stub({})
    expect(resolveSchedulerAlertToken('telegram', read)).toBeUndefined()
  })

  it('creds-based providers never read a token: their reader value is a project/app id, not a bot token', () => {
    const { read, calls } = stub({ [PROJECT_ENV]: 'project-id-would-be-here' })
    expect(resolveSchedulerAlertToken('googlechat', read)).toBeUndefined()
    expect(resolveSchedulerAlertToken('teams', read)).toBeUndefined()
    expect(calls).toEqual([])
  })
})

describe('schedule-runner source contract (sentinel removed, provider-aware)', () => {
  const src = readFileSync(join(__dirname, '..', 'web', 'schedule-runner.ts'), 'utf-8')

  it('no prompt prefix carries the dead chat_id: 0 sentinel anymore', () => {
    expect(src).not.toMatch(/chat_id:\s*0[,)]/)
  })

  it('the no-binding branch omits the delivery instruction instead of guessing a chat', () => {
    // The fallback prefix must be the bare task tag -- no channel mention, no
    // ALLOWED_CHAT_ID leak into a sub-agent prompt.
    expect(src).toContain('prompt omits the delivery instruction')
    expect(src).toMatch(/prefix = `\[Utemezett feladat: \$\{task\.name\}\] `/)
  })

  it('the delivery instruction names the resolved provider, not a hardcoded Telegram', () => {
    // Regression guard: the instruction used to say "Telegramon" for every
    // agent. It must now interpolate channelDeliveryName(bound.provider) so a
    // Slack-bound agent is told to reply on Slack.
    expect(src).toContain('channelDeliveryName(bound.provider)')
    expect(src).not.toMatch(/kuldd el Telegramon \(chat_id/)
  })

  it('an ambiguous 2+-candidate resolution is SKIPPED, not guessed, and raises visibility, on ANY provider', () => {
    // WRONGRECIP819: upstream's own multi-provider resolveBoundChannel still
    // guessed (warn + first-entry) for every provider. A sub-agent with 2+ DM
    // contacts and no telegramChatId pin must never receive a chat_id guess
    // in its prompt, regardless of which provider it is bound to.
    expect(src).toContain('scheduled task: delivery target is ambiguous')
    expect(src).toContain('logger.error(')
    expect(src).toContain('createAgentMessage(')
    expect(src).not.toMatch(/bound-chat resolution is ambiguous[\s\S]{0,80}using the first/)
    // The ambiguous branch falls through to the SAME bare-tag prefix as the
    // config-gap branch -- delivery is skipped either way, never guessed.
    const ambiguousIdx = src.indexOf('scheduled task: delivery target is ambiguous')
    const nextPrefixIdx = src.indexOf('prefix = `[Utemezett feladat: ${task.name}] `', ambiguousIdx)
    expect(nextPrefixIdx, 'ambiguous branch must fall through to the bare prefix').toBeGreaterThan(ambiguousIdx)
  })

  it('a 2+-candidate access.json never resolves to a guessed chat id (function-level contract)', () => {
    const fnStart = src.indexOf('export function resolveBoundChannel')
    expect(fnStart, 'resolveBoundChannel not found').toBeGreaterThan(0)
    const fnBody = src.slice(fnStart, src.indexOf('\n}\n', fnStart))
    expect(fnBody).toMatch(/candidates > 1\)\s*return\s*\{\s*provider,\s*chatId:\s*null,\s*ambiguousCandidates:\s*candidates\s*\}/)
    expect(fnBody).not.toContain('logger.warn')
  })

  it('resolution reads the access.json for the agent\'s own provider, not always telegram', () => {
    expect(src).toContain('resolveAgentProvider(agentName)')
    expect(src).toContain('channelStateDir(provider')
    expect(src).toContain('chatIdFromAccessConfig')
  })

  it('the system-level scheduler alerts send over CHANNEL_PROVIDER, not Telegram directly', () => {
    // The three alert paths (catch-up summary, pending-retry, task-timeout)
    // must route through the provider abstraction, never sendTelegramMessage.
    expect(src).not.toContain('sendTelegramMessage')
    expect(src).toContain('sendSchedulerAlertMessage')
    expect(src).toContain('getProvider(CHANNEL_PROVIDER)')
  })

  it('the main agent resolves from the configured owner chat, with "0" never treated as configured', () => {
    // Regression guard, distinct from WRONGRECIP819: OWNERCHAT803
    // (2026-08-03) established that the installer's "0" placeholder must
    // never be treated as a configured owner chat. Upstream's
    // resolveBoundChannel has NO main-agent special case at all -- it reads
    // access.json uniformly for every agent, main included -- so this class
    // of bug could resurface if that branch's wiring regresses. Two checks:
    // the wiring exists (source contract) and the underlying "0 is not
    // configured" guarantee it relies on actually holds (direct call, no
    // filesystem).
    const fnStart = src.indexOf('export function resolveBoundChannel')
    expect(fnStart, 'resolveBoundChannel not found').toBeGreaterThan(0)
    const fnBody = src.slice(fnStart, src.indexOf('\n}\n', fnStart))
    expect(fnBody).toMatch(/agentName === MAIN_AGENT_ID/)
    expect(fnBody).toMatch(/resolveOwnerChatId\(undefined,\s*configuredOwnerChatFor\(provider\),\s*provider\)/)
    expect(normalizeChatId('0')).toBeNull()
    expect(normalizeChatId('8668856531')).toBe('8668856531')
  })
})

describe('resolveBoundChannel (task.telegramChatId precedence, no filesystem for the pinned cases)', () => {
  it('"none" means no delivery target, by design -- never falls through to auto-resolution', () => {
    const result = resolveBoundChannel('sam', { telegramChatId: 'none' })
    expect(result.chatId).toBeNull()
    expect(result.ambiguousCandidates).toBeUndefined()
  })

  it('an explicit chat_id is used as-is, overriding any allowlist heuristic', () => {
    expect(resolveBoundChannel('max', { telegramChatId: '8321555318' }).chatId).toBe('8321555318')
  })

  it('an explicit override wins even for the main agent (author intent beats the default)', () => {
    expect(resolveBoundChannel('pedro', { telegramChatId: '8321555318' }).chatId).toBe('8321555318')
  })
})
