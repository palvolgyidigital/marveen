import type { Message } from 'grammy/types'

// Longer excerpts defeat the point (a quick "what were they replying to"
// glance in the <channel> tag) and needlessly grow the notification payload.
const EXCERPT_MAX = 200

// Same delimiter set as safeName() in server.ts: the excerpt lands inside the
// <channel> tag as an attribute value, and these characters would let the
// QUOTED message's author (who may not be the current sender — a group reply
// can quote anyone) break out of the tag or forge a second meta entry.
function safeExcerpt(s: string): string {
  return s.replace(/[<>[\]\r\n;]/g, '_').slice(0, EXCERPT_MAX)
}

// Fail-safe: a non-reply message (the overwhelming common case) yields {},
// so spreading this into the notification meta changes nothing for it — the
// <channel> tag looks exactly as it does today.
export function replyMeta(
  replyTo: Message | undefined,
): { reply_to_message_id?: string; reply_to_excerpt?: string } {
  if (!replyTo) return {}
  const text = replyTo.text ?? replyTo.caption ?? ''
  return {
    reply_to_message_id: String(replyTo.message_id),
    ...(text.trim() ? { reply_to_excerpt: safeExcerpt(text) } : {}),
  }
}
