import { CHANNEL_PROVIDER, CHANNEL_TOKEN, CHANNEL_CHAT_ID } from './config.js'
import { getProvider } from './channel-provider.js'
import { logger } from './logger.js'
import { markIfTestRun } from './test-run-marker.js'

export async function notifyChannel(text: string): Promise<void> {
  if (!CHANNEL_TOKEN || !CHANNEL_CHAT_ID) {
    logger.warn('Channel ertesites kihagyva: token vagy chat ID hianyzik')
    return
  }

  // Marked here at the funnel, NOT at call sites -- a new caller must not be
  // able to leak an unmarked message from a test run.
  const outbound = markIfTestRun(text)
  const provider = getProvider(CHANNEL_PROVIDER)
  const formatted = provider.formatMessage(outbound)
  const chunks = provider.splitMessage(formatted)

  for (const chunk of chunks) {
    try {
      const parseMode = CHANNEL_PROVIDER === 'telegram' ? 'HTML' : undefined
      await provider.sendMessage(CHANNEL_TOKEN, CHANNEL_CHAT_ID, chunk, parseMode)
    } catch (err) {
      logger.warn({ err }, 'notifyChannel: primary send failed, trying the unformatted fallback')
      try {
        await provider.sendMessage(CHANNEL_TOKEN, CHANNEL_CHAT_ID, outbound.slice(0, 4096))
      } catch (err2) {
        // Last resort: both sends failed and this text is gone. Measured
        // 2026-09-01: a stuck-input owner alert vanished here with no trace
        // anywhere, because this catch was empty -- log-only, no behavior
        // or retry-logic change.
        logger.warn({ err: err2 }, 'notifyChannel: fallback send also failed, message not delivered')
      }
    }
  }
}

// Backward-compatible alias
export const notifyTelegram = notifyChannel

// Security-event notification (break-glass password reset, security:reset).
// Unlike notifyChannel, a missing channel config is an EXPECTED state here
// (fresh installs, channel-less deployments), so it stays fully silent -- the
// recovery path must never depend on, or be noisy about, Telegram being wired.
export async function notifySecurityEvent(text: string): Promise<void> {
  if (!CHANNEL_TOKEN || !CHANNEL_CHAT_ID) return
  try {
    await notifyChannel(text)
  } catch {
    /* never let a notification failure break the recovery action itself */
  }
}
